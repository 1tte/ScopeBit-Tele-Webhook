"""
Bandarmology engine — multi-timeframe stealth accumulation tracker
with Broker Concentration, Foreign Flow, and Participation stats.
"""
import logging
import html
import asyncio
from datetime import datetime, timedelta, timezone
from api.market import get_orderbook, get_historical_summary
from api.fundamental import get_info
from api.broker import get_broker_summary
from api.client import _safe_float, _safe_int

log = logging.getLogger("bot")


def _fmt_val(val: float) -> str:
    abs_val = abs(val)
    sign = "+" if val >= 0 else "-"
    if abs_val >= 1_000_000_000_000: return f"{sign}{abs_val / 1_000_000_000_000:.2f}T"
    elif abs_val >= 1_000_000_000: return f"{sign}{abs_val / 1_000_000_000:.2f}M"
    elif abs_val >= 1_000_000: return f"{sign}{abs_val / 1_000_000:.1f}Jt"
    elif abs_val >= 1_000: return f"{sign}{abs_val / 1_000:.0f}Rb"
    else: return f"{sign}{abs_val:.0f}"


def _fmt_val_unsigned(val: float) -> str:
    abs_val = abs(val)
    if abs_val >= 1_000_000_000_000: return f"{abs_val / 1_000_000_000_000:.2f}T"
    elif abs_val >= 1_000_000_000: return f"{abs_val / 1_000_000_000:.2f}M"
    elif abs_val >= 1_000_000: return f"{abs_val / 1_000_000:.1f}Jt"
    elif abs_val >= 1_000: return f"{abs_val / 1_000:.0f}Rb"
    else: return f"{abs_val:.0f}"


def _fmt_price(val) -> str:
    if val is None or val == 0:
        return "-"
    return f"{int(val):,}".replace(",", ".")


def _broker_flag(btype: str) -> str:
    """Return bracket flag based on broker type."""
    if btype == "Asing":
        return "[A]"
    elif btype == "Lokal":
        return "[R]"
    elif btype == "Pemerintah":
        return "[G]"
    return "   "


def _get_effective_date(dt: datetime) -> datetime:
    """
    Returns the effective trading date based on market hours and weekends.
    - Sat/Sun -> Friday
    - Mon-Fri before 16:00 -> Previous trading day
    - Mon-Fri after 16:00 -> Today
    """
    wd = dt.weekday()
    hour = dt.hour
    
    if wd == 5: # Saturday
        return dt - timedelta(days=1)
    elif wd == 6: # Sunday
        return dt - timedelta(days=2)
    else: # Mon-Fri
        if hour < 16:
            if wd == 0: # Monday before 16:00 -> Friday
                return dt - timedelta(days=3)
            else: # Tue-Fri before 16:00 -> Previous Day
                return dt - timedelta(days=1)
        else:
            return dt

