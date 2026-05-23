from api.client import _safe_int

def calc_foreign_accum(historical: list) -> dict:
    if not historical:
        return {"accum_net": 0, "accum_buy": 0, "accum_sell": 0, "days": 0}
    accum_net = 0
    accum_buy = 0
    accum_sell = 0
    for d in historical:
        accum_net += _safe_int(d.get("net_foreign", 0))
        accum_buy += _safe_int(d.get("foreign_buy", 0))
        accum_sell += _safe_int(d.get("foreign_sell", 0))
    return {
        "accum_net": accum_net,
        "accum_buy": accum_buy,
        "accum_sell": accum_sell,
        "days": len(historical),
    }
