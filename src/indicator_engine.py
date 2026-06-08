# =============================================================================
# indicator_engine.py — Analysis Layer (1/3)
# Kalkulasi semua indikator teknikal untuk satu DataFrame OHLCV.
# Input : DataFrame OHLCV (1 symbol, 1 timeframe)
# Output: DataFrame yang sama + kolom indikator tambahan
# =============================================================================

import numpy as np
import pandas as pd
import ta

from config import (
    EMA_FAST, EMA_MID, EMA_SLOW,
    RSI_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD,
    ATR_PERIOD,
    MFI_PERIOD,
    OBV_MA_PERIOD,
    SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER,
    STOCHRSI_PERIOD, STOCHRSI_SMOOTH_K, STOCHRSI_SMOOTH_D
)
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Supertrend (implementasi manual — tidak tersedia di library ta)
# =============================================================================

def _calc_supertrend(df: pd.DataFrame, period: int, multiplier: float) -> pd.Series:
    """
    Hitung Supertrend. Return Series berisi 1 (bullish) atau -1 (bearish).

    Cara kerja:
      - Hitung ATR
      - Upper band = midprice + multiplier × ATR
      - Lower band = midprice - multiplier × ATR
      - Arah ditentukan dari posisi harga vs band terakhir
    """
    high = df['high']
    low  = df['low']
    close = df['close']

    # ATR
    atr = ta.volatility.average_true_range(high, low, close, window=period)

    mid = (high + low) / 2
    upper = mid + multiplier * atr
    lower = mid - multiplier * atr

    supertrend = pd.Series(index=df.index, dtype=float)
    direction  = pd.Series(index=df.index, dtype=float)

    for i in range(1, len(df)):
        # Update upper band — tidak boleh naik kalau sebelumnya sudah turun
        if upper.iloc[i] < upper.iloc[i - 1] or close.iloc[i - 1] > upper.iloc[i - 1]:
            final_upper = upper.iloc[i]
        else:
            final_upper = upper.iloc[i - 1]

        # Update lower band — tidak boleh turun kalau sebelumnya sudah naik
        if lower.iloc[i] > lower.iloc[i - 1] or close.iloc[i - 1] < lower.iloc[i - 1]:
            final_lower = lower.iloc[i]
        else:
            final_lower = lower.iloc[i - 1]

        # Tentukan arah
        prev_dir = direction.iloc[i - 1] if i > 1 else 1
        if prev_dir == -1 and close.iloc[i] > final_upper:
            direction.iloc[i] = 1   # Bullish
        elif prev_dir == 1 and close.iloc[i] < final_lower:
            direction.iloc[i] = -1  # Bearish
        else:
            direction.iloc[i] = prev_dir

        supertrend.iloc[i] = final_lower if direction.iloc[i] == 1 else final_upper

    return direction


# =============================================================================
# Fungsi Utama
# =============================================================================

def calculate_indicators(df: pd.DataFrame, timeframe: str = '') -> pd.DataFrame:
    """
    Tambahkan semua kolom indikator ke DataFrame OHLCV.

    Parameter:
        df          : DataFrame dengan kolom open, high, low, close, volume
        timeframe   : string opsional untuk logging ('15m', '1h', dst.)

    Return:
        DataFrame yang sama + kolom indikator baru.
        Baris awal yang mengandung NaN (karena warmup indikator) di-drop.
    """
    tf_label = f" [{timeframe}]" if timeframe else ""
    logger.info(f"Kalkulasi indikator{tf_label} — {len(df)} candles input")

    result = df.copy()
    close  = result['close']
    high   = result['high']
    low    = result['low']
    volume = result['volume']

    # -------------------------------------------------------------------------
    # TREND — EMA
    # -------------------------------------------------------------------------
    result['ema_fast'] = ta.trend.ema_indicator(close, window=EMA_FAST)
    result['ema_mid']  = ta.trend.ema_indicator(close, window=EMA_MID)
    result['ema_slow'] = ta.trend.ema_indicator(close, window=EMA_SLOW)

    # -------------------------------------------------------------------------
    # TREND — Supertrend
    # -------------------------------------------------------------------------
    result['supertrend_dir'] = _calc_supertrend(
        result, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER
    )
    # 1 = bullish, -1 = bearish

    # -------------------------------------------------------------------------
    # MOMENTUM — RSI
    # -------------------------------------------------------------------------
    result['rsi'] = ta.momentum.rsi(close, window=RSI_PERIOD)

    # -------------------------------------------------------------------------
    # MOMENTUM — MACD
    # -------------------------------------------------------------------------
    macd_obj = ta.trend.MACD(
        close,
        window_fast=MACD_FAST,
        window_slow=MACD_SLOW,
        window_sign=MACD_SIGNAL
    )
    result['macd']        = macd_obj.macd()
    result['macd_signal'] = macd_obj.macd_signal()
    result['macd_hist']   = macd_obj.macd_diff()   # histogram = macd - signal

    # -------------------------------------------------------------------------
    # MOMENTUM — Stochastic RSI
    # -------------------------------------------------------------------------
    stochrsi_obj = ta.momentum.StochRSIIndicator(
        close,
        window=STOCHRSI_PERIOD,
        smooth1=STOCHRSI_SMOOTH_K,
        smooth2=STOCHRSI_SMOOTH_D
    )
    result['stochrsi_k'] = stochrsi_obj.stochrsi_k()
    result['stochrsi_d'] = stochrsi_obj.stochrsi_d()

    # -------------------------------------------------------------------------
    # VOLATILITY — Bollinger Bands
    # -------------------------------------------------------------------------
    bb_obj = ta.volatility.BollingerBands(
        close, window=BB_PERIOD, window_dev=BB_STD
    )
    result['bb_upper'] = bb_obj.bollinger_hband()
    result['bb_mid']   = bb_obj.bollinger_mavg()
    result['bb_lower'] = bb_obj.bollinger_lband()
    result['bb_width'] = bb_obj.bollinger_wband()  # (upper-lower)/mid × 100

    # -------------------------------------------------------------------------
    # VOLATILITY — ATR
    # -------------------------------------------------------------------------
    result['atr'] = ta.volatility.average_true_range(
        high, low, close, window=ATR_PERIOD
    )

    # -------------------------------------------------------------------------
    # VOLUME — OBV
    # -------------------------------------------------------------------------
    result['obv']    = ta.volume.on_balance_volume(close, volume)
    result['obv_ma'] = result['obv'].rolling(window=OBV_MA_PERIOD).mean()
    # obv > obv_ma → volume mendukung tren; obv < obv_ma → volume melemah

    # -------------------------------------------------------------------------
    # VOLUME — MFI (Money Flow Index, pengganti CVD)
    # -------------------------------------------------------------------------
    result['mfi'] = ta.volume.money_flow_index(
        high, low, close, volume, window=MFI_PERIOD
    )

    # -------------------------------------------------------------------------
    # Drop baris awal yang NaN (warmup indikator)
    # EMA200 butuh 200 candle, jadi baris 0–199 akan NaN
    # -------------------------------------------------------------------------
    before = len(result)
    result = result.dropna(subset=['ema_slow', 'rsi', 'macd', 'atr', 'mfi'])
    after = len(result)

    logger.info(
        f"Indikator selesai{tf_label} — "
        f"{after} candles valid (drop {before - after} warmup rows)"
    )

    return result
