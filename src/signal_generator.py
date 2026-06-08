# =============================================================================
# signal_generator.py — Decision Layer (4.1)
# Buat draft sinyal Long/Short berdasarkan output Phase 3.
# Input : output indicator_engine, mtf_confluence, market_structure (1 symbol)
# Output: signal_draft dict, atau None jika tidak ada setup valid
# =============================================================================

from utils.logger import get_logger
from config import MIN_CONFLUENCE_SCORE, ATR_PERIOD

logger = get_logger(__name__)


# =============================================================================
# Helper: Hitung Entry Zone
# =============================================================================

def _calc_entry_zone(direction: str, current_price: float,
                     key_levels: dict) -> dict:
    """
    Hitung entry_low, entry_high, entry_mid berdasarkan arah dan key levels.

    Untuk LONG:
        entry_low  = support terdekat (atau current_price - 0.1% sebagai fallback)
        entry_high = current_price
    Untuk SHORT:
        entry_low  = current_price
        entry_high = resistance terdekat (atau current_price + 0.1% sebagai fallback)

    Return:
        {'entry_low': float, 'entry_high': float, 'entry_mid': float}
    """
    supports    = key_levels.get('support', [])
    resistances = key_levels.get('resistance', [])

    if direction == 'LONG':
        entry_high = current_price
        if supports:
            entry_low = supports[0]   # Support terdekat di bawah harga
        else:
            entry_low = current_price * 0.999  # Fallback: 0.1% di bawah harga
            logger.warning("Tidak ada support level — pakai fallback entry_low")

    else:  # SHORT
        entry_low = current_price
        if resistances:
            entry_high = resistances[0]   # Resistance terdekat di atas harga
        else:
            entry_high = current_price * 1.001  # Fallback: 0.1% di atas harga
            logger.warning("Tidak ada resistance level — pakai fallback entry_high")

    entry_mid = (entry_low + entry_high) / 2

    return {
        'entry_low':  round(entry_low, 4),
        'entry_high': round(entry_high, 4),
        'entry_mid':  round(entry_mid, 4),
    }


# =============================================================================
# Helper: Hitung Stop Loss
# =============================================================================

def _calc_sl(direction: str, entry_mid: float, atr: float,
             swings_4h: dict) -> float | None:
    """
    Hitung Stop Loss berbasis swing point + buffer ATR.

    Untuk LONG:
        SL = swing_low terdekat di bawah entry_mid - 0.5 × ATR
    Untuk SHORT:
        SL = swing_high terdekat di atas entry_mid + 0.5 × ATR

    Validasi:
        Jarak SL dari entry_mid harus antara 1× dan 3× ATR.
        Jika tidak → return None.

    Return:
        float atau None
    """
    buffer = 0.5 * atr

    if direction == 'LONG':
        # Cari swing low di bawah entry_mid
        candidates = [
            price for _, price in swings_4h.get('swing_lows', [])
            if price < entry_mid
        ]
        if not candidates:
            logger.warning("Tidak ada swing low di bawah entry — tidak bisa hitung SL")
            return None
        sl = max(candidates) - buffer  # Swing low terdekat - buffer

    else:  # SHORT
        # Cari swing high di atas entry_mid
        candidates = [
            price for _, price in swings_4h.get('swing_highs', [])
            if price > entry_mid
        ]
        if not candidates:
            logger.warning("Tidak ada swing high di atas entry — tidak bisa hitung SL")
            return None
        sl = min(candidates) + buffer  # Swing high terdekat + buffer

    # Validasi jarak SL
    sl_distance = abs(entry_mid - sl)

    if sl_distance < 1.0 * atr:
        logger.warning(
            f"SL terlalu dekat ({sl_distance:.2f} < 1.0× ATR {atr:.2f}) — batalkan"
        )
        return None

    if sl_distance > 3.0 * atr:
        logger.warning(
            f"SL terlalu jauh ({sl_distance:.2f} > 3.0× ATR {atr:.2f}) — batalkan"
        )
        return None

    return round(sl, 4)


# =============================================================================
# Helper: Hitung Target Profit
# =============================================================================

def _calc_tp(direction: str, entry_mid: float, sl: float,
             key_levels: dict) -> dict:
    """
    Hitung TP1, TP2, TP3 berbasis multiplier ATR dari sl_distance.

    TP1 = entry_mid ± sl_distance × 1.5
    TP2 = entry_mid ± sl_distance × 2.5
    TP3 = resistance/support berikutnya, atau entry_mid ± sl_distance × 4.0

    Return:
        {'tp1': float, 'tp2': float, 'tp3': float}
    """
    sl_distance = abs(entry_mid - sl)

    if direction == 'LONG':
        tp1 = entry_mid + sl_distance * 1.5
        tp2 = entry_mid + sl_distance * 2.5

        # TP3: resistance level berikutnya (lebih tinggi dari TP2)
        resistances = key_levels.get('resistance', [])
        tp3_candidates = [r for r in resistances if r > tp2]
        tp3 = tp3_candidates[0] if tp3_candidates else entry_mid + sl_distance * 4.0

    else:  # SHORT
        tp1 = entry_mid - sl_distance * 1.5
        tp2 = entry_mid - sl_distance * 2.5

        # TP3: support level berikutnya (lebih rendah dari TP2)
        supports = key_levels.get('support', [])
        tp3_candidates = [s for s in supports if s < tp2]
        tp3 = tp3_candidates[0] if tp3_candidates else entry_mid - sl_distance * 4.0

    return {
        'tp1': round(tp1, 4),
        'tp2': round(tp2, 4),
        'tp3': round(tp3, 4),
    }


# =============================================================================
# Helper: Cek MFI tidak ekstrem berlawanan arah
# =============================================================================

