"""bot_spot.py — Spot trading (Long-only) + Telegram commands."""
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
USE_TESTNET  = os.getenv("USE_TESTNET", "true").lower() == "true"
BASE_URL     = "https://demo-api.binance.com" if USE_TESTNET else "https://api.binance.com"
API_KEY      = os.getenv("SPOT_API_KEY", "").strip()
API_SECRET   = os.getenv("SPOT_API_SECRET", "").strip()
SYMBOL       = os.getenv("SYMBOL", "SOLUSDT").upper()
TIMEFRAME    = os.getenv("TIMEFRAME", "15m")
DRY_RUN      = os.getenv("DRY_RUN", "true").lower() == "true"
CAPITAL_USDT = float(os.getenv("SPOT_CAPITAL_USDT", "5.5"))

SL_ATR_MULT  = float(os.getenv("SL_ATR_MULT", "2.0"))
TP_ATR_MULT  = float(os.getenv("TP_ATR_MULT", "4.0"))
LOOP_SEC     = int(os.getenv("LOOP_SEC", "60"))

COIN        = base_asset(SYMBOL)
STATE_FILE  = Path(__file__).parent / "spot_state.json"
TRADES_FILE = Path(__file__).parent / "spot_trades.json"

PARAMS = {
    "ema_period":       int(os.getenv("EMA_PERIOD", "200")),
    "utbot_sens":       float(os.getenv("UTBOT_SENSITIVITY", "3")),
    "utbot_atr_period": int(os.getenv("UTBOT_ATR_PERIOD", "10")),
    "adx_period":       int(os.getenv("ADX_PERIOD", "14")),
    "adx_threshold":    float(os.getenv("ADX_THRESHOLD", "25")),
    "obv_ema_period":   int(os.getenv("OBV_EMA_PERIOD", "20")),
}

# ============ RUNTIME ============
_paused   = threading.Event()
_shutdown = threading.Event()

_sym_cache = {"info": None, "t": 0}
_tg_offset = {"id": 0}


# ============ EXCHANGE INFO ============
def get_symbol_info():
    if _sym_cache["info"] and (time.time() - _sym_cache["t"] < 3600):
        return _sym_cache["info"]
    try:
        r = requests.get(f"{BASE_URL}/api/v3/exchangeInfo",
                         params={"symbol": SYMBOL}, timeout=15).json()
        if "symbols" in r and r["symbols"]:
            _sym_cache["info"] = r["symbols"][0]
            _sym_cache["t"] = time.time()
            return r["symbols"][0]
    except Exception as e:
        log(f"exchangeInfo err: {e}", "SPOT")
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
            min_notional = float(f.get("minNotional", f.get("notional", 5.0)))
    return step, min_qty, min_notional


# ============ ACCOUNT ============
def get_balance(asset):
    r = signed_request("GET", BASE_URL, "/api/v3/account", API_KEY, API_SECRET)
    if not r or "balances" not in r:
        return 0.0
    for b in r["balances"]:
        if b.get("asset", "").upper() == asset.upper():
            return float(b.get("free", 0) or 0)
    return 0.0


def get_price():
    r = public_get(BASE_URL, "/api/v3/ticker/price", {"symbol": SYMBOL})
    if isinstance(r, dict):
        try:
            return float(r.get("price", 0))
        except Exception:
            return 0.0
    return 0.0


