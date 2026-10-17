"""bot_futures.py — Futures trading (Long + Short)."""
import os, sys, time, traceback
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from core import (
    log, load_state, save_state, signed_request, public_get, fetch_klines,
    generate_signal, base_asset, floor_to_step, format_qty,
)

# ============ CONFIG ============
USE_TESTNET   = os.getenv("USE_TESTNET", "true").lower() == "true"
BASE_URL      = "https://testnet.binancefuture.com" if USE_TESTNET else "https://fapi.binance.com"
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

COIN = base_asset(SYMBOL)
STATE_FILE = Path(__file__).parent / "futures_state.json"

PARAMS = {
    "ema_period":      int(os.getenv("EMA_PERIOD", "200")),
    "utbot_sens":      float(os.getenv("UTBOT_SENSITIVITY", "3")),
    "utbot_atr_period":int(os.getenv("UTBOT_ATR_PERIOD", "10")),
    "adx_period":      int(os.getenv("ADX_PERIOD", "14")),
    "adx_threshold":   float(os.getenv("ADX_THRESHOLD", "25")),
    "obv_ema_period":  int(os.getenv("OBV_EMA_PERIOD", "20")),
}

_sym_cache = {"info": None, "t": 0}


# ============ EXCHANGE INFO ============
def get_symbol_info():
    if _sym_cache["info"] and (time.time() - _sym_cache["t"] < 3600):
        return _sym_cache["info"]
    try:
        import requests
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
    if not info: return step, min_qty, min_notional
    for f in info.get("filters", []):
        ft = f.get("filterType")
        if ft == "LOT_SIZE":
            step = float(f["stepSize"]); min_qty = float(f["minQty"])
        elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
            min_notional = float(f.get("notional", f.get("minNotional", 5.0)))
    return step, min_qty, min_notional


# ============ SETUP ============
def setup_account():
    """Set margin type ISOLATED + leverage. Idempotent."""
    if DRY_RUN: 
        log("setup skip (DRY-RUN)", "FUT")
        return
    # Margin type
    r = signed_request("POST", BASE_URL, "/fapi/v1/marginType",
                       API_KEY, API_SECRET,
                       {"symbol": SYMBOL, "marginType": "ISOLATED"})
    # Error -4046 = already set, aman
    log(f"marginType: {str(r)[:80]}", "FUT")
    # Leverage
    r = signed_request("POST", BASE_URL, "/fapi/v1/leverage",
                       API_KEY, API_SECRET,
                       {"symbol": SYMBOL, "leverage": LEVERAGE})
    log(f"leverage: {str(r)[:80]}", "FUT")


# ============ ACCOUNT / POSITION ============
def get_balance(asset="USDT"):
    r = signed_request("GET", BASE_URL, "/fapi/v2/balance", API_KEY, API_SECRET)
    if not isinstance(r, list):
        return 0.0
    for b in r:
        if b.get("asset") == asset:
            return float(b.get("availableBalance", 0) or 0)
    return 0.0


def get_position_amt():
    """Return posisi saat ini: 0 kalau flat, >0 LONG, <0 SHORT."""
    r = signed_request("GET", BASE_URL, "/fapi/v2/positionRisk",
                       API_KEY, API_SECRET, {"symbol": SYMBOL})
    if isinstance(r, list) and r:
        try: return float(r[0].get("positionAmt", 0) or 0)
        except Exception: return 0.0
    return 0.0


def get_price():
    r = public_get(BASE_URL, "/fapi/v1/ticker/price", {"symbol": SYMBOL})
    if isinstance(r, dict):
        try: return float(r.get("price", 0))
        except Exception: return 0.0
    return 0.0


def get_funding_rate():
    """Return dict {'rate': float, 'next_time': int} atau None."""
    r = public_get(BASE_URL, "/fapi/v1/premiumIndex", {"symbol": SYMBOL})
    if isinstance(r, dict):
        try:
            return {
                "rate": float(r.get("lastFundingRate", 0) or 0),
                "next_time": int(r.get("nextFundingTime", 0) or 0),
            }
        except Exception: pass
    return None


def funding_gate(side):
    """Return (ok, reason). side = 'LONG' atau 'SHORT'."""
    if not FUNDING_CHECK:
        return True, "check_off"
    f = get_funding_rate()
    if not f:
        return True, "no_data"
    rate = f["rate"]
    if side == "LONG" and rate > FUNDING_MAX:
        return False, f"funding {rate*100:.4f}% > {FUNDING_MAX*100:.4f}% (mahal untuk LONG)"
    if side == "SHORT" and rate < -FUNDING_MAX:
        return False, f"funding {rate*100:.4f}% < -{FUNDING_MAX*100:.4f}% (mahal untuk SHORT)"
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
    if not r or not isinstance(r, dict): return False
    if r.get("dry_run"): return True
    return bool(r.get("orderId"))


# ============ TRADING ============
def _calc_qty(price, step):
    """qty dari margin × leverage."""
    notional = MARGIN_USDT * LEVERAGE
    qty = notional / price if price > 0 else 0
    return floor_to_step(qty, step)


