from bot.config import STOCKBIT_BASE_URL
from api.client import _get

async def get_fundachart(symbol: str, fitem_ids: str, timeframe: str = "3y") -> dict | None:
    """
    Fetch fundamental chart data (e.g. PE or PBV Bands) from Stockbit.
    
    Args:
        symbol: Stock symbol (e.g. BUMI)
        fitem_ids: Comma-separated list of ratio IDs (e.g. "12104,12101,12103,12102,12105,2891")
        timeframe: "1y", "3y", "5y", "10y"
    
    Returns:
        Dictionary containing the 'data' array response, or None on failure.
    """
    items = [x.strip() for x in fitem_ids.split(",") if x.strip()]
    if not items:
        return None
        
    chunks = [items[i:i + 5] for i in range(0, len(items), 5)]
    all_ratios = []
    company_name = symbol
    
    url = f"{STOCKBIT_BASE_URL}/fundachart"
    
    for chunk in chunks:
        params = {
            "companies": symbol,
            "item": ",".join(chunk),
            "timeframe": timeframe
        }
        data = await _get(url, params)
        if data and "data" in data and len(data["data"]) > 0:
            comp_data = data["data"][0]
            if "company_name" in comp_data:
                company_name = comp_data["company_name"]
            if "ratios" in comp_data:
                all_ratios.extend(comp_data["ratios"])
                
    if not all_ratios:
        return None
        
    return [{"company_name": company_name, "ratios": all_ratios}]
