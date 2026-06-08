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

# Baca dari env — diset sebagai GitHub Secret
_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

_BASE_URL  = f"https://api.telegram.org/bot{_BOT_TOKEN}"

# Konstanta retry
_MAX_RETRY    = 3
_RETRY_DELAY  = 5   # detik


# =============================================================================
# Helper: Kirim satu request ke Telegram API
# =============================================================================

def _send_request(text: str, parse_mode: str = "MarkdownV2") -> bool:
    """
    Kirim satu POST request ke Telegram sendMessage endpoint.

    Return:
        True jika berhasil (HTTP 200 + ok=True), False jika gagal.
    """
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

        # Telegram mengembalikan error detail di response body
        error_desc = response.json().get("description", "unknown error")
        logger.warning(
            f"Telegram API error — HTTP {response.status_code}: {error_desc}"
        )
        return False

    except requests.exceptions.RequestException as e:
        logger.warning(f"Request exception ke Telegram: {e}")
        return False


# =============================================================================
# Kirim pesan dengan retry
# =============================================================================

def send_message(text: str, parse_mode: str = "MarkdownV2") -> bool:
    """
    Kirim pesan ke channel dengan retry otomatis.

    Retry sebanyak _MAX_RETRY kali dengan jeda _RETRY_DELAY detik.
    Jika semua retry gagal, log ERROR tapi tidak crash program.

    Parameter:
        text       : pesan yang sudah diformat (output report_formatter)
        parse_mode : 'MarkdownV2' (default) atau 'HTML'

    Return:
        True jika berhasil terkirim, False jika semua retry gagal.
    """
    for attempt in range(1, _MAX_RETRY + 1):
        success = _send_request(text, parse_mode)

        if success:
            logger.info(f"✅ Pesan terkirim ke Telegram (attempt {attempt})")
            return True

        logger.warning(
            f"Gagal kirim ke Telegram (attempt {attempt}/{_MAX_RETRY})"
        )

        if attempt < _MAX_RETRY:
            time.sleep(_RETRY_DELAY)

    logger.error(
        f"Semua {_MAX_RETRY} retry gagal — pesan tidak terkirim. "
        f"Cek log untuk detail."
    )
    return False


# =============================================================================
# Kirim health check alert (error kritis)
# =============================================================================

def send_health_check_alert(message: str) -> bool:
    """
    Kirim alert error kritis ke channel.
    Dipakai oleh orchestrator.py saat terjadi kegagalan fatal.

    Parameter:
        message : string pesan alert (plain text, tidak perlu formatting)

    Return:
        True jika berhasil, False jika tidak.
    """
    logger.warning(f"Mengirim health check alert: {message}")
    # Gunakan plain text untuk alert error agar tidak gagal karena
    # karakter spesial MarkdownV2 di stack trace
    return send_message(message, parse_mode="HTML")


# =============================================================================
# Validasi koneksi (opsional, bisa dipanggil di awal orchestrator)
# =============================================================================

def validate_connection() -> bool:
    """
    Test koneksi ke Telegram API dengan memanggil getMe endpoint.
    Berguna untuk early-fail sebelum pipeline berjalan.

    Return:
        True jika token valid dan bot bisa dihubungi, False jika tidak.
    """
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
