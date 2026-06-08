# 🤖 Crypto Signal Bot

Bot sinyal trading crypto otomatis untuk **BTCUSDT**, **ETHUSDT**, dan **SOLUSDT** — berjalan di GitHub Actions, mengirim sinyal ke Telegram channel setiap 4 jam.

> **Channel:** [t.me/crypsibotchannel](https://t.me/crypsibotchannel) · **Bot:** [@crypsibot](https://t.me/crypsibot)

---

## 📋 Daftar Isi

- [Cara Kerja](#cara-kerja)
- [Arsitektur Pipeline](#arsitektur-pipeline)
- [Struktur File](#struktur-file)
- [Setup & Deploy](#setup--deploy)
- [Format Sinyal](#format-sinyal)
- [Indikator & Parameter](#indikator--parameter)
- [Aturan Keputusan](#aturan-keputusan)
- [Disclaimer](#disclaimer)

---

## Cara Kerja

1. GitHub Actions menjalankan bot setiap 4 jam (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
2. Bot mengambil data OHLCV, Funding Rate, dan Open Interest dari **Binance Futures API**
3. Indikator teknikal dihitung untuk 4 timeframe: 15m, 1H, 4H, 1D
4. Sinyal hanya dibuat jika **4H dan 1D structure sepakat** dan **confluence score ≥ 60/100**
5. Setiap sinyal divalidasi secara statistik (backtest 90 hari), dicek kelemahannya, dan divalidasi risk/reward-nya
6. Hasilnya dikirim ke Telegram channel — sinyal aktif atau market update jika tidak ada setup valid

---

## Arsitektur Pipeline

```
[GitHub Actions — setiap 4H]
            │
            ▼
   PHASE 2: Data Layer
   fetch_all_data()
   OHLCV 300 candle × 4 TF × 3 symbol  ← Binance Futures API
   + Funding Rate + Open Interest
            │
            ▼
   PHASE 3: Analysis Layer
   ┌──────────────────────┐
   │ indicator_engine     │  EMA, RSI, MACD, BB, ATR, OBV, MFI, Supertrend, StochRSI
   │ mtf_confluence       │  Confluence Score 0–100
   │ market_structure     │  Trend, Key Levels, Derivatives, Resolusi Konflik 4H vs 1D
   └──────────────────────┘
            │
            ▼
   PHASE 4: Decision Layer
   ┌──────────────────────────────────────────┐
   │ signal_generator    → draft sinyal       │
   │ statistical_validator → validasi backtest│
   │ devil_advocate      → cek kelemahan      │
   │ risk_manager        → validasi RR & SL   │
   └──────────────────────────────────────────┘
            │
       APPROVED / REJECTED
            │
            ▼
   PHASE 5: Output Layer
   report_formatter → telegram_sender
            │
            ▼
   [Telegram Channel]
```

---

## Struktur File

```
crypto-signal-bot/
│
├── .github/
│   └── workflows/
│       └── signal.yml              ← Scheduler & CI/CD
│
├── src/
│   ├── config.py                   ← Semua konstanta & parameter (satu sumber kebenaran)
│   │
│   ├── data_collector.py           ← Fetch OHLCV, Funding Rate, Open Interest
│   │
│   ├── indicator_engine.py         ← Kalkulasi semua indikator TA
│   ├── mtf_confluence.py           ← Scoring multi-timeframe
│   ├── market_structure.py         ← Trend, key levels, derivatives, resolusi konflik
│   │
│   ├── signal_generator.py         ← Draft sinyal Long/Short + kalkulasi TP/SL
│   ├── statistical_validator.py    ← Backtest 90 hari + win rate + EV
│   ├── devil_advocate.py           ← Validasi RSI divergence, BB squeeze, funding conflict
│   ├── risk_manager.py             ← Validasi RR & SL distance, position size informatif
│   │
│   ├── report_formatter.py         ← Format pesan Telegram
│   ├── orchestrator.py             ← Entry point utama
│   │
│   └── utils/
│       ├── logger.py               ← Logging standar (stdout → GitHub Actions)
│       └── telegram_sender.py      ← Kirim pesan + retry + health check
│
├── requirements.txt
└── README.md
```

---

## Setup & Deploy

### Prasyarat

- GitHub account
- Telegram Bot Token dari [@BotFather](https://t.me/BotFather)
- Telegram Channel (bot sudah jadi admin)

### Langkah 1 — Clone & Install

```bash
git clone https://github.com/nurudhuh/crypto-signal-bot.git
cd crypto-signal-bot
pip install -r requirements.txt
```

### Langkah 2 — Set GitHub Secrets

Buka **Settings → Secrets and variables → Actions** di repo, tambahkan dua secret:

| Secret Name | Isi |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token dari BotFather (format: `123456:ABC-DEF...`) |
| `TELEGRAM_CHAT_ID` | Username channel (format: `@crypsibotchannel`) |

### Langkah 3 — Deploy

Push ke branch `main` — GitHub Actions akan aktif otomatis sesuai jadwal cron.

Untuk **test manual** sebelum jadwal:

1. Buka tab **Actions** di repo
2. Pilih workflow **Crypto Signal Bot**
3. Klik **Run workflow**

### Langkah 4 — Monitoring

Bot wajib mengirim **minimal 1 pesan setiap 4 jam** ke channel:
- Sinyal aktif (jika ada setup valid)
- Market update (jika tidak ada setup)
- Alert error (jika pipeline gagal)

Jika channel diam lebih dari 8 jam → cek tab **Actions** di GitHub untuk melihat log error.

---

## Format Sinyal

### Sinyal Aktif

```
🟢 LONG Signal — BTCUSDT
⏱ Timeframe: 4H  |  🔥 Confidence: HIGH

📍 Entry Zone : 65,200.00 – 65,500.00
🎯 TP1        : 67,300.00  (+2.99%)
🎯 TP2        : 68,700.00  (+5.13%)
🎯 TP3        : 70,000.00  (+7.14%)
🛡 Stop Loss  : 63,800.00  (-2.37%)
⚖️ Risk/Reward : 1 : 2.6

📈 Struktur    : UPTREND (4H) & UPTREND (1D)
🔗 Confluence  : 74/100  (3 dari 4 TF sepakat)
📉 Win Rate    : 61%  (23 setup serupa, 90 hari)
💰 EV Score    : +0.34

⚡ Funding Rate : +0.0100% (NETRAL)
📦 Open Interest: NAIK — OI naik + harga naik → trend kuat

⚠️ Bukan saran finansial. DYOR. Manajemen risiko ada di tangan Anda.
```

### Market Update (No Trade)

```
📊 Market Update — 2026-06-01 08:00 UTC

📈 BTCUSDT  65,340.00  |  Struktur: UPTREND    |  Score: 58/100
↔️  ETHUSDT   3,210.00  |  Struktur: RANGING    |  Score: 41/100
📉 SOLUSDT    142.00   |  Struktur: DOWNTREND  |  Score: 33/100

⏸ Tidak ada setup valid saat ini.
Setup berikutnya dievaluasi dalam 4 jam.
```

---

## Indikator & Parameter

Semua parameter terpusat di `src/config.py`.

| Kategori | Indikator | Parameter Default |
|---|---|---|
| **Trend** | EMA | Fast=21, Mid=50, Slow=200 |
| **Trend** | Supertrend | Period=10, Multiplier=3.0 |
| **Momentum** | RSI | Period=14 |
| **Momentum** | MACD | Fast=12, Slow=26, Signal=9 |
| **Momentum** | Stochastic RSI | Period=14, SmoothK=3, SmoothD=3 |
| **Volatility** | Bollinger Bands | Period=20, StdDev=2 |
| **Volatility** | ATR | Period=14 |
| **Volume** | OBV | MA Period=20 |
| **Volume** | MFI | Period=14 |

### Threshold Keputusan

| Parameter | Nilai | Keterangan |
|---|---|---|
| `MIN_CONFLUENCE_SCORE` | 60 | Skor minimum dari 100 |
| `MIN_RR_RATIO` | 1.5 | Risk/Reward minimum |
| `MIN_WIN_RATE` | 45% | Win rate historis minimum |
| `MIN_EV` | > 0 | Expected Value harus positif |
| `MIN_SAMPLE_N` | 10 | Minimum setup serupa untuk backtest valid |
| `BACKTEST_DAYS` | 90 | Rolling window statistik (hari) |

---

## Aturan Keputusan

### Confluence Scoring

Skor dihitung per timeframe, kemudian diberi bobot:

| Timeframe | Bobot | Kondisi yang Dinilai |
|---|---|---|
| 1D | 40% | EMA alignment, RSI, MACD histogram, posisi vs BB mid |
| 4H | 30% | Sama seperti 1D |
| 1H | 20% | Sama seperti 1D |
| 15m | 10% | Sama seperti 1D |

### Resolusi Konflik 4H vs 1D

| 1D | 4H | Arah Diizinkan | Penalti Skor |
|---|---|---|---|
| UPTREND | UPTREND | LONG | — |
| DOWNTREND | DOWNTREND | SHORT | — |
| UPTREND | RANGING | LONG | -10 poin |
| DOWNTREND | RANGING | SHORT | -10 poin |
| Lainnya | — | ❌ No Trade | — |

### Kalkulasi TP & SL

```
SL   = swing low/high terdekat ± 0.5× ATR (buffer wick)
       Validasi: jarak SL harus 1–3× ATR dari entry

TP1  = entry_mid ± sl_distance × 1.5   (RR 1:1.5)
TP2  = entry_mid ± sl_distance × 2.5   (RR 1:2.5)
TP3  = key level berikutnya, atau entry_mid ± sl_distance × 4.0
```

### Checklist Devil Advocate

Sinyal ditolak jika ≥ 2 flag ditemukan:

| Cek | Kondisi Flag |
|---|---|
| RSI Divergence | Hidden bearish/bullish divergence terdeteksi |
| Funding Rate | Arah sinyal berlawanan dengan kondisi overheated |
| Volume Spike | Volume > 2.5× rata-rata 20 candle terakhir |
| BB Squeeze | Width < persentil ke-20 tanpa konfirmasi breakout |
| SL Distance | Jarak entry ke SL < 1× ATR |
| Sample Size | Jumlah setup serupa < 10 |

---

## Disclaimer

> Sinyal yang dihasilkan bot ini **bukan saran finansial**. Bot ini adalah alat bantu analisis teknikal otomatis. Selalu lakukan riset sendiri (DYOR) dan terapkan manajemen risiko yang sesuai dengan kondisi keuangan Anda. Performa historis tidak menjamin hasil di masa depan.
