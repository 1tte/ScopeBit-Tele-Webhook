import os
from dotenv import load_dotenv

load_dotenv()

# Telegram (Moved up for cipher key requirement)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Webhook for Token Distribution
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://scopebit.online/api/webhook-token/index.php")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "super_secret_webhook_key_123")

# Stockbit API - Prioritize encrypted backup token if exists
back_bearer, back_refresh = "", ""
try:
    from api.auth import get_backup_tokens
    back_bearer, back_refresh = get_backup_tokens()
except Exception:
    pass

STOCKBIT_BEARER_TOKEN = back_bearer if back_bearer else os.getenv("STOCKBIT_BEARER_TOKEN")
STOCKBIT_REFRESH_TOKEN = back_refresh if back_refresh else os.getenv("STOCKBIT_REFRESH_TOKEN")
STOCKBIT_BASE_URL = "https://exodus.stockbit.com"

STOCKBIT_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {STOCKBIT_BEARER_TOKEN}",
    "Referer": "https://stockbit.com/",
    "Origin": "https://stockbit.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}

# Bot Mode: "debug" or "production"
BOT_MODE = os.getenv("BOT_MODE", "debug").strip().lower()

def _int_env(key: str) -> int | None:
    """Safely convert an env var to int, returning None if empty/missing."""
    val = os.getenv(key)
    if not val or not val.strip():
        return None
    try:
        return int(val.strip())
    except ValueError:
        return None

if BOT_MODE == "production":
    ALLOWED_CHAT_ID = _int_env("PROD_CHAT_ID")
    ALLOWED_THREAD_ID = _int_env("PROD_THREAD_ID")
    JARVIS_THREAD_ID = _int_env("PROD_JARVIS_THREAD_ID")  # For automated JARVIS reports
    NEWS_THREAD_ID = _int_env("PROD_NEWS_THREAD_ID")      # For news broadcasts
else:
    ALLOWED_CHAT_ID = _int_env("DEBUG_CHAT_ID")
    ALLOWED_THREAD_ID = _int_env("DEBUG_THREAD_ID")
    JARVIS_THREAD_ID = _int_env("DEBUG_THREAD_ID")        # Same thread in debug
    NEWS_THREAD_ID = _int_env("DEBUG_NEWS_THREAD_ID")     # Same thread in debug

# Feature Toggles (default to True)
def _get_bool_env(key: str, default: bool = True) -> bool:
    val = os.getenv(key)
    if val is None: return default
    return val.strip().lower() == "true"

CMD_SM_ENABLED = _get_bool_env("CMD_SM_ENABLED")
CMD_BR_ENABLED = _get_bool_env("CMD_BR_ENABLED")
CMD_FA_ENABLED = _get_bool_env("CMD_FA_ENABLED")
CMD_SW_ENABLED = _get_bool_env("CMD_SW_ENABLED")
CMD_DT_ENABLED = _get_bool_env("CMD_DT_ENABLED")
CMD_RCM_ENABLED = _get_bool_env("CMD_RCM_ENABLED")
CMD_IM_ENABLED = _get_bool_env("CMD_IM_ENABLED")
CMD_FC_ENABLED = _get_bool_env("CMD_FC_ENABLED")
CMD_REPORT_ENABLED = _get_bool_env("CMD_REPORT_ENABLED")
