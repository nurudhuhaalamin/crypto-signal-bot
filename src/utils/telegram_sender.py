# =============================================================================
# telegram_sender.py — Output Layer (5.2)
# Kirim pesan ke Telegram channel dengan retry otomatis.
# Token dan chat_id dibaca dari environment variable.
# =============================================================================

import os
import time
import requests

from utils.logger import get_logger

logger = get_logger(__name__)

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
_BASE_URL  = f"https://api.telegram.org/bot{_BOT_TOKEN}"

_MAX_RETRY   = 3
_RETRY_DELAY = 5


def _send_request(text: str, parse_mode: str = "HTML") -> bool:
    if not _BOT_TOKEN or not _CHAT_ID:
        logger.error(
            "TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID tidak ditemukan di env. "
            "Pastikan GitHub Secrets sudah diset."
        )
        return False

    url     = f"{_BASE_URL}/sendMessage"
    payload = {
        "chat_id":                  _CHAT_ID,
        "text":                     text,
        "parse_mode":               parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 200 and response.json().get("ok"):
            return True

        error_desc = response.json().get("description", "unknown error")
        logger.warning(
            f"Telegram API error — HTTP {response.status_code}: {error_desc}\n"
            f"Isi pesan (100 char pertama): {text[:100]}"
        )
        return False

    except requests.exceptions.RequestException as e:
        logger.warning(f"Request exception ke Telegram: {e}")
        return False


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    for attempt in range(1, _MAX_RETRY + 1):
        success = _send_request(text, parse_mode)

        if success:
            logger.info(f"✅ Pesan terkirim ke Telegram (attempt {attempt})")
            return True

        logger.warning(f"Gagal kirim ke Telegram (attempt {attempt}/{_MAX_RETRY})")

        if attempt < _MAX_RETRY:
            time.sleep(_RETRY_DELAY)

    logger.error(f"Semua {_MAX_RETRY} retry gagal — pesan tidak terkirim.")
    return False


def send_health_check_alert(message: str) -> bool:
    logger.warning(f"Mengirim health check alert: {message}")
    return send_message(message, parse_mode="HTML")


def validate_connection() -> bool:
    if not _BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN kosong — tidak bisa validasi koneksi")
        return False

    try:
        response = requests.get(f"{_BASE_URL}/getMe", timeout=10)
        if response.status_code == 200 and response.json().get("ok"):
            bot_name = response.json()["result"].get("username", "unknown")
            logger.info(f"✅ Telegram koneksi valid — bot: @{bot_name}")
            return True

        logger.error(
            f"Telegram getMe gagal — HTTP {response.status_code}: "
            f"{response.json().get('description', 'unknown')}"
        )
        return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Tidak bisa menghubungi Telegram API: {e}")
        return False
