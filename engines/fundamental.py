"""
Fundamental Analysis Engine — comprehensive metric grading, fair value estimation,
and overall fundamental scoring.
"""


def _safe_num(val, fallback=None):
    """Convert any value to float, stripping '%', 'x', 'B', etc."""
    if val is None or val == "-" or val == "":
        return fallback
    s = str(val).replace(",", "").replace("%", "").replace("x", "").strip()
    # Handle 'B' (Billion) suffix from Stockbit
    multiplier = 1
    if s.upper().endswith("B"):
        s = s[:-1].strip()
        multiplier = 1_000_000_000
    elif s.upper().endswith("T"):
        s = s[:-1].strip()
        multiplier = 1_000_000_000_000
    try:
        return float(s) * multiplier
    except (ValueError, TypeError):
        return fallback


def _grade(value, thresholds, reverse=False):
    """Grade a metric value.
    thresholds = [(limit, label), ...] sorted ascending.
    reverse=True means lower is better (e.g. DER, PE).
    Returns (label_str, score_int) where score is 1-5 (1=worst, 5=best).
    """
    if value is None:
        return ("-", 0)

    if reverse:
        # Lower is better
        for i, (limit, label) in enumerate(thresholds):
            if value <= limit:
                return (label, 5 - i)
        return (thresholds[-1][1], 1)
    else:
        # Higher is better
        for i, (limit, label) in enumerate(thresholds):
            if value <= limit:
                return (label, i + 1)
        return (thresholds[-1][1], 5)


# ── Metric Grading Definitions ──

def grade_pe(pe):
    """PE Ratio grading. Lower is cheaper."""
    return _grade(pe, [
        (8, "Sangat Murah"),
        (15, "Wajar"),
        (25, "Mahal"),
        (40, "Sangat Mahal"),
        (999, "Overvalued"),
    ], reverse=True)


def grade_pbv(pbv):
    """PBV grading. Lower is cheaper."""
    return _grade(pbv, [
        (1.0, "Diskon"),
        (2.0, "Wajar"),
        (3.5, "Premium"),
        (6.0, "Mahal"),
        (999, "Sangat Mahal"),
    ], reverse=True)


def grade_roe(roe):
    """ROE grading. Higher is better."""
    return _grade(roe, [
        (5, "Buruk"),
        (10, "Kurang"),
        (15, "Cukup"),
        (20, "Baik"),
        (999, "Excellent"),
    ])


def grade_roa(roa):
    """ROA grading. Higher is better."""
    return _grade(roa, [
        (2, "Buruk"),
        (5, "Kurang"),
        (8, "Cukup"),
        (12, "Baik"),
        (999, "Excellent"),
    ])


def grade_npm(npm):
    """NPM grading. Higher is better."""
    return _grade(npm, [
        (3, "Tipis"),
        (8, "Cukup"),
        (15, "Sehat"),
        (25, "Tebal"),
        (999, "Excellent"),
    ])


def grade_der(der):
    """DER grading. Lower is better (less leveraged)."""
    return _grade(der, [
        (0.5, "Sangat Sehat"),
        (1.0, "Sehat"),
        (2.0, "Normal"),
        (3.0, "Agresif"),
        (999, "Bahaya"),
    ], reverse=True)


def grade_div_yield(dy):
    """Dividend Yield grading. Higher is better."""
    return _grade(dy, [
        (1, "Rendah"),
        (3, "Cukup"),
        (5, "Menarik"),
        (8, "Tinggi"),
        (999, "Sangat Tinggi"),
    ])


def grade_fscore(fs):
    """Piotroski F-Score 0-9. Higher is better."""
    return _grade(fs, [
        (3, "Weak"),
        (5, "Average"),
        (7, "Strong"),
        (8, "Very Strong"),
        (999, "Excellent"),
    ])


