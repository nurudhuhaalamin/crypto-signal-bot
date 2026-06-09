# =============================================================================
# config.py — Konstanta Global
# Semua parameter ada di sini. Tidak boleh ada angka hardcoded di modul lain.
# =============================================================================

# --- Target Asset & Timeframe ---
SYMBOLS      = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
TIMEFRAMES   = ['15m', '1h', '4h', '1d']
CANDLE_LIMIT = 800          # EMA200 warmup (200) + backtest 90 hari × 6 candle/hari (540) + buffer (60)

# --- OKX API ---
# OKX public API dapat diakses dari GitHub Actions tanpa blokir.
# Semua data futures (OHLCV, Funding Rate, Open Interest) tersedia gratis.
FUTURES_URL  = 'https://www.okx.com'

# Mapping symbol internal → instId OKX (USDT Perpetual Swap)
SYMBOL_MAP = {
    'BTCUSDT': 'BTC-USDT-SWAP',
    'ETHUSDT': 'ETH-USDT-SWAP',
    'SOLUSDT': 'SOL-USDT-SWAP',
}

# Mapping timeframe bot → format bar OKX
TIMEFRAME_MAP = {
    '15m': '15m',
    '1h':  '1H',
    '4h':  '4H',
    '1d':  '1D',
}

# --- Parameter Indikator ---
EMA_FAST              = 21
EMA_MID               = 50
EMA_SLOW              = 200

RSI_PERIOD            = 14

MACD_FAST             = 12
MACD_SLOW             = 26
MACD_SIGNAL           = 9

BB_PERIOD             = 20
BB_STD                = 2

ATR_PERIOD            = 14
MFI_PERIOD            = 14
OBV_MA_PERIOD         = 20   # MA dari OBV untuk konfirmasi tren volume

SUPERTREND_PERIOD     = 10
SUPERTREND_MULTIPLIER = 3.0

STOCHRSI_PERIOD       = 14
STOCHRSI_SMOOTH_K     = 3
STOCHRSI_SMOOTH_D     = 3

# --- Threshold Keputusan ---
MIN_CONFLUENCE_SCORE  = 60   # Skor minimum (0–100) untuk lanjut ke signal_generator
MIN_RR_RATIO          = 1.5  # Risk/Reward ratio minimum
MIN_WIN_RATE          = 0.45 # Win rate historis minimum (45%)
MIN_EV                = 0.0  # Expected Value minimum (harus positif)
MIN_SAMPLE_N          = 10   # Minimum setup serupa agar statistik valid

# --- Backtest ---
BACKTEST_DAYS         = 90   # Rolling window statistik (hari)

# --- Rate Limiting ke OKX ---
API_CALL_DELAY_SEC    = 0.3  # Jeda antar request (cegah rate limit)
API_RETRY_COUNT       = 3    # Jumlah retry jika request gagal
API_RETRY_DELAY_SEC   = 5    # Jeda antar retry (detik)

# --- Threshold Devil Advocate ---
BB_SQUEEZE_PERCENTILE = 20   # BB dianggap squeeze jika width < persentil ke-20
                              # dari 50 candle terakhir
VOLUME_SPIKE_MULT     = 2.5  # Volume anomali jika > 2.5× rata-rata 20 candle
FUNDING_RATE_EXTREME  = 0.001  # ±0.1% dalam desimal (threshold overheated)

# --- Definisi "Setup Serupa" untuk Statistical Validator ---
RSI_SIMILARITY_RANGE  = 10   # RSI dianggap serupa jika selisih <= 10 poin
                              # Contoh: RSI sinyal = 58 → cari historis RSI 48–68
