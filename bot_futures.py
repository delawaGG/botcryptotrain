"""bot_futures.py — Futures trading (Long + Short) + Telegram commands."""
import os, sys, time, json, traceback, threading
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import requests
from core import (
    log, load_state, save_state, signed_request, public_get, fetch_klines,
    generate_signal, base_asset, floor_to_step, format_qty,
)
from telegram_notif import (
    send as tg_send, is_ready as tg_ready,
    fmt_startup, fmt_shutdown, fmt_open, fmt_close, fmt_error, fmt_status,
)

# ============ CONFIG ============
USE_TESTNET   = os.getenv("USE_TESTNET", "true").lower() == "true"
BASE_URL      = "https://demo-fapi.binance.com" if USE_TESTNET else "https://fapi.binance.com"
API_KEY       = os.getenv("FUTURES_API_KEY", "").strip()
API_SECRET    = os.getenv("FUTURES_API_SECRET", "").strip()
SYMBOL        = os.getenv("SYMBOL", "SOLUSDT").upper()
TIMEFRAME     = os.getenv("TIMEFRAME", "15m")
DRY_RUN       = os.getenv("DRY_RUN", "true").lower() == "true"
MARGIN_USDT   = float(os.getenv("FUTURES_MARGIN_USDT", "5.5"))
LEVERAGE      = int(os.getenv("FUTURES_LEVERAGE", "3"))
ALLOW_SHORT   = os.getenv("ALLOW_SHORT", "true").lower() == "true"

SL_ATR_MULT   = float(os.getenv("SL_ATR_MULT", "2.0"))
TP_ATR_MULT   = float(os.getenv("TP_ATR_MULT", "4.0"))
LOOP_SEC      = int(os.getenv("LOOP_SEC", "60"))

FUNDING_CHECK = os.getenv("FUNDING_CHECK", "true").lower() == "true"
FUNDING_MAX   = float(os.getenv("FUNDING_MAX_RATE", "0.0005"))

COIN        = base_asset(SYMBOL)
STATE_FILE  = Path(__file__).parent / "futures_state.json"
TRADES_FILE = Path(__file__).parent / "futures_trades.json"

PARAMS = {
    "ema_period":       int(os.getenv("EMA_PERIOD", "200")),
    "utbot_sens":       float(os.getenv("UTBOT_SENSITIVITY", "3")),
    "utbot_atr_period": int(os.getenv("UTBOT_ATR_PERIOD", "10")),
    "adx_period":       int(os.getenv("ADX_PERIOD", "14")),
    "adx_threshold":    float(os.getenv("ADX_THRESHOLD", "25")),
    "obv_ema_period":   int(os.getenv("OBV_EMA_PERIOD", "20")),
}

# ============ RUNTIME FLAGS ============
_paused   = threading.Event()
_shutdown = threading.Event()

_sym_cache = {"info": None, "t": 0}
_tg_offset = {"id": 0}


# ============ EXCHANGE INFO ============
def get_symbol_info():
    if _sym_cache["info"] and (time.time() - _sym_cache["t"] < 3600):
        return _sym_cache["info"]
    try:
        r = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=15).json()
        for s in r.get("symbols", []):
            if s.get("symbol") == SYMBOL:
                _sym_cache["info"] = s
                _sym_cache["t"] = time.time()
                return s
    except Exception as e:
        log(f"exchangeInfo err: {e}", "FUT")
    return None


def get_lot_size(info):
    step = 1e-8; min_qty = 1e-8; min_notional = 5.0
    if not info:
        return step, min_qty, min_notional
    for f in info.get("filters", []):
        ft = f.get("filterType")
        if ft == "LOT_SIZE":
            step = float(f["stepSize"]); min_qty = float(f["minQty"])
        elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
            min_notional = float(f.get("notional", f.get("minNotional", 5.0)))
    return step, min_qty, min_notional


