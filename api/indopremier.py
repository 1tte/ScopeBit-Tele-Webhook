import aiohttp
import re
import logging

log = logging.getLogger("bot")

async def fetch_global_indices() -> dict:
    """
    Fetches real-time global indices percentage change from Indopremier HTML data.
    Parses the hidden PHP array inside the HTML comment block.
    Returns a dict mapping index names to their percentage change string.
    """
    url = "https://indopremier.com/ipotnews/nw-markets.php?page=indeks"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Referer": "https://indopremier.com/"
    }
    
    indices = {}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    
                    # Target codes to extract
                    # We map them to display names
                    targets = {
                        "DJIA": "Dow Jones",
                        "NASDAQ": "Nasdaq",
                        "NIKKEI": "Nikkei 225",
                        "H.S.I.": "Hang Seng",
                        "STRAITS": "STI (S'pore)",
                        "VIX": "VIX (Fear Index)"
                    }
                    
                    # Regex to find blocks like:
                    # [DJIA] => Array
                    #     (
                    #         [code] => DJIA
                    #         [last] => 47916.570
                    #         [chg] => -269.230
                    #         [pchg] => -0.55873307073868235040
                    for raw_code, display_name in targets.items():
                        # Use regex to find [pchg] for the specific code
                        # Escape special chars in raw_code
                        safe_code = re.escape(raw_code)
                        pattern = rf"\[{safe_code}\]\s*=>\s*Array.*?\[pchg\]\s*=>\s*([\-\d\.]+)"
                        match = re.search(pattern, html, re.DOTALL)
                        if match:
                            pchg_val = float(match.group(1))
                            sign = "+" if pchg_val > 0 else ""
                            indices[display_name] = f"{sign}{pchg_val:.2f}%"
    except Exception as e:
        log.warning(f"Failed to fetch global indices: {e}")
        
    return indices
