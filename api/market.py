import urllib.parse
import random
import time
from bot.config import STOCKBIT_BASE_URL
from api.client import _get, _safe_int
from api import cache as trade_cache


async def get_orderbook(symbol: str) -> dict | None:
    """Fetch current price, volume, and value from orderbook.
    Caches the result until 8:00 AM next day as requested for daily scan optimization.
    """
    cache_key = f"orderbook:{symbol}"
    cached = trade_cache.get(cache_key)
    if cached is not None:
        return cached

    url = f"{STOCKBIT_BASE_URL}/company-price-feed/v2/orderbook/companies/{symbol}"
    data = await _get(url)
    if not data or "data" not in data:
        return None

    d = data["data"]
    return {
        "last_price": _safe_int(d.get("lastprice", 0)),
        "change_pct": float(d.get("percentage_change", 0)),
        "volume": _safe_int(d.get("volume", 0)),
        "value": _safe_int(d.get("value", 0)),
        "frequency": _safe_int(d.get("frequency", 0)),
        "fnet": _safe_int(d.get("fnet", 0)),
        "high": _safe_int(d.get("high", 0)),
        "low": _safe_int(d.get("low", 0)),
        "bid": d.get("bid", []),
        "offer": d.get("offer", []),
    }
    
    trade_cache.put_daily(cache_key, res)
    return res

async def get_running_trade(symbol: str, limit: int = 0, on_progress=None) -> list:
    """Fetch running trades for flow analysis.
    
    API returns ~40 trades per page, so we paginate using trade_number cursor.
    limit=0 means fetch ALL trades (no cap).
    
    Args:
        symbol: Stock symbol
        limit: Max trades to fetch (0=all)
        on_progress: Optional callback(fetched_count, symbol) called every 5 pages
    
    Returns cached data if available (TTL until 8:00 AM next day).
    """
    # For scanner (limit > 0), check if we already have the full dataset (limit=0) cached
    if limit > 0:
        full_cached = trade_cache.get(f"trades:{symbol}:0")
        if full_cached is not None:
            return full_cached[:limit]
            
    cache_key = f"trades:{symbol}:{limit}"
    cached = trade_cache.get(cache_key)
    if cached is not None:
        return cached

    url = f"{STOCKBIT_BASE_URL}/order-trade/running-trade"
    all_trades = []
    trade_number = None
    last_trade_number = None
    page = 0

    while True:
        if limit > 0 and len(all_trades) >= limit:
            break

        params = {
            "sort": "DESC",
            "limit": 50,
            "order_by": "RUNNING_TRADE_ORDER_BY_TIME",
            "symbols[]": symbol,
            "action_type": "RUNNING_TRADE_ACTION_TYPE_ALL",
            "minimum_lot": 0,
        }
        if trade_number:
            params["trade_number"] = trade_number

        # Brute force retry mechanism for rate limits / timeouts
        retry_count = 0
        max_retries = 3
        data = None
        
        while retry_count < max_retries:
            data = await _get(url, params)
            if data and "data" in data:
                break
            
            retry_count += 1
            # Sleep random 0.1s - 0.3s before retrying to bypass rate limits
            time.sleep(random.uniform(0.1, 0.3))
            
        if not data or "data" not in data:
            # If after retries it still fails, just break and return what we have so far
            break

        batch = data["data"].get("running_trade", [])
        if not batch:
            break

        all_trades.extend(batch)
        page += 1

        # Progress callback every 5 pages (~200 trades)
        if on_progress and page % 5 == 0:
            on_progress(len(all_trades), symbol)

        # Use last trade_number as cursor for next page
        trade_number = batch[-1].get("trade_number")
        
        # Prevent infinite loop if API returns the exact same cursor endlessly
        if not trade_number or trade_number == last_trade_number:
            break
            
        last_trade_number = trade_number
        
        # Hard cap pages at 500 (25,000 trades) to prevent extreme hanging for highly active stocks
        if page >= 500:
            break

    result = all_trades[:limit] if limit > 0 else all_trades
    
    # Cache result (Daily TTL config to 8:00 AM)
    if result:
        trade_cache.put_daily(cache_key, result)
    
    return result

async def get_historical_summary(symbol: str, days: int = 20) -> list:
    """Fetch daily OHLC, Volume, and Foreign Flow."""
    from datetime import datetime, timedelta, timezone
    _WIB = timezone(timedelta(hours=7))
    end_date = datetime.now(_WIB)
    start_date = end_date - timedelta(days=days*2) # give buffer for weekends
        
    url = f"{STOCKBIT_BASE_URL}/company-price-feed/historical/summary/{symbol}"
    params = {
        "period": "HS_PERIOD_DAILY",
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "limit": days,
        "page": 1
    }
    data = await _get(url, params)
    if not data or "data" not in data:
        return []
        
    result = data["data"].get("result", [])
    
    # Compress the historical summary dictionaries to strip out unused bloat
    compressed = []
    for r in result:
        if isinstance(r, dict):
            compressed.append({
                "date": r.get("date"),
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "volume": r.get("volume"),
                "value": r.get("value"),
                "frequency": r.get("frequency"),
                "net_foreign": r.get("net_foreign")
            })
        
    return compressed

