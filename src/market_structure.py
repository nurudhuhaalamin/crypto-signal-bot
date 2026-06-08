# =============================================================================
# market_structure.py — Analysis Layer (3/3)
# Deteksi struktur pasar, key levels, dan interpretasi data derivatives.
# Input : DataFrame OHLCV 4H dan 1D (sudah ada indikator), funding_rate, OI
# Output: dict {structure, key_levels, derivatives_context, conflict_penalty}
# =============================================================================

import numpy as np
import pandas as pd

from config import FUNDING_RATE_EXTREME
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Swing Point Detection
# =============================================================================

def detect_swing_points(df: pd.DataFrame, n: int = 5) -> dict:
    """
    Temukan titik swing high dan swing low dalam DataFrame.

    Sebuah candle dianggap swing high jika high-nya lebih tinggi
    dari n candle di kiri dan n candle di kanannya.
    Begitu juga sebaliknya untuk swing low.

    Parameter:
        df : DataFrame OHLCV
        n  : jumlah candle kiri dan kanan sebagai pembanding (default 5)

    Return:
        {
            'swing_highs': list of (index, price),
            'swing_lows':  list of (index, price),
        }
    """
    swing_highs = []
    swing_lows  = []

    for i in range(n, len(df) - n):
        window_high = df['high'].iloc[i - n: i + n + 1]
        window_low  = df['low'].iloc[i - n: i + n + 1]

        if df['high'].iloc[i] == window_high.max():
            swing_highs.append((df.index[i], df['high'].iloc[i]))

        if df['low'].iloc[i] == window_low.min():
            swing_lows.append((df.index[i], df['low'].iloc[i]))

    logger.debug(
        f"Swing points: {len(swing_highs)} highs, {len(swing_lows)} lows"
    )

    return {
        'swing_highs': swing_highs,
        'swing_lows':  swing_lows,
    }


# =============================================================================
# Klasifikasi Struktur Pasar
# =============================================================================

def classify_structure(df: pd.DataFrame, tf: str = '') -> str:
    """
    Tentukan apakah pasar sedang UPTREND, DOWNTREND, atau RANGING.

    Logika:
      - Ambil 3 swing high dan 3 swing low terakhir
      - UPTREND   : swing highs naik DAN swing lows naik (Higher High, Higher Low)
      - DOWNTREND : swing highs turun DAN swing lows turun (Lower High, Lower Low)
      - RANGING   : pola tidak konsisten

    Return:
        'UPTREND' | 'DOWNTREND' | 'RANGING'
    """
    tf_label = f" [{tf}]" if tf else ""
    swings = detect_swing_points(df)

    highs = [price for _, price in swings['swing_highs'][-3:]]
    lows  = [price for _, price in swings['swing_lows'][-3:]]

    if len(highs) < 2 or len(lows) < 2:
        logger.warning(f"Swing points tidak cukup{tf_label} — default RANGING")
        return 'RANGING'

    hh = all(highs[i] > highs[i - 1] for i in range(1, len(highs)))  # Higher Highs
    hl = all(lows[i]  > lows[i - 1]  for i in range(1, len(lows)))   # Higher Lows
    lh = all(highs[i] < highs[i - 1] for i in range(1, len(highs)))  # Lower Highs
    ll = all(lows[i]  < lows[i - 1]  for i in range(1, len(lows)))   # Lower Lows

    if hh and hl:
        structure = 'UPTREND'
    elif lh and ll:
        structure = 'DOWNTREND'
    else:
        structure = 'RANGING'

    logger.info(f"Struktur{tf_label}: {structure}")
    return structure


# =============================================================================
# Key Levels (Support & Resistance)
# =============================================================================

def find_key_levels(df: pd.DataFrame, current_price: float) -> dict:
    """
    Temukan 2 level support dan 2 level resistance terdekat dari harga saat ini.

    Cara kerja:
      - Kumpulkan semua swing high → kandidat resistance
      - Kumpulkan semua swing low  → kandidat support
      - Filter: resistance hanya yang di atas current_price
      - Filter: support hanya yang di bawah current_price
      - Ambil 2 yang paling dekat dari masing-masing sisi

    Return:
        {
            'resistance': [harga_r1, harga_r2],  ← terdekat hingga terjauh
            'support':    [harga_s1, harga_s2],  ← terdekat hingga terjauh
        }
    """
    swings = detect_swing_points(df)

    all_highs = [price for _, price in swings['swing_highs']]
    all_lows  = [price for _, price in swings['swing_lows']]

    resistances = sorted([p for p in all_highs if p > current_price])
    supports    = sorted([p for p in all_lows  if p < current_price], reverse=True)

    result = {
        'resistance': resistances[:2] if len(resistances) >= 2 else resistances,
        'support':    supports[:2]    if len(supports) >= 2    else supports,
    }

    logger.info(
        f"Key levels (harga: {current_price:,.2f}) — "
        f"R: {[round(p, 2) for p in result['resistance']]} | "
        f"S: {[round(p, 2) for p in result['support']]}"
    )

    return result


