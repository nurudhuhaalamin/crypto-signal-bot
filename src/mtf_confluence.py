# =============================================================================
# mtf_confluence.py — Analysis Layer (2/3)
# Kalkulasi skor konfluensi multi-timeframe untuk satu symbol.
# Input : dict {tf: DataFrame_dengan_indikator} untuk 1 symbol
# Output: confluence_score (0–100) + breakdown per timeframe
# =============================================================================

import pandas as pd

from utils.logger import get_logger

logger = get_logger(__name__)

# Bobot per timeframe (total harus = 1.0)
TF_WEIGHTS = {
    '1d':  0.40,
    '4h':  0.30,
    '1h':  0.20,
    '15m': 0.10,
}


# =============================================================================
# Scoring per Timeframe
# =============================================================================

def _score_single_tf(df: pd.DataFrame, direction: str, tf: str) -> dict:
    """
    Hitung skor konfluensi untuk satu timeframe.

    Setiap kondisi yang terpenuhi = +1 poin (maksimum 4 poin).
    Skor TF = (poin / 4) × 100

    Parameter:
        df        : DataFrame dengan indikator (ambil baris terakhir)
        direction : 'LONG' atau 'SHORT'
        tf        : label timeframe untuk logging

    Return:
        dict {score, points, max_points, details}
    """
    row = df.iloc[-1]   # Kondisi saat ini = candle terakhir
    points = 0
    details = []
    max_points = 4

    if direction == 'LONG':

        # 1. EMA alignment: bullish (fast > mid > slow)
        if row['ema_fast'] > row['ema_mid'] > row['ema_slow']:
            points += 1
            details.append('✅ EMA bullish alignment')
        else:
            details.append('❌ EMA tidak bullish')

        # 2. RSI: di atas 50 (momentum positif) dan tidak overbought (< 70)
        if 50 < row['rsi'] < 70:
            points += 1
            details.append(f"✅ RSI bullish ({row['rsi']:.1f})")
        else:
            details.append(f"❌ RSI tidak ideal ({row['rsi']:.1f})")

        # 3. MACD histogram: positif DAN lebih besar dari candle sebelumnya
        prev_hist = df.iloc[-2]['macd_hist'] if len(df) >= 2 else 0
        if row['macd_hist'] > 0 and row['macd_hist'] > prev_hist:
            points += 1
            details.append('✅ MACD histogram positif & naik')
        else:
            details.append('❌ MACD histogram tidak mendukung')

        # 4. Harga di atas Bollinger mid
        if row['close'] > row['bb_mid']:
            points += 1
            details.append('✅ Harga di atas BB mid')
        else:
            details.append('❌ Harga di bawah BB mid')

    elif direction == 'SHORT':

        # 1. EMA alignment: bearish (fast < mid < slow)
        if row['ema_fast'] < row['ema_mid'] < row['ema_slow']:
            points += 1
            details.append('✅ EMA bearish alignment')
        else:
            details.append('❌ EMA tidak bearish')

        # 2. RSI: di bawah 50 (momentum negatif) dan tidak oversold (> 30)
        if 30 < row['rsi'] < 50:
            points += 1
            details.append(f"✅ RSI bearish ({row['rsi']:.1f})")
        else:
            details.append(f"❌ RSI tidak ideal ({row['rsi']:.1f})")

        # 3. MACD histogram: negatif DAN lebih kecil dari candle sebelumnya
        prev_hist = df.iloc[-2]['macd_hist'] if len(df) >= 2 else 0
        if row['macd_hist'] < 0 and row['macd_hist'] < prev_hist:
            points += 1
            details.append('✅ MACD histogram negatif & turun')
        else:
            details.append('❌ MACD histogram tidak mendukung')

        # 4. Harga di bawah Bollinger mid
        if row['close'] < row['bb_mid']:
            points += 1
            details.append('✅ Harga di bawah BB mid')
        else:
            details.append('❌ Harga di atas BB mid')

    score = round((points / max_points) * 100)

    logger.debug(
        f"  [{tf}] {direction} — {points}/{max_points} poin = skor {score}"
    )

    return {
        'score':      score,
        'points':     points,
        'max_points': max_points,
        'details':    details,
    }


# =============================================================================
# Fungsi Utama
# =============================================================================

def calc_confluence(tf_data: dict, direction: str) -> dict:
    """
    Hitung skor konfluensi multi-timeframe untuk satu symbol.

    Parameter:
        tf_data   : dict {tf: DataFrame_dengan_indikator}
                    Harus berisi semua timeframe: '15m', '1h', '4h', '1d'
        direction : 'LONG' atau 'SHORT'

    Return:
        {
            'score':     74,            ← Skor final (0–100)
            'direction': 'LONG',
            'breakdown': {
                '1d':  {'score': 100, 'points': 4, ...},
                '4h':  {'score': 75,  'points': 3, ...},
                '1h':  {'score': 50,  'points': 2, ...},
                '15m': {'score': 25,  'points': 1, ...},
            },
            'tfs_agreeing': 3,          ← Jumlah TF dengan skor >= 50
        }
    """
    logger.info(f"Kalkulasi konfluensi — arah: {direction}")

    breakdown = {}
    weighted_total = 0.0
    tfs_agreeing = 0

    for tf, weight in TF_WEIGHTS.items():
        if tf not in tf_data:
            logger.warning(f"Timeframe {tf} tidak ada di tf_data — di-skip")
            continue

        tf_result = _score_single_tf(tf_data[tf], direction, tf)
        breakdown[tf] = tf_result

        weighted_total += tf_result['score'] * weight

        if tf_result['score'] >= 50:
            tfs_agreeing += 1

    final_score = round(weighted_total)

    logger.info(
        f"Skor konfluensi {direction}: {final_score}/100 "
        f"({tfs_agreeing} dari {len(breakdown)} TF sepakat)"
    )

    return {
        'score':        final_score,
        'direction':    direction,
        'breakdown':    breakdown,
        'tfs_agreeing': tfs_agreeing,
    }


def get_best_direction(tf_data: dict) -> str | None:
    """
    Cek arah mana (LONG atau SHORT) yang punya skor konfluensi lebih tinggi.
    Dipakai oleh signal_generator sebelum membuat draft.

    Return:
        'LONG', 'SHORT', atau None jika keduanya di bawah threshold.
    """
    from config import MIN_CONFLUENCE_SCORE

    long_result  = calc_confluence(tf_data, 'LONG')
    short_result = calc_confluence(tf_data, 'SHORT')

    long_score  = long_result['score']
    short_score = short_result['score']

    logger.info(f"LONG score: {long_score} | SHORT score: {short_score}")

    # Keduanya di bawah threshold → tidak ada sinyal
    if long_score < MIN_CONFLUENCE_SCORE and short_score < MIN_CONFLUENCE_SCORE:
        logger.info("Kedua arah di bawah threshold. Tidak ada sinyal.")
        return None, long_result, short_result

    # Pilih yang lebih tinggi
    if long_score >= short_score:
        return 'LONG', long_result, short_result
    else:
        return 'SHORT', long_result, short_result
