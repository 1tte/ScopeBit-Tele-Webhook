import httpx
import logging
from contextvars import ContextVar
from bot.config import STOCKBIT_BASE_URL, STOCKBIT_HEADERS

log = logging.getLogger("bot")

api_request_counter = ContextVar('api_request_counter', default=None)

def _safe_int(val) -> int:
    """Safely convert API values like '2,970', '-', '' or '123' to int."""
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        cleaned = val.replace(",", "").replace(".", "").strip()
        if not cleaned or cleaned in ("-", "+", "–", "—"):
            return 0
        try:
            return int(cleaned)
        except ValueError:
            return 0
    return 0


def _safe_float(val) -> float:
    """Safely convert API values to float."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace(",", "").strip()
        if not cleaned or cleaned in ("-", "+", "–", "—"):
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


class AuthError(Exception):
    """Raised when Stockbit API returns 401 Unauthorized and refresh fails."""
    pass


import time
import asyncio
import json

_request_cache = {}

async def _get(url: str, params=None) -> dict | None:
    """Make authenticated GET request to Stockbit API.
    Uses a 15-second Future-based cache to perfectly deduplicate identical concurrent calls.
    On 401, attempts token refresh and retries.
    """
    try:
        cache_key = f"{url}?{json.dumps(params, sort_keys=True)}" if params else url
    except Exception:
        cache_key = f"{url}?{str(params)}"
        
    now = time.time()
    
    # Check cache for recent requests (< 15s)
    if cache_key in _request_cache:
        cache_time, cache_fut = _request_cache[cache_key]
        if now - cache_time < 15.0:
            try:
                # Wait for the pending concurrent request to finish
                return await cache_fut
            except Exception:
                pass # If the cached one failed, we just retry natively

    # Create new future for others to await
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _request_cache[cache_key] = (now, fut)
    
    # Cleanup old cache entries occasionally
    if len(_request_cache) > 100:
        for k in list(_request_cache.keys()):
            if now - _request_cache[k][0] > 15.0:
                del _request_cache[k]

    try:
        tracker = api_request_counter.get()
        if tracker is not None:
            tracker["count"] += 1
            
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=STOCKBIT_HEADERS, params=params)
            
            if resp.status_code == 401:
                log.info(f"AUTH | 401 received, attempting token refresh...")
                from api.auth import refresh_stockbit_token
                result = await refresh_stockbit_token()
                
                if result:
                    log.info("AUTH | Refresh succeeded, retrying request...")
                    # STOCKBIT_HEADERS dict is mutated in-place by refresh, re-read it
                    resp = await client.get(url, headers=STOCKBIT_HEADERS, params=params)
                    if resp.status_code == 401:
                        raise AuthError("Unauthorized: Token refresh succeeded but request still failed.")
                    resp.raise_for_status()
                    res = resp.json()
                    if not fut.done():
                        fut.set_result(res)
                    return res
                else:
                    raise AuthError("Unauthorized: Token refresh failed.")

            resp.raise_for_status()
            res = resp.json()
            if not fut.done():
                fut.set_result(res)
            return res
            
    except AuthError as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    except httpx.RequestError:
        if not fut.done():
            fut.set_result(None)
        return None
    except httpx.HTTPStatusError:
        if not fut.done():
            fut.set_result(None)
        return None
    except Exception as e:
        if not fut.done():
            fut.set_exception(e)
        raise e

