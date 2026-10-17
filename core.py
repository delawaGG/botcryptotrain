"""core.py — Indicators, signal generator, API helpers, log, state."""
import json, time, hmac, hashlib, urllib.parse
import requests
import numpy as np
from datetime import datetime
from pathlib import Path

_session = requests.Session()
_session.headers.update({"User-Agent": "TuyulTrend/1.0"})


def log(msg, tag="CORE"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}][{tag}] {msg}", flush=True)


# ============ STATE ============
def load_state(path):
    p = Path(path)
    if p.exists():
        try: return json.loads(p.read_text())
        except Exception: pass
    return {"position": None, "entry_price": 0, "qty": 0,
            "sl": 0, "tp": 0, "entry_time": 0}


def save_state(path, s):
    try: Path(path).write_text(json.dumps(s, indent=2))
    except Exception as e: log(f"save_state err: {e}", "STATE")


# ============ API HELPERS ============
def _sign(params, secret):
    qs = urllib.parse.urlencode(params)
    return hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()


def signed_request(method, base_url, path, api_key, api_secret, params=None, timeout=15):
    if not api_key or not api_secret:
        return None
    p = (params or {}).copy()
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 5000
    p["signature"] = _sign(p, api_secret)
    url = f"{base_url}{path}"
    headers = {"X-MBX-APIKEY": api_key}
    for attempt in range(3):
        try:
            if method == "GET":
                r = _session.get(url, params=p, headers=headers, timeout=timeout)
            else:
                r = _session.post(url, params=p, headers=headers, timeout=timeout)
            return r.json()
        except Exception as e:
            if attempt == 2:
                log(f"API err: {e}", "API")
                return None
            time.sleep(1.5 * (attempt + 1))


def public_get(base_url, path, params=None, timeout=15):
    for attempt in range(2):
        try:
            r = _session.get(f"{base_url}{path}", params=params, timeout=timeout)
            return r.json()
        except Exception:
            if attempt == 1: return None
            time.sleep(1)


def fetch_klines(base_url, kline_path, symbol, interval, limit=500):
    r = public_get(base_url, kline_path,
                   {"symbol": symbol, "interval": interval, "limit": limit})
    if not isinstance(r, list) or len(r) < 50:
        return None
    try:
        return {
            "open":   np.array([float(x[1]) for x in r], dtype=np.float64),
            "high":   np.array([float(x[2]) for x in r], dtype=np.float64),
            "low":    np.array([float(x[3]) for x in r], dtype=np.float64),
            "close":  np.array([float(x[4]) for x in r], dtype=np.float64),
            "volume": np.array([float(x[5]) for x in r], dtype=np.float64),
        }
    except Exception as e:
        log(f"parse klines err: {e}", "KLINE")
        return None


# ============ INDICATORS ============
def ema(values, period):
    n = len(values)
    out = np.full(n, np.nan)
    if n < period: return out
    alpha = 2.0 / (period + 1)
    out[period - 1] = values[:period].mean()
    for i in range(period, n):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def atr_wilder(highs, lows, closes, period):
    n = len(closes)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    out = np.full(n, np.nan)
    if n < period: return out
    out[period - 1] = tr[:period].mean()
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def adx_wilder(highs, lows, closes, period=14):
    n = len(closes)
    if n < period * 2 + 1:
        return np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    tr = np.zeros(n); plus_dm = np.zeros(n); minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    atr_s = np.full(n, np.nan); plus_s = np.full(n, np.nan); minus_s = np.full(n, np.nan)
    atr_s[period] = tr[1:period + 1].sum()
    plus_s[period] = plus_dm[1:period + 1].sum()
    minus_s[period] = minus_dm[1:period + 1].sum()
    for i in range(period + 1, n):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        plus_s[i] = plus_s[i - 1] - plus_s[i - 1] / period + plus_dm[i]
        minus_s[i] = minus_s[i - 1] - minus_s[i - 1] / period + minus_dm[i]
    plus_di = np.full(n, np.nan); minus_di = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(atr_s[i]) and atr_s[i] > 0:
            plus_di[i] = 100 * plus_s[i] / atr_s[i]
            minus_di[i] = 100 * minus_s[i] / atr_s[i]
    dx = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(plus_di[i]) and not np.isnan(minus_di[i]):
            s = plus_di[i] + minus_di[i]
            if s > 0: dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / s
    adx = np.full(n, np.nan)
    first = period * 2
    if n > first:
        sl = dx[period:first + 1]
        if not np.all(np.isnan(sl)):
            adx[first] = np.nanmean(sl)
        for i in range(first + 1, n):
            if not np.isnan(dx[i]) and not np.isnan(adx[i - 1]):
                adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx, plus_di, minus_di


def obv(closes, volumes):
    n = len(closes)
    out = np.zeros(n)
    for i in range(1, n):
        if closes[i] > closes[i - 1]:   out[i] = out[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]: out[i] = out[i - 1] - volumes[i]
        else:                            out[i] = out[i - 1]
    return out


