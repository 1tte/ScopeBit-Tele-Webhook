import os
import httpx
import json
import logging

log = logging.getLogger("bot")

def format_screener_rules(filters: list) -> str:
    if not filters: return "• Custom Query"
    rules = []
    for f in filters:
        try:
            name = f.get("item1name", "Unknown")
            op = f.get("operator", "")
            if f.get("type") == "compare":
                val = f.get("item2name", f.get("item2", ""))
            else:
                val = f.get("item2", "")
                if isinstance(val, str) and val.isdigit() and len(val) >= 7:
                    val_int = int(val)
                    if val_int >= 1_000_000_000:
                        val = f"{val_int/1_000_000_000:g} B"
                    elif val_int >= 1_000_000:
                        val = f"{val_int/1_000_000:g} M"
            rules.append(f"• {name} {op} {val}")
        except Exception:
            continue
    return "\n".join(rules) if rules else "• Custom Query"

async def run_screener(filters: list, sequence: list, ordercol: int = 2661, ordertype: str = "desc", page: int = 1) -> dict:
    """
    Executes a custom screener on Stockbit.
    On 401, attempts token refresh and retries once.
    
    :param filters: List of filter rule dicts.
    :param sequence: List of item IDs (e.g. [2661, 12465])
    :param ordercol: The item_id to sort by. Default 2661 (Price).
    :param ordertype: "asc" or "desc"
    :param page: Page number
    :return: The 'data' dict from the API response.
    """
    from bot.config import STOCKBIT_HEADERS
    from api.client import AuthError

    url = "https://exodus.stockbit.com/screener/templates"

    # Stockbit's screener template requires filter list and universe as stringified JSON
    payload = {
        "name": "TEMPLATE_BUILD_CUSTOM",
        "description": "",
        "save": "0",
        "ordertype": ordertype,
        "ordercol": ordercol,
        "page": page,
        "universe": json.dumps({"scope": "IHSG", "scopeID": "", "name": ""}),
        "filters": json.dumps(filters),
        "sequence": ",".join(map(str, sequence)),
        "screenerid": "0",
        "type": "TEMPLATE_TYPE_CUSTOM"
    }

    def _build_headers():
        auth_header = STOCKBIT_HEADERS.get("Authorization")
        if not auth_header:
            raise ValueError("Authorization header is not set in config.")
        return {
            "accept": "application/json",
            "authorization": auth_header,
            "content-type": "application/json",
            "origin": "https://stockbit.com",
            "referer": "https://stockbit.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        }

    async with httpx.AsyncClient(timeout=15.0) as client:
        headers = _build_headers()
        resp = await client.post(url, headers=headers, json=payload)

        if resp.status_code == 401:
            log.info("SCREENER AUTH | 401 received, attempting token refresh...")
            from api.auth import refresh_stockbit_token
            result = await refresh_stockbit_token()

            if result:
                log.info("SCREENER AUTH | Refresh succeeded, retrying screener...")
                headers = _build_headers()  # Re-build with updated token
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 401:
                    raise AuthError("Screener: Token refresh succeeded but request still 401.")
            else:
                raise AuthError("Screener: Token refresh failed.")

        if resp.status_code != 200:
            raise Exception(f"Screener API error: {resp.status_code} - {resp.text[:200]}")

        data = resp.json()
        return data.get("data", {})