async def get_trade_book(symbol: str) -> dict | None:
    """Fetch price distribution (fractions) for a symbol."""
    url = f"{STOCKBIT_BASE_URL}/order-trade/trade-book"
    params = {
        "symbol": symbol,
        "group_by": "GROUP_BY_PRICE"
    }
    data = await _get(url, params)
    if not data or "data" not in data:
        return None
        
    # Compress trade book 
    book_list_raw = data["data"].get("book", [])
    compressed_book = []
    if isinstance(book_list_raw, list):
        for b in book_list_raw:
            if isinstance(b, dict):
                # We only need price and total lot
                b_total = b.get("total", {}) if isinstance(b.get("total"), dict) else {}
                compressed_book.append({
                    "price": b.get("price"),
                    "total_lot": b_total.get("lot"),
                    "total_frequency": b_total.get("frequency")
                })
        
    book_total = data["data"].get("book_total", {}) if isinstance(data["data"].get("book_total"), dict) else {}
    return {
        "book": compressed_book,
        "book_total_lot": book_total.get("total_lot")
    }

async def get_trade_book_chart(symbol: str) -> dict | None:
    """Fetch 1-minute cumulative trade book chart for delta analysis."""
    url = f"{STOCKBIT_BASE_URL}/order-trade/trade-book/chart"
    params = {
        "symbol": symbol,
        "time_interval": "1m"
    }
    data = await _get(url, params)
    if not data or "data" not in data:
        return None
    return data["data"]


async def get_latest_market_date() -> str:
    """Fetch the last active trading date using BBCA as a baseline proxy."""
    cache_key = "market:latest_date"
    cached = trade_cache.get(cache_key)
    if cached: return cached
    
    from datetime import date
    try:
        hist = await get_historical_summary("BBCA", days=2)
        if hist and hasattr(hist, '__iter__') and len(hist) > 0:
            last_date = hist[-1].get("date", "").split("T")[0]
            if last_date:
                trade_cache.put_daily(cache_key, last_date)
                return last_date
    except Exception:
        pass
        
    fallback = date.today().isoformat()
    trade_cache.put_daily(cache_key, fallback)
    return fallback


async def get_market_detector(symbol: str) -> dict | None:
    """Fetch pre-calculated broker accumulation (bandar detector).
    Used by scanners to get Smart Money logic instantly without looping trades.
    Includes brute-retry logic with random sleep to handle rate limits.
    """
    cache_key = f"detector:{symbol}"
    cached = trade_cache.get(cache_key)
    if cached is not None:
        return cached

    target_date = await get_latest_market_date()
    
    url = f"https://exodus.stockbit.com/marketdetectors/{symbol}"
    params = {
        "from": target_date,
        "to": target_date,
        "transaction_type": "TRANSACTION_TYPE_NET",
        "market_board": "MARKET_BOARD_REGULER",
        "investor_type": "INVESTOR_TYPE_ALL",
        "limit": 10
    }
    
    import time
    import random

    for attempt in range(5):
        data = await _get(url, params)
        if data and "data" in data and "bandar_detector" in data["data"]:
            res = data["data"]["bandar_detector"]
            # Cache for 2 mins so scanner sweeps are fast
            trade_cache.put(cache_key, res, ttl=120)
            return res
        
        # Brute retry with random sleep 0.1-0.3s as requested
        time.sleep(random.uniform(0.1, 0.3))
        
    return None

async def get_market_movers_freq() -> list[str]:
    """Fetch list of active stock symbols from market mover (top frequency).
    
    Returns up to 100 most actively traded symbols by frequency. Cached for 120 seconds.
    """
    cache_key = "market_movers:active"
    cached = trade_cache.get(cache_key)
    if cached is not None:
        return cached

    # Use MOVER_TYPE_TOP_FREQUENCY as provided by user
    url = (
        f"{STOCKBIT_BASE_URL}/order-trade/market-mover"
        "?mover_type=MOVER_TYPE_TOP_FREQUENCY"
        "&filter_stocks=FILTER_STOCKS_TYPE_MAIN_BOARD"
        "&filter_stocks=FILTER_STOCKS_TYPE_DEVELOPMENT_BOARD"
        "&filter_stocks=FILTER_STOCKS_TYPE_ACCELERATION_BOARD"
        "&filter_stocks=FILTER_STOCKS_TYPE_NEW_ECONOMY_BOARD"
    )
    data = await _get(url)
    if not data or "data" not in data:
        return []

    symbols = []
    # Note: Stockbit returns mover_list in this endpoint
    for item in data["data"].get("mover_list", []):
        detail = item.get("stock_detail", {})
        code = detail.get("code", "")
        # Real stocks only
        if code and len(code) == 4:
            symbols.append(code)
            
    # Increase range to 100 symbols for better scanning diversity
    symbols = symbols[:100]
    
    if symbols:
        trade_cache.put(cache_key, symbols, ttl=120)
        
    return symbols



async def get_market_movers_exodus(mover_type: str = "MOVER_TYPE_TOP_GAINER") -> list:
    """Fetch Top Market Movers (Gainer, Loser, Volume, Value, Frequency, Foreign Buy/Sell).
    
    Valid mover types:
    - MOVER_TYPE_TOP_GAINER
    - MOVER_TYPE_TOP_LOSER
    - MOVER_TYPE_TOP_VALUE
    - MOVER_TYPE_TOP_VOLUME
    - MOVER_TYPE_TOP_FREQUENCY
    - MOVER_TYPE_NET_FOREIGN_BUY
    - MOVER_TYPE_NET_FOREIGN_SELL
    """
    url = f"{STOCKBIT_BASE_URL}/order-trade/market-mover"
    params = {
        "mover_type": mover_type,
        "filter_stocks": [
            "FILTER_STOCKS_TYPE_MAIN_BOARD",
            "FILTER_STOCKS_TYPE_DEVELOPMENT_BOARD",
            "FILTER_STOCKS_TYPE_ACCELERATION_BOARD",
            "FILTER_STOCKS_TYPE_NEW_ECONOMY_BOARD"
        ]
    }
    data = await _get(url, params)
    if not data or "data" not in data:
        return []
    
    return data["data"].get("mover_list", [])
