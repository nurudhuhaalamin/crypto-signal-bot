# =============================================================================
# data_collector.py — Data Layer
# Fetch semua data market dari OKX Futures API (USDT Perpetual Swap).
# OKX public API dapat diakses dari GitHub Actions tanpa blokir IP.
# Data yang diambil: OHLCV, Funding Rate, Open Interest — sama dengan sebelumnya.
# =============================================================================

import time
import requests
import pandas as pd

from config import (
    SYMBOLS, TIMEFRAMES, CANDLE_LIMIT, FUTURES_URL,
    SYMBOL_MAP, TIMEFRAME_MAP,
    API_CALL_DELAY_SEC, API_RETRY_COUNT, API_RETRY_DELAY_SEC
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Header standar agar request tidak dianggap bot primitif
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; CryptoSignalBot/1.0)',
    'Accept':     'application/json',
}


# =============================================================================
# Helper: Request dengan Retry
# =============================================================================

def _get(endpoint: str, params: dict) -> dict:
    """
    Kirim GET request ke OKX API dengan retry otomatis.
    OKX mengembalikan code='0' jika sukses.
    Jika semua retry gagal, raise Exception.
    """
    url = FUTURES_URL + endpoint

    for attempt in range(1, API_RETRY_COUNT + 1):
        try:
            response = requests.get(url, params=params, headers=_HEADERS, timeout=15)

            if response.status_code == 200:
                data = response.json()
                # OKX: code '0' = sukses (string, bukan integer)
                if data.get('code') == '0':
                    return data
                raise Exception(
                    f"OKX API error — code {data.get('code')}: "
                    f"{data.get('msg', 'unknown')}"
                )

            logger.warning(
                f"HTTP {response.status_code} dari {endpoint} "
                f"(attempt {attempt}/{API_RETRY_COUNT})"
            )

        except requests.exceptions.RequestException as e:
            logger.warning(
                f"Request error ke {endpoint}: {e} "
                f"(attempt {attempt}/{API_RETRY_COUNT})"
            )

        if attempt < API_RETRY_COUNT:
            time.sleep(API_RETRY_DELAY_SEC)

    raise Exception(f"Gagal fetch {endpoint} setelah {API_RETRY_COUNT} kali retry.")


# =============================================================================
# Fetch OHLCV
# =============================================================================

def fetch_ohlcv(symbol: str, tf: str, limit: int = CANDLE_LIMIT) -> pd.DataFrame:
    """
    Fetch data candlestick (OHLCV) dari OKX Futures.

    Return:
        DataFrame dengan kolom: open, high, low, close, volume
        Index: datetime UTC
    """
    inst_id  = SYMBOL_MAP[symbol]
    bar      = TIMEFRAME_MAP[tf]

    logger.info(f"Fetching OHLCV {symbol} {tf} ({limit} candles) dari OKX...")

    data = _get('/api/v5/market/candles', {
        'instId': inst_id,
        'bar':    bar,
        'limit':  limit,
    })

    # OKX candles: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    # Urutan: TERBARU dulu → harus di-reverse agar ascending
    raw = data['data']
    if not raw:
        raise Exception(f"OKX mengembalikan data kosong untuk {symbol} {tf}")

    raw = list(reversed(raw))

    df = pd.DataFrame(raw, columns=[
        'open_time', 'open', 'high', 'low', 'close',
        'volume', 'vol_ccy', 'vol_ccy_quote', 'confirm'
    ])

    df['open_time'] = pd.to_datetime(df['open_time'].astype('int64'), unit='ms', utc=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)

    df = df.set_index('open_time')
    df = df[['open', 'high', 'low', 'close', 'volume']]

    logger.info(
        f"OHLCV {symbol} {tf} — {len(df)} candles, "
        f"dari {df.index[0]} s/d {df.index[-1]}"
    )

    return df


# =============================================================================
# Fetch Funding Rate
# =============================================================================

def fetch_funding_rate(symbol: str) -> float:
    """
    Fetch funding rate terbaru untuk satu symbol dari OKX.

    Return:
        float — funding rate (contoh: 0.0001 = +0.01%)
        Positif = long bayar short
        Negatif = short bayar long
    """
    inst_id = SYMBOL_MAP[symbol]
    logger.info(f"Fetching funding rate {symbol} dari OKX...")

    data = _get('/api/v5/public/funding-rate', {'instId': inst_id})

    rate = float(data['data'][0]['fundingRate'])
    logger.info(f"Funding rate {symbol}: {rate:+.4%}")
    return rate