def grade_peg(peg):
    """PEG Ratio. Lower is better (cheap relative to growth)."""
    if peg is None:
        return ("-", 0)
    if peg < 0:
        return ("Negatif", 1)
    return _grade(peg, [
        (0.5, "Sangat Murah"),
        (1.0, "Murah"),
        (1.5, "Wajar"),
        (2.5, "Mahal"),
        (999, "Overvalued"),
    ], reverse=True)


# ── Fair Value Estimators ──

def estimate_fair_value(eps, bvps, roe, pe_ttm, pbv, price, div_payout):
    """
    Estimate fair value using multiple methods and return a blended average.
    Methods:
    1. Revised Graham Formula: V = [EPS × (8.5 + 2g) × 4.4] / Y
       - g = Sustainable Growth Rate (ROE × Retention Ratio)
       - Y = 6.8 (Proxy for IDR corporate bond yield)
    2. PBV-based: Fair = BVPS × Benchmark PBV (cap at 2.0x for conservative)
    3. PE-based: Fair = EPS × Benchmark PE (cap at 15.0x for conservative)
    """
    estimates = []
    methods = []

    # Method 1: Revised Graham Formula
    if eps is not None and eps > 0 and roe is not None:
        # Calculate Sustainable Growth Rate (SGR)
        # Retention Ratio = 1 - (Dividend Payout / 100). If no payout data, assume 50% retention
        retention = 0.5
        if div_payout is not None and 0 <= div_payout <= 100:
            retention = 1.0 - (div_payout / 100.0)
            
        growth_rate = roe * retention
        # Cap growth between 0% and 20% to prevent absurd valuations on hyper-growth anomalies
        growth_rate = max(0.0, min(growth_rate, 20.0))
        
        # Revised Graham with bond yield adjustment (Y = 6.8% for Indonesian market proxy)
        graham_val = (eps * (8.5 + 2 * growth_rate) * 4.4) / 6.8
        if graham_val > 0:
            estimates.append(graham_val)
            methods.append(("Graham (Revised)", graham_val))

    # Method 2: PBV-based fair value
    if bvps is not None and bvps > 0:
        # If company has high ROE (>15%), deserve higher PBV benchmark (2.0), else 1.2
        pbv_benchmark = 2.0 if roe is not None and roe > 15 else 1.2
        pbv_fair = bvps * pbv_benchmark
        estimates.append(pbv_fair)
        methods.append(("PBV Fair", pbv_fair))

    # Method 3: PE-based fair value
    if eps is not None and eps > 0:
        # If company has high growth, deserve higher PE (max 15)
        pe_benchmark = 15.0 if roe is not None and roe > 15 else 10.0
        pe_fair = eps * pe_benchmark
        estimates.append(pe_fair)
        methods.append(("PE Fair", pe_fair))

    if not estimates:
        return None, [], None

    avg_fair = sum(estimates) / len(estimates)

    # Margin of Safety
    if price is not None and price > 0 and avg_fair > 0:
        mos = ((avg_fair - price) / avg_fair) * 100
    else:
        mos = None

    return avg_fair, methods, mos


# ── Keystats Parser ──

