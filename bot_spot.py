"""bot_spot.py — Spot trading (Long-only)."""
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
BASE_URL      = "https://testnet.binance.vision" if USE_TESTNET else "https://api.binance.com"
API_KEY       = os.getenv("SPOT_API_KEY", "").strip()
API_SECRET    = os.getenv("SPOT_API_SECRET", "").strip()
SYMBOL        = os.getenv("SYMBOL", "SOLUSDT").upper()
TIMEFRAME     = os.getenv("TIMEFRAME", "15m")
DRY_RUN       = os.getenv("DRY_RUN", "true").lower() == "true"
CAPITAL_USDT  = float(os.getenv("SPOT_CAPITAL_USDT", "5.5"))

SL_ATR_MULT   = float(os.getenv("SL_ATR_MULT", "2.0"))
TP_ATR_MULT   = float(os.getenv("TP_ATR_MULT", "4.0"))
LOOP_SEC      = int(os.getenv("LOOP_SEC", "60"))

COIN = base_asset(SYMBOL)
STATE_FILE = Path(__file__).parent / "spot_state.json"

PARAMS = {
    "ema_period":      int(os.getenv("EMA_PERIOD", "200")),
    "utbot_sens":      float(os.getenv("UTBOT_SENSITIVITY", "3")),
    "utbot_atr_period":int(os.getenv("UTBOT_ATR_PERIOD", "10")),
    "adx_period":      int(os.getenv("ADX_PERIOD", "14")),
    "adx_threshold":   float(os.getenv("ADX_THRESHOLD", "25")),
    "obv_ema_period":  int(os.getenv("OBV_EMA_PERIOD", "20")),
}

_sym_cache = {"info": None, "t": 0}


def get_symbol_info():
    if _sym_cache["info"] and (time.time() - _sym_cache["t"] < 3600):
        return _sym_cache["info"]
    try:
        import requests
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
    if not info: return step, min_qty, min_notional
    for f in info.get("filters", []):
        ft = f.get("filterType")
        if ft == "LOT_SIZE":
            step = float(f["stepSize"]); min_qty = float(f["minQty"])
        elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
            min_notional = float(f.get("minNotional", f.get("notional", 5.0)))
    return step, min_qty, min_notional


def get_balance(asset):
    r = signed_request("GET", BASE_URL, "/api/v3/account", API_KEY, API_SECRET)
    if not r or "balances" not in r: return 0.0
    for b in r["balances"]:
        if b.get("asset", "").upper() == asset.upper():
            return float(b.get("free", 0) or 0)
    return 0.0


def get_price():
    r = public_get(BASE_URL, "/api/v3/ticker/price", {"symbol": SYMBOL})
    if isinstance(r, dict):
        try: return float(r.get("price", 0))
        except Exception: return 0.0
    return 0.0


def order_market(side, quote_qty=None, qty=None):
    if DRY_RUN:
        return {"dry_run": True, "orderId": int(time.time())}
    params = {"symbol": SYMBOL, "side": side, "type": "MARKET"}
    if quote_qty is not None:
        params["quoteOrderQty"] = f"{quote_qty:.2f}"
    elif qty is not None:
        params["quantity"] = qty
    return signed_request("POST", BASE_URL, "/api/v3/order",
                          API_KEY, API_SECRET, params)


def is_ok(r):
    if not r or not isinstance(r, dict): return False
    if r.get("dry_run"): return True
    return bool(r.get("orderId"))


