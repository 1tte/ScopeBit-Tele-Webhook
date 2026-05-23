import os
import json
import time
import asyncio
from datetime import datetime
from bot.config import STOCKBIT_BASE_URL
from api.client import _get

# Ensure cache directory exists
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)
FUNDA_CACHE_FILE = os.path.join(CACHE_DIR, "fundamentals.json")

# In-memory lock for writing to the cache file
_funda_cache_lock = asyncio.Lock()

def _get_today_str() -> str:
    """Returns YYYY-MM-DD for checking if cache is still valid today."""
    from datetime import datetime, timezone, timedelta
    _WIB = timezone(timedelta(hours=7))
    now = datetime.now(_WIB)
    # Cache resets at 06:00 AM everyday to ensure we get updated fundamental calc for the new day
    if now.hour < 6:
        from datetime import timedelta
        now = now - timedelta(days=1)
    return now.strftime("%Y-%m-%d")

async def _load_funda_cache() -> dict:
    """Load the fundamental cache from disk."""
    if not os.path.exists(FUNDA_CACHE_FILE):
        return {}
    try:
        with open(FUNDA_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Check if the cache is from today, if not, clear it
            if data.get("_date") != _get_today_str():
                return {}
            return data
    except Exception:
        return {}

async def _save_funda_cache(data: dict):
    """Save the fundamental cache to disk."""
    data["_date"] = _get_today_str()
    async with _funda_cache_lock:
        try:
            # Write to a temporary file first, then replace to prevent corruption
            tmp_file = f"{FUNDA_CACHE_FILE}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
            os.replace(tmp_file, FUNDA_CACHE_FILE)
        except Exception as e:
            import logging
            logging.getLogger("bot").warning(f"Gagal menyimpan cache fundamental: {e}")

async def _get_cached_funda(symbol: str, endpoint_type: str, fetch_url: str, params: dict = None, compressor_fn=lambda x: x) -> dict | None:
    """Helper to get fundamental data from disk cache or fetch from API."""
    cache_data = await _load_funda_cache()
    
    # Check if data exists in cache
    symbol_cache = cache_data.get(symbol, {})
    if endpoint_type in symbol_cache:
        return symbol_cache[endpoint_type]
        
    # If not in cache, fetch from API
    data = await _get(fetch_url, params)
    if not data or "data" not in data:
        return None
        
    # Compress the massive API response to only what we need
    result = compressor_fn(data["data"])
    
    # Save to cache
    if symbol not in cache_data:
        cache_data[symbol] = {}
    cache_data[symbol][endpoint_type] = result
    
    # Fire and forget save so it doesn't block the return
    asyncio.create_task(_save_funda_cache(cache_data))
    
    return result

def _compress_info(data: dict) -> dict:
    return {
        "name": data.get("name"),
        "sector": data.get("sector"),
        "sub_sector": data.get("sub_sector"),
        "price": data.get("price")
    }

def _compress_keystats(data: dict) -> dict:
    required_ids = {
        "12148", "2891", "16577", "2896", "13431", "13432", "2898", "2893", 
        "16533", "2897", "21457", "1561", "1562", "1563", "1460", "1461", 
        "1462", "13447", "1508", "1484", "1573", "1502", "13402", "2916", 
        "2915", "13200", "15718", "15882", "15879", "15880", "2536", "13366", "1467"
    }
    
    compressed = {
        "stats": {
            "market_cap": data.get("stats", {}).get("market_cap"),
            "current_share_outstanding": data.get("stats", {}).get("current_share_outstanding"),
            "enterprise_value": data.get("stats", {}).get("enterprise_value"),
            "free_float": data.get("stats", {}).get("free_float")
        },
        "closure_fin_items_results": []
    }
    
    for group in data.get("closure_fin_items_results", []):
        new_group = {"fin_name_results": []}
        for item in group.get("fin_name_results", []):
            fitem = item.get("fitem", {})
            f_id = fitem.get("id")
            if f_id in required_ids:
                new_group["fin_name_results"].append({
                    "fitem": {"id": f_id, "value": fitem.get("value")}
                })
        if new_group["fin_name_results"]:
            compressed["closure_fin_items_results"].append(new_group)
            
    return compressed

def _compress_profile(data: dict) -> dict:
    return {
        "shareholder": data.get("shareholder", [])[:5],
        "listing_information": data.get("listing_information", {}),
        "shareholder_numbers": data.get("shareholder_numbers", [])[:4]
    }

async def get_info(symbol: str) -> dict | None:
    """Fetch basic company info (sector, subsector, prices). Daily Cached."""
    url = f"{STOCKBIT_BASE_URL}/emitten/{symbol}/info"
    return await _get_cached_funda(symbol, "info", url, compressor_fn=_compress_info)

async def get_keystats(symbol: str) -> dict | None:
    """Fetch 10-year fundamental key stats ratios. Daily Cached."""
    url = f"{STOCKBIT_BASE_URL}/keystats/ratio/v1/{symbol}"
    params = {"year_limit": 10}
    return await _get_cached_funda(symbol, "keystats", url, params, compressor_fn=_compress_keystats)

async def get_profile(symbol: str) -> dict | None:
    """Fetch company profile (shareholders, dividend info, etc). Daily Cached."""
    url = f"{STOCKBIT_BASE_URL}/emitten/{symbol}/profile"
    return await _get_cached_funda(symbol, "profile", url, compressor_fn=_compress_profile)
