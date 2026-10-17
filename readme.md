# 🤖 TREND — Crypto Trading Bot

Bot trading crypto dengan strategi **Trend Following** menggunakan:
- EMA200 (filter trend utama)
- UTBot (trigger entry)
- ADX + EMA50 slope (deteksi regime)
- OBV (konfirmasi volume)
- ATR-based SL/TP (2× ATR / 4× ATR)

Mendukung **Spot** dan **Futures** (Long + Short) dalam satu codebase modular.

---

## 📁 Struktur Project

```

tuyul/
├── app.py              # Entry point — pilih mode spot/futures
├── bot_spot.py         # Eksekutor spot (Long-only)
├── bot_futures.py      # Eksekutor futures (Long + Short)
├── core.py             # Indikator, signal generator, API helper, log
├── .env                # Konfigurasi (API keys, parameter)
├── requirements.txt    # Dependencies
├── spot_state.json     # State spot (auto-generated)
└── futures_state.json  # State futures (auto-generated)

```

---

## ⚙️ Instalasi

### 1. Prasyarat

- **Python 3.9+**
- **pip** (package manager)
- Akun **Binance** (mainnet atau demo)

### 2. Install Dependencies

**Linux / macOS / Termux:**
```bash
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
python -m pip install -r requirements.txt
```

Isi requirements.txt:

```
requests>=2.31.0
numpy>=1.24.0
python-dotenv>=1.0.0
```

3. Setup API Key

⚠️ PENTING: Binance Testnet Lama SUDAH DIGANTI

Binance telah mengganti sistem testnet terpisah (testnet.binancefuture.com & testnet.binance.vision) dengan platform terpadu bernama "Demo Trading".

· ❌ testnet.binancefuture.com — SUDAH TIDAK BISA generate API key
· ❌ testnet.binance.vision — SUDAH TIDAK BISA generate API key
· ✅ demo.binance.com — Tempat baru untuk Demo Trading

Kalau kamu buka testnet lama dan tidak menemukan tempat untuk ambil API key, itu karena sudah dipindahkan. Ikuti panduan di bawah.

---

🧪 Setup Demo Trading (REKOMENDASI untuk belajar)

Langkah-langkah:

1. Login ke Akun Binance
   · Buka https://www.binance.com
   · Login dengan akun Binance kamu (akun biasa, bukan testnet)
2. Masuk ke Halaman Demo Trading
   · Kunjungi: https://demo.binance.com
   · Kalau pertama kali, klik "Start Demo Trading" atau sejenisnya
   · Masuk ke halaman trading dulu (klik salah satu pair), baru menu API akan muncul
3. Buka API Management
   · Langsung ke: https://demo.binance.com/en/my/settings/api-management
   · Atau: dari halaman trading → klik ikon profil → API Management
4. Create API Key
   · Klik "Create API" → beri label (mis. tuyul-bot)
   · Sistem akan generate API Key + Secret Key
   · ⚠️ Secret Key hanya muncul SEKALI — copy dan simpan di password manager
5. Enable Permission
   · ✅ Enable Futures (untuk bot_futures.py)
   · ✅ Enable Spot & Margin Trading (untuk bot_spot.py)
   · ❌ JANGAN enable Withdrawals
6. Saldo Demo
   · Binance Demo Trading kasih saldo virtual gratis (biasanya ~15.000 USDT)
   · Tidak ada uang nyata — aman untuk eksperimen
7. Paste ke .env
   ```
   FUTURES_API_KEY=isi_api_key_demo
   FUTURES_API_SECRET=isi_secret_demo
   SPOT_API_KEY=isi_api_key_demo
   SPOT_API_SECRET=isi_secret_demo
   USE_TESTNET=true
   ```

---

💰 Setup Mainnet (Uang Sungguhan)

⚠️ Lakukan ini HANYA setelah sukses di Demo Trading minimal 2 minggu.

1. Login Binance → Profile → API Management
   · URL: https://www.binance.com/en/my/settings/api-management
