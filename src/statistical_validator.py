# =============================================================================
# statistical_validator.py — Decision Layer (4.2)
# Backtest setup serupa pada data historis 90 hari.
# Input : signal_draft + DataFrame OHLCV 4H
# Output: signal_draft + field statistik, atau None jika stats buruk
#
# ⚠️ GUARD LOOK-AHEAD BIAS:
#   Saat mengevaluasi setup pada candle ke-N, hanya boleh menggunakan
#   data candle 0 s/d N. Outcome dihitung dari candle N+1 ke depan.
# =============================================================================

import pandas as pd
import numpy as np
from datetime import timedelta

from config import (
    BACKTEST_DAYS, MIN_SAMPLE_N, MIN_WIN_RATE, MIN_EV,
    RSI_SIMILARITY_RANGE, EMA_FAST, EMA_MID, EMA_SLOW
)
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Helper: Cek apakah candle historis memenuhi definisi "setup serupa"
# =============================================================================

def _is_similar_setup(row: pd.Series, direction: str,
                       current_rsi: float, current_structure: str) -> bool:
    """
    Cek apakah satu candle historis dianggap "setup serupa" dengan sinyal saat ini.

    Tiga kondisi harus terpenuhi semua:
      1. Arah EMA sesuai direction (bullish alignment untuk LONG, bearish untuk SHORT)
      2. RSI dalam range ±RSI_SIMILARITY_RANGE dari RSI sinyal saat ini
      3. Market structure sama (kolom 'structure')

    Return:
        True jika serupa, False jika tidak.
    """
    # 1. EMA alignment
    if direction == 'LONG':
        ema_ok = row['ema_fast'] > row['ema_mid'] > row['ema_slow']
    else:  # SHORT
        ema_ok = row['ema_fast'] < row['ema_mid'] < row['ema_slow']

    if not ema_ok:
        return False

    # 2. RSI similarity
    if pd.isna(row['rsi']):
        return False
    rsi_diff = abs(row['rsi'] - current_rsi)
    if rsi_diff > RSI_SIMILARITY_RANGE:
        return False

    # 3. Market structure sama
    row_structure = row.get('structure', None)
    if row_structure != current_structure:
        return False

    return True


# =============================================================================
# Helper: Simulasi outcome dari candle N+1 ke depan
# =============================================================================

def _simulate_outcome(df: pd.DataFrame, start_idx: int,
                       tp1: float, sl: float, direction: str,
                       max_candles: int = 20) -> str:
    """
    Simulasi apakah TP1 atau SL tercapai lebih dulu setelah candle start_idx.

    Hanya melihat candle start_idx+1 sampai start_idx+max_candles.
    Ini adalah outcome candle — bukan look-ahead dari titik evaluasi.

    Return:
        'WIN'  — jika TP1 tercapai sebelum SL
        'LOSS' — jika SL tercapai sebelum TP1
        'OPEN' — jika tidak ada yang tercapai dalam max_candles
    """
    future = df.iloc[start_idx + 1: start_idx + 1 + max_candles]

    for _, candle in future.iterrows():
        if direction == 'LONG':
            if candle['high'] >= tp1:
                return 'WIN'
            if candle['low'] <= sl:
                return 'LOSS'
        else:  # SHORT
            if candle['low'] <= tp1:
                return 'WIN'
            if candle['high'] >= sl:
                return 'LOSS'

    return 'OPEN'


# =============================================================================
# Fungsi: Backtest Setup Serupa
# =============================================================================

