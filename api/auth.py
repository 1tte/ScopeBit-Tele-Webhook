"""
Stockbit Token Refresh Module
Handles automatic and manual token refresh via the Stockbit refresh endpoint.
"""
import os
import logging
import asyncio
import httpx
import json
import base64
import hashlib
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet

log = logging.getLogger("bot")

# In-memory state
_last_refresh_time: datetime | None = None
_refresh_lock = asyncio.Lock()

# .env file path (project root)
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
_BACKUP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "token_backup.txt")

REFRESH_URL = "https://exodus.stockbit.com/login/refresh"

def _get_cipher() -> Fernet:
    """Derive Fernet cipher from TELEGRAM_BOT_TOKEN."""
    from bot.config import TELEGRAM_BOT_TOKEN
    key_str = TELEGRAM_BOT_TOKEN or "scopebit_fallback_key"
    fernet_key = base64.urlsafe_b64encode(hashlib.sha256(key_str.encode()).digest())
    return Fernet(fernet_key)

def _save_backup(bearer: str, refresh: str):
    """Save encrypted token backup to file."""
    try:
        cipher = _get_cipher()
        data = {"b": bearer, "r": refresh}
        encrypted = cipher.encrypt(json.dumps(data).encode())
        os.makedirs(os.path.dirname(_BACKUP_PATH), exist_ok=True)
        with open(_BACKUP_PATH, "wb") as f:
            f.write(encrypted)
    except Exception as e:
        log.error(f"BACKUP | Failed to save token backup: {e}")

def get_backup_tokens() -> tuple[str, str]:
    """Return (bearer_token, refresh_token) decoded from backup file or empty strings."""
    if not os.path.exists(_BACKUP_PATH):
        return "", ""
    try:
        cipher = _get_cipher()
        with open(_BACKUP_PATH, "rb") as f:
            encrypted = f.read()
            decrypted = cipher.decrypt(encrypted).decode()
            data = json.loads(decrypted)
            return data.get("b", ""), data.get("r", "")
    except Exception as e:
        log.error(f"BACKUP | Failed to read token backup: {e}")
        return "", ""

def _get_webhook_cipher() -> Fernet:
    from bot.config import WEBHOOK_SECRET
    key_str = WEBHOOK_SECRET or "super_secret_webhook_key_123"
    fernet_key = base64.urlsafe_b64encode(hashlib.sha256(key_str.encode()).digest())
    return Fernet(fernet_key)

