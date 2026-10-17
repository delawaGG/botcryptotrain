"""telegram_notif.py — Kirim notifikasi via Telegram Bot API."""
import os
import requests
from datetime import datetime

ENABLED   = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()

_session = requests.Session()


def is_ready():
    return ENABLED and BOT_TOKEN and CHAT_ID


def send(text, silent=False):
    """Kirim pesan ke Telegram. Return True kalau sukses."""
    if not is_ready():
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = _session.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": silent,
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[TG] err: {e}")
        return False


# ============ FORMAT PESAN ============
def fmt_startup(symbol, timeframe, mode, network, margin, leverage, short_enabled):
    return (
        f"🚀 <b>TUYUL TREND STARTED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Symbol    : <code>{symbol}</code>\n"
        f"⏱ Timeframe : {timeframe}\n"
        f"🎯 Mode      : {mode}\n"
        f"🌐 Network   : {network}\n"
        f"💰 Margin    : ${margin} × {leverage}x\n"
        f"📉 Short     : {'ON' if short_enabled else 'OFF'}\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


def fmt_shutdown():
    return f"🛑 <b>Bot STOPPED</b>\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


def fmt_open(side, symbol, price, qty, margin, leverage, sl, tp, reason):
    emoji = "🟢" if side == "LONG" else "🔴"
    return (
        f"{emoji} <b>OPEN {side}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Pair      : <code>{symbol}</code>\n"
        f"💵 Price     : <code>{price:.6f}</code>\n"
        f"📦 Qty       : <code>{qty}</code>\n"
        f"💰 Margin    : ${margin} × {leverage}x\n"
        f"🛑 SL        : <code>{sl:.6f}</code>\n"
        f"🎯 TP        : <code>{tp:.6f}</code>\n"
        f"📝 Reason    : {reason}\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )


def fmt_close(side, symbol, entry, exit_p, pnl_pct, reason):
    emoji = "✅" if pnl_pct >= 0 else "❌"
    sign = "+" if pnl_pct >= 0 else ""
    return (
        f"{emoji} <b>CLOSE {side}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Pair      : <code>{symbol}</code>\n"
        f"📥 Entry     : <code>{entry:.6f}</code>\n"
        f"📤 Exit      : <code>{exit_p:.6f}</code>\n"
        f"📊 PnL       : <b>{sign}{pnl_pct:.2f}%</b>\n"
        f"📝 Reason    : {reason}\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )


def fmt_error(msg):
    return (
        f"⚠️ <b>ERROR</b>\n"
        f"<pre>{msg[:500]}</pre>\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )


def fmt_status(symbol, price, regime, adx, utbot, position, entry, pnl_pct):
    pos_str = position or "FLAT"
    if position and entry > 0:
        extra = f"\n📥 Entry     : <code>{entry:.6f}</code>\n📊 PnL       : {pnl_pct:+.2f}%"
    else:
        extra = ""
    return (
        f"📊 <b>STATUS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Pair      : <code>{symbol}</code>\n"
        f"💵 Price     : <code>{price:.6f}</code>\n"
        f"🌊 Regime    : {regime}\n"
        f"📈 ADX       : {adx:.1f}\n"
        f"🎯 UTBot     : {utbot}\n"
        f"📍 Posisi    : <b>{pos_str}</b>{extra}\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