async def analyze_bandar(symbol: str) -> str | None:
    """Perform detailed multi-timeframe bandarmology stealth analysis."""
    symbol = symbol.upper().strip()

    _WIB = timezone(timedelta(hours=7))
    now = datetime.now(_WIB)
    today = _get_effective_date(now)
    today_str = today.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # Ordered from shortest to longest (1D → 1M)
    timeframes = [
        ("1 HARI", 0),
        ("5 HARI", 7),
        ("2 MINGGU", 14),
        ("1 BULAN", 30),
    ]

    results = {}

    tasks = [
        get_orderbook(symbol),
        get_info(symbol),
        get_historical_summary(symbol, 20)
    ]
    
    for label, days_back in timeframes:
        start_str = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
        tasks.append(get_broker_summary(symbol, None, start_date_str=start_str, end_date_str=today_str))

    res = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Gathered asyncio results validation ignores Pylance false positives
    ob = res[0] if not isinstance(res[0], Exception) else None  # type: ignore
    info = res[1] if not isinstance(res[1], Exception) else None  # type: ignore
    hist = res[2] if not isinstance(res[2], Exception) else None  # type: ignore
    
    idx = 3
    for label, _ in timeframes:
        results[label] = res[idx] if not isinstance(res[idx], Exception) else None
        idx += 1

    if not any(results.values()):
        return f"Data Bandarmology untuk <b>{symbol}</b> tidak ditemukan."

    comp_name = html.escape(info.get("name", "?")) if info else "?"

    L = "━" * 38
    o = [f"<b>BANDARMOLOGY: {comp_name} ({symbol})</b>"]
    o.append(f"<code>Tanggal : {current_time_str} (Data: {today_str})</code>")

    # ── Current Price ──
    if ob:
        price = ob["last_price"]
        pct = ob["change_pct"]
        sign = "+" if pct >= 0 else ""
        fnet = ob.get("fnet", 0)
        o.append(f"<code>Harga   : {_fmt_price(price)} ({sign}{pct:.2f}%)</code>")
    o.append(f"<code>{L}</code>")

    # ── Foreign Flow (from historical summary) ──
    if hist and len(hist) > 0:
        o.append("<b>FOREIGN FLOW</b>")
        fnet_today_val = ob.get("fnet", 0) if ob else 0
        fnet_label = "Net Buy" if fnet_today_val >= 0 else "Net Sell"

        ff_lines = [f"Today        : {_fmt_val(fnet_today_val):>10} ({fnet_label})"]

        # Calculate 5D and 20D foreign accumulation
        fnet_5d = 0
        fnet_20d = 0
        for i, h in enumerate(reversed(hist)):
            fn = _safe_int(h.get("net_foreign", 0))
            if i < 5:
                fnet_5d += fn
            fnet_20d += fn

        ff_lines.append(f"Acc 5D       : {_fmt_val(fnet_5d):>10} ({'Akum' if fnet_5d >= 0 else 'Dist'})")
        ff_lines.append(f"Acc 20D      : {_fmt_val(fnet_20d):>10} ({'Akum' if fnet_20d >= 0 else 'Dist'})")

        o.append("<code>" + "\n".join(ff_lines) + "</code>")
        o.append(f"<code>{L}</code>")

    # ── Multi-Timeframe Broker Activity (1D → 1M) ──
    o.append("<b>BROKER ACTIVITY (Per Timeframe)</b>")

    for label, _ in timeframes:
        data = results.get(label)
        if not data:
            continue

        bs = data.get("broker_summary", {})
        det = data.get("bandar_detector", {})

        status = det.get("broker_accdist", "-")
        if "Acc" in status:
            status_tag = "ACC"
        elif "Dist" in status:
            status_tag = "DIST"
        else:
            status_tag = status.upper()

        total_buyer = det.get("total_buyer", 0)
        total_seller = det.get("total_seller", 0)
        net_val = det.get("value", 0)

        o.append(f"<b>[{label}] {status_tag} | B:{total_buyer} S:{total_seller} | Net: {_fmt_val(net_val)}</b>")

        # Top 3 Buyers
        buyers = bs.get("brokers_buy", [])[:3]
        seller_list = bs.get("brokers_sell", [])[:3]

        lines = []
        for b in buyers:
            code = b.get("netbs_broker_code", "?")
            lot = int(_safe_float(b.get("blot", 0)))
            val = int(_safe_float(b.get("bval", 0)))
            avg = int(_safe_float(b.get("netbs_buy_avg_price", 0)))
            btype = b.get("type", "")
            flag = _broker_flag(btype)
            lines.append(f"  B: {code:2}{flag:>4} {_fmt_val_unsigned(lot):>6} Lot  Avg {_fmt_price(avg)}")

        for s in seller_list:
            code = s.get("netbs_broker_code", "?")
            lot = int(_safe_float(s.get("slot", 0)))
            val = int(_safe_float(s.get("sval", 0)))
            avg = int(_safe_float(s.get("netbs_sell_avg_price", 0)))
            stype = s.get("type", "")
            flag = _broker_flag(stype)
            lines.append(f"  S: {code:2}{flag:>4} {_fmt_val_unsigned(lot):>6} Lot  Avg {_fmt_price(avg)}")

        if lines:
            o.append("<code>" + "\n".join(lines) + "</code>")

    o.append(f"<code>{L}</code>")

    # ── Broker Concentration (from 1D detector) ──
    det_1d = results.get("1 HARI", {}).get("bandar_detector", {})
    if det_1d:
        o.append("<b>BROKER CONCENTRATION (1D)</b>")
        tiers = [
            ("Top 1 ", det_1d.get("top1")),
            ("Top 3 ", det_1d.get("top3")),
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
        o.append(f"<code>{L}</code>")

    # ── Stealth Accumulation Detection ──
    # Cross-reference: broker appears in Top 5 buyers of BOTH 1M and 5D
    try:
        data_1m = results.get("1 BULAN") or {}
        data_5d = results.get("5 HARI") or {}
        buy_1m = {b.get("netbs_broker_code"): b for b in data_1m.get("broker_summary", {}).get("brokers_buy", [])[:5]}
        buy_5d = {b.get("netbs_broker_code"): b for b in data_5d.get("broker_summary", {}).get("brokers_buy", [])[:5]}

        sell_1m = {s.get("netbs_broker_code"): s for s in data_1m.get("broker_summary", {}).get("brokers_sell", [])[:5]}
        sell_5d = {s.get("netbs_broker_code"): s for s in data_5d.get("broker_summary", {}).get("brokers_sell", [])[:5]}

        stealth_acc = set(buy_1m.keys()).intersection(set(buy_5d.keys())) - {None, "?", "Unknown"}
        stealth_dist = set(sell_1m.keys()).intersection(set(sell_5d.keys())) - {None, "?", "Unknown"}

        if stealth_acc or stealth_dist:
            o.append("<b>STEALTH MODE</b>")
            stealth_lines = []

            for sb in stealth_acc:
                lot_1m = int(_safe_float(buy_1m[sb].get("blot", 0)))
                avg_1m = int(_safe_float(buy_1m[sb].get("netbs_buy_avg_price", 0)))
                lot_5d = int(_safe_float(buy_5d[sb].get("blot", 0)))
                stealth_lines.append(
                    f"{sb} AKUM konsisten 1M ({_fmt_val_unsigned(lot_1m)} Lot) "
                    f"+ 5D ({_fmt_val_unsigned(lot_5d)} Lot) "
                    f"Avg Rp {_fmt_price(avg_1m)}"
                )

            for sb in stealth_dist:
                lot_1m = int(_safe_float(sell_1m[sb].get("slot", 0)))
                avg_1m = int(_safe_float(sell_1m[sb].get("netbs_sell_avg_price", 0)))
                lot_5d = int(_safe_float(sell_5d[sb].get("slot", 0)))
                stealth_lines.append(
                    f"{sb} DIST konsisten 1M ({_fmt_val_unsigned(lot_1m)} Lot) "
                    f"+ 5D ({_fmt_val_unsigned(lot_5d)} Lot) "
                    f"Avg Rp {_fmt_price(avg_1m)}"
                )

            if stealth_lines:
                o.append("<code>" + "\n".join(stealth_lines) + "</code>")
            o.append(f"<code>{L}</code>")

    except Exception as e:
        log.warning(f"Stealth calc error: {e}")

    # ── Retail vs Asing Flow ──
    # Uses authoritative foreign flow data (fnet from orderbook / historical)
    # instead of broker summary top-N which only covers listed brokers
    try:
        data_1d = results.get("1 HARI") or {}
        data_5d = results.get("5 HARI") or {}
        det_1d_local = data_1d.get("bandar_detector", {})
        det_5d_local = data_5d.get("bandar_detector", {})

        # 1D: Use fnet from orderbook (same source as FOREIGN FLOW section)
        asing_net_1d = ob.get("fnet", 0) if ob else 0
        # Total net from bandar detector
        total_net_1d = det_1d_local.get("value", 0)
        # Retail = total - asing
        retail_net_1d = total_net_1d - asing_net_1d

        # 5D: Use accumulated net_foreign from historical (same source as FOREIGN FLOW)
        asing_net_5d = 0
        if hist and len(hist) > 0:
            for i, h in enumerate(reversed(hist)):
                if i < 5:
                    asing_net_5d += _safe_int(h.get("net_foreign", 0))
        total_net_5d = det_5d_local.get("value", 0)
        retail_net_5d = total_net_5d - asing_net_5d

        o.append("<b>RETAIL vs ASING FLOW (Rp)</b>")
        flow_lines = [
            f"           {'1D':>12} {'5D':>12}",
            f"Retail Net : {_fmt_val(retail_net_1d):>12} {_fmt_val(retail_net_5d):>12}",
            f"Asing Net  : {_fmt_val(asing_net_1d):>12} {_fmt_val(asing_net_5d):>12}",
        ]
        o.append("<code>" + "\n".join(flow_lines) + "</code>")

        # Detect behavioral patterns
        signals = []

        # FOMO: Retail net buy besar, tapi Asing net sell (smart money keluar)
        if retail_net_1d > 0 and asing_net_1d < 0 and abs(asing_net_1d) > retail_net_1d * 0.3:
            signals.append("RETAIL FOMO (1D): Retail beli agresif, Asing distribusi")
        if retail_net_5d > 0 and asing_net_5d < 0 and abs(asing_net_5d) > retail_net_5d * 0.3:
            signals.append("RETAIL FOMO (5D): Retail akumulasi, Smart Money keluar")

        # PANIC SELL: Retail net sell, tapi Asing net buy (smart money masuk)
        if retail_net_1d < 0 and asing_net_1d > 0 and abs(retail_net_1d) > asing_net_1d * 0.3:
            signals.append("PANIC SELLING (1D): Retail buang barang, Asing akumulasi")
        if retail_net_5d < 0 and asing_net_5d > 0 and abs(retail_net_5d) > asing_net_5d * 0.3:
            signals.append("PANIC SELLING (5D): Retail dist, Smart Money masuk")

        # SMART ACCUMULATION: Asing beli besar tanpa retail ikut
        if asing_net_1d > 0 and retail_net_1d < 0:
            signals.append("SMART ACCUMULATION (1D): Asing quietly accumulating")
        if asing_net_5d > 0 and retail_net_5d < 0:
            signals.append("SMART ACCUMULATION (5D): Asing accumulating consistently")

        # BOTH SELLING: semua jual
        if retail_net_1d < 0 and asing_net_1d < 0:
            signals.append("EXODUS (1D): Retail dan Asing sama-sama distribusi")

        # BOTH BUYING: semua beli
        if retail_net_1d > 0 and asing_net_1d > 0:
            signals.append("CONSENSUS BUY (1D): Retail dan Asing sama-sama akumulasi")

        if signals:
            o.append("<code>" + "\n".join(signals) + "</code>")
        o.append(f"<code>{L}</code>")

    except Exception as e:
        log.warning(f"Retail behavior calc error: {e}")

    # ── Volume Profile ──
    try:
        if ob and hist and len(hist) > 0:
            vol_today = _safe_int(ob.get("volume", 0))
            val_today = _safe_int(ob.get("value", 0))

            # Calculate avg volume and value from historical
            vols = [_safe_int(h.get("volume", 0)) for h in hist if _safe_int(h.get("volume", 0)) > 0]
            vals = [_safe_int(h.get("value", 0)) for h in hist if _safe_int(h.get("value", 0)) > 0]
            avg_vol = sum(vols) / len(vols) if vols else 0
            avg_val = sum(vals) / len(vals) if vals else 0

            vol_ratio = (vol_today / avg_vol * 100) if avg_vol > 0 else 0
            val_ratio = (val_today / avg_val * 100) if avg_val > 0 else 0

            # Visual bar (max 10 blocks)
            bar_blocks = min(10, int(vol_ratio / 20))  # each block = 20%
            vol_bar = "█" * bar_blocks + "░" * (10 - bar_blocks)

            if vol_ratio >= 200:
                vol_signal = "VOLUME SURGE"
            elif vol_ratio >= 150:
                vol_signal = "Above Average"
            elif vol_ratio >= 80:
                vol_signal = "Normal"
            elif vol_ratio > 0:
                vol_signal = "Low Volume"
            else:
                vol_signal = "No Data"

            o.append("<b>VOLUME PROFILE</b>")
            vp_lines = [
                f"Vol Today : {_fmt_val_unsigned(vol_today):>10} ({vol_ratio:.0f}% avg)",
                f"Vol Avg20 : {_fmt_val_unsigned(avg_vol):>10}",
                f"Val Today : {_fmt_val_unsigned(val_today):>10} ({val_ratio:.0f}% avg)",
                f"Status    : {vol_signal}",
            ]
            o.append("<code>" + "\n".join(vp_lines) + "</code>")
            o.append(f"<code>{L}</code>")

    except Exception as e:
        log.warning(f"Volume profile calc error: {e}")

    # ── Broker Dominance ──
    try:
        data_1d = results.get("1 HARI") or {}
        bs_1d = data_1d.get("broker_summary", {})

        # Sum buy + sell values by broker type
        type_vals = {"Asing": 0, "Lokal": 0, "Pemerintah": 0}

        for b in bs_1d.get("brokers_buy", []):
            btype = b.get("type", "Lokal")
            val = int(_safe_float(b.get("bval", 0)))
            if btype in type_vals:
                type_vals[btype] += val

        for s in bs_1d.get("brokers_sell", []):
            stype = s.get("type", "Lokal")
            val = int(_safe_float(s.get("sval", 0)))
            if stype in type_vals:
                type_vals[stype] += val

        total_flow = sum(type_vals.values())

        if total_flow > 0:
            pct_asing = type_vals["Asing"] / total_flow * 100
            pct_retail = type_vals["Lokal"] / total_flow * 100
            pct_gov = type_vals["Pemerintah"] / total_flow * 100

            o.append("<b>BROKER DOMINANCE (1D)</b>")
            dom_lines = [
                f"Asing  : {pct_asing:>5.1f}% ({_fmt_val_unsigned(type_vals['Asing'])})",
                f"Retail : {pct_retail:>5.1f}% ({_fmt_val_unsigned(type_vals['Lokal'])})",
            ]
            if pct_gov >= 1:
                dom_lines.append(f"Gov    : {pct_gov:>5.1f}% ({_fmt_val_unsigned(type_vals['Pemerintah'])})")
            o.append("<code>" + "\n".join(dom_lines) + "</code>")
            o.append(f"<code>{L}</code>")

    except Exception as e:
        log.warning(f"Broker dominance calc error: {e}")

    # ── Harga vs Akumulasi (Price Conviction) ──
    try:
        data_1d = results.get("1 HARI") or {}
        bs_1d = data_1d.get("broker_summary", {})
        current_price = ob.get("last_price", 0) if ob else 0

        if current_price > 0:
            conviction_lines = []
            buyers_1d = bs_1d.get("brokers_buy", [])[:5]

            for b in buyers_1d:
                code = b.get("netbs_broker_code", "?")
                avg = int(_safe_float(b.get("netbs_buy_avg_price", 0)))
                lot = int(_safe_float(b.get("blot", 0)))
                btype = b.get("type", "")
                flag = _broker_flag(btype)

                if avg > 0:
                    diff_pct = ((current_price - avg) / avg) * 100
                    if diff_pct <= -5:
                        status = "RUGI"
                    elif diff_pct < 0:
                        status = "Minus"
                    elif diff_pct < 1:
                        status = "Impas"
                    else:
                        status = "Untung"
                    conviction_lines.append(
                        f"{code:2}{flag:>4} Avg {_fmt_price(avg):>7} vs {_fmt_price(current_price):>7} ({diff_pct:+.1f}%) {status}"
                    )

            if conviction_lines:
                o.append("<b>AKUMULASI vs HARGA (Top 5 Buyer)</b>")
                o.append("<code>" + "\n".join(conviction_lines) + "</code>")
                o.append(f"<code>{L}</code>")

    except Exception as e:
        log.warning(f"Price conviction calc error: {e}")

    # ── Kesimpulan Otomatis ──
    try:
        conclusions = []
        current_price = ob.get("last_price", 0) if ob else 0
        change_pct = ob.get("change_pct", 0) if ob else 0
        fnet_today = ob.get("fnet", 0) if ob else 0

        # 1. Price Trend
        if change_pct <= -5:
            conclusions.append("Harga anjlok signifikan hari ini")
        elif change_pct <= -2:
            conclusions.append("Harga turun cukup dalam")
        elif change_pct < 0:
            conclusions.append("Harga sedikit melemah")
        elif change_pct >= 5:
            conclusions.append("Harga naik tajam")
        elif change_pct >= 2:
            conclusions.append("Harga menguat signifikan")
        elif change_pct > 0:
            conclusions.append("Harga naik tipis")

        # 2. Foreign Flow narrative
        if fnet_today > 1_000_000_000:
            conclusions.append(f"Asing beli agresif ({_fmt_val(fnet_today)})")
        elif fnet_today > 0:
            conclusions.append(f"Asing net buy ({_fmt_val(fnet_today)})")
        elif fnet_today < -1_000_000_000:
            conclusions.append(f"Asing jual besar-besaran ({_fmt_val(fnet_today)})")
        elif fnet_today < 0:
            conclusions.append(f"Asing net sell ({_fmt_val(fnet_today)})")

        # 3. Stealth detection narrative
        data_1m = results.get("1 BULAN") or {}
        data_5d = results.get("5 HARI") or {}
        buy_1m_codes = {b.get("netbs_broker_code") for b in data_1m.get("broker_summary", {}).get("brokers_buy", [])[:5]}
        buy_5d_codes = {b.get("netbs_broker_code") for b in data_5d.get("broker_summary", {}).get("brokers_buy", [])[:5]}
        stealth = buy_1m_codes & buy_5d_codes - {None, "?"}
        if stealth:
            conclusions.append(f"Stealth accumulation terdeteksi: {', '.join(stealth)}")

        # 4. Broker concentration narrative (from 1D detector)
        det_1d_local = (results.get("1 HARI") or {}).get("bandar_detector", {})
        top5_data = det_1d_local.get("top5", {})
        if top5_data:
            top5_accdist = top5_data.get("accdist", "")
            top5_pct = top5_data.get("percent", 0)
            if "Big Acc" in top5_accdist:
                conclusions.append(f"Top 5 broker akumulasi besar ({top5_pct:+.1f}%)")
            elif "Big Dist" in top5_accdist:
                conclusions.append(f"Top 5 broker distribusi besar ({top5_pct:+.1f}%)")

        # 5. Volume narrative
        if ob and hist and len(hist) > 0:
            vol_today_c = _safe_int(ob.get("volume", 0))
            vols_c = [_safe_int(h.get("volume", 0)) for h in hist if _safe_int(h.get("volume", 0)) > 0]
            avg_vol_c = sum(vols_c) / len(vols_c) if vols_c else 0
            if avg_vol_c > 0:
                ratio_c = vol_today_c / avg_vol_c * 100
                if ratio_c >= 200:
                    conclusions.append(f"Volume melonjak {ratio_c:.0f}% dari rata-rata")
                elif ratio_c < 50:
                    conclusions.append(f"Volume sangat rendah ({ratio_c:.0f}% avg)")

        # 6. Divergence detection
        if change_pct < -2 and fnet_today > 0:
            conclusions.append("DIVERGENCE: Harga turun tapi Asing beli — potensi reversal")
        elif change_pct > 2 and fnet_today < 0:
            conclusions.append("DIVERGENCE: Harga naik tapi Asing jual — hati-hati koreksi")

        if conclusions:
            o.append("<b>KESIMPULAN</b>")
            o.append("<code>" + "\n".join(conclusions) + "</code>")
            o.append(f"<code>{L}</code>")

    except Exception as e:
        log.warning(f"Conclusion calc error: {e}")

    o.append("<i>⚠️ Disclaimer: Bukan ajakan jual/beli.</i>")
    return "\n".join(o)