# =============================================================================
# Fetch Open Interest
# =============================================================================

def fetch_open_interest(symbol: str) -> float:
    """
    Fetch open interest terbaru untuk satu symbol dari OKX.

    Return:
        float — open interest dalam satuan kontrak (base currency)
    """
    inst_id = SYMBOL_MAP[symbol]
    logger.info(f"Fetching open interest {symbol} dari OKX...")

    data = _get('/api/v5/public/open-interest', {'instId': inst_id})

    # 'oi' = open interest dalam kontrak (base currency, misal BTC untuk BTC-USDT-SWAP)
    oi = float(data['data'][0]['oi'])
    logger.info(f"Open interest {symbol}: {oi:,.2f}")
    return oi


# =============================================================================
# Fetch All Data (Entry Point Utama)
# =============================================================================

def fetch_all_data() -> dict:
    """
    Fetch semua data yang dibutuhkan pipeline untuk semua symbol dan timeframe.

    Return:
        dict dengan struktur:
        {
            'BTCUSDT': {
                'ohlcv': {
                    '15m': DataFrame,
                    '1h':  DataFrame,
                    '4h':  DataFrame,
                    '1d':  DataFrame,
                },
                'funding_rate': float,
                'open_interest': float,
            },
            ...
        }

        Symbol yang gagal di-fetch akan di-skip.
        Jika semua symbol gagal, return dict kosong {}.
    """
    logger.info("=== Memulai fetch semua data market (OKX) ===")
    all_data = {}
    failed_symbols = []

    for symbol in SYMBOLS:
        try:
            logger.info(f"--- Fetching data untuk {symbol} ---")
            symbol_data = {'ohlcv': {}}

            for tf in TIMEFRAMES:
                symbol_data['ohlcv'][tf] = fetch_ohlcv(symbol, tf)
                time.sleep(API_CALL_DELAY_SEC)

            symbol_data['funding_rate']  = fetch_funding_rate(symbol)
            time.sleep(API_CALL_DELAY_SEC)

            symbol_data['open_interest'] = fetch_open_interest(symbol)
            time.sleep(API_CALL_DELAY_SEC)

            all_data[symbol] = symbol_data
            logger.info(f"✅ {symbol} — semua data berhasil di-fetch")

        except Exception as e:
            logger.warning(f"⚠️ Gagal fetch data untuk {symbol}: {e} — symbol di-skip")
            failed_symbols.append(symbol)

    total   = len(SYMBOLS)
    success = len(all_data)
    logger.info(f"=== Fetch selesai: {success}/{total} symbol berhasil ===")

    if failed_symbols:
        logger.warning(f"Symbol yang di-skip: {failed_symbols}")

    if success == 0:
        logger.error("Semua symbol gagal di-fetch. Pipeline dihentikan.")
        return {}

    return all_data


# =============================================================================
# Validasi Data
# =============================================================================

def validate_data(all_data: dict) -> bool:
    """
    Validasi dasar semua DataFrame yang sudah di-fetch.

    Return:
        True jika semua valid, False jika ada masalah kritis.
    """
    logger.info("Memvalidasi data yang sudah di-fetch...")
    passed = True

    for symbol, data in all_data.items():
        for tf, df in data['ohlcv'].items():

            if len(df) < CANDLE_LIMIT:
                logger.warning(
                    f"{symbol} {tf}: hanya {len(df)} candles "
                    f"(minimum {CANDLE_LIMIT})"
                )
                passed = False

            nan_cols = df[['close', 'volume']].isnull().any()
            if nan_cols.any():
                logger.warning(
                    f"{symbol} {tf}: NaN ditemukan di kolom "
                    f"{nan_cols[nan_cols].index.tolist()}"
                )
                passed = False

        fr = data.get('funding_rate')
        if fr is None or not isinstance(fr, float):
            logger.warning(f"{symbol}: funding_rate tidak valid ({fr})")
            passed = False

        oi = data.get('open_interest')
        if oi is None or not isinstance(oi, float) or oi <= 0:
            logger.warning(f"{symbol}: open_interest tidak valid ({oi})")
            passed = False

    if passed:
        logger.info("✅ Semua data valid.")
    else:
        logger.warning("⚠️ Ada data yang tidak valid. Cek log di atas.")

    return passed