# ============ TRADING ============
def open_long(price, atr):
    info = get_symbol_info()
    step, min_qty, min_notional = get_lot_size(info)
    usdt = get_balance("USDT") if not DRY_RUN else CAPITAL_USDT
    size = min(usdt * 0.98, CAPITAL_USDT)
    if size < min_notional:
        log(f"size ${size:.2f} < minNotional ${min_notional:.2f} — skip", "SPOT")
        return False
    log(f"🟢 BUY {COIN} @ {price:.6f} | ${size:.2f}", "SPOT")
    r = order_market("BUY", quote_qty=size)
    if not is_ok(r):
        log(f"❌ BUY gagal: {str(r)[:150]}", "SPOT"); return False
    time.sleep(2)
    qty_raw = size / price if DRY_RUN else get_balance(COIN)
    qty = floor_to_step(qty_raw, step)
    if qty < min_qty:
        log(f"qty {qty} < minQty {min_qty}", "SPOT"); return False
    st = load_state(STATE_FILE)
    st.update({
        "position": "LONG", "entry_price": price, "qty": qty,
        "sl": price - SL_ATR_MULT * atr,
        "tp": price + TP_ATR_MULT * atr,
        "entry_time": time.time(),
    })
    save_state(STATE_FILE, st)
    log(f"✅ LONG | qty={format_qty(qty, step)} | SL={st['sl']:.6f} | TP={st['tp']:.6f}", "SPOT")
    return True


def close_long(reason=""):
    st = load_state(STATE_FILE)
    if st["position"] != "LONG": return False
    info = get_symbol_info()
    step, min_qty, _ = get_lot_size(info)
    qty = st["qty"]
    if not DRY_RUN:
        real = get_balance(COIN)
        if real > 0: qty = real
    qty = floor_to_step(qty, step)
    if qty < min_qty:
        st["position"] = None; save_state(STATE_FILE, st); return False
    qty_s = format_qty(qty, step)
    log(f"🔴 SELL {COIN} qty={qty_s} reason={reason}", "SPOT")
    r = order_market("SELL", qty=qty_s)
    if not is_ok(r):
        log(f"❌ SELL gagal: {str(r)[:150]}", "SPOT"); return False
    curr = get_price()
    pnl = (curr - st["entry_price"]) / st["entry_price"] * 100 if st["entry_price"] > 0 else 0
    log(f"✅ CLOSED | PnL ≈ {pnl:+.2f}%", "SPOT")
    st.update({"position": None, "entry_price": 0, "qty": 0, "sl": 0, "tp": 0})
    save_state(STATE_FILE, st)
    return True


# ============ LOOP ============
def run_once():
    kl = fetch_klines(BASE_URL, "/api/v3/klines", SYMBOL, TIMEFRAME, 500)
    if kl is None:
        log("klines kosong", "SPOT"); return
    sig = generate_signal(kl, PARAMS)
    st = load_state(STATE_FILE)
    log(f"{sig['action']} | {sig['regime']} | ADX {sig['adx']:.1f} | "
        f"UTBot {sig['utbot']} | price {sig['price']:.6f}", "SPOT")

    if st["position"] is None:
        if sig["action"] == "BUY":
            open_long(sig["price"], sig["atr"])
        return

    if st["position"] == "LONG":
        p = sig["price"]
        if p <= st["sl"]:      close_long("STOP_LOSS"); return
        if p >= st["tp"]:      close_long("TAKE_PROFIT"); return
        if sig["utbot"] == "SELL": close_long("UTBOT_SELL"); return
        if sig["regime"] == "Sideways": close_long("REGIME_SIDEWAYS"); return
        pnl = (p - st["entry_price"]) / st["entry_price"] * 100
        log(f"HOLD | PnL {pnl:+.2f}% | SL {st['sl']:.6f} | TP {st['tp']:.6f}", "SPOT")


def main():
    log("=" * 60, "SPOT")
    log(f"SYMBOL    : {SYMBOL}", "SPOT")
    log(f"TIMEFRAME : {TIMEFRAME}", "SPOT")
    log(f"MODE      : {'DRY-RUN' if DRY_RUN else 'LIVE 🔴'} | "
        f"NETWORK: {'TESTNET' if USE_TESTNET else 'MAINNET'}", "SPOT")
    log(f"CAPITAL   : ${CAPITAL_USDT}", "SPOT")
    log("=" * 60, "SPOT")
    while True:
        try: run_once()
        except KeyboardInterrupt: log("Shutdown.", "SPOT"); sys.exit(0)
        except Exception as e:
            log(f"ERR: {e}", "SPOT"); traceback.print_exc()
        time.sleep(LOOP_SEC)


if __name__ == "__main__":
    main()
