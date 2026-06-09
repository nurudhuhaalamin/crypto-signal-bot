# =============================================================================
# report_formatter.py — Output Layer (5.1)
# Format signal_final atau market update menjadi pesan Telegram siap kirim.
# Input : signal_final dict (atau list market update)
# Output: string pesan berformat MarkdownV2
# =============================================================================

import re
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Helper: Escape MarkdownV2
# =============================================================================

def _esc(text) -> str:
    """
    Escape semua karakter spesial MarkdownV2 Telegram.
    Wajib dipakai pada semua nilai dinamis (harga, simbol, timestamp, dll).
    Karakter: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))


# =============================================================================
# Helper: Format angka harga
# =============================================================================

def _fmt_price(price: float) -> str:
    """Format harga dengan koma ribuan dan 2 desimal. Contoh: 65,340.50"""
    return f"{price:,.2f}"


def _fmt_pct(pct: float, with_sign: bool = True) -> str:
    """Format persentase. Contoh: +2.50% atau -1.80%"""
    if with_sign:
        return f"{pct:+.2f}%"
    return f"{pct:.2f}%"


def _fmt_funding(rate: float) -> str:
    """Format funding rate ke persen dengan 4 desimal. Contoh: +0.0100%"""
    return f"{rate * 100:+.4f}%"


# =============================================================================
# Helper: Emoji arah
# =============================================================================

def _direction_emoji(direction: str) -> str:
    return "🟢" if direction == "LONG" else "🔴"


def _confidence_emoji(confidence: str) -> str:
    return {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "❄️"}.get(confidence, "")


def _structure_emoji(structure: str) -> str:
    return {"UPTREND": "📈", "DOWNTREND": "📉", "RANGING": "↔️"}.get(structure, "")


# =============================================================================
# Format: Signal Aktif
# =============================================================================

def format_signal(signal_final: dict) -> str:
    symbol     = signal_final['symbol']
    direction  = signal_final['direction']
    confidence = signal_final['confidence']
    structure  = signal_final['structure']
    structure_1d = signal_final.get('structure_1d', structure)

    entry_low  = signal_final['entry_low']
    entry_high = signal_final['entry_high']
    tp1        = signal_final['tp1']
    tp2        = signal_final['tp2']
    tp3        = signal_final['tp3']
    sl         = signal_final['sl']
    rr         = signal_final['rr']

    tp1_pct = signal_final.get('tp1_pct_from_entry', 0)
    tp2_pct = signal_final.get('tp2_pct_from_entry', 0)
    tp3_pct = signal_final.get('tp3_pct_from_entry', 0)
    sl_pct  = signal_final.get('sl_pct_from_entry', 0)

    confluence   = signal_final['confluence']
    tfs_agreeing = signal_final.get('tfs_agreeing', 0)
    win_rate     = signal_final['win_rate']
    ev           = signal_final['ev']
    sample_n     = signal_final['sample_n']

    derivatives   = signal_final.get('derivatives', {})
    funding_label = derivatives.get('funding_label', 'NETRAL')
    oi_label      = derivatives.get('oi_label', 'STABIL')
    oi_signal     = derivatives.get('oi_signal', '')

    funding_raw = signal_final.get('funding_rate_raw', None)
    if funding_raw is not None:
        funding_display = _esc(_fmt_funding(funding_raw))
    else:
        funding_display = _esc(f"({funding_label})")

    oi_display = _esc(f"{oi_label} — {oi_signal}" if oi_signal else oi_label)

    flags = signal_final.get('flags', [])
    flags_section = ""
    if flags:
        flags_text = "\n".join(f"  • {_esc(f)}" for f in flags)
        flags_section = f"\n\n⚠️ *Catatan \\(MODIFIED\\):*\n{flags_text}"

    timestamp = _esc(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    msg = (
        f"{_direction_emoji(direction)} *{_esc(direction)} Signal — {_esc(symbol)}*\n"
        f"⏱ Timeframe: 4H  |  {_confidence_emoji(confidence)} Confidence: {_esc(confidence)}\n"
        f"\n"
        f"📍 *Entry Zone :* {_esc(_fmt_price(entry_low))} – {_esc(_fmt_price(entry_high))}\n"
        f"🎯 *TP1        :* {_esc(_fmt_price(tp1))}  \\({_esc(_fmt_pct(tp1_pct))}\\)\n"
        f"🎯 *TP2        :* {_esc(_fmt_price(tp2))}  \\({_esc(_fmt_pct(tp2_pct))}\\)\n"
        f"🎯 *TP3        :* {_esc(_fmt_price(tp3))}  \\({_esc(_fmt_pct(tp3_pct))}\\)\n"
        f"🛡 *Stop Loss  :* {_esc(_fmt_price(sl))}  \\({_esc(_fmt_pct(sl_pct))}\\)\n"
        f"⚖️ *Risk/Reward :* 1 : {_esc(rr)}\n"
        f"\n"
        f"{_structure_emoji(structure)} *Struktur :* {_esc(structure)} \\(4H\\) & {_esc(structure_1d)} \\(1D\\)\n"
        f"🔗 *Confluence :* {_esc(confluence)}/100  \\({_esc(tfs_agreeing)} dari 4 TF sepakat\\)\n"
        f"📉 *Win Rate   :* {_esc(f'{win_rate:.0%}')}  \\({_esc(sample_n)} setup serupa, 90 hari\\)\n"
        f"💰 *EV Score   :* {_esc(f'{ev:+.2f}')}\n"
        f"\n"
        f"⚡ *Funding Rate :* {funding_display}\n"
        f"📦 *Open Interest:* {oi_display}"
        f"{flags_section}\n"
        f"\n"
        f"_{timestamp}_\n"
        f"\n"
        f"⚠️ _Bukan saran finansial\\. DYOR\\. Manajemen risiko ada di tangan Anda\\._"
    )

    logger.info(f"Pesan signal diformat — {symbol} {direction} {confidence}")
    return msg


# =============================================================================
# Format: Market Update (No Trade)
# =============================================================================

def format_market_update(market_snapshots: list) -> str:
    timestamp = _esc(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    lines = [
        f"📊 *Market Update — {timestamp}*\n"
    ]

    for snap in market_snapshots:
        symbol    = snap.get('symbol', '?')
        price     = snap.get('price', 0)
        structure = snap.get('structure', 'RANGING')
        score     = snap.get('score', 0)
        emoji     = _structure_emoji(structure)

        lines.append(
            f"{emoji} *{_esc(symbol)}*  {_esc(_fmt_price(price))}  |  "
            f"Struktur: {_esc(structure)}  |  Score: {_esc(score)}/100"
        )

    lines.append(
        f"\n"
        f"⏸ _Tidak ada setup valid saat ini\\._\n"
        f"_Setup berikutnya dievaluasi dalam 4 jam\\._"
    )

    msg = "\n".join(lines)
    logger.info(f"Pesan market update diformat — {len(market_snapshots)} symbol")
    return msg


# =============================================================================
# Format: Alert Error
# =============================================================================

def format_error_alert(timestamp: str, error_summary: str) -> str:
    """
    Dikirim via send_health_check_alert (parse_mode HTML / plain text).
    Tidak perlu MarkdownV2 escaping.
    """
    msg = (
        f"⚠️ *Run Gagal*\n"
        f"🕐 {timestamp}\n"
        f"❌ {error_summary}"
    )
    logger.warning(f"Error alert diformat — {error_summary}")
    return msg
