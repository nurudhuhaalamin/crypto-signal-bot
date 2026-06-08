# 🤖 Crypto Signal Bot — Technical Plan (Final)

> **Repo:** `github.com/nurudhuh/crypto-signal-bot`
> **Channel:** `t.me/crypsibotchannel`
> **Bot:** `@crypsibot`
> **Update cadence:** Every 4 hours (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
> **Assets:** BTCUSDT · ETHUSDT · SOLUSDT

---

## 📐 Arsitektur Pipeline

```
[GitHub Actions Scheduler — every 4H]
              │
              ▼
     [PHASE 2: Data Layer]
     fetch_all_data()
     OHLCV (300 candles × 4 TF × 3 symbol)
     + Funding Rate + Open Interest
              │
              ▼
     [PHASE 3: Analysis Layer]
     ┌─────────────────────┐
     │ indicator_engine    │  EMA, RSI, MACD, BB, ATR, OBV, MFI
     │ mtf_confluence      │  Confluence Score 0–100
     │ market_structure    │  Trend, Key Levels, Derivatives Context
     └─────────────────────┘
              │
              ▼
     [PHASE 4: Decision Layer]
     ┌─────────────────────────────────────────┐
     │ signal_generator    → draft sinyal      │
     │ statistical_validator → validasi hist.  │
     │ devil_advocate      → cek kelemahan     │
     │ risk_manager        → validasi RR & SL  │
     └─────────────────────────────────────────┘
              │
         APPROVED / REJECTED
              │
              ▼
     [PHASE 5: Output Layer]
     report_formatter → telegram_sender
              │
              ▼
     [Telegram Channel → User]
```

---

## 📁 Struktur File Repository

```
crypto-signal-bot/
│
├── .github/
│   └── workflows/
│       └── signal.yml              ← Scheduler + CI/CD
│
├── src/
│   ├── config.py                   ← Konstanta global
│   │
│   ├── data_collector.py           ← Fetch semua data market
│   │
│   ├── indicator_engine.py         ← Kalkulasi semua indikator TA
│   ├── mtf_confluence.py           ← Scoring multi-timeframe
│   ├── market_structure.py         ← Trend, key levels, derivatives
│   │
│   ├── signal_generator.py         ← Draft sinyal Long/Short/No Trade
│   ├── statistical_validator.py    ← Backtest + win rate + EV
│   ├── devil_advocate.py           ← Validasi kelemahan sinyal
│   ├── risk_manager.py             ← RR, SL, position size
│   │
│   ├── report_formatter.py         ← Format pesan Telegram
│   │
│   └── utils/
│       ├── logger.py               ← Logging standar
│       └── telegram_sender.py      ← Kirim pesan + retry
│
├── requirements.txt
└── README.md
```

---

## ✅ PHASE 0 — Setup & Infrastruktur
**Status: SELESAI ✅**

| Komponen | Detail | Status |
|---|---|---|
| GitHub Repo | `github.com/nurudhuh/crypto-signal-bot` (public) | ✅ |
| Telegram Bot | `@crypsibot` | ✅ |
| Telegram Channel | `t.me/crypsibotchannel` (publik) | ✅ |
| Bot jadi Admin channel | Diangkat oleh Dhuha | ✅ |
| GitHub Secret: `TELEGRAM_BOT_TOKEN` | Token dari BotFather | ✅ |
| GitHub Secret: `TELEGRAM_CHAT_ID` | `@crypsibotchannel` | ✅ |

---

## 🔧 PHASE 1 — Fondasi Project

### File yang dibuat (urutan wajib):

**`requirements.txt`**
```
requests>=2.31.0
pandas>=2.0.0
pandas-ta>=0.3.14b
numpy>=1.24.0
scipy>=1.11.0
```

> ⚠️ Tidak menggunakan `ta-lib` karena butuh kompilasi C dan bermasalah di GitHub Actions.
> `pandas-ta` adalah pure Python, aman dipakai di environment manapun.

---

**`src/config.py`** — Konstanta global
```python
SYMBOLS      = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
TIMEFRAMES   = ['15m', '1h', '4h', '1d']
CANDLE_LIMIT = 300          # Minimum untuk EMA200 + buffer
BASE_URL     = 'https://api.binance.com'
FUTURES_URL  = 'https://fapi.binance.com'

# Threshold keputusan
MIN_CONFLUENCE_SCORE = 60   # dari 100
MIN_RR_RATIO         = 1.5  # Risk/Reward minimum
MIN_WIN_RATE         = 0.45 # Win rate historis minimum
MIN_EV               = 0.0  # Expected Value minimum (> 0)

# Backtest
BACKTEST_DAYS = 90          # Rolling window statistik
```

---

**`src/utils/logger.py`** — Logging standar
- Format: `[TIMESTAMP] [LEVEL] [MODULE] message`
- Dipakai oleh semua module sejak awal
- Output ke stdout (GitHub Actions akan capture otomatis)

---

## 📡 PHASE 2 — Data Layer

### `src/data_collector.py`

**Fungsi utama:**

| Fungsi | Endpoint Binance | Output |
|---|---|---|
| `fetch_ohlcv(symbol, tf, limit=300)` | `/api/v3/klines` | DataFrame [open,high,low,close,volume] |
| `fetch_funding_rate(symbol)` | `/fapi/v1/fundingRate` | float |
| `fetch_open_interest(symbol)` | `/fapi/v1/openInterest` | float |
| `fetch_all_data()` | semua di atas | dict nested `{symbol: {tf: df}}` |

**Aturan fetch:**

```
Setiap timeframe wajib fetch minimal 300 candle:
- 15m → 300 candle = ~75 jam data
- 1h  → 300 candle = ~12.5 hari data
- 4h  → 300 candle = ~50 hari data
- 1d  → 300 candle = ~300 hari data

Alasan: EMA200 butuh 200 candle minimum.
300 candle = EMA200 valid + 100 candle buffer.
```

**Error handling di phase ini:**
```
Jika fetch 1 symbol gagal  → log WARNING, skip symbol, lanjut
Jika fetch semua gagal     → log ERROR, kirim alert ke channel, stop pipeline
Jika respons Binance != 200 → retry 3x dengan delay 5 detik
```

**Test wajib sebelum lanjut Phase 3:**
- [ ] Print head(5) setiap DataFrame
- [ ] Cek tidak ada NaN di kolom close, volume
- [ ] Cek jumlah row = 300 untuk setiap TF
- [ ] Cek funding rate & OI berhasil di-fetch

---

## 📊 PHASE 3 — Analysis Layer

> ⚠️ Tiga modul ini **tidak menghasilkan keputusan**. Hanya kalkulasi dan scoring murni.

---

### `src/indicator_engine.py`

**Input:** DataFrame OHLCV (1 symbol, 1 timeframe)
**Output:** DataFrame yang sama + kolom indikator

| Kategori | Indikator | Catatan |
|---|---|---|
| **Trend** | EMA 21, EMA 50, EMA 200 | Wajib 300 candle |
| **Trend** | Supertrend (ATR-based) | |
| **Momentum** | RSI (14) | |
| **Momentum** | MACD (12,26,9) | |
| **Momentum** | Stochastic RSI | |
| **Volatility** | Bollinger Bands (20,2) | |
| **Volatility** | ATR (14) | Dipakai risk_manager |
| **Volume** | OBV | |
| **Volume** | MFI (Money Flow Index) | Pengganti CVD |

> ❌ **CVD dihapus dari rencana** karena kalkulasi akuratnya butuh tick data,
> bukan OHLCV. Menampilkan CVD dari OHLCV = data menyesatkan.
>
> ❌ **VWAP hanya dipakai di 15m dan 1h.**
> VWAP di 4h/1d tidak reliable karena reset harian membuat window terlalu pendek.

---

### `src/mtf_confluence.py`

**Input:** Output `indicator_engine` untuk semua 4 TF (1 symbol)
**Output:** `confluence_score` (0–100) + breakdown per TF

**Cara kalkulasi skor:**

```
Bobot per timeframe:
  1d  = 40%
  4h  = 30%
  1h  = 20%
  15m = 10%

Cek per TF (contoh untuk arah LONG):
  +1 jika EMA21 > EMA50 > EMA200 (bullish alignment)
  +1 jika RSI > 50 dan tidak overbought (< 70)
  +1 jika MACD histogram positif dan naik
  +1 jika harga di atas Bollinger mid
  Skor TF = (poin dapat / 4) × 100

Final score = Σ(skor TF × bobot TF)
```

**Threshold:** Minimum skor 60 untuk lanjut ke signal_generator.

---

### `src/market_structure.py`

**Input:** DataFrame OHLCV 4H dan 1D (1 symbol)
**Output:** dict `{structure, key_levels, derivatives_context}`

| Fungsi | Output |
|---|---|
| `detect_swing_points(df, n=5)` | List swing high & swing low |
| `classify_structure()` | `UPTREND` / `DOWNTREND` / `RANGING` |
| `find_key_levels()` | 2 support + 2 resistance terdekat dari harga saat ini |
| `read_derivatives()` | Interpretasi funding rate + OI |

**Interpretasi derivatives:**

```
Funding Rate > +0.1%  → Overheated long, bearish bias
Funding Rate < -0.1%  → Overheated short, bullish bias
OI naik + harga naik  → Trend kuat, konfirmasi long
OI naik + harga turun → Trend kuat, konfirmasi short
OI turun              → Posisi ditutup, kehati-hatian
```

---

## 🧠 PHASE 4 — Decision Layer

> ⚠️ Urutan eksekusi di phase ini **wajib berurutan** — output satu jadi input berikutnya.

---

### `src/signal_generator.py` ← Langkah 4.1

**Input:** Output Phase 3 (indicator + confluence + structure) untuk 1 symbol
**Output:** `signal_draft` dict atau `None`

**Syarat minimum untuk menghasilkan draft:**
```
confluence_score >= MIN_CONFLUENCE_SCORE (60)
structure != 'RANGING'  (kecuali ada setup range breakout eksplisit)
MFI tidak ekstrem berlawanan arah
```

**Isi `signal_draft`:**
```python
{
  'symbol'     : 'BTCUSDT',
  'direction'  : 'LONG',       # atau 'SHORT'
  'entry_low'  : 65200,
  'entry_high' : 65500,
  'tp1'        : 67000,
  'tp2'        : 68500,
  'tp3'        : 70000,
  'sl'         : 63800,
  'timeframe'  : '4h',
  'structure'  : 'UPTREND',
  'confluence' : 74,
  'atr'        : 850,
}
```

> Kalau tidak ada setup valid → return `None`, tidak lanjut ke step berikutnya.

---

### `src/statistical_validator.py` ← Langkah 4.2

**Input:** `signal_draft` + DataFrame OHLCV 4H (90 hari)
**Output:** `signal_draft` + field statistik, atau `None` kalau stats buruk

**Fungsi utama:**

```
backtest_similar_setups(df, signal_draft, window=90_hari)
  └── Loop setiap candle di 90 hari terakhir
  └── Cari kondisi serupa: arah EMA, posisi RSI, struktur
  └── Simulasi: apakah TP1 tercapai sebelum SL?
  └── Hitung: win_rate, avg_profit, avg_loss

calc_expected_value(win_rate, avg_profit, avg_loss)
  └── EV = (win_rate × avg_profit) - (loss_rate × avg_loss)

classify_confidence(win_rate, ev)
  └── HIGH   : EV > 0 AND win_rate > 0.55
  └── MEDIUM : EV > 0 AND win_rate 0.45–0.55
  └── LOW    : EV <= 0 OR win_rate < 0.45 → batalkan sinyal
```

> ⚠️ **Guard look-ahead bias WAJIB:**
> Saat mengevaluasi setup pada candle ke-N,
> hanya boleh menggunakan data candle 0 s/d N.
> Outcome dihitung dari candle N+1 ke depan.
> Pelanggaran ini akan menghasilkan win rate semu yang menyesatkan.

**Output jika lulus:**
```python
signal_draft['win_rate']   = 0.61
signal_draft['ev']         = 0.34
signal_draft['confidence'] = 'HIGH'
signal_draft['sample_n']   = 23    # jumlah setup serupa ditemukan
```

---

### `src/devil_advocate.py` ← Langkah 4.3

**Input:** `signal_draft` yang sudah ada data statistik
**Output:** `{verdict: 'APPROVED'/'REJECTED'/'MODIFIED', flags: []}`

**Checklist validasi (semua bisa dihitung dari data Binance):**

| Cek | Kondisi REJECTED |
|---|---|
| RSI divergence | Hidden bearish divergence untuk LONG (atau sebaliknya) |
| Funding rate conflict | Signal LONG tapi funding rate > +0.1% (market overextended) |
| Volume spike anomali | Volume 4H terakhir > 2.5× rata-rata 20 candle → uncertainty tinggi |
| Bollinger squeeze trap | BB width sangat sempit tapi belum ada konfirmasi breakout |
| SL terlalu dekat noise | Jarak entry ke SL < 1× ATR |
| Sample terlalu kecil | `sample_n` < 10 → statistik tidak signifikan |

**Verdict logic:**
```
0 flag   → APPROVED
1 flag   → MODIFIED (sesuaikan level entry/SL jika memungkinkan)
≥ 2 flag → REJECTED → stop, tidak kirim sinyal
```

> ❌ **Cek kalender ekonomi (FOMC, CPI) dihapus** karena tidak ada
> free API yang reliable untuk ini tanpa registrasi berbayar.

---

### `src/risk_manager.py` ← Langkah 4.4

**Input:** `signal_draft` APPROVED/MODIFIED
**Output:** `signal_final` dengan parameter risk lengkap, atau `None`

```
validate_rr()
  └── rr = (tp1 - entry_mid) / (entry_mid - sl)
  └── Jika rr < 1.5 → REJECTED

validate_sl_distance()
  └── sl_distance = abs(entry_mid - sl)
  └── Jika sl_distance < 1.0 × ATR → REJECTED (terlalu dekat noise)
  └── Jika sl_distance > 3.0 × ATR → REJECTED (SL terlalu jauh, RR rusak)

calc_position_size()
  └── Hanya kalkulasi informatif, tidak bisa tahu modal user
  └── Tampilkan sebagai: "Risiko 1% modal = X USDT per kontrak"
```

---

## 📨 PHASE 5 — Output Layer

### `src/report_formatter.py`

**Format pesan — Signal Aktif:**
```
🟢 LONG Signal — BTCUSDT
⏱ Timeframe: 4H  |  📊 Confidence: HIGH

📍 Entry Zone : 65,200 – 65,500
🎯 TP1        : 67,000  (+2.4%)
🎯 TP2        : 68,500  (+4.6%)
🎯 TP3        : 70,000  (+6.9%)
🛡 Stop Loss  : 63,800  (-2.6%)
⚖️ Risk/Reward : 1 : 2.6

📈 Struktur    : Uptrend (4H & 1D)
🔗 Confluence  : 74/100 (3 dari 4 TF sepakat)
📉 Win Rate    : 61%  (23 setup serupa, 90 hari)
💰 EV Score    : +0.34

⚡ Funding Rate : +0.02% (netral)
📦 Open Interest: Naik (konfirmasi trend)

⚠️ Bukan saran finansial. DYOR. Manajemen risiko ada di tangan Anda.
```

**Format pesan — No Trade:**
```
📊 Market Update — [TIMESTAMP UTC]

BTCUSDT  65,340  | Struktur: Uptrend  | Score: 58/100
ETHUSDT   3,210  | Struktur: Ranging  | Score: 41/100
SOLUSDT     142  | Struktur: Downtrend| Score: 33/100

⏸ Tidak ada setup valid saat ini.
Setup berikutnya dievaluasi dalam 4 jam.
```

---

### `src/utils/telegram_sender.py`

```
send_message(text, parse_mode='Markdown')
  └── POST ke https://api.telegram.org/bot{TOKEN}/sendMessage
  └── chat_id = TELEGRAM_CHAT_ID dari env variable

send_with_retry(text, max_retry=3, delay=5)
  └── Retry 3× dengan jeda 5 detik jika gagal
  └── Jika semua retry gagal → log ERROR, tidak crash program
```

---

## ⚙️ PHASE 6 — Integrasi & Deploy

### `src/orchestrator.py`

```python
def main():
    # 1. Load config & env
    # 2. fetch_all_data() — jika gagal total: kirim alert, exit
    # 3. Loop per symbol:
    #    a. run indicator_engine (semua TF)
    #    b. calc mtf_confluence
    #    c. analyze market_structure
    #    d. generate signal_draft → jika None: skip ke market update
    #    e. statistical_validator → jika LOW: skip
    #    f. devil_advocate → jika REJECTED: skip
    #    g. risk_manager → jika gagal validasi: skip
    #    h. format_report(signal_final)
    # 4. Jika ada sinyal: kirim satu per satu
    # 5. Jika tidak ada sinyal sama sekali: kirim market update
    # 6. Log ringkasan run
```

**Error handling per symbol:**
```
Setiap symbol dibungkus try/except terpisah.
Error di BTCUSDT tidak boleh menghentikan ETH dan SOL.
Semua error di-log tapi program tetap jalan sampai selesai.
```

---

### `.github/workflows/signal.yml`

```yaml
name: Crypto Signal Bot

on:
  schedule:
    - cron: '0 0,4,8,12,16,20 * * *'   # Setiap 4 jam (UTC)
  workflow_dispatch:                      # Manual trigger untuk testing

jobs:
  run-signal:
    runs-on: ubuntu-latest
    timeout-minutes: 15                   # Paksa stop jika macet

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run signal pipeline
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID:   ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python src/orchestrator.py
```

---

## ✅ Master Checklist Pengerjaan

### Phase 0 — Setup ✅ DONE
- [x] GitHub repo public dibuat
- [x] Telegram bot `@crypsibot` dibuat
- [x] Channel `t.me/crypsibotchannel` dibuat
- [x] Bot diangkat jadi admin channel
- [x] GitHub Secrets: `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` disimpan

### Phase 1 — Fondasi
- [ ] `requirements.txt` dibuat
- [ ] `src/config.py` dibuat
- [ ] `src/utils/logger.py` dibuat

### Phase 2 — Data Layer
- [ ] `src/data_collector.py` dibuat
- [ ] Test: semua DataFrame 300 baris, tidak ada NaN
- [ ] Test: funding rate & OI berhasil di-fetch

### Phase 3 — Analysis Layer
- [ ] `src/indicator_engine.py` dibuat
- [ ] Test: nilai indikator diverifikasi manual vs TradingView
- [ ] `src/mtf_confluence.py` dibuat
- [ ] Test: skor trending vs sideways berbeda signifikan
- [ ] `src/market_structure.py` dibuat
- [ ] Test: structure detection akurat pada data historis

### Phase 4 — Decision Layer
- [ ] `src/signal_generator.py` dibuat
- [ ] `src/statistical_validator.py` dibuat — **guard look-ahead bias aktif**
- [ ] `src/devil_advocate.py` dibuat
- [ ] `src/risk_manager.py` dibuat
- [ ] Test end-to-end 1 symbol: dari data mentah sampai keputusan final

### Phase 5 — Output Layer
- [ ] `src/report_formatter.py` dibuat
- [ ] `src/utils/telegram_sender.py` dibuat
- [ ] Test: pesan terkirim ke channel, format benar

### Phase 6 — Deploy
- [ ] `src/orchestrator.py` dibuat
- [ ] `.github/workflows/signal.yml` dibuat
- [ ] Test: `workflow_dispatch` manual berhasil
- [ ] Monitor 3 run otomatis pertama
- [ ] Verifikasi: tidak ada silent fail

---

## ⚠️ Aturan Tidak Boleh Dilanggar

1. **Jangan lanjut ke phase berikutnya sebelum test phase sebelumnya lulus.**
2. **Jangan tampilkan CVD** — data tidak akurat dari OHLCV.
3. **Jangan pakai VWAP di 4H dan 1D** — misleading karena reset harian.
4. **Statistical validator wajib punya guard look-ahead bias** — tanpa ini, win rate yang ditampilkan ke user adalah palsu.
5. **Setiap sinyal wajib menyertakan disclaimer** — ini bukan saran finansial.
6. **Minimum sample backtest = 10 setup** — di bawah itu, statistik tidak signifikan dan tidak boleh ditampilkan.
7. **Setiap symbol harus di-handle secara independen** — satu error tidak boleh membunuh seluruh pipeline.

---

*Dokumen ini adalah rencana final setelah review dan koreksi arsitektur.*
*Revisi terakhir: Juni 2026*
