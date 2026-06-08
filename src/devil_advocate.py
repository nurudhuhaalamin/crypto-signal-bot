# =============================================================================
# devil_advocate.py — Decision Layer (4.3)
# Validasi kelemahan sinyal sebelum dikirim ke risk_manager.
# Input : signal_draft yang sudah ada data statistik
# Output: {'verdict': 'APPROVED'/'REJECTED'/'MODIFIED', 'flags': []}
# =============================================================================

import numpy as np
import pandas as pd

from config import (
    BB_SQUEEZE_PERCENTILE, VOLUME_SPIKE_MULT,
    FUNDING_RATE_EXTREME, MIN_SAMPLE_N
)
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Cek 1: RSI Divergence (Hidden)
# =============================================================================

def _check_rsi_divergence(df_4h: pd.DataFrame, direction: str) -> str | None:
    """
    Deteksi Hidden Divergence yang berbahaya untuk arah sinyal.

    Hidden Bearish Divergence (berbahaya untuk LONG):
      Harga: Higher Low (swing_low[2] > swing_low[1])
      RSI  : Lower Low  (rsi_at_swing[2] < rsi_at_swing[1])

    Hidden Bullish Divergence (berbahaya untuk SHORT):
      Harga: Lower High (swing_high[2] < swing_high[1])
      RSI  : Higher High (rsi_at_swing[2] > rsi_at_swing[1])

    Langkah:
      1. Ambil 20 candle terakhir di 4H
      2. Cari 2 titik swing (low untuk LONG, high untuk SHORT)
      3. Bandingkan harga dan RSI di titik tersebut

    Return:
        String deskripsi flag jika divergence terdeteksi, None jika bersih.
    """
    recent = df_4h.iloc[-20:].reset_index(drop=True)
    n = 2  # window swing: 2 candle kiri dan kanan

    if direction == 'LONG':
        # Cari swing lows
        swing_indices = []
        for i in range(n, len(recent) - n):
            window = recent['low'].iloc[i - n: i + n + 1]
            if recent['low'].iloc[i] == window.min():
                swing_indices.append(i)

        if len(swing_indices) < 2:
            logger.debug("Kurang dari 2 swing low — skip cek divergence")
            return None

        # Ambil 2 swing low terakhir
        idx1, idx2 = swing_indices[-2], swing_indices[-1]
        price1 = recent['low'].iloc[idx1]
        price2 = recent['low'].iloc[idx2]
        rsi1   = recent['rsi'].iloc[idx1]
        rsi2   = recent['rsi'].iloc[idx2]

        # Hidden Bearish: harga Higher Low tapi RSI Lower Low
        if price2 > price1 and rsi2 < rsi1:
            msg = (
                f"Hidden bearish divergence terdeteksi — "
                f"harga HL ({price1:.2f}→{price2:.2f}) "
                f"tapi RSI LL ({rsi1:.1f}→{rsi2:.1f})"
            )
            logger.warning(msg)
            return msg

    else:  # SHORT
        # Cari swing highs
        swing_indices = []
        for i in range(n, len(recent) - n):
            window = recent['high'].iloc[i - n: i + n + 1]
            if recent['high'].iloc[i] == window.max():
                swing_indices.append(i)

        if len(swing_indices) < 2:
            logger.debug("Kurang dari 2 swing high — skip cek divergence")
            return None

        idx1, idx2 = swing_indices[-2], swing_indices[-1]
        price1 = recent['high'].iloc[idx1]
        price2 = recent['high'].iloc[idx2]
        rsi1   = recent['rsi'].iloc[idx1]
        rsi2   = recent['rsi'].iloc[idx2]

        # Hidden Bullish: harga Lower High tapi RSI Higher High
        if price2 < price1 and rsi2 > rsi1:
            msg = (
                f"Hidden bullish divergence terdeteksi — "
                f"harga LH ({price1:.2f}→{price2:.2f}) "
                f"tapi RSI HH ({rsi1:.1f}→{rsi2:.1f})"
            )
            logger.warning(msg)
            return msg

    return None