2. Klik Create API → System generated
3. Beri label (mis. "tuyul-live")
4. Enable:
   · ✅ Enable Spot & Margin Trading
   · ✅ Enable Futures
5. DISABLE (WAJIB):
   · ❌ Enable Withdrawals
   · ❌ Enable Internal Transfer
   · ❌ Permits Universal Transfer
6. Restrict IP ke IP publik kamu (sangat disarankan)
7. Copy API Key + Secret → paste ke .env:
   ```
   SPOT_API_KEY=isi_disini
   SPOT_API_SECRET=isi_disini
   FUTURES_API_KEY=isi_disini
   FUTURES_API_SECRET=isi_disini
   USE_TESTNET=false
   ```

---

🚀 Penggunaan

Mode Spot (Long-only)

Edit .env:

```bash
TRADING_MODE=spot
USE_TESTNET=true
DRY_RUN=true
SPOT_CAPITAL_USDT=5.5
```

Jalankan:

```bash
python app.py
```

Mode Futures (Long + Short)

Edit .env:

```bash
TRADING_MODE=futures
USE_TESTNET=true
DRY_RUN=true
FUTURES_MARGIN_USDT=5.5
FUTURES_LEVERAGE=3
ALLOW_SHORT=true
```

Jalankan:

```bash
python app.py
```

---

⚙️ Konfigurasi .env Lengkap

```bash
# === MODE ===
TRADING_MODE=futures          # 'spot' atau 'futures'
USE_TESTNET=true              # true = Demo Trading, false = Mainnet

# === SYMBOL ===
SYMBOL=SOLUSDT                # Pair yang ditradingkan
TIMEFRAME=15m                 # 1m, 5m, 15m, 1h, 4h, 1d

# === API KEYS ===
SPOT_API_KEY=
SPOT_API_SECRET=
FUTURES_API_KEY=
FUTURES_API_SECRET=

# === TRADING ===
DRY_RUN=true                  # true = simulasi, false = live
SPOT_CAPITAL_USDT=5.5         # Modal per order (spot)
FUTURES_MARGIN_USDT=5.5       # Margin per posisi (futures)
FUTURES_LEVERAGE=3            # Leverage (1-10 aman)
ALLOW_SHORT=true              # Izinkan short di futures

# === STRATEGI ===
EMA_PERIOD=200
UTBOT_SENSITIVITY=3
UTBOT_ATR_PERIOD=10
ADX_PERIOD=14
ADX_THRESHOLD=25
OBV_EMA_PERIOD=20

# === RISK ===
SL_ATR_MULT=2.0
TP_ATR_MULT=4.0

# === FUNDING GATE ===
FUNDING_CHECK=true
FUNDING_MAX_RATE=0.0005

# === LOOP ===
LOOP_SEC=60
```

---

🔧 Update Kode: Base URL untuk Demo Trading

⚠️ Setelah dapat API key dari Demo Trading, kamu WAJIB update Base URL di kode.

Binance Demo Trading pakai domain berbeda dari testnet lama:

bot_futures.py — Ubah baris BASE_URL:

```python
# SEBELUM (testnet lama — sudah tidak aktif):
# BASE_URL = "https://testnet.binancefuture.com" if USE_TESTNET else "https://fapi.binance.com"

# SESUDAH (Demo Trading baru):
BASE_URL = "https://demo-fapi.binance.com" if USE_TESTNET else "https://fapi.binance.com"
```

bot_spot.py — Ubah baris BASE_URL:

```python
# SEBELUM (testnet lama — sudah tidak aktif):
# BASE_URL = "https://testnet.binance.vision" if USE_TESTNET else "https://api.binance.com"

# SESUDAH (Demo Trading baru):
BASE_URL = "https://demo-api.binance.com" if USE_TESTNET else "https://api.binance.com"
```

Kalau tidak diubah, bot akan error -2015: Invalid API-key karena API key Demo Trading tidak valid di endpoint testnet lama.

---

📊 Cara Kerja Strategi

Aturan Entry LONG

