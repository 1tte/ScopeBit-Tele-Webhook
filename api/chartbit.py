from datetime import datetime, timedelta, timezone
from bot.config import STOCKBIT_BASE_URL
from api.client import _get, _safe_int, _safe_float

# Jakarta timezone offset (UTC+7)
_WIB = timezone(timedelta(hours=7))


async def get_daily_chart(symbol: str, days: int = 120) -> list:
    """Fetch daily OHLCV data from Stockbit Chartbit endpoint."""
    now_wib = datetime.now(_WIB)
    end_date = now_wib
    start_date = end_date - timedelta(days=days)

    # Chartbit uses from=NEWEST, to=OLDEST (descending order)
    url = f"{STOCKBIT_BASE_URL}/chartbit/{symbol}/price/daily"
    params = {
        "from": end_date.strftime("%Y-%m-%d"),
        "to": start_date.strftime("%Y-%m-%d"),
        "limit": 0
    }
    data = await _get(url, params)
    if not data or "data" not in data:
        return []

    chartbit = data["data"].get("chartbit", [])
    if not chartbit:
        return []

    results = []
    results = []
    for candle in chartbit:
        # Some old days might have no volume or prices, skip to save RAM
        c = _safe_int(candle.get("close", 0))
        if c == 0:
            continue
            
        results.append({
            "date": candle.get("date", ""),
            "open": _safe_int(candle.get("open", 0)),
            "high": _safe_int(candle.get("high", 0)),
            "low": _safe_int(candle.get("low", 0)),
            "close": c,
            "volume": _safe_int(candle.get("volume", 0)),
        })

    # Sort ascending by date
    results.sort(key=lambda x: x["date"])
    return results


async def get_intraday_chart(symbol: str) -> list:
    """Fetch intraday (5-min) OHLCV data from Stockbit Chartbit endpoint.
    
    Uses Unix timestamps matching Stockbit's format:
        from = today market open (00:00 WIB as Unix timestamp)
        to   = yesterday end (23:59 WIB as Unix timestamp)
    
    Note: 'from' > 'to' is the Stockbit convention (newest first).
    """
    now_wib = datetime.now(_WIB)
    
    # 'from' = Now (Newest)
    from_ts = int(now_wib.timestamp())
    
    # 'to' = 45 days ago (Oldest) untuk memastikan cukup 21+ hari trading (MA20 daily)
    # Buffer: 21 trading days + weekends + libur nasional IDX
    lookback_days = now_wib - timedelta(days=45)
    to_ts = int(lookback_days.timestamp())
    
    url = f"{STOCKBIT_BASE_URL}/chartbit/{symbol}/price/intraday"
    params = {
        "from": from_ts,
        "to": to_ts,
        "limit": 0
    }
    data = await _get(url, params)
    if not data or "data" not in data:
        return []

    chartbit = data["data"].get("chartbit", [])
    if not chartbit:
        return []

    results = []
    results = []
    for candle in chartbit:
        c = _safe_int(candle.get("close", 0))
        if c == 0:
            continue
            
        # Intraday payload uses "datetime" or "unix_timestamp" instead of "date"
        raw_date = candle.get("datetime", candle.get("unix_timestamp", candle.get("date", "")))
        
        results.append({
            "date": str(raw_date),
            "open": _safe_int(candle.get("open", 0)),
            "high": _safe_int(candle.get("high", 0)),
            "low": _safe_int(candle.get("low", 0)),
            "close": c,
            "volume": _safe_int(candle.get("volume", 0)),
        })

    # Sort ascending by date (intraday timestamps)
    results.sort(key=lambda x: x["date"])
    return results
