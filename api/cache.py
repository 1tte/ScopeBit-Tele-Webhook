"""
In-memory TTL cache for API responses.
Caches running trades per symbol to avoid re-fetching for repeated requests.
"""
import time
import threading
import logging
from datetime import datetime, timedelta

log = logging.getLogger("bot")

_cache = {}
_lock = threading.Lock()

# Default TTL: 5 minutes (trades refresh during market hours)
DEFAULT_TTL = 300

def get_8am_expiry_ttl() -> int:
    """Calculate seconds until the next 8:00 AM for daily cache reset."""
    now = datetime.now()
    target = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    ttl = (target - now).total_seconds()
    return int(ttl)


def get(key: str):
    """Get cached value if exists and not expired. Returns None if miss."""
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if time.time() > expiry:
            del _cache[key]
            return None
        return value


def put(key: str, value, ttl: int = DEFAULT_TTL):
    """Store value in cache with TTL in seconds."""
    with _lock:
        _cache[key] = (value, time.time() + ttl)


def put_daily(key: str, value):
    """Store value in cache that expires at 8:00 AM next day."""
    ttl = get_8am_expiry_ttl()
    with _lock:
        _cache[key] = (value, time.time() + ttl)


def invalidate(key: str):
    """Remove a specific key from cache."""
    with _lock:
        _cache.pop(key, None)


def clear():
    """Clear all cached data."""
    with _lock:
        _cache.clear()
    log.info("Cache cleared")


def stats() -> dict:
    """Return cache statistics."""
    with _lock:
        now = time.time()
        total = len(_cache)
        active = sum(1 for _, (_, exp) in _cache.items() if exp > now)
        return {"total": total, "active": active, "expired": total - active}