# =============================================================================
# Interpretasi Derivatives
# =============================================================================

def read_derivatives(funding_rate: float, open_interest: float,
                     prev_open_interest: float | None,
                     current_price: float, prev_price: float | None) -> dict:
    """
    Interpretasikan Funding Rate dan Open Interest.

    Parameter:
        funding_rate      : float, misal 0.0001 = +0.01%
        open_interest     : float, OI saat ini
        prev_open_interest: float atau None, OI sebelumnya (4 jam lalu)
        current_price     : float
        prev_price        : float atau None

    Return:
        {
            'funding_label'  : 'NETRAL' | 'OVERHEATED_LONG' | 'OVERHEATED_SHORT',
            'funding_bias'   : 'BULLISH' | 'BEARISH' | 'NEUTRAL',
            'oi_label'       : 'NAIK' | 'TURUN' | 'STABIL',
            'oi_signal'      : string deskripsi,
            'summary'        : string ringkasan untuk output Telegram,
        }
    """
    # --- Funding Rate ---
    if funding_rate > FUNDING_RATE_EXTREME:
        funding_label = 'OVERHEATED_LONG'
        funding_bias  = 'BEARISH'   # Terlalu banyak long → rentan reversal turun
    elif funding_rate < -FUNDING_RATE_EXTREME:
        funding_label = 'OVERHEATED_SHORT'
        funding_bias  = 'BULLISH'   # Terlalu banyak short → rentan reversal naik
    else:
        funding_label = 'NETRAL'
        funding_bias  = 'NEUTRAL'

    # --- Open Interest ---
    if prev_open_interest is not None and prev_price is not None:
        oi_change    = open_interest - prev_open_interest
        price_change = current_price - prev_price

        if oi_change > 0 and price_change > 0:
            oi_label  = 'NAIK'
            oi_signal = 'OI naik + harga naik → trend kuat, konfirmasi long'
        elif oi_change > 0 and price_change < 0:
            oi_label  = 'NAIK'
            oi_signal = 'OI naik + harga turun → trend turun kuat, konfirmasi short'
        elif oi_change < 0:
            oi_label  = 'TURUN'
            oi_signal = 'OI turun → posisi ditutup, hati-hati'
        else:
            oi_label  = 'STABIL'
            oi_signal = 'OI stabil → tidak ada sinyal tambahan'
    else:
        oi_label  = 'STABIL'
        oi_signal = 'Data OI sebelumnya tidak tersedia'

    # --- Summary ---
    fr_pct  = funding_rate * 100
    summary = (
        f"FR: {fr_pct:+.4f}% ({funding_label}) | OI: {oi_label} ({oi_signal})"
    )

    logger.info(f"Derivatives — {summary}")

    return {
        'funding_label': funding_label,
        'funding_bias':  funding_bias,
        'oi_label':      oi_label,
        'oi_signal':     oi_signal,
        'summary':       summary,
    }


# =============================================================================
# Resolusi Konflik 4H vs 1D
# =============================================================================