def backtest_similar_setups(df_4h: pd.DataFrame, signal_draft: dict) -> dict:
    """
    Loop data historis 90 hari, cari setup serupa, simulasi outcome.

    Parameter:
        df_4h        : DataFrame OHLCV 4H dengan kolom indikator + 'structure'
        signal_draft : output generate_signal()

    Return:
        {
            'sample_n'   : int,    jumlah setup serupa ditemukan
            'win_rate'   : float,  proporsi WIN dari semua WIN+LOSS
            'avg_profit' : float,  rata-rata profit relatif saat WIN (dalam %)
            'avg_loss'   : float,  rata-rata loss relatif saat LOSS (dalam %)
            'ev'         : float,  expected value
        }
    """
    direction   = signal_draft['direction']
    current_rsi = signal_draft.get('current_rsi', df_4h['rsi'].iloc[-1])
    structure   = signal_draft['structure']
    tp1         = signal_draft['tp1']
    sl          = signal_draft['sl']
    entry_mid   = signal_draft['entry_mid']

    # Window 90 hari terakhir (kecuali candle paling akhir = sinyal saat ini)
    cutoff = df_4h.index[-1] - timedelta(days=BACKTEST_DAYS)
    df_window = df_4h[df_4h.index >= cutoff].iloc[:-1]  # Exclude candle terakhir

    wins   = []
    losses = []
    sample_n = 0

    # ⚠️ GUARD LOOK-AHEAD BIAS: evaluasi candle ke-i hanya pakai data 0..i
    df_full = df_4h[df_4h.index <= df_4h.index[-2]]  # Semua data kecuali candle aktif

    for i, (ts, row) in enumerate(df_window.iterrows()):
        # Cari posisi candle ini di df_full
        try:
            global_idx = df_full.index.get_loc(ts)
        except KeyError:
            continue

        # Hanya pakai data up to candle ini (anti look-ahead)
        if not _is_similar_setup(row, direction, current_rsi, structure):
            continue

        sample_n += 1

        # Simulasi outcome dari candle berikutnya
        outcome = _simulate_outcome(df_full, global_idx, tp1, sl, direction)

        if outcome == 'WIN':
            # Profit = jarak entry ke TP1, relatif terhadap entry
            profit_pct = abs(tp1 - entry_mid) / entry_mid * 100
            wins.append(profit_pct)

        elif outcome == 'LOSS':
            # Loss = jarak entry ke SL, relatif terhadap entry
            loss_pct = abs(sl - entry_mid) / entry_mid * 100
            losses.append(loss_pct)
        # OPEN: tidak dihitung sebagai WIN atau LOSS

    total_decided = len(wins) + len(losses)

    if total_decided == 0:
        logger.warning("Tidak ada setup serupa dengan outcome jelas (semua OPEN atau 0 sample)")
        return {
            'sample_n':   sample_n,
            'win_rate':   0.0,
            'avg_profit': 0.0,
            'avg_loss':   0.0,
            'ev':         -1.0,
        }

    win_rate   = len(wins) / total_decided
    avg_profit = float(np.mean(wins))   if wins   else 0.0
    avg_loss   = float(np.mean(losses)) if losses else 0.0

    logger.info(
        f"Backtest selesai — {sample_n} setup serupa ditemukan | "
        f"{len(wins)}W / {len(losses)}L | win_rate: {win_rate:.1%}"
    )

    return {
        'sample_n':   sample_n,
        'win_rate':   win_rate,
        'avg_profit': round(avg_profit, 4),
        'avg_loss':   round(avg_loss, 4),
        'ev':         0.0,  # akan dihitung di calc_expected_value
    }


# =============================================================================
# Fungsi: Hitung Expected Value
# =============================================================================

def calc_expected_value(win_rate: float, avg_profit: float,
                         avg_loss: float) -> float:
    """
    EV = (win_rate × avg_profit) - (loss_rate × avg_loss)

    Return:
        float, positif = harapan profit, negatif = harapan rugi
    """
    loss_rate = 1 - win_rate
    ev = (win_rate * avg_profit) - (loss_rate * avg_loss)
    return round(ev, 4)


# =============================================================================
# Fungsi: Klasifikasi Confidence
# =============================================================================

def classify_confidence(win_rate: float, ev: float) -> str:
    """
    HIGH   : EV > 0 DAN win_rate > 0.55
    MEDIUM : EV > 0 DAN win_rate antara 0.45–0.55
    LOW    : EV <= 0 ATAU win_rate < 0.45

    Return:
        'HIGH' | 'MEDIUM' | 'LOW'
    """
    if ev > MIN_EV and win_rate > 0.55:
        return 'HIGH'
    elif ev > MIN_EV and win_rate >= MIN_WIN_RATE:
        return 'MEDIUM'
    else:
        return 'LOW'