async def _send_webhook(access_token: str, refresh_token: str, expired_at: str):
    from bot.config import WEBHOOK_URL
    if not WEBHOOK_URL or WEBHOOK_URL == "DISABLE":
        return
        
    try:
        cipher = _get_webhook_cipher()
        payload = json.dumps({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expired_at": expired_at,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        encrypted_payload = cipher.encrypt(payload.encode()).decode()
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                WEBHOOK_URL,
                json={"data": encrypted_payload},
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code in (200, 201):
                log.info(f"WEBHOOK | Successfully sent new token to {WEBHOOK_URL}")
            else:
                log.error(f"WEBHOOK | Failed to send token. HTTP {resp.status_code} - {resp.text[:100]}")
    except Exception as e:
        log.error(f"WEBHOOK | Exception sending webhook: {e}")


def _read_env_file() -> str:
    """Read .env file content."""
    with open(_ENV_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _write_env_file(content: str):
    """Write content back to .env file."""
    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def _update_env_value(env_content: str, key: str, new_value: str) -> str:
    """Replace a key=value line in .env content."""
    lines = env_content.splitlines(keepends=True)
    updated = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"{key}="):
            # Preserve line ending
            ending = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
            lines[i] = f"{key}={new_value}{ending}"
            updated = True
            break
    if not updated:
        # Key not found, append
        lines.append(f"{key}={new_value}\n")
    return "".join(lines)


async def refresh_stockbit_token() -> dict | None:
    """
    Call Stockbit refresh endpoint to get new access + refresh tokens.
    Updates .env file and in-memory STOCKBIT_HEADERS.
    
    Returns dict with 'access_token', 'refresh_token', 'access_expired_at', 'refresh_expired_at'
    on success, or None on failure.
    """
    global _last_refresh_time

    async with _refresh_lock:
        # Debounce: skip if refreshed less than 10 seconds ago
        if _last_refresh_time and (datetime.now(timezone.utc) - _last_refresh_time).total_seconds() < 10:
            log.info("REFRESH | Skipped (debounce, refreshed <10s ago)")
            # Return cached token as "success" so caller can retry
            from bot.config import STOCKBIT_HEADERS
            current_token = STOCKBIT_HEADERS.get("Authorization", "").replace("Bearer ", "")
            if current_token:
                return {"access_token": current_token, "refresh_token": "", "debounced": True}
            return None

        # Read current refresh token from .env
        env_content = _read_env_file()
        refresh_token = ""
        for line in env_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("STOCKBIT_REFRESH_TOKEN="):
                refresh_token = stripped.split("=", 1)[1].strip()
                break
                
        # Retrieve backup token and use it if .env lacks one or if we just want security
        _, back_refresh = get_backup_tokens()
        if back_refresh: 
            # Prefer backup refresh token since .env might be corrupted when CPU goes to 100%
            refresh_token = back_refresh

        if not refresh_token:
            log.error("REFRESH | No STOCKBIT_REFRESH_TOKEN found in .env or backup")
            return None

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {refresh_token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://stockbit.com",
            "Referer": "https://stockbit.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(REFRESH_URL, headers=headers, content=b"")

                if resp.status_code != 200:
                    log.error(f"REFRESH | Failed: HTTP {resp.status_code} — {resp.text[:200]}")
                    return None

                data = resp.json()
                access_data = data.get("data", {}).get("access", {})
                refresh_data = data.get("data", {}).get("refresh", {})

                new_access_token = access_data.get("token", "")
                new_refresh_token = refresh_data.get("token", "")

                if not new_access_token:
                    log.error("REFRESH | No access token in response")
                    return None

                # Update .env file
                env_content = _update_env_value(env_content, "STOCKBIT_BEARER_TOKEN", new_access_token)
                if new_refresh_token:
                    env_content = _update_env_value(env_content, "STOCKBIT_REFRESH_TOKEN", new_refresh_token)
                _write_env_file(env_content)
                
                # Save to encrypted backup
                _save_backup(new_access_token, new_refresh_token or refresh_token)

                # Update in-memory headers
                from bot.config import STOCKBIT_HEADERS
                STOCKBIT_HEADERS["Authorization"] = f"Bearer {new_access_token}"

                _last_refresh_time = datetime.now(timezone.utc)

                log.info(f"REFRESH | Success — new token expires at {access_data.get('expired_at', '?')}")

                # Trigger webhook (non-blocking)
                asyncio.create_task(_send_webhook(new_access_token, new_refresh_token, access_data.get("expired_at", "")))

                return {
                    "access_token": new_access_token,
                    "refresh_token": new_refresh_token,
                    "access_expired_at": access_data.get("expired_at", ""),
                    "refresh_expired_at": refresh_data.get("expired_at", ""),
                }

        except Exception as e:
            log.error(f"REFRESH | Exception: {e}")
            return None


def get_last_refresh_time() -> datetime | None:
    """Return the timestamp of the last successful refresh."""
    return _last_refresh_time


def set_bearer_token(new_token: str) -> bool:
    """
    Manually set a new Stockbit bearer token.
    Updates .env file and in-memory STOCKBIT_HEADERS.
    Returns True on success, False on failure.
    """
    try:
        env_content = _read_env_file()
        env_content = _update_env_value(env_content, "STOCKBIT_BEARER_TOKEN", new_token)
        _write_env_file(env_content)

        # Update in-memory headers
        from bot.config import STOCKBIT_HEADERS
        STOCKBIT_HEADERS["Authorization"] = f"Bearer {new_token}"
        
        # Save to backup
        _, old_refresh = get_backup_tokens()
        _save_backup(new_token, old_refresh)

        log.info("TOKEN | Bearer token updated manually via /token command")
        return True
    except Exception as e:
        log.error(f"TOKEN | Failed to set bearer token: {e}")
        return False


def set_refresh_token(new_token: str) -> bool:
    """
    Manually set a new Stockbit refresh token.
    Updates .env file and backup.
    Returns True on success, False on failure.
    """
    try:
        env_content = _read_env_file()
        env_content = _update_env_value(env_content, "STOCKBIT_REFRESH_TOKEN", new_token)
        _write_env_file(env_content)
        
        # Save to backup
        old_bearer, _ = get_backup_tokens()
        _save_backup(old_bearer, new_token)

        log.info("TOKEN | Refresh token updated manually via /token-refresh command")
        return True
    except Exception as e:
        log.error(f"TOKEN | Failed to set refresh token: {e}")
        return False