# ============ ACCOUNT SETUP ============
def setup_account():
    if DRY_RUN:
        log("setup skip (DRY-RUN)", "FUT")
        return
    r = signed_request("POST", BASE_URL, "/fapi/v1/marginType",
                       API_KEY, API_SECRET,
                       {"symbol": SYMBOL, "marginType": "ISOLATED"})
    log(f"marginType: {str(r)[:80]}", "FUT")
    r = signed_request("POST", BASE_URL, "/fapi/v1/leverage",
                       API_KEY, API_SECRET,
                       {"symbol": SYMBOL, "leverage": LEVERAGE})
    log(f"leverage: {str(r)[:80]}", "FUT")


# ============ ACCOUNT / MARKET DATA ============
def get_balance(asset="USDT"):
    r = signed_request("GET", BASE_URL, "/fapi/v2/balance", API_KEY, API_SECRET)
    if not isinstance(r, list):
        return 0.0
    for b in r:
        if b.get("asset") == asset:
            return float(b.get("availableBalance", 0) or 0)
    return 0.0


def get_position_amt():
    r = signed_request("GET", BASE_URL, "/fapi/v2/positionRisk",
                       API_KEY, API_SECRET, {"symbol": SYMBOL})
    if isinstance(r, list) and r:
        try:
            return float(r[0].get("positionAmt", 0) or 0)
        except Exception:
            return 0.0
    return 0.0


def get_price():
    r = public_get(BASE_URL, "/fapi/v1/ticker/price", {"symbol": SYMBOL})
    if isinstance(r, dict):
        try:
            return float(r.get("price", 0))
        except Exception:
            return 0.0
    return 0.0


def get_funding_rate():
    r = public_get(BASE_URL, "/fapi/v1/premiumIndex", {"symbol": SYMBOL})
    if isinstance(r, dict):
        try:
            return {"rate": float(r.get("lastFundingRate", 0) or 0),
                    "next_time": int(r.get("nextFundingTime", 0) or 0)}
        except Exception:
            pass
    return None


def funding_gate(side):
    if not FUNDING_CHECK:
        return True, "check_off"
    f = get_funding_rate()
    if not f:
        return True, "no_data"
    rate = f["rate"]
    if side == "LONG" and rate > FUNDING_MAX:
        return False, f"funding {rate*100:.4f}% (mahal untuk LONG)"
    if side == "SHORT" and rate < -FUNDING_MAX:
        return False, f"funding {rate*100:.4f}% (mahal untuk SHORT)"
    return True, f"funding {rate*100:.4f}%"


# ============ ORDER ============
def order_market(side, qty_str, reduce_only=False):
    if DRY_RUN:
        return {"dry_run": True, "orderId": int(time.time())}
    p = {"symbol": SYMBOL, "side": side, "type": "MARKET", "quantity": qty_str}
    if reduce_only:
        p["reduceOnly"] = "true"
    return signed_request("POST", BASE_URL, "/fapi/v1/order",
                          API_KEY, API_SECRET, p)


def is_ok(r):
    if not r or not isinstance(r, dict):
        return False
    if r.get("dry_run"):
        return True
    return bool(r.get("orderId"))


# ============ TRADE LOGGER ============
def load_trades():
    if TRADES_FILE.exists():
        try:
            return json.loads(TRADES_FILE.read_text())
        except Exception:
            return []
    return []


def log_trade(rec):
    try:
        data = load_trades()
        data.append(rec)
        TRADES_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        log(f"log_trade err: {e}", "FUT")


def compute_stats():
    trades = load_trades()
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "winrate": 0.0,
                "total_pnl_pct": 0.0, "avg_pnl_pct": 0.0,
                "best": 0.0, "worst": 0.0, "last5": []}
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    pnls = [t["pnl_pct"] for t in trades]
    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": len(wins) / len(trades) * 100,
        "total_pnl_pct": sum(pnls),
        "avg_pnl_pct": sum(pnls) / len(pnls),
        "best": max(pnls),
        "worst": min(pnls),
        "last5": trades[-5:],
    }


# ============ TRADING ============
def _calc_qty(price, step):
    notional = MARGIN_USDT * LEVERAGE
    qty = notional / price if price > 0 else 0
    return floor_to_step(qty, step)


