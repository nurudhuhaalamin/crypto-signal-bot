# =============================================================================
# orchestrator.py — Entry Point Utama
# Jalankan seluruh pipeline: fetch → analysis → decision → output.
# Dipanggil oleh GitHub Actions setiap 4 jam.
#
# Urutan eksekusi:
#   1. Validasi koneksi Telegram
#   2. fetch_all_data()
#   3. Per symbol: indicator → confluence → structure → signal → validate → advocate → risk
#   4. Kirim sinyal aktif (jika ada) atau market update (jika tidak ada)
#   5. Log ringkasan run (health check)
# =============================================================================

import sys
from datetime import datetime, timezone

from config import SYMBOLS, MIN_CONFLUENCE_SCORE
from data_collector import fetch_all_data, validate_data
from indicator_engine import calculate_indicators
from mtf_confluence import get_best_direction, calc_confluence
from market_structure import analyze_market_structure
from signal_generator import generate_signal
from statistical_validator import validate_statistically
from devil_advocate import run_devil_advocate
from risk_manager import validate_risk
from report_formatter import format_signal, format_market_update, format_error_alert
from utils.telegram_sender import send_message, send_health_check_alert, validate_connection
from utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Helper: Buat snapshot market untuk pesan No Trade
# =============================================================================

def _build_market_snapshot(symbol: str, tf_indicators: dict,
                             market_struct: dict,
                             best_score: int) -> dict:
    """
    Buat ringkasan singkat kondisi market untuk satu symbol.
    Dipakai oleh format_market_update() jika tidak ada sinyal.
    """
    df_4h = tf_indicators.get('4h')
    price = float(df_4h['close'].iloc[-1]) if df_4h is not None else 0.0

    return {
        'symbol':    symbol,
        'price':     price,
        'structure': market_struct.get('structure_4h', 'RANGING'),
        'score':     best_score,
    }


# =============================================================================
# Pipeline per Symbol
# =============================================================================

