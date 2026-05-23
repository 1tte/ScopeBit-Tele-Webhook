"""
Market-wide scanner engine.
Scans active stocks in parallel and calculates money flow for each.
"""
import concurrent.futures
import logging

from api.market import get_market_detector, get_market_movers_exodus, get_latest_market_date

log = logging.getLogger("bot")


async def _scan_single(symbol: str) -> dict | None:
    """Fetch pre-calculated broker accumulation for one symbol."""
    try:
        data = await get_market_detector(symbol)
        if not data:
            return None
            
        # Extract pre-calculated amounts
        top3_amount = data.get("top3", {}).get("amount", 0)
        top10_amount = data.get("top10", {}).get("amount", 0)
        
        # Smart Money (SM) = Top 3 Brokers Accumulation (Whales)
        sm = top3_amount
        
        # Bad Money (BM) = Mid-Tier Brokers (Followers)
        # We define this as the accumulation from Top 10 but excluding the Top 3 whales.
        bm = top10_amount - top3_amount
        
        # Clean Money (CM) = SM - BM
        # (This remains high when whales buy and mid-tier/retail sell)
        cm = sm - bm

        return {
            "symbol": symbol,
            "cm": cm,
            "sm": sm,
            "bm": bm,
            "tx": data.get("total_buyer", 0) + data.get("total_seller", 0),
            "whale_th": 0,
            "retail_th": 0,
        }
    except Exception as e:
        log.debug(f"Scanner skip {symbol}: {e}")
        return None


import asyncio

async def scan_market(sort_key: str = "cm", filter_fn=None, top_n: int = 15, max_workers: int = 50) -> tuple[list[dict], str]:
    """Scan all active stocks, return (results, date_str)."""
    # Get active symbols from market movers
    from api.market import get_market_movers_exodus
    symbols = await get_market_movers_exodus("MOVER_TYPE_TOP_FREQUENCY")
    
    date_str = await get_latest_market_date()
    
    if not symbols:
        return [], date_str

    # Extract just the code from the mover list details
    target_symbols = []
    for m in symbols:
        code = m.get("stock_detail", {}).get("code", "")
        if code and len(code) == 4:
            target_symbols.append(code)
            
    # We want up to 100 symbols for a good scan
    target_symbols = target_symbols[:100]

    log.info(f"Scanner: scanning {len(target_symbols)} stocks concurrently...")

    tasks = [_scan_single(sym) for sym in target_symbols]
    scan_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    results = []
    for r in scan_results:
        if isinstance(r, dict):
            results.append(r)

    # Apply filter if provided
    if filter_fn:
        results = [r for r in results if filter_fn(r)]

    # Sort by absolute value descending
    results.sort(key=lambda x: x.get(sort_key, 0), reverse=True)

    return results[:top_n], date_str
