"""
Dropdown Enable Engine — Supplementary Smart Money & Bandarmology Analysis

Automatically triggered when technical indicators produce a BUY signal.
Fetches SM + Bandar data in parallel and returns a detailed analysis
as a separate Telegram message (reply to the chart).

IMPORTANT: This engine does NOT modify the Trading Plan Action.
           It provides supplementary intelligence only.

References:
  - Smart Money (HAKA/HAKI Volume): Stockbit Tradebook (Larry Williams methodology)
  - Spoofing Detection: Order Book vs Matched Volume ratio
  - Bandarmology: Broker Accumulation/Distribution via MarketDetectors API
  - Stealth Accumulation: Cross-reference Top 5 buyers across 1D & 5D timeframes
  - Foreign Flow: Net foreign buy/sell from orderbook + historical summary
"""
import logging
import asyncio
from datetime import datetime, timedelta, timezone

from api.market import get_orderbook, get_trade_book_chart, get_historical_summary
from api.broker import get_broker_summary
from api.client import _safe_float, _safe_int
from engines.smart_money import calc_money_flow_chart, calc_spoofing_index

log = logging.getLogger("bot")

# ──────────────────────────────────────────────
# Trigger Detection
# ──────────────────────────────────────────────

def is_buy_signal(caption: str) -> bool:
    """Determine if a trading plan caption contains a BUY signal.
    
    Triggers on:
    - BUY NOW, BUY (Breakout ...), BUY NOW (Momentum Break)
    - WAIT TO BUY (Breakout di X) — still a buy thesis, SM/Bandar validates it
    
    Does NOT trigger on:
    - AVOID, WAIT (Pantul...), POOR_RR, plain WAIT without "TO BUY"
    """
    if not caption:
        return False
    
    upper = caption.upper()
    
    for line in upper.split("\n"):
        if "ACTION" in line and ":" in line:
            action_part = line.split(":", 1)[1].strip()
            # Exclude explicit non-buy actions first
            if "AVOID" in action_part or "POOR" in action_part:
                return False
            # Match: BUY NOW, BUY (Breakout...), WAIT TO BUY
            if action_part.startswith("BUY") or "MOMENTUM" in action_part:
                return True
            if action_part.startswith("WAIT TO BUY"):
                return True
            break
    
    return False


# ──────────────────────────────────────────────
# Value Formatting Helpers
# ──────────────────────────────────────────────

def _fmt_val(val: float) -> str:
    """Format Rupiah value with +/- sign (e.g. +129.17M, -85.23M)."""
    abs_val = abs(val)
    sign = "+" if val >= 0 else "-"
    if abs_val >= 1_000_000_000_000:
        return f"{sign}{abs_val / 1_000_000_000_000:.2f}T"
    elif abs_val >= 1_000_000_000:
        return f"{sign}{abs_val / 1_000_000_000:.2f}M"
    elif abs_val >= 1_000_000:
        return f"{sign}{abs_val / 1_000_000:.1f}Jt"
    elif abs_val >= 1_000:
        return f"{sign}{abs_val / 1_000:.0f}Rb"
    else:
        return f"{sign}{abs_val:.0f}"


def _fmt_val_unsigned(val: float) -> str:
    abs_val = abs(val)
    if abs_val >= 1_000_000_000_000:
        return f"{abs_val / 1_000_000_000_000:.2f}T"
    elif abs_val >= 1_000_000_000:
        return f"{abs_val / 1_000_000_000:.2f}M"
    elif abs_val >= 1_000_000:
        return f"{abs_val / 1_000_000:.1f}Jt"
    elif abs_val >= 1_000:
        return f"{abs_val / 1_000:.0f}Rb"
    else:
        return f"{abs_val:.0f}"


def _fmt_price(val) -> str:
    if val is None or val == 0:
        return "-"
    return f"{int(val):,}".replace(",", ".")


def _broker_flag(btype: str) -> str:
    if btype == "Asing":
        return "[A]"
    elif btype == "Lokal":
        return "[R]"
    elif btype == "Pemerintah":
        return "[G]"
    return "   "


