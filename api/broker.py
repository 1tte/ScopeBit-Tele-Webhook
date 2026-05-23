from bot.config import STOCKBIT_BASE_URL
from api.client import _get


def _last_trading_day(dt):
    """Roll back to the most recent trading day (skip Saturday/Sunday)."""
    while dt.weekday() >= 5:  # 5=Saturday, 6=Sunday
        from datetime import timedelta
        dt -= timedelta(days=1)
    return dt


async def get_broker_summary(symbol: str, days: int = 1, start_date_str: str = None, end_date_str: str = None) -> dict | None:
    """Fetch broker summary (Top Buyers/Sellers) from market detectors.
    If start_date_str and end_date_str are provided ('YYYY-MM-DD'), they override 'days'.
    """
    from datetime import datetime, timedelta, timezone
    _WIB = timezone(timedelta(hours=7))
    
    if start_date_str and end_date_str:
        # Adjust end date to last trading day if it falls on a weekend
        try:
            end_parsed = datetime.strptime(end_date_str, "%Y-%m-%d").replace(tzinfo=_WIB)
            end_parsed = _last_trading_day(end_parsed)
            end_dt = end_parsed.strftime("%Y-%m-%d")
        except ValueError:
            end_dt = end_date_str
        start_dt = start_date_str
    else:
        end_date = _last_trading_day(datetime.now(_WIB))
        if days == 1:
            # For 1D: query exactly the last trading day
            start_dt = end_date.strftime("%Y-%m-%d")
            end_dt = end_date.strftime("%Y-%m-%d")
        else:
            start_date = end_date - timedelta(days=days * 2)  # roughly skip weekends
            start_dt = start_date.strftime("%Y-%m-%d")
            end_dt = end_date.strftime("%Y-%m-%d")

    url = f"{STOCKBIT_BASE_URL}/marketdetectors/{symbol}"
    params = {
        "from": start_dt,
        "to": end_dt,
        "transaction_type": "TRANSACTION_TYPE_NET",
        "market_board": "MARKET_BOARD_REGULER",
        "investor_type": "INVESTOR_TYPE_ALL",
        "limit": 25,
    }
    data = await _get(url, params)
    if not data or "data" not in data:
        return None
        
    raw = data["data"]
    
    # Compress the detector and broker list
    det = raw.get("bandar_detector", {}) if isinstance(raw.get("bandar_detector"), dict) else {}
    bs = raw.get("broker_summary", {}) if isinstance(raw.get("broker_summary"), dict) else {}
    
    top1 = det.get("top1", {}) if isinstance(det.get("top1"), dict) else {}
    top3 = det.get("top3", {}) if isinstance(det.get("top3"), dict) else {}
    top5 = det.get("top5", {}) if isinstance(det.get("top5"), dict) else {}
    top10 = det.get("top10", {}) if isinstance(det.get("top10"), dict) else {}
    
    comp_det = {
        "broker_accdist": det.get("broker_accdist"),
        "total_buyer": det.get("total_buyer"),
        "total_seller": det.get("total_seller"),
        "value": det.get("value"),
        "top1": {"accdist": top1.get("accdist"), "percent": top1.get("percent")},
        "top3": {"accdist": top3.get("accdist"), "percent": top3.get("percent")},
        "top5": {"accdist": top5.get("accdist"), "percent": top5.get("percent")},
        "top10": {"accdist": top10.get("accdist"), "percent": top10.get("percent")}
    }
    
    comp_bs_buy = []
    bs_buy_list = bs.get("brokers_buy", [])
    if isinstance(bs_buy_list, list):
        for b in bs_buy_list:
            if isinstance(b, dict):
                comp_bs_buy.append({
                    "netbs_broker_code": b.get("netbs_broker_code"),
                    "blot": b.get("blot"),
                    "bval": b.get("bval"),
                    "netbs_buy_avg_price": b.get("netbs_buy_avg_price"),
                    "type": b.get("type")
                })
        
    comp_bs_sell = []
    bs_sell_list = bs.get("brokers_sell", [])
    if isinstance(bs_sell_list, list):
        for s in bs_sell_list:
            if isinstance(s, dict):
                comp_bs_sell.append({
                    "netbs_broker_code": s.get("netbs_broker_code"),
                    "slot": s.get("slot"),
                    "sval": s.get("sval"),
                    "netbs_sell_avg_price": s.get("netbs_sell_avg_price"),
                    "type": s.get("type")
                })

    return {
        "bandar_detector": comp_det,
        "broker_summary": {
            "brokers_buy": comp_bs_buy,
            "brokers_sell": comp_bs_sell
        }
    }
