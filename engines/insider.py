import logging
import html
from datetime import datetime
import asyncio
from api.market import get_historical_summary
from api.fundamental import get_info
from api.insider import get_insider_moves
from api.client import _safe_float

log = logging.getLogger("bot")

def _fmt_qty(val: float) -> str:
    abs_val = abs(val)
    if abs_val >= 1_000_000_000: return f"{abs_val / 1_000_000_000:.2f}B"
    elif abs_val >= 1_000_000: return f"{abs_val / 1_000_000:.2f}M"
    elif abs_val >= 1_000: return f"{abs_val / 1_000:.1f}K"
    else: return f"{abs_val:.0f}"

def _fmt_price(val) -> str:
    if val is None or val == 0:
        return "-"
    return f"{int(val):,}".replace(",", ".")

async def get_insider_raw_data(symbol: str) -> dict | None:
    """Fetch and process Insider & Major Holder data, returning raw data dict."""
    symbol = symbol.upper().strip()

    info, moves, hist = await asyncio.gather(
        get_info(symbol),
        get_insider_moves(symbol, 50),
        get_historical_summary(symbol, 1)
    )

    if not info and not moves:
        return None

    comp_name = info.get("name", "?") if info else "?"
    
    from datetime import timezone, timedelta
    _WIB = timezone(timedelta(hours=7))
    today_str = datetime.now(_WIB).strftime("%Y-%m-%d %H:%M:%S")
    price = 0
    pct = 0
    if hist and len(hist) > 0:
        last_data = hist[0]
        price = last_data.get("close", 0)
        pct = last_data.get("change_percentage", 0)

    if not moves:
        return {
            "symbol": symbol,
            "company_name": comp_name,
            "price": price,
            "pct": pct,
            "update_time": today_str,
            "has_moves": False
        }

    total_buy_shares = 0
    total_sell_shares = 0
    total_buy_val = 0
    total_sell_val = 0
    
    actor_summary = {}
    recent_moves = []
    
    for m in moves:
        action = m.get("action_type", "").lower()
        name = m.get("name", "Unknown")
        shares_str = str(m.get("changes", {}).get("value", "0")).replace(",", "")
        shares = abs(_safe_float(shares_str))
        
        price_str = str(m.get("price_formatted", "0")).replace("Rp", "").replace(".", "").replace(",", "").strip()
        _price = _safe_float(price_str)
        date = m.get("date", "-")
        
        val = shares * _price
        
        if name not in actor_summary:
            actor_summary[name] = {"buy_shares": 0, "sell_shares": 0, "type": m.get("data_source", {}).get("label", "Major")}
            
        if "buy" in action:
            total_buy_shares += shares
            total_buy_val += val
            actor_summary[name]["buy_shares"] += shares
        elif "sell" in action:
            total_sell_shares += shares
            total_sell_val += val
            actor_summary[name]["sell_shares"] += shares
            
        if len(recent_moves) < 10:
            act_type = "buy" if "buy" in action else "sell"
            recent_moves.append({
                "date": date[:6],
                "action": act_type,
                "shares": shares,
                "price": _price,
                "name": name
            })

    net_shares = total_buy_shares - total_sell_shares
    net_val = total_buy_val - total_sell_val
    
    sorted_actors = sorted(
        actor_summary.items(), 
        key=lambda x: (x[1]["buy_shares"] - x[1]["sell_shares"]), 
        reverse=True
    )
    top_buyers = [{"name": a[0], "net": a[1]["buy_shares"] - a[1]["sell_shares"]} for a in sorted_actors if (a[1]["buy_shares"] - a[1]["sell_shares"]) > 0][:3]
    top_sellers = [{"name": a[0], "net": a[1]["sell_shares"] - a[1]["buy_shares"]} for a in sorted_actors if (a[1]["sell_shares"] - a[1]["buy_shares"]) > 0][::-1][:3]
    
    return {
        "symbol": symbol,
        "company_name": comp_name,
        "price": price,
        "pct": pct,
        "update_time": today_str,
        "has_moves": True,
        "total_buy_shares": total_buy_shares,
        "total_buy_val": total_buy_val,
        "total_sell_shares": total_sell_shares,
        "total_sell_val": total_sell_val,
        "net_shares": net_shares,
        "net_val": net_val,
        "top_buyers": top_buyers,
        "top_sellers": top_sellers,
        "recent_moves": recent_moves
    }

