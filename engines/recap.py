import asyncio
from api.market import get_market_movers_exodus, get_orderbook
from api.client import _safe_int, _safe_float

# Mappings from user shorthand to Stockbit API Keys
MOVER_TYPES = {
    "gainer": "MOVER_TYPE_TOP_GAINER",
    "loser": "MOVER_TYPE_TOP_LOSER",
    "val": "MOVER_TYPE_TOP_VALUE",
    "vol": "MOVER_TYPE_TOP_VOLUME",
    "freq": "MOVER_TYPE_TOP_FREQUENCY",
    "fbuy": "MOVER_TYPE_NET_FOREIGN_BUY",
    "fsell": "MOVER_TYPE_NET_FOREIGN_SELL"
}

async def _fetch_rsv(symbol: str) -> int:
    """Helper to fetch orderbook purely for High/Low to calc RSV."""
    try:
        ob = await get_orderbook(symbol)
        if not ob: return 0
        p = ob.get("last_price", 0)
        h = ob.get("high", 0)
        l = ob.get("low", 0)
        if h == 0 and l == 0: return 0
        if h == l: return 100
        return int(((p - l) / (h - l)) * 100)
    except Exception:
        return 0

async def get_clean_money_recap(mover_key: str = "val", limit: int = 20) -> list:
    """
    Fetch top movers and calculate Clean Money and RSV.
    """
    mover_type = MOVER_TYPES.get(mover_key.lower(), "MOVER_TYPE_TOP_VALUE")
    movers = await get_market_movers_exodus(mover_type)
    movers = movers[:limit] if movers else []
    
    if not movers:
        return []

    results = []
    
    # Pre-parse basic data from mover payload
    for m in movers:
        code = m.get("stock_detail", {}).get("code", "???")
        price = _safe_int(m.get("price", 0))
        gain_pct = _safe_float(m.get("change", {}).get("percentage", 0))
        freq = _safe_int(m.get("frequency", {}).get("raw", 0))
        val = _safe_int(m.get("value", {}).get("raw", 0))
        
        # Mover API already calculates total Buy and Sell turnover natively
        net_buy = _safe_int(m.get("net_buy", {}).get("raw", 0))
        net_sell = _safe_int(m.get("net_sell", {}).get("raw", 0))
        
        # Net sell might be returned as positive absolute in payload, ensure it's negative here
        bad_money = -abs(net_sell)
        smart_money = net_buy
        clean_money = smart_money + bad_money
        
        results.append({
            "code": code,
            "freq": freq,
            "gain_pct": gain_pct,
            "val": val,
            "price": price,
            "smart": smart_money,
            "bad": bad_money,
            "clean": clean_money,
            "rsv": 0 # to be filled by gather
        })

    # Prepare awaitables for RSV fetch
    rsv_tasks = [_fetch_rsv(r["code"]) for r in results]
    
    # Gather responses
    rsv_values = await asyncio.gather(*rsv_tasks, return_exceptions=True)
    
    for idx, rsv_res in enumerate(rsv_values):
        if isinstance(rsv_res, Exception):
            results[idx]["rsv"] = 0
        else:
            results[idx]["rsv"] = rsv_res

    return results