def open_position(side, price, atr):
    info = get_symbol_info()
    step, min_qty, min_notional = get_lot_size(info)
    notional = MARGIN_USDT * LEVERAGE
    if notional < min_notional:
        log(f"notional ${notional:.2f} < min ${min_notional:.2f}", "FUT")
        return False

    ok, why = funding_gate(side)
    if not ok:
        log(f"🚫 {side} skip: {why}", "FUT")
        return False

    qty = _calc_qty(price, step)
    if qty < min_qty:
        log(f"qty {qty} < minQty {min_qty}", "FUT")
        return False
    qty_s = format_qty(qty, step)

    order_side = "BUY" if side == "LONG" else "SELL"
    log(f"🟢 OPEN {side} {COIN} @ {price:.6f} | qty={qty_s} | {why}", "FUT")
    r = order_market(order_side, qty_s, reduce_only=False)
    if not is_ok(r):
        log(f"❌ {side} gagal: {str(r)[:150]}", "FUT")
        return False

    if side == "LONG":
        sl = price - SL_ATR_MULT * atr
        tp = price + TP_ATR_MULT * atr
    else:
        sl = price + SL_ATR_MULT * atr
        tp = price - TP_ATR_MULT * atr

    st = load_state(STATE_FILE)
    st.update({
        "position": side, "entry_price": price, "qty": qty,
        "sl": sl, "tp": tp, "entry_time": time.time(),
    })
    save_state(STATE_FILE, st)
    log(f"✅ {side} | SL={sl:.6f} | TP={tp:.6f}", "FUT")

    tg_send(fmt_open(side, SYMBOL, price, qty_s,
                     MARGIN_USDT, LEVERAGE, sl, tp, why))
    return True


def close_position(reason=""):
    st = load_state(STATE_FILE)
    side = st.get("position")
    if side not in ("LONG", "SHORT"):
        return False
    info = get_symbol_info()
    step, min_qty, _ = get_lot_size(info)

    qty = st["qty"]
    if not DRY_RUN:
        real_amt = abs(get_position_amt())
        if real_amt > 0:
            qty = real_amt
    qty = floor_to_step(qty, step)
    if qty < min_qty:
        st["position"] = None
        save_state(STATE_FILE, st)
        return False
    qty_s = format_qty(qty, step)

    order_side = "SELL" if side == "LONG" else "BUY"
    log(f"🔴 CLOSE {side} {COIN} qty={qty_s} | {reason}", "FUT")
    r = order_market(order_side, qty_s, reduce_only=True)
    if not is_ok(r):
        log(f"❌ CLOSE gagal: {str(r)[:150]}", "FUT")
        return False

    curr = get_price()
    ep = st["entry_price"]
    if side == "LONG":
        pnl = (curr - ep) / ep * 100 if ep > 0 else 0
    else:
        pnl = (ep - curr) / ep * 100 if ep > 0 else 0

    log(f"✅ CLOSED {side} | PnL ≈ {pnl:+.2f}%", "FUT")

    # Log trade untuk /stats
    log_trade({
        "side": side, "symbol": SYMBOL,
        "entry": ep, "exit": curr, "qty": qty,
        "pnl_pct": round(pnl, 4), "reason": reason,
        "opened_at": st.get("entry_time", 0),
        "closed_at": time.time(),
    })

    tg_send(fmt_close(side, SYMBOL, ep, curr, pnl, reason))

    st.update({"position": None, "entry_price": 0, "qty": 0, "sl": 0, "tp": 0})
    save_state(STATE_FILE, st)
    return True