async def analyze_insider(symbol: str) -> str | None:
    """Perform Insider & Major Holder analysis."""
    symbol = symbol.upper().strip()

    info, moves, hist = await asyncio.gather(
        get_info(symbol),
        get_insider_moves(symbol, 50),
        get_historical_summary(symbol, 1)
    )

    if not info and not moves:
        return f"<b>{symbol}</b>: Bot sedang istirahat 💤"

    comp_name = html.escape(info.get("name", "?")) if info else "?"
    
    L = "━" * 38
    o = [f"<b>INSIDER & MAJOR HOLDER: {comp_name} ({symbol})</b>"]

    from datetime import timezone, timedelta
    _WIB = timezone(timedelta(hours=7))
    today_str = datetime.now(_WIB).strftime("%Y-%m-%d %H:%M:%S")
    if hist and len(hist) > 0:
        last_data = hist[0]
        price = last_data.get("close", 0)
        pct = last_data.get("change_percentage", 0)
        sign = "+" if pct >= 0 else ""
        o.append(f"<code>Harga   : {_fmt_price(price)} ({sign}{pct:.2f}%)</code>")
    o.append(f"<code>Update  : {today_str}</code>")
    o.append(f"<code>{L}</code>")

    if not moves:
        o.append("<code>Belum ada transaksi Insider/Major Holder terbaru.</code>")
        o.append(f"<code>{L}</code>")
        o.append("<i>⚠️ Disclaimer: Bukan ajakan jual/beli.</i>")
        return "\n".join(o)

    # 1. Agregasi Total Berdasarkan Tipe (Beli / Jual)
    # 2. Detail 10 Transaksi Terakhir
    total_buy_shares = 0
    total_sell_shares = 0
    total_buy_val = 0
    total_sell_val = 0
    
    # We will track individuals to see who is the most aggressive
    actor_summary = {}

    recent_moves = []
    
    for m in moves:
        action = m.get("action_type", "").lower()
        name = m.get("name", "Unknown")
        shares_str = str(m.get("changes", {}).get("value", "0")).replace(",", "")
        shares = abs(_safe_float(shares_str))
        
        price_str = str(m.get("price_formatted", "0")).replace("Rp", "").replace(".", "").replace(",", "").strip()
        price = _safe_float(price_str)
        date = m.get("date", "-")
        
        # Calculate approximate value if price is available
        val = shares * price
        
        if name not in actor_summary:
            actor_summary[name] = {"buy_shares": 0, "sell_shares": 0, "type": m.get("data_source", {}).get("label", "Major")}
            
        if "buy" in action:
            total_buy_shares += shares
            total_buy_val += val
            actor_summary[name]["buy_shares"] += shares
        elif "sell" in action:
            total_sell_shares += shares
            total_sell_val += val
            actor_summary[name]["sell_shares"] += shares
            
        if len(recent_moves) < 10:
            act_icon = "✓" if "buy" in action else "✗"
            act_label = "BUY " if "buy" in action else "SELL"
            price_val = _fmt_price(price)
            
            # Line 1: Date | Icon | Action | Qty | @ Price
            line1 = f"{date[:6]:<6} | {act_icon} {act_label} {_fmt_qty(shares):>6} @ {price_val}"
            # Line 2: Name (indented)
            line2 = f"   └ {name[:30]}"
            recent_moves.append(f"{line1}\n{line2}")

    net_shares = total_buy_shares - total_sell_shares
    net_val = total_buy_val - total_sell_val
    
    # --- SUMMARY SECTION ---
    o.append("<b>SUMMARY (Top 50 Data Terakhir)</b>")
    net_label = "AKUMULASI" if net_shares > 0 else ("DISTRIBUSI" if net_shares < 0 else "NEUTRAL")
    o.append("<code>"
             f"Status       : {net_label}\n"
             f"Total Beli   : {_fmt_qty(total_buy_shares)} Lmbr (Rp {_fmt_qty(total_buy_val)})\n"
             f"Total Jual   : {_fmt_qty(total_sell_shares)} Lmbr (Rp {_fmt_qty(total_sell_val)})\n"
             f"Net Volume   : {_fmt_qty(net_shares)} Lembar\n"
             f"Net Value    : Rp {_fmt_qty(net_val)}"
             "</code>")
    o.append(f"<code>{L}</code>")
    
    # --- TOP ACTORS ---
    # Sort actors by highest net volume
    sorted_actors = sorted(
        actor_summary.items(), 
        key=lambda x: (x[1]["buy_shares"] - x[1]["sell_shares"]), 
        reverse=True
    )
    
    top_buyers = [a for a in sorted_actors if (a[1]["buy_shares"] - a[1]["sell_shares"]) > 0][:3]
    top_sellers = [a for a in sorted_actors if (a[1]["sell_shares"] - a[1]["buy_shares"]) > 0][::-1][:3] # Reverse to get the biggest negative net
    
    if top_buyers or top_sellers:
        o.append("<b>TOP ACTORS NET VOLUME</b>")
        actor_lines = []
        for name, data in top_buyers:
            net = data["buy_shares"] - data["sell_shares"]
            actor_lines.append(f"[✓] {_fmt_qty(net):>6} Lmbr | {name[:20]}")
        for name, data in top_sellers:
            net = data["sell_shares"] - data["buy_shares"]
            actor_lines.append(f"[✗] {_fmt_qty(net):>6} Lmbr | {name[:20]}")
            
        o.append("<code>" + "\n".join(actor_lines) + "</code>")
        o.append(f"<code>{L}</code>")

    # --- LATEST TRANSACTIONS ---
    if recent_moves:
        o.append("<b>10 TRANSAKSI TERBARU</b>")
        o.append("<code>" + "\n".join(recent_moves) + "</code>")
        o.append(f"<code>{L}</code>")

    o.append("<i>⚠️ Disclaimer: Bukan ajakan jual/beli. Data bisa delay dari laporan bursa.</i>")
    return "\n".join(o)
