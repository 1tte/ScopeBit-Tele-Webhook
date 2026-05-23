from api.client import _safe_int, _safe_float


def calc_money_flow_chart(chart_data: dict, fallback_price: float, whale_mult: float = 5.0, retail_mult: float = 0.5) -> dict | None:
    """Calculate Smart Money vs Bad Money using the minute-by-minute cumulative trade book chart.
    
    Update: User requested exact numbers matching Stockbit's Tradebook "Smart" and "Bad" UI.
    In Stockbit UI, Smart Money = Total HAKA (Buy) Volume, Bad Money = Total HAKI (Sell) Volume.
    """
    if not chart_data:
        return None

    buy_data = chart_data.get("buy", [])
    sell_data = chart_data.get("sell", [])
    prices_data = chart_data.get("prices", [])

    if not buy_data or not sell_data:
        return None

    def parse_raw(obj, key):
        if obj and key in obj and obj[key] is not None:
            return float(str(obj[key].get("raw", 0)).replace(",", ""))
        return 0.0

    # Extract overall totals from the very last known cumulative points
    total_buy_lot = parse_raw(buy_data[-1], "lot")
    total_buy_freq = parse_raw(buy_data[-1], "frequency")
    total_sell_lot = parse_raw(sell_data[-1], "lot")
    total_sell_freq = parse_raw(sell_data[-1], "frequency")

    grand_total_freq = total_buy_freq + total_sell_freq

    if grand_total_freq == 0:
        return None

    # As per user's reference table:
    # Smart Money = Total HAKA Lot * 100 * Price (or simply Turnover Buy Value)
    # Bad Money = Total HAKI Lot * 100 * Price (or simply Turnover Sell Value)
    
    last_price = fallback_price
    if prices_data and prices_data[-1].get("value"):
        last_price = float(prices_data[-1]["value"].get("raw", fallback_price))

    if last_price <= 0:
        return None

    # To get exact Rupiah Value matching the user's table (like "129.17M"), 
    # we convert Total Buy/Sell Lots to actual Money Turnover:
    smart_money = total_buy_lot * 100 * last_price
    # Bad money is negative convention
    bad_money = -1 * (total_sell_lot * 100 * last_price)

    return {
        "smart_money": smart_money,
        "bad_money": bad_money,
        "clean_money": smart_money + bad_money,
        "tx_count": int(grand_total_freq),
        "whale_threshold": 0.0,
        "retail_threshold": 0.0
    }

def calc_rsv(current_price: int, high_price: int, low_price: int) -> float:
    """Calculate Relative Strength Value (RSV) using intraday price."""
    if high_price - low_price > 0:
        return ((current_price - low_price) / (high_price - low_price)) * 100
    return 50.0

def calc_volume_ratio(current_volume: int, historical: list) -> float:
    if not historical:
        return 0.0
    volumes = [_safe_int(d.get("volume", 0)) for d in historical if _safe_int(d.get("volume", 0)) > 0]
    if not volumes:
        return 0.0
    avg = sum(volumes) / len(volumes)
    return current_volume / avg if avg > 0 else 0.0

def calc_price_strength(trade_book: dict) -> list:
    """Return top 3 price levels sorted by total lot."""
    if not trade_book or not trade_book.get("book"):
        return []

    levels = []
    for entry in trade_book["book"]:
        price = _safe_int(entry.get("price", 0))
        buy_lot = _safe_int(entry.get("buy", {}).get("lot", 0))
        sell_lot = _safe_int(entry.get("sell", {}).get("lot", 0))
        total_lot = buy_lot + sell_lot
        if total_lot > 0:
            levels.append({
                "price": price,
                "buy_lot": buy_lot,
                "sell_lot": sell_lot,
                "total": total_lot,
                "net": buy_lot - sell_lot,
            })

    levels.sort(key=lambda x: x["total"], reverse=True)
    return levels[:3]

def calc_spoofing_index(ob_data: dict) -> dict | None:
    """Calculate the ratio of Order Book resting volume to actual matched volume.
    
    If order book volume is > 10x the matched volume, it's highly likely to be
    'fake walls' (spoofing) where orders are placed to intimidate and then canceled.
    """
    if not ob_data or "bid" not in ob_data or "offer" not in ob_data:
        return None

    # Calculate total resting volume in orderbook
    total_ob_vol = 0
    for b in ob_data.get("bid", []):
        total_ob_vol += _safe_int(b.get("volume", 0))
    for o in ob_data.get("offer", []):
        total_ob_vol += _safe_int(o.get("volume", 0))

    match_vol = _safe_int(ob_data.get("volume", 0))
    if match_vol == 0:
        return None

    ratio = total_ob_vol / match_vol
    
    # If ratio is > 10x, it's considered spoofed/fake walls
    is_spoofing = ratio > 10.0

    return {
        "ob_vol": total_ob_vol,
        "match_vol": match_vol,
        "ratio": ratio,
        "is_spoofing": is_spoofing
    }

def calc_broker_summary(broker_data: dict) -> dict:
    """Extract top 3 buyer and seller brokers."""
    result = {"top_buyers": [], "top_sellers": []}
    if not broker_data:
        return result

    bs = broker_data.get("broker_summary", {})

    for b in (bs.get("brokers_buy", []) or [])[:3]:
        code = b.get("netbs_broker_code", "?")
        val = int(_safe_float(b.get("bval", 0)))
        lot = int(_safe_float(b.get("blot", 0)))
        broker_type = b.get("type", "")
        result["top_buyers"].append({"code": code, "val": val, "lot": lot, "type": broker_type})

    for s in (bs.get("brokers_sell", []) or [])[:3]:
        code = s.get("netbs_broker_code", "?")
        val = int(_safe_float(s.get("sval", 0)))
        lot = int(_safe_float(s.get("slot", 0)))
        broker_type = s.get("type", "")
        result["top_sellers"].append({"code": code, "val": val, "lot": lot, "type": broker_type})

    return result