def parse_keystats(ks_data: dict) -> dict:
    """Extract important fundamental ratios from keystats data."""
    result = {}
    if not ks_data or "closure_fin_items_results" not in ks_data:
        return result

    for group in ks_data.get("closure_fin_items_results", []):
        for item in group.get("fin_name_results", []):
            fitem = item.get("fitem", {})
            f_id = fitem.get("id")
            f_val = fitem.get("value", "-")

            if f_id == "12148": result["pe_annual"] = f_val
            elif f_id == "2891": result["pe_ttm"] = f_val
            elif f_id == "16577": result["pe_forward"] = f_val
            elif f_id == "2896": result["pbv"] = f_val
            elif f_id == "13431": result["peg"] = f_val
            elif f_id == "13432": result["peg_3yr"] = f_val
            elif f_id == "2898": result["earnings_yield"] = f_val
            elif f_id == "2893": result["ps_ratio"] = f_val
            elif f_id == "16533": result["pcf_ratio"] = f_val
            elif f_id == "2897": result["ev_ebit"] = f_val
            elif f_id == "21457": result["ev_ebitda"] = f_val

            # Profitability
            elif f_id == "1561": result["gpm"] = f_val
            elif f_id == "1562": result["opm"] = f_val
            elif f_id == "1563": result["npm"] = f_val

            # Effectiveness
            elif f_id == "1460": result["roa"] = f_val
            elif f_id == "1461": result["roe"] = f_val
            elif f_id == "1462": result["roce"] = f_val
            elif f_id == "13447": result["roic"] = f_val

            # Solvency
            elif f_id == "1508": result["der"] = f_val
            elif f_id == "1484": result["icr"] = f_val
            elif f_id == "1573": result["liab_equity"] = f_val
            elif f_id == "1502": result["fin_leverage"] = f_val
            elif f_id == "13402": result["altman_z"] = f_val

            # Dividend
            elif f_id == "2916": result["div_payout"] = f_val
            elif f_id == "2915": result["div_yield"] = f_val

            # Per Share
            elif f_id == "13200": result["eps"] = f_val
            elif f_id == "15718": result["bvps"] = f_val
            elif f_id == "15882": result["fcfps"] = f_val
            elif f_id == "15879": result["cashps"] = f_val
            elif f_id == "15880": result["revps"] = f_val

            # Cash Flow
            elif f_id == "2536": result["fcf"] = f_val

            # Scores
            elif f_id == "13366": result["f_score"] = f_val

            # Efficiency
            elif f_id == "1467": result["asset_turnover"] = f_val

    return result


def parse_profile(profile_data: dict) -> dict:
    """Extract shareholders, listing info, and shareholder count history."""
    result = {"shareholders": [], "listing": {}, "shareholder_numbers": []}
    if not profile_data:
        return result

    for sh in profile_data.get("shareholder", [])[:5]:
        name = sh.get("name", "")
        pct = sh.get("percentage", "0%")
        if name:
            result["shareholders"].append({"name": name, "pct": pct})

    li = profile_data.get("listing_information", {})
    if li:
        fpct = li.get("foreign_percentage", {}).get("formatted", "-")
        lpct = li.get("local_percentage", {}).get("formatted", "-")
        result["listing"]["foreign"] = fpct
        result["listing"]["local"] = lpct
        result["listing"]["total_shares"] = li.get("total_shares", 0)

    # Shareholder count history (latest 4 entries)
    for sn in profile_data.get("shareholder_numbers", [])[:4]:
        result["shareholder_numbers"].append({
            "date": sn.get("shareholder_date", "-"),
            "total": sn.get("total_share", "-"),
            "change": sn.get("change", 0),
            "change_fmt": sn.get("change_formatted", ""),
        })

    return result


def score_to_grade(score: float, is_total: bool = False) -> tuple[str, str]:
    """
    Converts a raw score into a Letter Grade and Label.
    If is_total is True, assumes a 0-100 scale. Else assumes a 1-5 scale.
    """
    if is_total:
        if score >= 85: return "A", "Sangat Sehat"
        elif score >= 70: return "B", "Sehat"
        elif score >= 55: return "C", "Cukup"
        elif score >= 40: return "D", "Kurang Sehat"
        else: return "E", "Berbahaya"
    else:
        if score >= 4.5: return "A", "Sangat Baik"
        elif score >= 3.5: return "B", "Baik"
        elif score >= 2.5: return "C", "Cukup"
        elif score >= 1.5: return "D", "Kurang"
        else: return "E", "Buruk"


