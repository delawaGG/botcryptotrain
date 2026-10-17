Fase 0 — Setup (Hari 1)

☐ Install Python + dependencies
☐ Buat akun Binance Testnet
☐ Generate API key testnet
☐ Isi .env
☐ Jalankan python app.py dengan DRY_RUN=true
☐ Pastikan log muncul tanpa error

Fase 1 — Dry-Run Testnet (3 hari)

☐ Jalankan bot 24/7 (pakai nohup atau screen)
☐ Log semua signal yang muncul
☐ Verifikasi logika entry/exit
☐ Pastikan tidak crash
☐ Belum ada uang real

Fase 2 — Live Testnet (2 minggu)

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
5. Testnet ≠ Mainnet. Hasil testnet bagus belum tentu sama di mainnet.
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
Atau cek history di Binance → Order History.

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

Versi: 1.0
Update terakhir: 2026
Status: Beta — untuk pembelajaran, bukan untuk produksi serius

Remember: Trading is not a get-rich-quick scheme. It's a skill that takes years to master.
Mulai kecil, belajar dari kesalahan, dan tetap disiplin.