# =============================================================================
# Cek 2: Funding Rate Conflict
# =============================================================================

def _check_funding_rate(signal_draft: dict) -> str | None:
    """
    Cek apakah funding rate bertentangan dengan arah sinyal.

    LONG + funding rate > +0.1%  → pasar overheated long, rentan reversal turun
    SHORT + funding rate < -0.1% → pasar overheated short, rentan reversal naik

    Return:
        String flag jika konflik, None jika aman.
    """
    derivatives   = signal_draft.get('derivatives', {})
    funding_rate  = signal_draft.get('funding_rate_raw', None)
    funding_label = derivatives.get('funding_label', 'NETRAL')
    direction     = signal_draft['direction']

    if direction == 'LONG' and funding_label == 'OVERHEATED_LONG':
        msg = (
            f"Funding rate conflict — signal LONG tapi pasar overheated long "
            f"({funding_label})"
        )
        logger.warning(msg)
        return msg

    if direction == 'SHORT' and funding_label == 'OVERHEATED_SHORT':
        msg = (
            f"Funding rate conflict — signal SHORT tapi pasar overheated short "
            f"({funding_label})"
        )
        logger.warning(msg)
        return msg

    return None


# =============================================================================
# Cek 3: Volume Spike Anomali
# =============================================================================

def _check_volume_spike(df_4h: pd.DataFrame) -> str | None:
    """
    Cek apakah volume candle terakhir anomali (spike tidak wajar).

    Anomali: volume[-1] > VOLUME_SPIKE_MULT × rata-rata volume 20 candle terakhir

    Volume spike bisa berarti manipulasi atau event tidak terduga —
    keduanya meningkatkan risiko sinyal false.

    Return:
        String flag jika anomali, None jika normal.
    """
    if len(df_4h) < 21:
        logger.debug("Data tidak cukup untuk cek volume spike — di-skip")
        return None

    vol_now  = df_4h['volume'].iloc[-1]
    vol_mean = df_4h['volume'].iloc[-21:-1].mean()

    if vol_now > VOLUME_SPIKE_MULT * vol_mean:
        msg = (
            f"Volume spike anomali — vol sekarang {vol_now:,.0f} > "
            f"{VOLUME_SPIKE_MULT}× rata-rata ({vol_mean:,.0f})"
        )
        logger.warning(msg)
        return msg

    return None


# =============================================================================
# Cek 4: Bollinger Squeeze Trap
# =============================================================================

def _check_bb_squeeze(df_4h: pd.DataFrame) -> str | None:
    """
    Cek apakah BB sedang dalam kondisi squeeze tanpa konfirmasi breakout.

    Squeeze: bb_width[-1] < persentil ke-BB_SQUEEZE_PERCENTILE dari 50 candle terakhir
    Jika masih squeeze (belum breakout) → sinyal mungkin prematur.

    Konfirmasi breakout: harga sudah menutup di luar BB (di atas upper atau di bawah lower).

    Return:
        String flag jika squeeze trap, None jika aman.
    """
    if len(df_4h) < 50:
        logger.debug("Data tidak cukup untuk cek BB squeeze — di-skip")
        return None

    bb_width_recent = df_4h['bb_width'].iloc[-50:]
    threshold       = np.percentile(bb_width_recent, BB_SQUEEZE_PERCENTILE)
    current_width   = df_4h['bb_width'].iloc[-1]

    if current_width >= threshold:
        return None  # Bukan squeeze

    # Ini squeeze — cek apakah sudah ada konfirmasi breakout
    last_close  = df_4h['close'].iloc[-1]
    bb_upper    = df_4h['bb_upper'].iloc[-1]
    bb_lower    = df_4h['bb_lower'].iloc[-1]

    breakout_confirmed = (last_close > bb_upper) or (last_close < bb_lower)

    if not breakout_confirmed:
        msg = (
            f"BB squeeze trap — width {current_width:.2f} < "
            f"persentil ke-{BB_SQUEEZE_PERCENTILE} ({threshold:.2f}), "
            f"belum ada konfirmasi breakout"
        )
        logger.warning(msg)
        return msg

    return None


