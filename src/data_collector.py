# =============================================================================
# data_collector.py — Data Layer
# Fetch semua data market dari Binance Futures API.
# Semua endpoint dari fapi.binance.com agar OHLCV konsisten
# dengan Funding Rate dan Open Interest.
# =============================================================================

import time
import requests
import pandas as pd

from config import (
    SYMBOLS, TIMEFRAMES, CANDLE_LIMIT, FUTURES_URL,
    API_CALL_DELAY_SEC, API_RETRY_COUNT, API_RETRY_DELAY_SEC
)
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Helper: Request dengan Retry
# =============================================================================

def _get(endpoint: str, params: dict) -> dict | list:
    """
    Kirim GET request ke Binance Futures API dengan retry otomatis.
    Jika semua retry gagal, raise Exception.
    """
    url = FUTURES_URL + endpoint

    for attempt in range(1, API_RETRY_COUNT + 1):
        try:
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                return response.json()

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
    Fetch data candlestick (OHLCV) dari Binance Futures.

    Return:
        DataFrame dengan kolom: open, high, low, close, volume
        Index: datetime UTC
    """
    logger.info(f"Fetching OHLCV {symbol} {tf} ({limit} candles)...")

    raw = _get('/fapi/v1/klines', {
        'symbol': symbol,
        'interval': tf,
        'limit': limit
    })

    # Binance klines: [open_time, open, high, low, close, volume, ...]
    df = pd.DataFrame(raw, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])

    # Konversi tipe data
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)

    df = df.set_index('open_time')
    df = df[['open', 'high', 'low', 'close', 'volume']]

    logger.info(f"OHLCV {symbol} {tf} — {len(df)} candles, "
                f"dari {df.index[0]} s/d {df.index[-1]}")

    return df


# =============================================================================
# Fetch Funding Rate
# =============================================================================

def fetch_funding_rate(symbol: str) -> float:
    """
    Fetch funding rate terbaru untuk satu symbol.

    Return:
        float — funding rate (contoh: 0.0001 = +0.01%)
        Positif = long bayar short (pasar overheated long)
        Negatif = short bayar long (pasar overheated short)
    """
    logger.info(f"Fetching funding rate {symbol}...")

    raw = _get('/fapi/v1/fundingRate', {
        'symbol': symbol,
        'limit': 1
    })

    rate = float(raw[-1]['fundingRate'])
    logger.info(f"Funding rate {symbol}: {rate:+.4%}")
    return rate


# =============================================================================
# Fetch Open Interest
# =============================================================================

def fetch_open_interest(symbol: str) -> float:
    """
    Fetch open interest terbaru untuk satu symbol.

    Return:
        float — jumlah kontrak open interest saat ini
        Naik + harga naik   → trend kuat, konfirmasi long
        Naik + harga turun  → trend kuat, konfirmasi short
        Turun               → posisi ditutup, hati-hati
    """
    logger.info(f"Fetching open interest {symbol}...")

    raw = _get('/fapi/v1/openInterest', {'symbol': symbol})

    oi = float(raw['openInterest'])
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
            'ETHUSDT': { ... },
            'SOLUSDT': { ... },
        }

        Symbol yang gagal di-fetch akan di-skip (tidak masuk dict).
        Jika semua symbol gagal, return dict kosong {}.
    """
    logger.info("=== Memulai fetch semua data market ===")
    all_data = {}
    failed_symbols = []

    for symbol in SYMBOLS:
        try:
            logger.info(f"--- Fetching data untuk {symbol} ---")
            symbol_data = {'ohlcv': {}}

            # Fetch OHLCV untuk setiap timeframe
            for tf in TIMEFRAMES:
                symbol_data['ohlcv'][tf] = fetch_ohlcv(symbol, tf)
                time.sleep(API_CALL_DELAY_SEC)  # Rate limit guard

            # Fetch Funding Rate
            symbol_data['funding_rate'] = fetch_funding_rate(symbol)
            time.sleep(API_CALL_DELAY_SEC)

            # Fetch Open Interest
            symbol_data['open_interest'] = fetch_open_interest(symbol)
            time.sleep(API_CALL_DELAY_SEC)

            all_data[symbol] = symbol_data
            logger.info(f"✅ {symbol} — semua data berhasil di-fetch")

        except Exception as e:
            logger.warning(f"⚠️ Gagal fetch data untuk {symbol}: {e} — symbol di-skip")
            failed_symbols.append(symbol)

    # Evaluasi hasil
    total = len(SYMBOLS)
    success = len(all_data)
    logger.info(f"=== Fetch selesai: {success}/{total} symbol berhasil ===")

    if failed_symbols:
        logger.warning(f"Symbol yang di-skip: {failed_symbols}")

    if success == 0:
        logger.error("Semua symbol gagal di-fetch. Pipeline dihentikan.")
        # Return dict kosong — orchestrator.py yang akan handle alert & exit
        return {}

    return all_data


# =============================================================================
# Validasi Data (dipanggil setelah fetch_all_data)
# =============================================================================

def validate_data(all_data: dict) -> bool:
    """
    Validasi dasar semua DataFrame yang sudah di-fetch.
    Cek: jumlah baris, tidak ada NaN, tipe data benar.

    Return:
        True jika semua valid, False jika ada masalah kritis.
    """
    logger.info("Memvalidasi data yang sudah di-fetch...")
    passed = True

    for symbol, data in all_data.items():
        for tf, df in data['ohlcv'].items():

            # Cek jumlah baris
            if len(df) < CANDLE_LIMIT:
                logger.warning(
                    f"{symbol} {tf}: hanya {len(df)} candles "
                    f"(minimum {CANDLE_LIMIT})"
                )
                passed = False

            # Cek NaN di kolom kritis
            nan_cols = df[['close', 'volume']].isnull().any()
            if nan_cols.any():
                logger.warning(
                    f"{symbol} {tf}: NaN ditemukan di kolom "
                    f"{nan_cols[nan_cols].index.tolist()}"
                )
                passed = False

        # Cek funding rate valid
        fr = data.get('funding_rate')
        if fr is None or not isinstance(fr, float):
            logger.warning(f"{symbol}: funding_rate tidak valid ({fr})")
            passed = False

        # Cek open interest valid
        oi = data.get('open_interest')
        if oi is None or not isinstance(oi, float) or oi <= 0:
            logger.warning(f"{symbol}: open_interest tidak valid ({oi})")
            passed = False

    if passed:
        logger.info("✅ Semua data valid.")
    else:
        logger.warning("⚠️ Ada data yang tidak valid. Cek log di atas.")

    return passed