# =============================================================================
# Fungsi Utama
# =============================================================================

def validate_statistically(df_4h: pd.DataFrame,
                             signal_draft: dict) -> dict | None:
    """
    Jalankan backtest dan evaluasi statistik pada signal_draft.

    Proses:
      1. Tambahkan kolom 'structure' ke df_4h (untuk cek setup serupa)
      2. Backtest 90 hari
      3. Hitung EV dan confidence
      4. Return signal_draft yang diperkaya, atau None jika stats buruk

    Parameter:
        df_4h        : DataFrame 4H dengan indikator (output indicator_engine)
        signal_draft : output generate_signal()

    Return:
        signal_draft yang sudah ditambah field statistik, atau None.
    """
    logger.info(
        f"=== Statistical validation — {signal_draft['symbol']} "
        f"{signal_draft['direction']} ==="
    )

    # Simpan RSI saat ini ke draft (dibutuhkan oleh _is_similar_setup)
    signal_draft['current_rsi'] = float(df_4h['rsi'].iloc[-1])

    # ------------------------------------------------------------------
    # Tambahkan kolom 'structure' ke df_4h untuk keperluan backtest
    # (Gunakan EMA alignment sederhana sebagai proxy struktur per-candle)
    # ------------------------------------------------------------------
    df = df_4h.copy()

    def _infer_structure(row):
        if row['ema_fast'] > row['ema_mid'] > row['ema_slow']:
            return 'UPTREND'
        elif row['ema_fast'] < row['ema_mid'] < row['ema_slow']:
            return 'DOWNTREND'
        else:
            return 'RANGING'

    df['structure'] = df.apply(_infer_structure, axis=1)

    # ------------------------------------------------------------------
    # Backtest
    # ------------------------------------------------------------------
    stats = backtest_similar_setups(df, signal_draft)

    sample_n   = stats['sample_n']
    win_rate   = stats['win_rate']
    avg_profit = stats['avg_profit']
    avg_loss   = stats['avg_loss']

    # ------------------------------------------------------------------
    # Cek minimum sample
    # ------------------------------------------------------------------
    if sample_n < MIN_SAMPLE_N:
        logger.info(
            f"Sample terlalu sedikit: {sample_n} < {MIN_SAMPLE_N} minimum — "
            f"sinyal ditolak (statistik tidak signifikan)"
        )
        return None

    # ------------------------------------------------------------------
    # Hitung EV dan confidence
    # ------------------------------------------------------------------
    ev         = calc_expected_value(win_rate, avg_profit, avg_loss)
    confidence = classify_confidence(win_rate, ev)

    logger.info(
        f"Stats — win_rate: {win_rate:.1%} | EV: {ev:+.4f} | "
        f"confidence: {confidence} | sample_n: {sample_n}"
    )

    # ------------------------------------------------------------------
    # Tolak jika confidence LOW
    # ------------------------------------------------------------------
    if confidence == 'LOW':
        logger.info(
            f"Confidence LOW (win_rate={win_rate:.1%}, EV={ev:+.4f}) — "
            f"sinyal ditolak"
        )
        return None

    # ------------------------------------------------------------------
    # Enrichment: tambahkan field statistik ke signal_draft
    # ------------------------------------------------------------------
    signal_draft['win_rate']   = round(win_rate, 4)
    signal_draft['ev']         = ev
    signal_draft['confidence'] = confidence
    signal_draft['sample_n']   = sample_n
    signal_draft['avg_profit'] = avg_profit
    signal_draft['avg_loss']   = avg_loss

    logger.info(
        f"✅ Statistical validation passed — {signal_draft['symbol']} "
        f"{signal_draft['direction']} | confidence: {confidence}"
    )

    return signal_draft