def open_position(side, price, atr):
    """side = 'LONG' atau 'SHORT'."""
    info = get_symbol_info()
    step, min_qty, min_notional = get_lot_size(info)
    notional = MARGIN_USDT * LEVERAGE
    if notional < min_notional:
        log(f"notional ${notional:.2f} < min ${min_notional:.2f}", "FUT")
        return False

    # Funding gate
    ok, why = funding_gate(side)
    if not ok:
        log(f"🚫 {side} skip: {why}", "FUT"); return False

    qty = _calc_qty(price, step)
    if qty < min_qty:
        log(f"qty {qty} < minQty {min_qty}", "FUT"); return False
    qty_s = format_qty(qty, step)

    # LONG = BUY, SHORT = SELL (open)
    order_side = "BUY" if side == "LONG" else "SELL"
    log(f"🟢 OPEN {side} {COIN} @ {price:.6f} | qty={qty_s} | "
        f"margin ${MARGIN_USDT} | {why}", "FUT")
    r = order_market(order_side, qty_s, reduce_only=False)
    if not is_ok(r):
        log(f"❌ {side} gagal: {str(r)[:150]}", "FUT"); return False

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
        if real_amt > 0: qty = real_amt
    qty = floor_to_step(qty, step)
    if qty < min_qty:
        st["position"] = None; save_state(STATE_FILE, st); return False
    qty_s = format_qty(qty, step)

    # Close: LONG → SELL, SHORT → BUY, dengan reduceOnly
    order_side = "SELL" if side == "LONG" else "BUY"
    log(f"🔴 CLOSE {side} {COIN} qty={qty_s} | {reason}", "FUT")
    r = order_market(order_side, qty_s, reduce_only=True)
    if not is_ok(r):
        log(f"❌ CLOSE gagal: {str(r)[:150]}", "FUT"); return False

    curr = get_price()
    ep = st["entry_price"]
    if side == "LONG":
        pnl = (curr - ep) / ep * 100 if ep > 0 else 0
    else:
        pnl = (ep - curr) / ep * 100 if ep > 0 else 0
    log(f"✅ CLOSED {side} | PnL ≈ {pnl:+.2f}%", "FUT")
    st.update({"position": None, "entry_price": 0, "qty": 0, "sl": 0, "tp": 0})
    save_state(STATE_FILE, st)
    return True


# ============ LOOP ============
def run_once():
    kl = fetch_klines(BASE_URL, "/fapi/v1/klines", SYMBOL, TIMEFRAME, 500)
    if kl is None:
        log("klines kosong", "FUT"); return
    sig = generate_signal(kl, PARAMS)
    st = load_state(STATE_FILE)

    log(f"{sig['action']} | {sig['regime']} | ADX {sig['adx']:.1f} | "
        f"UTBot {sig['utbot']} | price {sig['price']:.6f} | "
        f"pos={st['position'] or 'FLAT'}", "FUT")

    # --- FLAT: cek entry ---
    if st["position"] is None:
        if sig["action"] == "BUY":
            open_position("LONG", sig["price"], sig["atr"])
        elif sig["action"] == "SELL" and ALLOW_SHORT:
            open_position("SHORT", sig["price"], sig["atr"])
        return

    # --- LONG: cek exit ---
    if st["position"] == "LONG":
        p = sig["price"]
        if p <= st["sl"]:      close_position("STOP_LOSS"); return
        if p >= st["tp"]:      close_position("TAKE_PROFIT"); return
        if sig["utbot"] == "SELL": close_position("UTBOT_SELL"); return
        if sig["regime"] == "Sideways": close_position("REGIME_SIDEWAYS"); return
        pnl = (p - st["entry_price"]) / st["entry_price"] * 100
        log(f"HOLD LONG | PnL {pnl:+.2f}% | SL {st['sl']:.6f} | TP {st['tp']:.6f}", "FUT")
        return

    # --- SHORT: cek exit ---
    if st["position"] == "SHORT":
        p = sig["price"]
        if p >= st["sl"]:      close_position("STOP_LOSS"); return
        if p <= st["tp"]:      close_position("TAKE_PROFIT"); return
        if sig["utbot"] == "BUY": close_position("UTBOT_BUY"); return
        if sig["regime"] == "Sideways": close_position("REGIME_SIDEWAYS"); return
        pnl = (st["entry_price"] - p) / st["entry_price"] * 100
        log(f"HOLD SHORT | PnL {pnl:+.2f}% | SL {st['sl']:.6f} | TP {st['tp']:.6f}", "FUT")
        return


def main():
    log("=" * 60, "FUT")
    log(f"SYMBOL    : {SYMBOL}", "FUT")
    log(f"TIMEFRAME : {TIMEFRAME}", "FUT")
    log(f"MODE      : {'DRY-RUN' if DRY_RUN else 'LIVE 🔴'} | "
        f"NETWORK: {'TESTNET' if USE_TESTNET else 'MAINNET'}", "FUT")
    log(f"MARGIN    : ${MARGIN_USDT} × {LEVERAGE}x = ${MARGIN_USDT*LEVERAGE} notional", "FUT")
    log(f"SHORT     : {'ENABLED' if ALLOW_SHORT else 'DISABLED'}", "FUT")
    log(f"FUNDING   : {'ON' if FUNDING_CHECK else 'OFF'} | max {FUNDING_MAX*100:.4f}%/8h", "FUT")
    log("=" * 60, "FUT")

    setup_account()
    time.sleep(1)

    while True:
        try: run_once()
        except KeyboardInterrupt: log("Shutdown.", "FUT"); sys.exit(0)
        except Exception as e:
            log(f"ERR: {e}", "FUT"); traceback.print_exc()
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    main()