def utbot(closes, highs, lows, sensitivity=3.0, atr_period=10):
    n = len(closes)
    a = atr_wilder(highs, lows, closes, atr_period)
    nloss = sensitivity * a
    stop = np.full(n, np.nan)
    pos = np.zeros(n, dtype=int)
    sig = ["HOLD"] * n
    start = atr_period
    if n <= start: return sig, stop, pos
    stop[start] = closes[start] - nloss[start] if not np.isnan(nloss[start]) else closes[start]
    for i in range(start + 1, n):
        if np.isnan(nloss[i]):
            stop[i] = stop[i - 1]; pos[i] = pos[i - 1]; continue
        prev = stop[i - 1]
        if closes[i] > prev and closes[i - 1] > prev:
            stop[i] = max(prev, closes[i] - nloss[i])
        elif closes[i] < prev and closes[i - 1] < prev:
            stop[i] = min(prev, closes[i] + nloss[i])
        elif closes[i] > prev:
            stop[i] = closes[i] - nloss[i]
        else:
            stop[i] = closes[i] + nloss[i]
        if closes[i - 1] < prev and closes[i] > stop[i]:   pos[i] = 1
        elif closes[i - 1] > prev and closes[i] < stop[i]: pos[i] = -1
        else: pos[i] = pos[i - 1]
        if pos[i] == 1 and pos[i - 1] != 1:   sig[i] = "BUY"
        elif pos[i] == -1 and pos[i - 1] != -1: sig[i] = "SELL"
    return sig, stop, pos


def market_regime(closes, adx_val, ema50, adx_threshold=25, lookback=10):
    if len(closes) < 60 or np.isnan(adx_val): return "Warmup"
    if adx_val < adx_threshold: return "Sideways"
    if len(ema50) < lookback + 1 or np.isnan(ema50[-lookback - 1]): return "Warmup"
    slope = ema50[-1] - ema50[-lookback - 1]
    if slope > 0:   return "Trending_Bullish"
    elif slope < 0: return "Trending_Bearish"
    return "Sideways"


# ============ SIGNAL GENERATOR (SHARED) ============
def generate_signal(klines, params):
    """Return dict sinyal yang sama untuk spot & futures."""
    closes = klines["close"]; highs = klines["high"]
    lows = klines["low"]; vols = klines["volume"]
    price = closes[-1]

    ema200 = ema(closes, params["ema_period"])
    ema50 = ema(closes, 50)
    atr_val = atr_wilder(highs, lows, closes, params["utbot_atr_period"])
    sig_arr, _, _ = utbot(closes, highs, lows,
                          params["utbot_sens"], params["utbot_atr_period"])
    utbot_signal = sig_arr[-1]
    obv_arr = obv(closes, vols)
    obv_ema = ema(obv_arr, params["obv_ema_period"])
    adx_arr, _, _ = adx_wilder(highs, lows, closes, params["adx_period"])
    adx_now = adx_arr[-1]
    regime = market_regime(closes, adx_now, ema50,
                           params["adx_threshold"], lookback=10)

    if np.isnan(atr_val[-1]) or np.isnan(ema200[-1]):
        return {"action": "HOLD", "reason": "indicators_not_ready",
                "price": float(price), "atr": 0.0, "regime": "Warmup",
                "utbot": "HOLD", "adx": 0.0, "obv_up": False, "obv_down": False}

    ma200 = ema200[-1]
    obv_now = obv_arr[-1]
    obv_ema_now = obv_ema[-1] if not np.isnan(obv_ema[-1]) else 0.0
    obv_up = bool(obv_now > obv_ema_now)
    obv_down = bool(obv_now < obv_ema_now)

    trending = regime in ("Trending_Bullish", "Trending_Bearish")

    action = "HOLD"
    reason = "no_signal"

    if trending and price > ma200 and utbot_signal == "BUY" and obv_up:
        action = "BUY"
        reason = f"{regime}|price>ema200|utbot=BUY|obv_up"
    elif trending and price < ma200 and utbot_signal == "SELL" and obv_down:
        action = "SELL"
        reason = f"{regime}|price<ema200|utbot=SELL|obv_down"

    return {
        "action": action, "reason": reason,
        "price": float(price), "atr": float(atr_val[-1]),
        "ema200": float(ma200), "regime": regime,
        "utbot": utbot_signal,
        "adx": float(adx_now) if not np.isnan(adx_now) else 0.0,
        "obv_up": obv_up, "obv_down": obv_down,
    }


# ============ SYMBOL UTILS ============
def base_asset(symbol):
    for q in ("USDT", "BUSD", "USDC", "FDUSD", "TUSD", "BTC", "ETH", "BNB"):
        if symbol.endswith(q):
            return symbol[:-len(q)]
    return symbol


def floor_to_step(qty, step):
    if step <= 0: return qty
    precision = max(0, -int(np.floor(np.log10(step))))
    factor = 10 ** precision
    return np.floor(qty * factor) / factor


def format_qty(qty, step):
    qty = floor_to_step(qty, step)
    if step >= 1: return str(int(qty))
    precision = max(0, -int(np.floor(np.log10(step))))
    return f"{qty:.{precision}f}"
