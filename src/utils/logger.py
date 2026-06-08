# =============================================================================
# logger.py — Logging Standar
# Format: [TIMESTAMP] [LEVEL] [MODULE] message
# Output ke stdout — GitHub Actions akan capture otomatis.
# =============================================================================

import logging
import sys
from datetime import datetime, timezone


def get_logger(module_name: str) -> logging.Logger:
    """
    Buat logger dengan format standar untuk satu module.

    Cara pakai di module lain:
        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Pesan info")
        logger.warning("Pesan warning")
        logger.error("Terjadi error")
    """
    logger = logging.getLogger(module_name)

    # Hindari duplicate handler kalau dipanggil berkali-kali
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Handler ke stdout (bukan stderr) agar GitHub Actions bisa capture
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)

    # Format: [2026-06-01 08:00:00 UTC] [INFO] [data_collector] Fetching BTCUSDT...
    formatter = logging.Formatter(
        fmt='[%(asctime)s UTC] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Paksa timezone UTC di log
    formatter.converter = lambda *args: datetime.now(timezone.utc).timetuple()

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