def _get_effective_date(dt: datetime) -> datetime:
    """Returns the effective trading date based on market hours and weekends.
    Same logic as bandarmology.py to ensure consistent date handling.
    - Sat/Sun -> Friday
    - Mon-Fri before 16:00 -> Previous trading day
    - Mon-Fri after 16:00 -> Today
    """
    wd = dt.weekday()
    hour = dt.hour

    if wd == 5:  # Saturday
        return dt - timedelta(days=1)
    elif wd == 6:  # Sunday
        return dt - timedelta(days=2)
    else:  # Mon-Fri
        if hour < 16:
            if wd == 0:  # Monday before 16:00 -> Friday
                return dt - timedelta(days=3)
            else:  # Tue-Fri before 16:00 -> Previous Day
                return dt - timedelta(days=1)
        else:
            return dt


# ──────────────────────────────────────────────
# Core: Dropdown Analysis Pipeline
# ──────────────────────────────────────────────

async def analyze_dropdown(symbol: str) -> str | None:
    """Perform Smart Money + Bandarmology deep analysis.
    
    Returns a detailed HTML-formatted analysis string combining:
    1. Smart Money (HAKA/HAKI money flow + dominance)
    2. Bandarmology (1D/5D broker concentration + top brokers + stealth)
    3. Foreign Flow (today + 5D accumulation)
    4. Microstructure (spoofing detection)
    5. Behavioral Pattern (Retail vs Asing flow)
    
    Output goes to a separate Telegram message (reply to chart).
    Max length: ~4096 chars (Telegram text message limit).
    
    API Cost: 5 requests per call
    """
    symbol = symbol.upper().strip()
    
    try:
        # ── Calculate effective trading date (same as bandarmology.py) ──
        _WIB = timezone(timedelta(hours=7))
        now = datetime.now(_WIB)
        today = _get_effective_date(now)
        today_str = today.strftime("%Y-%m-%d")
        five_days_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        
        # ── Fetch all data in parallel (5 concurrent API calls) ──
        tasks = [
            get_trade_book_chart(symbol),                                        # [0] Money Flow
            get_orderbook(symbol),                                               # [1] OB + Foreign + Price
            get_broker_summary(symbol, None,
                             start_date_str=today_str,
                             end_date_str=today_str),                            # [2] Bandar 1D (exact trading day)
            get_broker_summary(symbol, None,
                             start_date_str=five_days_ago,
                             end_date_str=today_str),                            # [3] Bandar 5D
            get_historical_summary(symbol, days=5),                              # [4] Historical (foreign flow 5D)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        tb_chart = results[0] if not isinstance(results[0], Exception) else None
        ob       = results[1] if not isinstance(results[1], Exception) else None
        broker_1d = results[2] if not isinstance(results[2], Exception) else None
        broker_5d = results[3] if not isinstance(results[3], Exception) else None
        hist     = results[4] if not isinstance(results[4], Exception) else None
        
        # Need at least orderbook to proceed
        if not ob:
            return None
        
        price = ob.get("last_price", 0)
        L = "━" * 34
        o = []
        
        o.append(f"<b>DEPTH ANALYSIS — {symbol}</b>")
        
        # ════════════════════════════════════════════
        # SECTION 1: SMART MONEY (Money Flow)
        # ════════════════════════════════════════════
        
        o.append(f"<code>{L}</code>")
        o.append("<b>SMART MONEY</b>")
        
        if tb_chart and price > 0:
            mf = calc_money_flow_chart(tb_chart, fallback_price=price)
            if mf:
                sm = mf["smart_money"]
                bm = mf["bad_money"]
                cm = mf["clean_money"]
                tx = mf["tx_count"]
                
                total = abs(sm) + abs(bm)
                pwr = abs(cm) / total * 100 if total > 0 else 0
                
                if cm > 0:
                    status = "BUYER DOM"
                elif cm < 0:
                    status = "SELLER DOM"
                else:
                    status = "NEUTRAL"
                
                sm_lines = [
                    f"SM (HAKA)    : {_fmt_val(sm):>12}",
                    f"BM (HAKI)    : {_fmt_val(bm):>12}",
                    f"Clean Money  : {_fmt_val(cm):>12}",
                    f"Status       : {status:>12}",
                    f"Power Ratio  : {f'{pwr:.1f}%':>12}",
                    f"Transaksi    : {f'{tx:,}x'.replace(',','.'):>12}",
                ]
                o.append("<code>" + "\n".join(sm_lines) + "</code>")
            else:
                o.append("<code>Data tradebook belum tersedia</code>")
        else:
            o.append("<code>Data tradebook belum tersedia</code>")
        
        # ════════════════════════════════════════════
        # SECTION 2: BANDARMOLOGY (1D & 5D)
        # ════════════════════════════════════════════
        
        o.append(f"<code>{L}</code>")
        o.append("<b>BANDARMOLOGY</b>")
        
        for label, broker_data in [("1D", broker_1d), ("5D", broker_5d)]:
            if not broker_data:
                continue
            
            det = broker_data.get("bandar_detector", {})
            bs = broker_data.get("broker_summary", {})
            
            accdist = det.get("broker_accdist", "-")
            accdist_short = _shorten_accdist(accdist)
            total_buyer = det.get("total_buyer", 0)
            total_seller = det.get("total_seller", 0)
            net_val = det.get("value", 0)
            
            o.append(f"<b>[{label}] {accdist_short} | B:{total_buyer} S:{total_seller} | Net: {_fmt_val(net_val)}</b>")
            
            # Top 3 Buyers + Sellers compact
            buyers = bs.get("brokers_buy", [])[:3]
            sellers = bs.get("brokers_sell", [])[:3]
            
            broker_lines = []
            for b in buyers:
                code = b.get("netbs_broker_code", "?")
                lot = int(_safe_float(b.get("blot", 0)))
                avg = int(_safe_float(b.get("netbs_buy_avg_price", 0)))
                btype = b.get("type", "")
                flag = _broker_flag(btype)
                broker_lines.append(f"  B: {code:2}{flag:>4} {_fmt_val_unsigned(lot):>6} Lot  Avg {_fmt_price(avg)}")
            
            for s in sellers:
                code = s.get("netbs_broker_code", "?")
                lot = int(_safe_float(s.get("slot", 0)))
                avg = int(_safe_float(s.get("netbs_sell_avg_price", 0)))
                stype = s.get("type", "")
                flag = _broker_flag(stype)
                broker_lines.append(f"  S: {code:2}{flag:>4} {_fmt_val_unsigned(lot):>6} Lot  Avg {_fmt_price(avg)}")
            
            if broker_lines:
                o.append("<code>" + "\n".join(broker_lines) + "</code>")
        
        # ── Broker Concentration (1D) ──
        if broker_1d:
            det_1d = broker_1d.get("bandar_detector", {})
            tiers = [
                ("Top 5 ", det_1d.get("top5")),
                ("Top 10", det_1d.get("top10")),
            ]
            conc_lines = []
            for tier_label, tier_data in tiers:
                if not tier_data:
                    continue
                acc_label = tier_data.get("accdist", "-")
                pct = tier_data.get("percent", 0)
                conc_lines.append(f"{tier_label} : {acc_label:<14} ({pct:+.1f}%)")
            
            if conc_lines:
                o.append("<code>" + "\n".join(conc_lines) + "</code>")
        
        # ── Stealth Accumulation (1D ∩ 5D top buyers) ──
        if broker_1d and broker_5d:
            try:
                bs_1d = broker_1d.get("broker_summary", {})
                bs_5d = broker_5d.get("broker_summary", {})
                
                buy_1d_map = {b.get("netbs_broker_code"): b for b in bs_1d.get("brokers_buy", [])[:5]}
                buy_5d_map = {b.get("netbs_broker_code"): b for b in bs_5d.get("brokers_buy", [])[:5]}
                
                sell_1d_map = {s.get("netbs_broker_code"): s for s in bs_1d.get("brokers_sell", [])[:5]}
                sell_5d_map = {s.get("netbs_broker_code"): s for s in bs_5d.get("brokers_sell", [])[:5]}
                
                stealth_acc = set(buy_1d_map.keys()) & set(buy_5d_map.keys()) - {None, "?", "Unknown", ""}
                stealth_dist = set(sell_1d_map.keys()) & set(sell_5d_map.keys()) - {None, "?", "Unknown", ""}
                
                if stealth_acc or stealth_dist:
                    stealth_lines = []
                    for sb in stealth_acc:
                        lot_1d = int(_safe_float(buy_1d_map[sb].get("blot", 0)))
                        lot_5d = int(_safe_float(buy_5d_map[sb].get("blot", 0)))
                        btype = buy_1d_map[sb].get("type", "")
                        flag = _broker_flag(btype)
                        stealth_lines.append(
                            f"{sb}{flag} AKUM 1D ({_fmt_val_unsigned(lot_1d)} lot) "
                            f"+ 5D ({_fmt_val_unsigned(lot_5d)} lot)"
                        )
                    for sb in stealth_dist:
                        lot_1d = int(_safe_float(sell_1d_map[sb].get("slot", 0)))
                        lot_5d = int(_safe_float(sell_5d_map[sb].get("slot", 0)))
                        stype = sell_1d_map[sb].get("type", "")
                        flag = _broker_flag(stype)
                        stealth_lines.append(
                            f"{sb}{flag} DIST 1D ({_fmt_val_unsigned(lot_1d)} lot) "
                            f"+ 5D ({_fmt_val_unsigned(lot_5d)} lot)"
                        )
                    
                    if stealth_lines:
                        o.append("<b>STEALTH MODE</b>")
                        o.append("<code>" + "\n".join(stealth_lines) + "</code>")
                        
            except Exception as e:
                log.warning(f"Stealth detection error: {e}")
        
        # ════════════════════════════════════════════
        # SECTION 3: FOREIGN FLOW
        # ════════════════════════════════════════════
        
        o.append(f"<code>{L}</code>")
        o.append("<b>FOREIGN FLOW</b>")
        
        fnet_today = ob.get("fnet", 0)
        fnet_label = "Net Buy" if fnet_today >= 0 else "Net Sell"
        ff_lines = [f"Today        : {_fmt_val(fnet_today):>10} ({fnet_label})"]
        
        if hist and len(hist) > 0:
            fnet_5d = 0
            for i, h in enumerate(reversed(hist)):
                if i < 5:
                    fnet_5d += _safe_int(h.get("net_foreign", 0))
            
            ff_lines.append(f"Acc 5D       : {_fmt_val(fnet_5d):>10} ({'Akum' if fnet_5d >= 0 else 'Dist'})")
        
        o.append("<code>" + "\n".join(ff_lines) + "</code>")
        
        # ════════════════════════════════════════════
        # SECTION 4: MICROSTRUCTURE (Spoofing)
        # ════════════════════════════════════════════
        
        spoof = calc_spoofing_index(ob)
        if spoof:
            ratio = spoof.get("ratio", 0)
            is_spoof = spoof.get("is_spoofing", False)
            
            o.append(f"<code>{L}</code>")
            o.append("<b>MICROSTRUCTURE</b>")
            
            spoof_warning = "FAKE WALL DETECTED" if is_spoof else ("High" if ratio >= 5.0 else "Normal")
            ms_lines = [
                f"OB vs Match  : {f'{ratio:.1f}x':>10}",
                f"OB Volume    : {_fmt_val_unsigned(spoof['ob_vol']) + ' lot':>10}",
                f"Match Volume : {_fmt_val_unsigned(spoof['match_vol']) + ' lot':>10}",
                f"Status       : {spoof_warning:>10}",
            ]
            o.append("<code>" + "\n".join(ms_lines) + "</code>")
        
        # ════════════════════════════════════════════
        # SECTION 5: KESIMPULAN
        # ════════════════════════════════════════════
        
        conclusions = _build_conclusions(ob, broker_1d, broker_5d, hist, tb_chart, price)
        
        if conclusions:
            o.append(f"<code>{L}</code>")
            o.append("<b>KESIMPULAN</b>")
            o.append("<code>" + "\n".join(conclusions) + "</code>")
        
        o.append(f"<code>{L}</code>")
        
        final_text = "\n".join(o)
        
        # Safety: cap at 4000 chars (Telegram limit is 4096)
        if len(final_text) > 4000:
            final_text = final_text[:3990] + "\n...</code>"
        
        return final_text
        
    except Exception as e:
        log.warning(f"Dropdown analysis error for {symbol}: {e}")
        return None


# ──────────────────────────────────────────────
# Conclusion Builder
# ──────────────────────────────────────────────

def _build_conclusions(ob: dict, broker_1d: dict | None, broker_5d: dict | None,
                       hist: list | None, tb_chart: dict | None, price: float) -> list[str]:
    """Build a list of analytical conclusions from all available data."""
    conclusions = []
    
    if not ob:
        return conclusions
    
    fnet = ob.get("fnet", 0)
    change_pct = ob.get("change_pct", 0)
    
    # 1. Retail vs Asing behavioral pattern
    if broker_1d:
        det = broker_1d.get("bandar_detector", {})
        total_net = det.get("value", 0)
        retail_net = total_net - fnet
        
        if retail_net > 0 and fnet > 0:
            conclusions.append("Retail + Asing sama-sama akumulasi (CONSENSUS)")
        elif fnet > 0 and retail_net < 0:
            conclusions.append("Asing akumulasi, retail distribusi (SMART ACCUM)")
        elif retail_net < 0 and fnet > 0 and abs(retail_net) > abs(fnet) * 0.3:
            conclusions.append("Retail buang barang, Asing tampung (PANIC SELL)")
        elif retail_net > 0 and fnet < 0 and abs(fnet) > abs(retail_net) * 0.3:
            conclusions.append("Retail beli agresif, Asing jual (RETAIL FOMO)")
        elif retail_net < 0 and fnet < 0:
            conclusions.append("Retail + Asing sama-sama distribusi (EXODUS)")
    
    # 2. Smart Money dominance
    if tb_chart and price > 0:
        mf = calc_money_flow_chart(tb_chart, fallback_price=price)
        if mf:
            cm = mf["clean_money"]
            total = abs(mf["smart_money"]) + abs(mf["bad_money"])
            pwr = abs(cm) / total * 100 if total > 0 else 0
            if cm > 0 and pwr >= 30:
                conclusions.append(f"Money flow dominan buyer (power {pwr:.0f}%)")
            elif cm < 0 and pwr >= 30:
                conclusions.append(f"Money flow dominan seller (power {pwr:.0f}%)")
    
    # 3. Broker concentration insight
    if broker_1d:
        det_1d = broker_1d.get("bandar_detector", {})
        top5 = det_1d.get("top5", {})
        if top5:
            top5_label = top5.get("accdist", "")
            top5_pct = top5.get("percent", 0)
            if "Acc" in top5_label:
                conclusions.append(f"Top 5 broker akumulasi ({top5_pct:+.1f}%)")
            elif "Dist" in top5_label:
                conclusions.append(f"Top 5 broker distribusi ({top5_pct:+.1f}%)")
    
    # 4. Foreign flow divergence
    if change_pct < -2 and fnet > 0:
        conclusions.append("DIVERGENCE: Harga turun tapi Asing beli")
    elif change_pct > 2 and fnet < 0:
        conclusions.append("DIVERGENCE: Harga naik tapi Asing jual")
    
    # 5. Foreign accumulation trend (5D)
    if hist and len(hist) > 0:
        fnet_5d = 0
        for i, h in enumerate(reversed(hist)):
            if i < 5:
                fnet_5d += _safe_int(h.get("net_foreign", 0))
        
        if fnet_5d > 0 and fnet > 0:
            conclusions.append("Asing konsisten akumulasi (1D + 5D positif)")
        elif fnet_5d < 0 and fnet < 0:
            conclusions.append("Asing konsisten distribusi (1D + 5D negatif)")
    
    return conclusions


# ──────────────────────────────────────────────
# Internal Helpers
# ──────────────────────────────────────────────

def _shorten_accdist(accdist: str) -> str:
    """Shorten bandarmology accumulation/distribution labels."""
    if not accdist:
        return "-"
    
    s = accdist.strip()
    
    mappings = {
        "Big Accumulation": "Big Acc",
        "Small Accumulation": "Sm Acc",
        "Big Distribution": "Big Dist",
        "Small Distribution": "Sm Dist",
        "Accumulation": "Acc",
        "Distribution": "Dist",
        "Big Acc": "Big Acc",
        "Sm Acc": "Sm Acc",
        "Big Dist": "Big Dist",
        "Sm Dist": "Sm Dist",
    }
    
    for key, val in mappings.items():
        if s.lower() == key.lower():
            return val
    
    lower = s.lower()
    if "big" in lower and "acc" in lower:
        return "Big Acc"
    elif "small" in lower and "acc" in lower:
        return "Sm Acc"
    elif "big" in lower and "dist" in lower:
        return "Big Dist"
    elif "small" in lower and "dist" in lower:
        return "Sm Dist"
    elif "acc" in lower:
        return "Acc"
    elif "dist" in lower:
        return "Dist"
    
    return s[:12]