def order_market(side, quote_qty=None, qty=None):
    if DRY_RUN:
        return {"dry_run": True, "orderId": int(time.time())}
    p = {"symbol": SYMBOL, "side": side, "type": "MARKET"}
    if quote_qty is not None:
        p["quoteOrderQty"] = f"{quote_qty:.2f}"
    elif qty is not None:
        p["quantity"] = qty
    return signed_request("POST", BASE_URL, "/api/v3/order",
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
        log(f"log_trade err: {e}", "SPOT")


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
def open_long(price, atr):
    info = get_symbol_info()
    step, min_qty, min_notional = get_lot_size(info)
    usdt = get_balance("USDT") if not DRY_RUN else CAPITAL_USDT
    size = min(usdt * 0.98, CAPITAL_USDT)
    if size < min_notional:
        log(f"size ${size:.2f} < min ${min_notional:.2f}", "SPOT")
        return False

    log(f"🟢 BUY {COIN} @ {price:.6f} | ${size:.2f}", "SPOT")
    r = order_market("BUY", quote_qty=size)
    if not is_ok(r):
        log(f"❌ BUY gagal: {str(r)[:150]}", "SPOT")
        return False

    time.sleep(2)
    qty_raw = size / price if DRY_RUN else get_balance(COIN)
    qty = floor_to_step(qty_raw, step)
    if qty < min_qty:
        log(f"qty {qty} < minQty {min_qty}", "SPOT")
        return False

    sl = price - SL_ATR_MULT * atr
    tp = price + TP_ATR_MULT * atr
    qty_s = format_qty(qty, step)

    st = load_state(STATE_FILE)
    st.update({"position": "LONG", "entry_price": price, "qty": qty,
               "sl": sl, "tp": tp, "entry_time": time.time()})
    save_state(STATE_FILE, st)
    log(f"✅ LONG | qty={qty_s} | SL={sl:.6f} | TP={tp:.6f}", "SPOT")

    tg_send(fmt_open("LONG", SYMBOL, price, qty_s,
                     size, 1, sl, tp, "signal_entry"))
    return True


def close_long(reason=""):
    st = load_state(STATE_FILE)
    if st["position"] != "LONG":
        return False
    info = get_symbol_info()
    step, min_qty, _ = get_lot_size(info)

    qty = st["qty"]
    if not DRY_RUN:
        real = get_balance(COIN)
        if real > 0:
            qty = real
    qty = floor_to_step(qty, step)
    if qty < min_qty:
        st["position"] = None
        save_state(STATE_FILE, st)
        return False
    qty_s = format_qty(qty, step)

    log(f"🔴 SELL {COIN} qty={qty_s} | {reason}", "SPOT")
    r = order_market("SELL", qty=qty_s)
    if not is_ok(r):
        log(f"❌ SELL gagal: {str(r)[:150]}", "SPOT")
        return False

    curr = get_price()
    ep = st["entry_price"]
    pnl = (curr - ep) / ep * 100 if ep > 0 else 0
    log(f"✅ CLOSED | PnL ≈ {pnl:+.2f}%", "SPOT")

    log_trade({
        "side": "LONG", "symbol": SYMBOL,
        "entry": ep, "exit": curr, "qty": qty,
        "pnl_pct": round(pnl, 4), "reason": reason,
        "opened_at": st.get("entry_time", 0),
        "closed_at": time.time(),
    })

    tg_send(fmt_close("LONG", SYMBOL, ep, curr, pnl, reason))

    st.update({"position": None, "entry_price": 0, "qty": 0, "sl": 0, "tp": 0})
    save_state(STATE_FILE, st)
    return True


# ============ MAIN TICK ============
def run_once():
    kl = fetch_klines(BASE_URL, "/api/v3/klines", SYMBOL, TIMEFRAME, 500)
    if kl is None:
        log("klines kosong", "SPOT")
        return
    sig = generate_signal(kl, PARAMS)
    st = load_state(STATE_FILE)

    log(f"{sig['action']} | {sig['regime']} | ADX {sig['adx']:.1f} | "
        f"UTBot {sig['utbot']} | price {sig['price']:.6f} | "
        f"pos={st['position'] or 'FLAT'}", "SPOT")

    if st["position"] is None:
        if sig["action"] == "BUY":
            open_long(sig["price"], sig["atr"])
        return

    if st["position"] == "LONG":
        p = sig["price"]
        if p <= st["sl"]:
            close_long("STOP_LOSS"); return
        if p >= st["tp"]:
            close_long("TAKE_PROFIT"); return
        if sig["utbot"] == "SELL":
            close_long("UTBOT_SELL"); return
        if sig["regime"] == "Sideways":
            close_long("REGIME_SIDEWAYS"); return
        pnl = (p - st["entry_price"]) / st["entry_price"] * 100
        log(f"HOLD LONG | PnL {pnl:+.2f}%", "SPOT")


# ============ TELEGRAM COMMANDS ============
def _cmd_status():
    kl = fetch_klines(BASE_URL, "/api/v3/klines", SYMBOL, TIMEFRAME, 100)
    if kl is None:
        tg_send("⚠️ Gagal fetch klines")
        return
    sig = generate_signal(kl, PARAMS)
    st = load_state(STATE_FILE)
    pos = st.get("position") or "FLAT"
    entry = st.get("entry_price", 0)
    pnl = 0.0
    if pos != "FLAT" and entry > 0:
        pnl = (sig["price"] - entry) / entry * 100
    tg_send(fmt_status(SYMBOL, sig["price"], sig["regime"],
                       sig["adx"], sig["utbot"], pos, entry, pnl))


def _cmd_posisi():
    st = load_state(STATE_FILE)
    if not st.get("position"):
        tg_send("📍 Tidak ada posisi (FLAT)")
        return
    price = get_price()
    entry = st["entry_price"]
    pnl = (price - entry) / entry * 100 if entry > 0 else 0
    tg_send(fmt_status(SYMBOL, price, "—", 0, "—", "LONG", entry, pnl))


def _cmd_stats():
    s = compute_stats()
    if s["total"] == 0:
        tg_send("📊 Belum ada trade")
        return
    lines = [
        f"📊 <b>STATISTIK SPOT</b>",
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
        lines.append(f"{emoji} LONG {t['pnl_pct']:+.2f}% ({t['reason']})")
    tg_send("\n".join(lines))


def _cmd_pause():
    _paused.set()
    tg_send("⏸ <b>Bot di-pause.</b>")


def _cmd_resume():
    _paused.clear()
    tg_send("▶️ <b>Bot resumed.</b>")


def _cmd_stop():
    tg_send("🛑 <b>Shutdown...</b>")
    _shutdown.set()


def _cmd_help():
    tg_send(
        "🤖 <b>COMMAND TUYUL SPOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "/status — Harga & regime saat ini\n"
        "/posisi — Detail posisi\n"
        "/stats  — Statistik trading\n"
        "/pause  — Pause bot\n"
        "/resume — Resume bot\n"
        "/stop   — Shutdown\n"
        "/help   — Menu ini"
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
    if not tg_ready():
        return
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    url = f"https://api.telegram.org/bot{token}/getUpdates"

    log("📱 Telegram command listener aktif", "SPOT")
    while not _shutdown.is_set():
        try:
            r = requests.get(url, params={
                "offset": _tg_offset["id"] + 1, "timeout": 20,
            }, timeout=25)
            data = r.json()
            for upd in data.get("result", []):
                _tg_offset["id"] = upd["update_id"]
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = (msg.get("text") or "").strip().lower()
                sender = str(msg.get("chat", {}).get("id", ""))
                if sender != chat_id or not text.startswith("/"):
                    continue
                cmd = text.split()[0].split("@")[0]
                fn = _CMD_MAP.get(cmd)
                if fn:
                    try:
                        fn()
                    except Exception as e:
                        tg_send(fmt_error(f"cmd err: {e}"))
                else:
                    tg_send(f"❓ {cmd}\nKirim /help")
        except Exception as e:
            log(f"tg poll err: {e}", "TG")
        time.sleep(2)


# ============ MAIN ============
def main():
    log("=" * 60, "SPOT")
    log(f"SYMBOL    : {SYMBOL}", "SPOT")
    log(f"TIMEFRAME : {TIMEFRAME}", "SPOT")
    log(f"MODE      : {'DRY-RUN' if DRY_RUN else 'LIVE 🔴'} | "
        f"NETWORK: {'TESTNET' if USE_TESTNET else 'MAINNET'}", "SPOT")
    log(f"CAPITAL   : ${CAPITAL_USDT}", "SPOT")
    log("=" * 60, "SPOT")

    if tg_ready():
        tg_send(fmt_startup(SYMBOL, TIMEFRAME,
                            'DRY-RUN' if DRY_RUN else 'LIVE 🔴',
                            'TESTNET' if USE_TESTNET else 'MAINNET',
                            CAPITAL_USDT, 1, False))
        log("📱 Telegram aktif", "SPOT")
        threading.Thread(target=telegram_poll_loop, daemon=True).start()

    while not _shutdown.is_set():
        if _paused.is_set():
            log("⏸ PAUSED", "SPOT")
        else:
            try:
                run_once()
            except Exception as e:
                log(f"ERR: {e}", "SPOT")
                traceback.print_exc()
                tg_send(fmt_error(str(e)))
        for _ in range(LOOP_SEC):
            if _shutdown.is_set():
                break
            time.sleep(1)

    log("Shutdown.", "SPOT")
    tg_send(fmt_shutdown())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _shutdown.set()
        tg_send(fmt_shutdown())
        log("Ctrl+C — shutdown.", "SPOT")