def run_pipeline_for_symbol(symbol: str, symbol_data: dict) -> dict | None:
    """
    Jalankan pipeline lengkap untuk satu symbol.

    Return:
        signal_final dict jika sinyal valid dan lulus semua validasi,
        None jika tidak ada sinyal atau ditolak di salah satu tahap.

    Side effect:
        Mengisi dan return juga 'snapshot' untuk market update via return value.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"  Pipeline: {symbol}")
    logger.info(f"{'='*60}")

    ohlcv        = symbol_data['ohlcv']
    funding_rate = symbol_data['funding_rate']
    open_interest = symbol_data['open_interest']

    # ------------------------------------------------------------------
    # Step 3a: Kalkulasi indikator semua timeframe
    # ------------------------------------------------------------------
    tf_indicators = {}
    for tf, df in ohlcv.items():
        tf_indicators[tf] = calculate_indicators(df, timeframe=tf)

    # ------------------------------------------------------------------
    # Step 3b: Market structure (4H & 1D) + resolusi konflik
    # ------------------------------------------------------------------
    df_4h = tf_indicators.get('4h')
    df_1d = tf_indicators.get('1d')

    if df_4h is None or df_1d is None:
        logger.error(f"{symbol}: DataFrame 4H atau 1D tidak tersedia — skip")
        return None

    market_struct = analyze_market_structure(
        df_4h, df_1d, funding_rate, open_interest, symbol=symbol
    )

    # ------------------------------------------------------------------
    # Step 3c: MTF Confluence — cari arah terbaik
    # ------------------------------------------------------------------
    direction, long_result, short_result = get_best_direction(tf_indicators)

    if direction is None:
        logger.info(f"{symbol}: Tidak ada arah dengan confluence cukup")
        best_score = max(long_result['score'], short_result['score'])
        return {'_snapshot': _build_market_snapshot(
            symbol, tf_indicators, market_struct, best_score
        )}

    confluence_result = long_result if direction == 'LONG' else short_result
    best_score = confluence_result['score']

    # ------------------------------------------------------------------
    # Step 3d: Generate signal draft
    # ------------------------------------------------------------------
    signal_draft = generate_signal(
        symbol, tf_indicators, confluence_result, market_struct
    )

    if signal_draft is None:
        logger.info(f"{symbol}: Tidak ada signal draft yang valid")
        return {'_snapshot': _build_market_snapshot(
            symbol, tf_indicators, market_struct, best_score
        )}

    # Sertakan funding_rate_raw untuk report_formatter
    signal_draft['funding_rate_raw'] = funding_rate

    # ------------------------------------------------------------------
    # Step 3e: Statistical validation
    # ------------------------------------------------------------------
    signal_draft = validate_statistically(df_4h, signal_draft)

    if signal_draft is None:
        logger.info(f"{symbol}: Ditolak oleh statistical validator")
        return {'_snapshot': _build_market_snapshot(
            symbol, tf_indicators, market_struct, best_score
        )}

    # ------------------------------------------------------------------
    # Step 3f: Devil advocate
    # ------------------------------------------------------------------
    da_result = run_devil_advocate(df_4h, signal_draft)

    if da_result['verdict'] == 'REJECTED':
        logger.info(f"{symbol}: Ditolak oleh devil advocate")
        return {'_snapshot': _build_market_snapshot(
            symbol, tf_indicators, market_struct, best_score
        )}

    # Teruskan signal_draft yang mungkin sudah dimodifikasi + flags
    signal_draft = da_result['signal_draft']
    signal_draft['verdict'] = da_result['verdict']
    signal_draft['flags']   = da_result['flags']

    # ------------------------------------------------------------------
    # Step 3g: Risk manager
    # ------------------------------------------------------------------
    signal_final = validate_risk(signal_draft)

    if signal_final is None:
        logger.info(f"{symbol}: Ditolak oleh risk manager")
        return {'_snapshot': _build_market_snapshot(
            symbol, tf_indicators, market_struct, best_score
        )}

    logger.info(f"✅ {symbol}: Signal final siap dikirim")
    return signal_final


# =============================================================================
# Main
# =============================================================================

def main():
    run_ts  = datetime.now(timezone.utc)
    run_str = run_ts.strftime("%Y-%m-%d %H:%M:%S UTC")

    logger.info(f"{'#'*60}")
    logger.info(f"  CRYPTO SIGNAL BOT — RUN START: {run_str}")
    logger.info(f"{'#'*60}")

    # ------------------------------------------------------------------
    # Step 1: Validasi koneksi Telegram
    # ------------------------------------------------------------------
    if not validate_connection():
        logger.error("Tidak bisa terhubung ke Telegram — pipeline dihentikan")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Fetch semua data market
    # ------------------------------------------------------------------
    all_data = fetch_all_data()

    if not all_data:
        msg = f"⚠️ Run {run_str} gagal: Semua symbol gagal di-fetch dari Binance API."
        logger.error(msg)
        send_health_check_alert(msg)
        sys.exit(1)

    if not validate_data(all_data):
        logger.warning("Ada data tidak valid — pipeline tetap dilanjutkan, cek log")

    # ------------------------------------------------------------------
    # Step 3: Loop per symbol — jalankan pipeline
    # ------------------------------------------------------------------
    signals_to_send = []
    market_snapshots = []

    for symbol in SYMBOLS:
        if symbol not in all_data:
            logger.warning(f"{symbol} tidak ada di all_data — skip")
            continue

        try:
            result = run_pipeline_for_symbol(symbol, all_data[symbol])

            if result is None:
                # Error internal — tidak ada snapshot
                market_snapshots.append({
                    'symbol': symbol, 'price': 0,
                    'structure': 'RANGING', 'score': 0
                })

            elif '_snapshot' in result:
                # Pipeline selesai tapi tidak ada sinyal
                market_snapshots.append(result['_snapshot'])

            else:
                # Signal final siap dikirim
                signals_to_send.append(result)
                # Juga buat snapshot untuk referensi (tidak dikirim jika ada sinyal)
                market_snapshots.append({
                    'symbol':    result['symbol'],
                    'price':     result['entry_mid'],
                    'structure': result['structure'],
                    'score':     result['confluence'],
                })

        except Exception as e:
            # Error per symbol tidak boleh membunuh pipeline symbol lain
            logger.error(f"Error tidak tertangani pada {symbol}: {e}", exc_info=True)
            market_snapshots.append({
                'symbol': symbol, 'price': 0,
                'structure': 'RANGING', 'score': 0
            })

    # ------------------------------------------------------------------
    # Step 4: Kirim output ke Telegram
    # ------------------------------------------------------------------
    n_sent = 0

    if signals_to_send:
        for signal_final in signals_to_send:
            msg = format_signal(signal_final)
            if send_message(msg):
                n_sent += 1
                logger.info(
                    f"✅ Sinyal terkirim: {signal_final['symbol']} "
                    f"{signal_final['direction']}"
                )
            else:
                logger.error(
                    f"Gagal kirim sinyal {signal_final['symbol']} "
                    f"— cek koneksi Telegram"
                )
    else:
        # Tidak ada sinyal → kirim market update
        update_msg = format_market_update(market_snapshots)
        if send_message(update_msg):
            n_sent += 1
            logger.info("✅ Market update terkirim (no trade)")
        else:
            # Bahkan market update gagal — kirim plain text alert
            fallback = format_error_alert(run_str, "Gagal kirim market update ke Telegram")
            send_health_check_alert(fallback)

    # ------------------------------------------------------------------
    # Step 5: Log ringkasan run (health check)
    # ------------------------------------------------------------------
    end_ts  = datetime.now(timezone.utc)
    elapsed = round((end_ts - run_ts).total_seconds(), 1)

    logger.info(f"\n{'#'*60}")
    logger.info(
        f"=== RUN COMPLETE: {run_str} | "
        f"Signals sent: {n_sent} | "
        f"Duration: {elapsed}s ==="
    )
    logger.info(f"{'#'*60}")


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    main()