```
✅ Regime = Trending_Bullish atau Bearish
✅ Harga > EMA200
✅ UTBot sinyal = BUY
✅ OBV > EMA(OBV, 20)
✅ (Futures) Funding rate OK untuk LONG
```

Aturan Entry SHORT (Futures only)

```
✅ Regime = Trending_Bullish atau Bearish
✅ Harga < EMA200
✅ UTBot sinyal = SELL
✅ OBV < EMA(OBV, 20)
✅ Funding rate OK untuk SHORT
```

Aturan Exit

```
LONG:
- Harga ≤ entry - 2×ATR (Stop Loss)
- Harga ≥ entry + 4×ATR (Take Profit)
- UTBot sinyal = SELL
- Regime berubah → Sideways

SHORT:
- Harga ≥ entry + 2×ATR (Stop Loss)
- Harga ≤ entry - 4×ATR (Take Profit)
- UTBot sinyal = BUY
- Regime berubah → Sideways
```

Rasio Risk:Reward

```
SL = 2× ATR
TP = 4× ATR
R:R = 1:2

Winrate target: 40-45%
Expectancy: positif kalau disiplin
```

---

🐛 Troubleshooting

❌ Tidak ada menu/tempat untuk ambil API key di testnet

Penyebab: Binance sudah mengganti sistem testnet terpisah dengan Demo Trading.

Fix:

1. JANGAN pakai testnet.binancefuture.com atau testnet.binance.vision — sudah usang
2. Masuk ke https://demo.binance.com (login pakai akun Binance biasa)
3. Masuk ke halaman trading dulu (klik salah satu pair) — menu API baru akan muncul
4. Buka https://demo.binance.com/en/my/settings/api-management
5. Klik Create API → copy API Key + Secret
6. Update .env dengan key baru
7. Update BASE_URL di kode ke https://demo-fapi.binance.com (futures) atau https://demo-api.binance.com (spot)
8. Restart bot

---

Error: -1021: Timestamp for this request is outside of the recvWindow

Penyebab: Waktu HP/laptop tidak sinkron dengan server Binance.

Fix:

· Android (Termux): pkg install ntpdate && ntpdate pool.ntp.org
· Linux: sudo ntpdate pool.ntp.org
· Windows: Settings → Time & Language → Sync now
· Restart bot.

---

Error: -2015: Invalid API-key, IP, or permissions

Penyebab: API key salah, IP tidak di-whitelist, atau permission kurang.

Fix:

1. Cek FUTURES_API_KEY / SPOT_API_KEY di .env (tidak ada spasi di awal/akhir)
2. Cek API key belum expired
3. Cek permission Enable Futures / Enable Spot Trading sudah dicentang di halaman API Management Demo Trading (bukan testnet lama!)
4. Pastikan BASE_URL sudah diarahkan ke demo-fapi.binance.com / demo-api.binance.com, bukan testnet lama
5. Kalau IP restriction aktif, tambahkan IP publik kamu

---

Error: -4164: Order's notional must be no smaller than 5

Penyebab: Order size di bawah minimum Binance ($5).

Fix: Naikkan di .env:

```bash
SPOT_CAPITAL_USDT=6.0
FUTURES_MARGIN_USDT=2.0   # dengan leverage 3x → notional $6
```

---

Error: -4046: No need to change margin type

Penyebab: Margin type sudah ISOLATED sebelumnya.

Fix: Abaikan saja. Ini bukan error, hanya info.

---

Error: -2019: Margin is insufficient

Penyebab: Saldo tidak cukup untuk buka posisi.

Fix:

· Cek saldo di Binance (Demo: cek di demo.binance.com)
· Kurangi FUTURES_MARGIN_USDT atau FUTURES_LEVERAGE
· Cek ada posisi terbuka yang mengunci margin

---

Error: -1111: Precision is over the maximum defined

Penyebab: Qty tidak sesuai stepSize.

Fix: Bot sudah otomatis round ke stepSize. Kalau masih error:

· Restart bot (cache exchangeInfo lama)
· Hapus spot_state.json / futures_state.json

---

Bot tidak eksekusi order, hanya log "HOLD"

Kemungkinan penyebab:

1. Indikator belum siap → butuh minimal 200 candle. Tunggu beberapa jam.
2. Regime Sideways → ADX < 25. Sabar.
3. UTBot belum trigger → tunggu sinyal BUY/SELL
4. OBV tidak konfirmasi → tunggu OBV cross EMA
5. Funding gate block → cek log, mungkin funding sedang mahal

Normal: kadang 4-8 jam tanpa entry. Jangan panik.

---

Bot crash / mati

Cek log terakhir:

```bash
tail -50 log.txt    # atau lihat output terminal
```

Kalau karena error network: Bot akan retry otomatis. Kalau crash total, restart.

Auto-restart (Termux/Linux):

```bash
while true; do
    python app.py
    echo "Restart dalam 10 detik..."
    sleep 10
done
```

---

State korup / posisi tidak sync

Gejala: Bot pikir FLAT padahal ada posisi, atau sebaliknya.

Fix:

1. Stop bot
2. Cek posisi real di Binance (atau Demo Trading)
3. Edit manual spot_state.json / futures_state.json
4. Atau hapus file state — bot akan reset ke FLAT
5. Restart bot

Format state:

```json
{
  "position": "LONG",
  "entry_price": 145.98,
  "qty": 0.113,
  "sl": 142.52,
  "tp": 152.90,
  "entry_time": 1729234567.89
}
```

---

DRY_RUN=false tapi order tidak masuk

Cek:

1. API key permission (Futures harus enabled di Demo Trading)
2. Saldo cukup
3. Symbol valid (SOLUSDT bukan SOL_USDT)
4. Base URL sudah diarahkan ke Demo Trading (demo-fapi.binance.com)
5. Log error spesifik (biasanya ada kode)

---

🎯 Roadmap

Fase 0 — Setup (Hari 1)

☐ Install Python + dependencies
☐ Buat akun Binance Demo Trading (demo.binance.com)
☐ Generate API key di https://demo.binance.com/en/my/settings/api-management
☐ Update BASE_URL di bot_spot.py dan bot_futures.py
☐ Isi .env dengan API key Demo
☐ Jalankan python app.py dengan DRY_RUN=true
☐ Pastikan log muncul tanpa error

Fase 1 — Dry-Run Demo (3 hari)

☐ Jalankan bot 24/7 (pakai nohup atau screen)
☐ Log semua signal yang muncul
☐ Verifikasi logika entry/exit
☐ Pastikan tidak crash
☐ Belum ada uang real

Fase 2 — Live Demo Trading (2 minggu)

☐ Set DRY_RUN=false
☐ Bot buka/tutup posisi real (uang dummy)
☐ Catat setiap trade di spreadsheet:
  · Waktu entry, harga, ATR, regime
  · Waktu exit, PnL, reason
☐ Evaluasi setelah 2 minggu:
  · Winrate ≥ 40%? → lanjut
  · Sharpe positif? → lanjut
  · Max drawdown < 20%? → lanjut
  · Kalau tidak, tuning parameter atau ganti strategi

Fase 3 — Live Mainnet Kecil (1 bulan)

☐ Deposit Rp 100.000 ke Binance (via P2P)
☐ Set USE_TESTNET=false, DRY_RUN=false
☐ FUTURES_MARGIN_USDT=1.5, LEVERAGE=3 (notional ~$4.5)
☐ Pantau harian, jangan biarkan tanpa cek >2 hari
☐ Evaluasi bulanan: profit/loss, max DD, jumlah trade

Fase 4 — Scale (jika Fase 3 profit ≥ 1 bulan)

☐ Naikkan margin 2x lipat
☐ Tambah symbol (mis. BTCUSDT + ETHUSDT)
☐ Tambah fitur:
  · Telegram notif entry/exit
  · Backtest script
  · Auto-compound (margin naik jika profit)

Fase 5 — Advanced (3-6 bulan, opsional)

☐ Tambah timeframe (multi-TF confirmation)
☐ Ensemble strategi (trend + mean reversion)
☐ Machine learning overlay (Colab training + Termux inference)
☐ Portfolio allocation (bobot per symbol)