# ============ MAIN TICK ============
def run_once():
    kl = fetch_klines(BASE_URL, "/fapi/v1/klines", SYMBOL, TIMEFRAME, 500)
    if kl is None:
        log("klines kosong", "FUT")
        return
    sig = generate_signal(kl, PARAMS)
    st = load_state(STATE_FILE)

    log(f"{sig['action']} | {sig['regime']} | ADX {sig['adx']:.1f} | "
        f"UTBot {sig['utbot']} | price {sig['price']:.6f} | "
        f"pos={st['position'] or 'FLAT'}", "FUT")

    if st["position"] is None:
        if sig["action"] == "BUY":
            open_position("LONG", sig["price"], sig["atr"])
        elif sig["action"] == "SELL" and ALLOW_SHORT:
            open_position("SHORT", sig["price"], sig["atr"])
        return

    if st["position"] == "LONG":
        p = sig["price"]
        if p <= st["sl"]:
            close_position("STOP_LOSS"); return
        if p >= st["tp"]:
            close_position("TAKE_PROFIT"); return
        if sig["utbot"] == "SELL":
            close_position("UTBOT_SELL"); return
        if sig["regime"] == "Sideways":
            close_position("REGIME_SIDEWAYS"); return
        pnl = (p - st["entry_price"]) / st["entry_price"] * 100
        log(f"HOLD LONG | PnL {pnl:+.2f}%", "FUT")
        return

    if st["position"] == "SHORT":
        p = sig["price"]
        if p >= st["sl"]:
            close_position("STOP_LOSS"); return
        if p <= st["tp"]:
            close_position("TAKE_PROFIT"); return
        if sig["utbot"] == "BUY":
            close_position("UTBOT_BUY"); return
        if sig["regime"] == "Sideways":
            close_position("REGIME_SIDEWAYS"); return
        pnl = (st["entry_price"] - p) / st["entry_price"] * 100
        log(f"HOLD SHORT | PnL {pnl:+.2f}%", "FUT")
        return


# ============ TELEGRAM COMMANDS ============
def _cmd_status():
    kl = fetch_klines(BASE_URL, "/fapi/v1/klines", SYMBOL, TIMEFRAME, 100)
    if kl is None:
        tg_send("⚠️ Gagal fetch klines")
        return
    sig = generate_signal(kl, PARAMS)
    st = load_state(STATE_FILE)
    pos = st.get("position") or "FLAT"
    entry = st.get("entry_price", 0)
    pnl = 0.0
    if pos != "FLAT" and entry > 0:
        if pos == "LONG":
            pnl = (sig["price"] - entry) / entry * 100
        else:
            pnl = (entry - sig["price"]) / entry * 100
    tg_send(fmt_status(SYMBOL, sig["price"], sig["regime"],
                       sig["adx"], sig["utbot"], pos, entry, pnl))


def _cmd_posisi():
    st = load_state(STATE_FILE)
    pos = st.get("position")
    if not pos:
        tg_send("📍 Tidak ada posisi terbuka (FLAT)")
        return
    price = get_price()
    entry = st["entry_price"]
    if pos == "LONG":
        pnl = (price - entry) / entry * 100 if entry > 0 else 0
    else:
        pnl = (entry - price) / entry * 100 if entry > 0 else 0
    tg_send(fmt_status(SYMBOL, price, "—", 0, "—", pos, entry, pnl))


def _cmd_stats():
    s = compute_stats()
    if s["total"] == 0:
        tg_send("📊 Belum ada trade tercatat")
        return
    lines = [
        f"📊 <b>STATISTIK TRADING</b>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"Total Trade : <b>{s['total']}</b>",
        f"Win / Loss  : {s['wins']} / {s['losses']}",
        f"Winrate     : <b>{s['winrate']:.1f}%</b>",
        f"Total PnL   : <b>{s['total_pnl_pct']:+.2f}%</b>",
        f"Avg PnL     : {s['avg_pnl_pct']:+.2f}%",
        f"Best        : {s['best']:+.2f}%",
        f"Worst       : {s['worst']:+.2f}%",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"<b>5 Trade Terakhir:</b>",
    ]
    for t in s["last5"]:
        emoji = "✅" if t["pnl_pct"] >= 0 else "❌"
        lines.append(f"{emoji} {t['side']} {t['pnl_pct']:+.2f}% ({t['reason']})")
    tg_send("\n".join(lines))


def _cmd_pause():
    _paused.set()
    tg_send("⏸ <b>Bot di-pause.</b>\nTidak akan buka posisi baru.\n"
            "Kirim /resume untuk lanjut.")


def _cmd_resume():
    _paused.clear()
    tg_send("▶️ <b>Bot resumed.</b>")


def _cmd_stop():
    tg_send("🛑 <b>Shutdown...</b>")
    _shutdown.set()


