# =============================================================================
# report_formatter.py — Output Layer (5.1)
# Format signal_final atau market update menjadi pesan Telegram siap kirim.
# Menggunakan HTML parse mode — lebih andal dari MarkdownV2.
# HTML hanya perlu escape: & → &amp;  < → &lt;  > → &gt;
# =============================================================================

from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Helper: Escape HTML
# =============================================================================

def _esc(text) -> str:
    """Escape karakter spesial HTML untuk Telegram."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# =============================================================================
# Helper: Format angka
# =============================================================================

def _fmt_price(price: float) -> str:
    return f"{price:,.2f}"

def _fmt_pct(pct: float, with_sign: bool = True) -> str:
    return f"{pct:+.2f}%" if with_sign else f"{pct:.2f}%"

def _fmt_funding(rate: float) -> str:
    return f"{rate * 100:+.4f}%"


# =============================================================================
# Helper: Emoji
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
    symbol       = signal_final['symbol']
    direction    = signal_final['direction']
    confidence   = signal_final['confidence']
    structure    = signal_final['structure']
    structure_1d = signal_final.get('structure_1d', structure)

    entry_low  = signal_final['entry_low']
    entry_high = signal_final['entry_high']
    tp1 = signal_final['tp1']
    tp2 = signal_final['tp2']
    tp3 = signal_final['tp3']
    sl  = signal_final['sl']
    rr  = signal_final['rr']

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
    funding_display = _esc(_fmt_funding(funding_raw)) if funding_raw is not None else _esc(f"({funding_label})")
    oi_display = _esc(f"{oi_label} — {oi_signal}" if oi_signal else oi_label)

    flags = signal_final.get('flags', [])
    flags_section = ""
    if flags:
        flags_text = "\n".join(f"  • {_esc(f)}" for f in flags)
        flags_section = f"\n\n⚠️ <b>Catatan (MODIFIED):</b>\n{flags_text}"

    timestamp = _esc(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    msg = (
        f"{_direction_emoji(direction)} <b>{_esc(direction)} Signal — {_esc(symbol)}</b>\n"
        f"⏱ Timeframe: 4H  |  {_confidence_emoji(confidence)} Confidence: {_esc(confidence)}\n"
        f"\n"
        f"📍 <b>Entry Zone :</b> {_esc(_fmt_price(entry_low))} – {_esc(_fmt_price(entry_high))}\n"
        f"🎯 <b>TP1        :</b> {_esc(_fmt_price(tp1))}  ({_esc(_fmt_pct(tp1_pct))})\n"
        f"🎯 <b>TP2        :</b> {_esc(_fmt_price(tp2))}  ({_esc(_fmt_pct(tp2_pct))})\n"
        f"🎯 <b>TP3        :</b> {_esc(_fmt_price(tp3))}  ({_esc(_fmt_pct(tp3_pct))})\n"
        f"🛡 <b>Stop Loss  :</b> {_esc(_fmt_price(sl))}  ({_esc(_fmt_pct(sl_pct))})\n"
        f"⚖️ <b>Risk/Reward :</b> 1 : {_esc(rr)}\n"
        f"\n"
        f"{_structure_emoji(structure)} <b>Struktur :</b> {_esc(structure)} (4H) &amp; {_esc(structure_1d)} (1D)\n"
        f"🔗 <b>Confluence :</b> {_esc(confluence)}/100  ({_esc(tfs_agreeing)} dari 4 TF sepakat)\n"
        f"📉 <b>Win Rate   :</b> {_esc(f'{win_rate:.0%}')}  ({_esc(sample_n)} setup serupa, 90 hari)\n"
        f"💰 <b>EV Score   :</b> {_esc(f'{ev:+.2f}')}\n"
        f"\n"
        f"⚡ <b>Funding Rate :</b> {funding_display}\n"
        f"📦 <b>Open Interest:</b> {oi_display}"
        f"{flags_section}\n"
        f"\n"
        f"<i>{timestamp}</i>\n"
        f"\n"
        f"⚠️ <i>Bukan saran finansial. DYOR. Manajemen risiko ada di tangan Anda.</i>"
    )

    logger.info(f"Pesan signal diformat — {symbol} {direction} {confidence}")
    return msg


# =============================================================================
# Format: Market Update (No Trade)
# =============================================================================

def format_market_update(market_snapshots: list) -> str:
    timestamp = _esc(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    lines = [f"📊 <b>Market Update — {timestamp}</b>\n"]

    for snap in market_snapshots:
        symbol    = snap.get('symbol', '?')
        price     = snap.get('price', 0)
        structure = snap.get('structure', 'RANGING')
        score     = snap.get('score', 0)
        emoji     = _structure_emoji(structure)

        lines.append(
            f"{emoji} <b>{_esc(symbol)}</b>  {_esc(_fmt_price(price))}  |  "
            f"Struktur: {_esc(structure)}  |  Score: {_esc(score)}/100"
        )

    lines.append(
        f"\n"
        f"⏸ <i>Tidak ada setup valid saat ini.</i>\n"
        f"<i>Setup berikutnya dievaluasi dalam 4 jam.</i>"
    )

    msg = "\n".join(lines)
    logger.info(f"Pesan market update diformat — {len(market_snapshots)} symbol")
    return msg


# =============================================================================
# Format: Alert Error
# =============================================================================

def format_error_alert(timestamp: str, error_summary: str) -> str:
    msg = (
        f"⚠️ <b>Run Gagal</b>\n"
        f"🕐 {_esc(timestamp)}\n"
        f"❌ {_esc(error_summary)}"
    )
    logger.warning(f"Error alert diformat — {error_summary}")
    return msg
