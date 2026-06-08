# =============================================================================
# risk_manager.py — Decision Layer (4.4)
# Validasi RR, SL distance, dan kalkulasi position size informatif.
# Input : signal_draft APPROVED/MODIFIED dari devil_advocate
# Output: signal_final dict dengan parameter risk lengkap, atau None
# =============================================================================

from config import MIN_RR_RATIO
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Validasi Risk/Reward
# =============================================================================

def validate_rr(signal_draft: dict) -> tuple[bool, float]:
    """
    Hitung RR dari TP1 dan SL, validasi terhadap MIN_RR_RATIO.

    RR = |TP1 - entry_mid| / |entry_mid - SL|

    Return:
        (True, rr_value) jika valid, (False, rr_value) jika tidak.
    """
    direction  = signal_draft['direction']
    entry_mid  = signal_draft['entry_mid']
    tp1        = signal_draft['tp1']
    sl         = signal_draft['sl']

    reward = abs(tp1 - entry_mid)
    risk   = abs(entry_mid - sl)

    if risk == 0:
        logger.error("Risk = 0 (entry_mid == SL) — tidak bisa hitung RR")
        return False, 0.0

    rr = round(reward / risk, 2)

    if rr < MIN_RR_RATIO:
        logger.info(
            f"RR tidak cukup: {rr} < {MIN_RR_RATIO} minimum — sinyal ditolak"
        )
        return False, rr

    logger.info(f"RR valid: 1:{rr} (minimum 1:{MIN_RR_RATIO})")
    return True, rr


# =============================================================================
# Validasi SL Distance
# =============================================================================

def validate_sl_distance(signal_draft: dict) -> bool:
    """
    Cek jarak SL dari entry_mid:
      - Terlalu dekat (< 1.0× ATR) → kena noise, sinyal false
      - Terlalu jauh  (> 3.0× ATR) → RR rusak, tidak efisien

    Return:
        True jika valid, False jika tidak.
    """
    entry_mid    = signal_draft['entry_mid']
    sl           = signal_draft['sl']
    atr          = signal_draft['atr']
    sl_distance  = abs(entry_mid - sl)

    if sl_distance < 1.0 * atr:
        logger.info(
            f"SL terlalu dekat: {sl_distance:.4f} < 1.0× ATR ({atr:.4f}) — ditolak"
        )
        return False

    if sl_distance > 3.0 * atr:
        logger.info(
            f"SL terlalu jauh: {sl_distance:.4f} > 3.0× ATR ({atr:.4f}) — ditolak"
        )
        return False

    logger.info(
        f"SL distance valid: {sl_distance:.4f} "
        f"({sl_distance / atr:.2f}× ATR)"
    )
    return True


# =============================================================================
# Kalkulasi Position Size (Informatif)
# =============================================================================

def calc_position_size(signal_draft: dict) -> dict:
    """
    Hitung position size untuk berbagai ukuran modal (informatif, tidak eksekusi).

    Rumus:
      Risk per trade = risk_pct × modal
      Kontrak       = Risk per trade / sl_distance_per_kontrak

    Karena modal user tidak diketahui, tampilkan dalam format:
      "Risiko 1% modal = X USDT per 1000 USDT modal"

    Return:
        {
            'risk_per_1000_usdt': float,  ← USDT yang berisiko jika modal $1000
            'sl_pct': float,              ← jarak SL dalam persen dari entry
            'tp1_pct': float,             ← jarak TP1 dalam persen dari entry
        }
    """
    entry_mid = signal_draft['entry_mid']
    sl        = signal_draft['sl']
    tp1       = signal_draft['tp1']

    sl_pct  = abs(entry_mid - sl)  / entry_mid * 100
    tp1_pct = abs(tp1 - entry_mid) / entry_mid * 100

    # Jika modal $1000 dan risk 1% = $10 per trade
    # Berapa kontrak? = $10 / (sl_pct% × 1000) = 10 / sl_distance_in_usd_per_1000
    sl_usd_per_1000 = sl_pct / 100 * 1000
    risk_per_1000   = round(sl_usd_per_1000, 2)

    logger.info(
        f"Position size — SL: {sl_pct:.2f}% | TP1: {tp1_pct:.2f}% | "
        f"Risk 1% dari $1000 = ${risk_per_1000:.2f}"
    )

    return {
        'risk_per_1000_usdt': risk_per_1000,
        'sl_pct':             round(sl_pct, 4),
        'tp1_pct':            round(tp1_pct, 4),
    }


# =============================================================================
# Fungsi Utama
# =============================================================================

def validate_risk(signal_draft: dict) -> dict | None:
    """
    Jalankan semua validasi risk dan lengkapi signal_draft menjadi signal_final.

    Urutan validasi:
      1. validate_sl_distance — SL tidak terlalu dekat/jauh dari noise
      2. validate_rr          — RR minimum terpenuhi
      3. calc_position_size   — kalkulasi informatif

    Parameter:
        signal_draft : output devil_advocate (sudah APPROVED/MODIFIED)

    Return:
        signal_final dict jika semua validasi lulus, None jika tidak.
    """
    symbol    = signal_draft['symbol']
    direction = signal_draft['direction']

    logger.info(f"=== Risk Manager — {symbol} {direction} ===")

    # ------------------------------------------------------------------
    # 1. Validasi SL distance
    # ------------------------------------------------------------------
    if not validate_sl_distance(signal_draft):
        logger.info(f"❌ Risk validation REJECTED — SL distance tidak valid")
        return None

    # ------------------------------------------------------------------
    # 2. Validasi RR
    # ------------------------------------------------------------------
    rr_valid, rr_value = validate_rr(signal_draft)
    if not rr_valid:
        logger.info(f"❌ Risk validation REJECTED — RR tidak mencukupi ({rr_value})")
        return None

    # ------------------------------------------------------------------
    # 3. Kalkulasi position size (informatif)
    # ------------------------------------------------------------------
    pos_size = calc_position_size(signal_draft)

    # ------------------------------------------------------------------
    # Susun signal_final
    # ------------------------------------------------------------------
    signal_final = {
        **signal_draft,
        'rr':                 rr_value,
        'sl_pct':             pos_size['sl_pct'],
        'tp1_pct':            pos_size['tp1_pct'],
        'risk_per_1000_usdt': pos_size['risk_per_1000_usdt'],
    }

    # Hitung persentase pergerakan dari entry ke setiap TP dan SL
    entry = signal_final['entry_mid']

    def _pct(price):
        diff = (price - entry) / entry * 100
        return round(diff, 2)

    signal_final['tp1_pct_from_entry'] = _pct(signal_final['tp1'])
    signal_final['tp2_pct_from_entry'] = _pct(signal_final['tp2'])
    signal_final['tp3_pct_from_entry'] = _pct(signal_final['tp3'])
    signal_final['sl_pct_from_entry']  = _pct(signal_final['sl'])

    logger.info(
        f"✅ Risk validation PASSED — {symbol} {direction} | "
        f"RR 1:{rr_value} | SL: {signal_final['sl_pct_from_entry']:+.2f}% | "
        f"TP1: {signal_final['tp1_pct_from_entry']:+.2f}%"
    )

    return signal_final