def calc_fundamental(info_data: dict, ks_data: dict, profile_data: dict) -> dict:
    """Combine info, keystats, and profile into a graded fundamental summary."""
    stats = ks_data.get("stats", {}) if ks_data else {}
    res = {
        "name": info_data.get("name", "?") if info_data else "?",
        "sector": info_data.get("sector", "?") if info_data else "?",
        "sub_sector": info_data.get("sub_sector", "?") if info_data else "?",
        "price": info_data.get("price", "0") if info_data else "0",
        "market_cap": stats.get("market_cap", "-"),
        "share_outstanding": stats.get("current_share_outstanding", "-"),
        "enterprise_value": stats.get("enterprise_value", "-"),
        "free_float": stats.get("free_float", "-"),
    }

    ks = parse_keystats(ks_data)
    res.update(ks)
    res["profile"] = parse_profile(profile_data)

    # Parse numeric values for grading
    price_num = _safe_num(res.get("price"), 0)
    pe_num = _safe_num(res.get("pe_ttm"))
    pbv_num = _safe_num(res.get("pbv"))
    roe_num = _safe_num(res.get("roe"))
    roa_num = _safe_num(res.get("roa"))
    npm_num = _safe_num(res.get("npm"))
    der_num = _safe_num(res.get("der"))
    dy_num = _safe_num(res.get("div_yield"))
    fs_num = _safe_num(res.get("f_score"))
    peg_num = _safe_num(res.get("peg"))
    eps_num = _safe_num(res.get("eps"))
    bvps_num = _safe_num(res.get("bvps"))
    dp_num = _safe_num(res.get("div_payout"))

    # Grade each metric
    res["grades"] = {
        "pe": grade_pe(pe_num),
        "pbv": grade_pbv(pbv_num),
        "roe": grade_roe(roe_num),
        "roa": grade_roa(roa_num),
        "npm": grade_npm(npm_num),
        "der": grade_der(der_num),
        "div_yield": grade_div_yield(dy_num),
        "f_score": grade_fscore(fs_num),
        "peg": grade_peg(peg_num),
    }

    # Fair Value Estimation
    fair_val, methods, mos = estimate_fair_value(
        eps_num, bvps_num, roe_num, pe_num, pbv_num, price_num, dp_num
    )
    res["fair_value"] = fair_val
    res["fair_methods"] = methods
    res["margin_of_safety"] = mos

    # Overall Score (weighted average of grades, 0-100)
    weights = {
        "pe": 15, "pbv": 10, "roe": 20, "roa": 10,
        "npm": 15, "der": 10, "f_score": 10, "peg": 10,
    }
    total_weight = 0
    total_score = 0
    
    # Pillar aggregators
    val_score, val_w = 0, 0
    prof_score, prof_w = 0, 0
    solv_score, solv_w = 0, 0
    
    for key, w in weights.items():
        _, score = res["grades"].get(key, ("-", 0))
        if score > 0:
            total_score += score * w
            total_weight += w
            
            # Group into Pillars
            if key in ["pe", "pbv", "peg"]:
                val_score += score * w
                val_w += w
            elif key in ["roe", "roa", "npm"]:
                prof_score += score * w
                prof_w += w
            elif key in ["der", "f_score"]:
                solv_score += score * w
                solv_w += w

    if total_weight > 0:
        overall = (total_score / total_weight) * 20  # scale to 0-100
    else:
        overall = 0

    res["overall_score"] = round(overall)
    
    # Calculate Pillar Averages (1-5 scale)
    avg_val = (val_score / val_w) if val_w > 0 else 0
    avg_prof = (prof_score / prof_w) if prof_w > 0 else 0
    avg_solv = (solv_score / solv_w) if solv_w > 0 else 0
    
    # Assign Letter Grades
    val_grade, val_label = score_to_grade(avg_val)
    prof_grade, prof_label = score_to_grade(avg_prof)
    solv_grade, solv_label = score_to_grade(avg_solv)
    tot_grade, tot_label = score_to_grade(overall, is_total=True)
    
    res["pillar_grades"] = {
        "valuation": {"grade": val_grade, "label": val_label},
        "profitability": {"grade": prof_grade, "label": prof_label},
        "solvency": {"grade": solv_grade, "label": solv_label},
    }
    
    res["overall_grade"] = tot_grade
    res["overall_label"] = tot_label

    return res