---

⚠️ Disclaimer & Risk Warning

1. Trading crypto = risiko tinggi. Kamu bisa kehilangan seluruh modal.
2. Bot ini BUKAN jaminan profit. Strategi ini butuh disiplin dan evaluasi terus-menerus.
3. Uang yang dipakai = uang yang RELA hilang. Jangan pakai uang dapur, uang sekolah, atau uang pinjaman.
4. Tidak ada sistem yang 100% winrate. Winrate 40-50% dengan R:R 1:2 masih bisa profit.
5. Demo Trading ≠ Mainnet. Hasil demo bagus belum tentu sama di mainnet.
6. Backtest ≠ Masa depan. Data historis tidak menjamin performa ke depan.
7. Mulai kecil, belajar, baru scale. Jangan langsung modal besar.

---

📞 Tips Praktis

Menjalankan 24/7 (Termux Android)

```bash
# Install screen
pkg install screen

# Buat session baru
screen -S tuyul

# Jalankan bot
python app.py

# Detach: tekan Ctrl+A, lalu D
# Reattach: screen -r tuyul
```

Menjalankan 24/7 (VPS/Linux)

```bash
# Pakai nohup
nohup python app.py > log.txt 2>&1 &

# Cek proses
ps aux | grep app.py

# Stop
kill $(pgrep -f app.py)
```

Backup state

```bash
cp spot_state.json spot_state.backup.json
cp futures_state.json futures_state.backup.json
```

Cek PnL kumulatif

Buka state.json → lihat entry_price vs current price.
Atau cek history di Binance → Order History (atau Demo Trading → Order History).

---

📝 Catatan Pengembangan

File yang aman di-edit

· .env — konfigurasi
· core.py — tambah indikator/sinyal

File yang JANGAN di-edit kalau tidak paham

· bot_spot.py, bot_futures.py — logika eksekusi order
· app.py — dispatcher

Menambah simbol baru

1. Cek pair tersedia di Binance (mis. DOGEUSDT, XRPUSDT)
2. Update .env: SYMBOL=DOGEUSDT
3. Restart bot
4. Test dulu dengan DRY_RUN=true

Menambah timeframe

Support: 1m, 5m, 15m, 30m, 1h, 4h, 1d.
Update .env: TIMEFRAME=1h

---

🎓 Belajar Lanjutan

Kalau mau mendalami:

1. Backtest — uji strategi di data 1-3 tahun sebelum live
2. Walk-forward analysis — validasi parameter tidak overfit
3. Monte Carlo — simulasi ribuan skenario PnL
4. Risk management — position sizing, Kelly criterion, max DD rules
5. Market microstructure — orderbook, spread, slippage

Rekomendasi bacaan:

· Trading Systems and Methods — Perry Kaufman
· Algorithmic Trading — Ernest Chan
· Advances in Financial Machine Learning — Marcos Lopez de Prado

---

📜 Lisensi & Kontribusi

Bot ini untuk pembelajaran pribadi. Silakan modifikasi sesuai kebutuhan.

Kalau menemukan bug atau punya saran, catat di sini:

```
[Tanggal] - [Masalah] - [Fix/Status]
```

---

📌 Changelog

v1.1 (2026-10)

· 🔄 BREAKING: Update Demo Trading endpoints (Binance ganti testnet lama)
· 📝 Tambah panduan ambil API key di demo.binance.com
· 🐛 Fix: troubleshooting untuk "tidak ada menu API key"
· 📝 Update troubleshooting -2015 untuk arahkan ke Demo Trading

v1.0 (2026-10)

· Initial release
· Spot + Futures support
· Long + Short untuk futures
· Funding rate gate
· DRY_RUN mode

---

Versi: 1.1
Update terakhir: Oktober 2026
Status: Beta — untuk pembelajaran, bukan untuk produksi serius

Remember: Trading is not a get-rich-quick scheme. It's a skill that takes years to master.
Mulai kecil, belajar dari kesalahan, dan tetap disiplin.