# =============================================================================
# Cek 5: SL Terlalu Dekat Noise
# =============================================================================

def _check_sl_distance(signal_draft: dict) -> str | None:
    """
    Redundant check dari risk_manager — lebih baik tangkap lebih awal.
    Jarak entry ke SL harus >= 1× ATR.

    Return:
        String flag jika terlalu dekat, None jika aman.
    """
    entry_mid = signal_draft['entry_mid']
    sl        = signal_draft['sl']
    atr       = signal_draft['atr']
    distance  = abs(entry_mid - sl)

    if distance < 1.0 * atr:
        msg = (
            f"SL terlalu dekat noise — jarak {distance:.2f} < 1.0× ATR {atr:.2f}"
        )
        logger.warning(msg)
        return msg

    return None


# =============================================================================
# Cek 6: Sample Terlalu Kecil
# =============================================================================

def _check_sample_size(signal_draft: dict) -> str | None:
    """
    Pastikan sample_n dari statistical_validator memenuhi minimum.
    (Double-check — seharusnya sudah ditolak di validator, tapi lebih aman dicek lagi)

    Return:
        String flag jika kurang, None jika aman.
    """
    sample_n = signal_draft.get('sample_n', 0)
    if sample_n < MIN_SAMPLE_N:
        msg = (
            f"Sample terlalu kecil — {sample_n} < {MIN_SAMPLE_N} minimum "
            f"(statistik tidak signifikan)"
        )
        logger.warning(msg)
        return msg

    return None


# =============================================================================
# Fungsi Utama
# =============================================================================

def run_devil_advocate(df_4h: pd.DataFrame,
                        signal_draft: dict) -> dict:
    """
    Jalankan semua checklist validasi pada signal_draft.

    Parameter:
        df_4h        : DataFrame 4H dengan indikator (dari indicator_engine)
        signal_draft : output validate_statistically()

    Return:
        {
            'verdict': 'APPROVED' | 'REJECTED' | 'MODIFIED',
            'flags'  : list of string (deskripsi masalah yang ditemukan),
            'signal_draft': signal_draft (mungkin sudah dimodifikasi),
        }
    """
    symbol    = signal_draft['symbol']
    direction = signal_draft['direction']

    logger.info(f"=== Devil Advocate — {symbol} {direction} ===")

    flags = []

    # ------------------------------------------------------------------
    # Jalankan semua cek
    # ------------------------------------------------------------------
    checks = [
        ("RSI Divergence",     _check_rsi_divergence(df_4h, direction)),
        ("Funding Rate",       _check_funding_rate(signal_draft)),
        ("Volume Spike",       _check_volume_spike(df_4h)),
        ("BB Squeeze Trap",    _check_bb_squeeze(df_4h)),
        ("SL Distance",        _check_sl_distance(signal_draft)),
        ("Sample Size",        _check_sample_size(signal_draft)),
    ]

    for check_name, result in checks:
        if result is not None:
            logger.warning(f"  ⚠️  [{check_name}] {result}")
            flags.append(result)
        else:
            logger.debug(f"  ✅  [{check_name}] OK")

    # ------------------------------------------------------------------
    # Verdict logic
    # ------------------------------------------------------------------
    n_flags = len(flags)

    if n_flags == 0:
        verdict = 'APPROVED'
        logger.info(f"✅ Devil advocate: APPROVED — tidak ada flag")

    elif n_flags == 1:
        verdict = 'MODIFIED'
        logger.info(
            f"⚠️  Devil advocate: MODIFIED — 1 flag ditemukan, "
            f"sinyal tetap diteruskan dengan catatan"
        )

    else:
        verdict = 'REJECTED'
        logger.info(
            f"❌ Devil advocate: REJECTED — {n_flags} flag ditemukan "
            f"(batas maksimum 1)"
        )

    return {
        'verdict':      verdict,
        'flags':        flags,
        'signal_draft': signal_draft,
    }
