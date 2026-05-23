import logging
from bot.config import STOCKBIT_BASE_URL
from .client import _get

log = logging.getLogger("api")

async def get_insider_moves(symbol: str, limit: int = 50) -> list[dict]:
    """
    Fetch Insider and Major Holder movements.
    Endpoint: /insider/company/majorholder
    Limit default is 50, but we just grab page 1.
    """
    symbol = symbol.upper().strip()
    url = f"{STOCKBIT_BASE_URL}/insider/company/majorholder"
    
    try:
        data = await _get(url, params={"symbol": symbol, "page": 1})
        if not data:
            return []
        
        return data.get("data", {}).get("movement", [])
    except Exception as e:
        log.error(f"Error fetching insider moves for {symbol}: {e}")
        return []