def _check_mfi(df_4h, direction: str) -> bool:
    """
    Return True jika MFI tidak ekstrem berlawanan arah.
    Ekstrem = > 80 untuk SHORT signal, atau < 20 untuk LONG signal.
    (MFI ekstrem berlawanan bisa jadi counter-signal)
    """
    mfi = df_4h['mfi'].iloc[-1]

    if direction == 'LONG' and mfi < 20:
        logger.warning(f"MFI oversold ekstrem ({mfi:.1f}) — tidak biasa untuk LONG")
        return False

    if direction == 'SHORT' and mfi > 80:
        logger.warning(f"MFI overbought ekstrem ({mfi:.1f}) — tidak biasa untuk SHORT")
        return False

    return True


# =============================================================================
# Fungsi Utama
# =============================================================================

def generate_signal(
    symbol: str,
    tf_indicators: dict,      # {tf: DataFrame_dengan_indikator}
    confluence_result: dict,  # output calc_confluence()
    market_struct: dict,      # output analyze_market_structure()
) -> dict | None:
    """
    Buat draft sinyal berdasarkan output Phase 3.

    Syarat minimum untuk menghasilkan draft:
      1. confluence_score >= MIN_CONFLUENCE_SCORE (60)
      2. allowed_direction dari market_structure tidak None
      3. MFI tidak ekstrem berlawanan arah

    Parameter:
        symbol           : 'BTCUSDT', 'ETHUSDT', 'SOLUSDT'
        tf_indicators    : dict {tf: DataFrame} dari indicator_engine
        confluence_result: output calc_confluence() untuk arah yang dipilih
        market_struct    : output analyze_market_structure()

    Return:
        signal_draft dict jika setup valid, None jika tidak.
    """
    logger.info(f"=== Generate signal untuk {symbol} ===")

    # ------------------------------------------------------------------
    # Cek 1: Arah sinyal diizinkan oleh market structure
    # ------------------------------------------------------------------
    direction = market_struct.get('allowed_direction')
    if direction is None:
        logger.info(
            f"Tidak ada sinyal — {market_struct.get('conflict_reason', 'arah tidak diizinkan')}"
        )
        return None

    # ------------------------------------------------------------------
    # Cek 2: Confluence score mencukupi (dengan penalti jika ada)
    # ------------------------------------------------------------------
    raw_score = confluence_result.get('score', 0)
    penalty   = market_struct.get('confluence_penalty', 0)
    final_score = raw_score - penalty

    if final_score < MIN_CONFLUENCE_SCORE:
        logger.info(
            f"Confluence score tidak cukup: {raw_score} - {penalty} penalti "
            f"= {final_score} (minimum {MIN_CONFLUENCE_SCORE})"
        )
        return None

    logger.info(
        f"Confluence score: {raw_score} - {penalty} penalti = {final_score} ✅"
    )

    # ------------------------------------------------------------------
    # Ambil data yang dibutuhkan
    # ------------------------------------------------------------------
    df_4h = tf_indicators.get('4h')
    if df_4h is None or len(df_4h) < 2:
        logger.error("DataFrame 4H tidak tersedia atau terlalu pendek")
        return None

    current_price = market_struct['current_price']
    atr           = float(df_4h['atr'].iloc[-1])
    key_levels    = market_struct['key_levels']
    swings_4h     = market_struct['swings_4h']

    # ------------------------------------------------------------------
    # Cek 3: MFI tidak ekstrem berlawanan arah
    # ------------------------------------------------------------------
    if not _check_mfi(df_4h, direction):
        logger.info(f"MFI gagal cek — sinyal {direction} dibatalkan")
        return None

    # ------------------------------------------------------------------
    # Hitung Entry Zone
    # ------------------------------------------------------------------
    entry = _calc_entry_zone(direction, current_price, key_levels)
    entry_mid = entry['entry_mid']

    # ------------------------------------------------------------------
    # Hitung Stop Loss
    # ------------------------------------------------------------------
    sl = _calc_sl(direction, entry_mid, atr, swings_4h)
    if sl is None:
        logger.info("Tidak bisa hitung SL yang valid — sinyal dibatalkan")
        return None

    # ------------------------------------------------------------------
    # Hitung Target Profit
    # ------------------------------------------------------------------
    tp = _calc_tp(direction, entry_mid, sl, key_levels)

    # ------------------------------------------------------------------
    # Susun signal_draft
    # ------------------------------------------------------------------
    signal_draft = {
        'symbol':      symbol,
        'direction':   direction,
        'entry_low':   entry['entry_low'],
        'entry_high':  entry['entry_high'],
        'entry_mid':   entry_mid,
        'tp1':         tp['tp1'],
        'tp2':         tp['tp2'],
        'tp3':         tp['tp3'],
        'sl':          sl,
        'timeframe':   '4h',
        'structure':   market_struct['structure_4h'],
        'structure_1d': market_struct['structure_1d'],
        'confluence':  final_score,
        'atr':         round(atr, 4),
        'derivatives': market_struct['derivatives'],
        'key_levels':  key_levels,
        'tfs_agreeing': confluence_result.get('tfs_agreeing', 0),
        'breakdown':   confluence_result.get('breakdown', {}),
    }

    sl_distance = abs(entry_mid - sl)
    rr_preview  = round((tp['tp1'] - entry_mid) / sl_distance, 2) if direction == 'LONG' \
                  else round((entry_mid - tp['tp1']) / sl_distance, 2)

    logger.info(
        f"✅ Signal draft dibuat — {symbol} {direction} | "
        f"Entry: {entry_mid:,.2f} | SL: {sl:,.2f} | TP1: {tp['tp1']:,.2f} | "
        f"RR preview: 1:{rr_preview}"
    )

    return signal_draft