def _cmd_help():
    tg_send(
        "🤖 <b>COMMAND TUYUL TREND</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "/status  — Cek harga & regime saat ini\n"
        "/posisi  — Detail posisi terbuka\n"
        "/stats   — Statistik semua trade\n"
        "/pause   — Pause (tidak buka posisi baru)\n"
        "/resume  — Resume dari pause\n"
        "/stop    — Matikan bot dengan aman\n"
        "/help    — Menu ini"
    )


_CMD_MAP = {
    "/status": _cmd_status,
    "/posisi": _cmd_posisi,
    "/pos":    _cmd_posisi,
    "/stats":  _cmd_stats,
    "/pause":  _cmd_pause,
    "/resume": _cmd_resume,
    "/stop":   _cmd_stop,
    "/help":   _cmd_help,
    "/start":  _cmd_help,
}


def telegram_poll_loop():
    """Polling command dari Telegram. Jalan di thread terpisah."""
    if not tg_ready():
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    url = f"https://api.telegram.org/bot{token}/getUpdates"

    log("📱 Telegram command listener aktif", "FUT")

    while not _shutdown.is_set():
        try:
            r = requests.get(url, params={
                "offset": _tg_offset["id"] + 1,
                "timeout": 20,
            }, timeout=25)
            data = r.json()
            for upd in data.get("result", []):
                _tg_offset["id"] = upd["update_id"]
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = (msg.get("text") or "").strip().lower()
                sender_chat = str(msg.get("chat", {}).get("id", ""))

                if sender_chat != chat_id:
                    continue
                if not text.startswith("/"):
                    continue

                # Strip @botname suffix
                cmd = text.split()[0].split("@")[0]
                fn = _CMD_MAP.get(cmd)
                if fn:
                    try:
                        fn()
                    except Exception as e:
                        tg_send(fmt_error(f"cmd {cmd} err: {e}"))
                else:
                    tg_send(f"❓ Command tidak dikenal: {cmd}\nKirim /help")
        except Exception as e:
            log(f"tg poll err: {e}", "TG")
        time.sleep(2)


# ============ MAIN ============
def main():
    log("=" * 60, "FUT")
    log(f"SYMBOL    : {SYMBOL}", "FUT")
    log(f"TIMEFRAME : {TIMEFRAME}", "FUT")
    log(f"MODE      : {'DRY-RUN' if DRY_RUN else 'LIVE 🔴'} | "
        f"NETWORK: {'TESTNET' if USE_TESTNET else 'MAINNET'}", "FUT")
    log(f"MARGIN    : ${MARGIN_USDT} × {LEVERAGE}x = "
        f"${MARGIN_USDT*LEVERAGE} notional", "FUT")
    log(f"SHORT     : {'ENABLED' if ALLOW_SHORT else 'DISABLED'}", "FUT")
    log(f"FUNDING   : {'ON' if FUNDING_CHECK else 'OFF'} | "
        f"max {FUNDING_MAX*100:.4f}%/8h", "FUT")
    log("=" * 60, "FUT")

    setup_account()
    time.sleep(1)

    # Telegram startup + command listener
    if tg_ready():
        tg_send(fmt_startup(SYMBOL, TIMEFRAME,
                            'DRY-RUN' if DRY_RUN else 'LIVE 🔴',
                            'TESTNET' if USE_TESTNET else 'MAINNET',
                            MARGIN_USDT, LEVERAGE, ALLOW_SHORT))
        log("📱 Telegram aktif", "FUT")
        threading.Thread(target=telegram_poll_loop, daemon=True).start()

    while not _shutdown.is_set():
        if _paused.is_set():
            log("⏸ PAUSED", "FUT")
        else:
            try:
                run_once()
            except Exception as e:
                log(f"ERR: {e}", "FUT")
                traceback.print_exc()
                tg_send(fmt_error(str(e)))
        # Sleep in chunks biar responsif terhadap /stop dan /pause
        for _ in range(LOOP_SEC):
            if _shutdown.is_set():
                break
            time.sleep(1)

    log("Shutdown.", "FUT")
    tg_send(fmt_shutdown())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _shutdown.set()
        tg_send(fmt_shutdown())
        log("Ctrl+C — shutdown.", "FUT")