def resolve_structure_conflict(structure_4h: str, structure_1d: str) -> dict:
    """
    Tentukan arah sinyal yang diizinkan berdasarkan aturan resolusi konflik
    antara timeframe 4H dan 1D.

    Aturan:
      - 1D adalah acuan utama (tren besar)
      - 4H adalah konteks entry timing
      - Sinyal hanya dibuat jika 1D dan 4H SEPAKAT

    Return:
        {
            'allowed_direction': 'LONG' | 'SHORT' | None,
            'confluence_penalty': int,   ← penalti skor (0 atau 10)
            'reason': string,
        }
    """
    logger.info(
        f"Resolusi konflik struktur — 1D: {structure_1d} | 4H: {structure_4h}"
    )

    # Keduanya sepakat UPTREND → boleh LONG
    if structure_1d == 'UPTREND' and structure_4h == 'UPTREND':
        return {
            'allowed_direction': 'LONG',
            'confluence_penalty': 0,
            'reason': '1D dan 4H sama-sama UPTREND'
        }

    # Keduanya sepakat DOWNTREND → boleh SHORT
    if structure_1d == 'DOWNTREND' and structure_4h == 'DOWNTREND':
        return {
            'allowed_direction': 'SHORT',
            'confluence_penalty': 0,
            'reason': '1D dan 4H sama-sama DOWNTREND'
        }

    # 1D UPTREND tapi 4H RANGING → boleh LONG dengan penalti skor
    if structure_1d == 'UPTREND' and structure_4h == 'RANGING':
        return {
            'allowed_direction': 'LONG',
            'confluence_penalty': 10,
            'reason': '1D UPTREND tapi 4H RANGING — skor dikurangi 10'
        }

    # 1D DOWNTREND tapi 4H RANGING → boleh SHORT dengan penalti skor
    if structure_1d == 'DOWNTREND' and structure_4h == 'RANGING':
        return {
            'allowed_direction': 'SHORT',
            'confluence_penalty': 10,
            'reason': '1D DOWNTREND tapi 4H RANGING — skor dikurangi 10'
        }

    # Semua skenario konflik lainnya → No Trade
    reason_map = {
        ('UPTREND',   'DOWNTREND'): '4H melawan 1D — terlalu berisiko untuk LONG',
        ('DOWNTREND', 'UPTREND'):   '4H melawan 1D — terlalu berisiko untuk SHORT',
        ('RANGING',   'UPTREND'):   '1D ranging — tidak ada tren directional jelas',
        ('RANGING',   'DOWNTREND'): '1D ranging — tidak ada tren directional jelas',
        ('RANGING',   'RANGING'):   'Keduanya ranging — tidak ada sinyal',
    }
    reason = reason_map.get(
        (structure_1d, structure_4h),
        f'Kombinasi tidak diizinkan: 1D={structure_1d}, 4H={structure_4h}'
    )

    logger.info(f"Tidak ada sinyal — {reason}")

    return {
        'allowed_direction': None,
        'confluence_penalty': 0,
        'reason': reason
    }


# =============================================================================
# Fungsi Utama (Entry Point)
# =============================================================================

def analyze_market_structure(df_4h: pd.DataFrame, df_1d: pd.DataFrame,
                              funding_rate: float, open_interest: float,
                              symbol: str = '') -> dict:
    """
    Jalankan semua analisis struktur pasar untuk satu symbol.

    Parameter:
        df_4h         : DataFrame OHLCV 4H (dengan indikator)
        df_1d         : DataFrame OHLCV 1D (dengan indikator)
        funding_rate  : float dari data_collector
        open_interest : float dari data_collector
        symbol        : string opsional untuk logging

    Return:
        {
            'structure_4h'       : 'UPTREND' | 'DOWNTREND' | 'RANGING',
            'structure_1d'       : 'UPTREND' | 'DOWNTREND' | 'RANGING',
            'allowed_direction'  : 'LONG' | 'SHORT' | None,
            'confluence_penalty' : int,
            'conflict_reason'    : string,
            'key_levels'         : {'resistance': [...], 'support': [...]},
            'derivatives'        : {...},
            'swings_4h'          : {'swing_highs': [...], 'swing_lows': [...]},
        }
    """
    sym_label = f" [{symbol}]" if symbol else ""
    logger.info(f"=== Analisis market structure{sym_label} ===")

    current_price = float(df_4h['close'].iloc[-1])
    prev_price    = float(df_4h['close'].iloc[-2]) if len(df_4h) >= 2 else None

    # OI sebelumnya tidak tersedia di sini — bisa di-extend nanti jika perlu
    prev_oi = None

    structure_4h = classify_structure(df_4h, tf='4h')
    structure_1d = classify_structure(df_1d, tf='1d')

    conflict_result  = resolve_structure_conflict(structure_4h, structure_1d)
    key_levels       = find_key_levels(df_4h, current_price)
    derivatives      = read_derivatives(
        funding_rate, open_interest, prev_oi, current_price, prev_price
    )
    swings_4h        = detect_swing_points(df_4h)

    return {
        'structure_4h':       structure_4h,
        'structure_1d':       structure_1d,
        'allowed_direction':  conflict_result['allowed_direction'],
        'confluence_penalty': conflict_result['confluence_penalty'],
        'conflict_reason':    conflict_result['reason'],
        'key_levels':         key_levels,
        'derivatives':        derivatives,
        'swings_4h':          swings_4h,
        'current_price':      current_price,
    }
