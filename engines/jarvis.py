"""
JARVIS — Persistent Intelligence System
Infinity Stones Screener Engine

Runs 7 screening passes daily using comprehensive ScopeBit metrics.
Accumulates data permanently. Builds conviction scores over time.
Past data informs future predictions.
"""

import os
import sys
import json
import logging
import asyncio
import pytz
from datetime import datetime, timedelta

# Add project root to python path so it can find the 'api' package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.screener import run_screener

log = logging.getLogger("bot")


# ─────────────────────────────────────────────────────────
# METRIC ID MAPPING — VERIFIED from official ScopeBit API
# ─────────────────────────────────────────────────────────
# Source: /screener/metrics endpoint (metrics.txt)
# Every ID below is VERIFIED against the official response.

METRIC = {
    # ── Price & Volume ──────────────────────────────────
    "price":                2661,     # Price
    "price_unadj":          13118,    # Price (Unadjusted)
    "open_price":           20891,    # Open Price
    "high_price":           20893,    # High Price
    "low_price":            20892,    # Low Price
    "prev_price":           13622,    # Previous Price
    "volume":               12469,    # Volume
    "prev_volume":          15490,    # Previous Volume
    "value":                13620,    # Value
    "frequency":            3229,     # Frequency
    "freq_analyzer":        15394,    # Frequency Analyzer
    "freq_spike":           15396,    # Frequency Spike
    "vol_chg_1d":           13650,    # 1 Day Volume Change
    "price_change":         15628,    # Price Change (absolute)

    # ── Moving Averages (Price) ─────────────────────────
    "ma5":                  12459,    # Price MA 5
    "ma10":                 12457,    # Price MA 10
    "ma20":                 12458,    # Price MA 20
    "ma50":                 12460,    # Price MA 50
    "ma100":                12461,    # Price MA 100
    "ma200":                12462,    # Price MA 200

    # ── Moving Averages (Volume) ────────────────────────
    "vma5":                 12465,    # Volume MA 5
    "vma10":                12463,    # Volume MA 10
    "vma20":                12464,    # Volume MA 20
    "vma50":                12466,    # Volume MA 50

    # ── Value Moving Averages ───────────────────────────
    "val_ma5":              16452,    # Value MA 5
    "val_ma20":             16454,    # Value MA 20

    # ── Price Performance ───────────────────────────────
    "ret_1d_pct":           15629,    # 1 Day Price Returns (%)
    "ret_1w":               14812,    # 1 Week Price Returns
    "ret_1m":               1564,     # 1 Month Price Returns
    "ret_3m":               1565,     # 3 Month Price Returns
    "ret_6m":               1566,     # 6 Month Price Returns
    "ret_1y":               1567,     # 1 Year Price Returns
    "ret_ytd":              1569,     # Year to Date Price Returns
    "high_52w":             1570,     # 52 Week High
    "low_52w":              1571,     # 52 Week Low
    "near_52w_high":        13412,    # Near 52 Week High
    "cagr_3y":              16458,    # 3 Year CAGR Price Performance
    "cagr_5y":              16459,    # 5 Year CAGR Price Performance

    # ── Relative Strength ───────────────────────────────
    "rs_1m":                13374,    # 1 Month RS Line
    "rs_3m":                13373,    # 3 Month RS Line
    "rs_6m":                13372,    # 6 Month RS Line
    "rs_9m":                13407,    # 9 Month RS Line
    "rs_1y":                13371,    # 1 Year RS Line

    # ── Bandarmology & Foreign Flow ─────────────────────
    "bandar_value":         14399,    # Bandar Value
    "bandar_accum":         14400,    # Bandar Accum/Dist
    "bandar_value_ma10":    14424,    # Bandar Value MA 10
    "bandar_value_ma20":    14426,    # Bandar Value MA 20
    "prev_bandar_value":    14425,    # Previous Bandar Value
    "foreign_flow":         3218,     # Foreign Flow
    "foreign_flow_ma20":    13521,    # Foreign Flow MA 20
    "foreign_flow_ma50":    13524,    # Foreign Flow MA 50
    "net_foreign":          3194,     # Net Foreign Buy / Sell
    "net_foreign_ma10":     13539,    # Net Foreign Buy / Sell MA10
    "net_foreign_ma20":     13540,    # Net Foreign Buy / Sell MA20
    "foreign_buy_streak":   13561,    # Net Foreign Buy Streak
    "foreign_sell_streak":  13562,    # Net Foreign Sell Streak
    "foreign_1w":           13591,    # 1 Week Net Foreign Flow
    "foreign_1m":           13580,    # 1 Month Net Foreign Flow
    "foreign_3m":           13581,    # 3 Month Net Foreign Flow
    "foreign_6m":           13582,    # 6 Month Net Foreign Flow
    "foreign_1y":           13583,    # 1 Year Net Foreign Flow
    "foreign_ytd":          13584,    # YTD Net Foreign Flow

    # ── Insider Activity ────────────────────────────────
    "insider_3m_pct":       21365,    # Net Insider Buy / Sell (3M) (%)
    "insider_6m_pct":       21366,    # Net Insider Buy / Sell (6M) (%)
    "insider_1y_pct":       21367,    # Net Insider Buy / Sell (1Y) (%)
    "insider_ytd_pct":      21368,    # Net Insider Buy / Sell (YTD) (%)

    # ── Valuation ───────────────────────────────────────
    "pe_ttm":               2891,     # Current PE Ratio (TTM)
    "pe_annual":            12148,    # Current PE Ratio (Annualised)
    "pe_forward":           16577,    # Forward PE Ratio
    "pbv":                  2896,     # Current Price to Book Value
    "ps_ttm":               2893,     # Current Price to Sales (TTM)
    "peg":                  13431,    # PEG Ratio
    "peg_3yr":              13432,    # PEG Ratio (3yr)
    "peg_forward":          13430,    # PEG (Forward)
    "earnings_yield":       2898,     # Earnings Yield (TTM)
    "ev_ebit":              2897,     # EV to EBIT (TTM)
    "ev_ebitda":            21457,    # EV to EBITDA (TTM)
    "graham_mult":          13434,    # Graham Multiplier
    "magic_formula":        13473,    # Magic Formula (%)
    "fscore":               13366,    # Piotroski F-Score
    "eps_rating":           13382,    # EPS Rating
    "rs_rating":            13387,    # Relative Strength Rating
    "p_ncav":               13409,    # P/NCAV
    "p_nnwc":               13410,    # P/NNWC

    # ── Analyst Consensus ───────────────────────────────
    "target_high":          20283,    # Price Target (High)
    "target_median":        20284,    # Price Target (Median)
    "target_low":           20285,    # Price Target (Low)
    "exp_rev_yoy":          21098,    # Expected Revenue (Growth: YoY)
    "exp_ni_yoy":           21102,    # Expected Net Income (Growth: YoY)
    "exp_eps_yoy":          21104,    # Expected EPS (Growth: YoY)

    # ── Profitability ───────────────────────────────────
    "gpm_q":                1561,     # Gross Profit Margin (Quarter)
    "gpm_ttm":              2290,     # Gross Profit Margin (TTM)(%)
    "opm_q":                1562,     # Operating Profit Margin (Quarter)
    "opm_ttm":              3106,     # Operating Profit Margin (TTM)(%)
    "npm_q":                1563,     # Net Profit Margin (Quarter)
    "npm_ttm":              3107,     # Net Profit Margin (TTM)(%)
    "npm_avg_5y":           13438,    # Average (Net Profit Margin 5yr)

    # ── Management Effectiveness ────────────────────────
    "roa":                  1460,     # Return on Assets (TTM)
    "roe":                  1461,     # Return on Equity (TTM)
    "roce":                 1462,     # Return on Capital Employed (TTM)
    "roic":                 13447,    # Return On Invested Capital (TTM)
    "roe_avg_3y":           13439,    # Average (RoE 3 yr)
    "roe_avg_5y":           13440,    # Average (RoE 5 yr)
    "asset_turnover":       1467,     # Asset Turnover (TTM)
    "roc_greenblatt":       13411,    # ROC Greenblatt

    # ── Revenue Growth ──────────────────────────────────
    "rev_growth_qoq":       2994,     # Revenue (Growth QoQ)
    "rev_growth_yoy":       2992,     # Revenue (Growth: Quarterly YoY)
    "rev_growth_annual":    3206,     # Revenue (Growth: Annual YoY)
    "rev_growth_3y":        2995,     # Revenue (Growth: 3 Year)
    "sales_streak":         13418,    # Sales Growth Streak

    # ── Net Income Growth ───────────────────────────────
    "ni_growth_qoq":        3066,     # Net Income (Growth QoQ)
    "ni_growth_yoy":        3064,     # Net Income (Growth: Quarterly YoY)
    "ni_growth_annual":     3216,     # Net Income (Growth: Annual YoY)
    "ni_growth_3y":         3067,     # Net Income (Growth: 3 Year)
    "ni_streak":            18075,    # Net Income Growth Streak
    "ni_streak_annual":     18076,    # Net Income Growth Streak (Annual)

    # ── EPS Growth ──────────────────────────────────────
    "eps_growth_qoq":       1469,     # EPS (QoQ Growth)
    "eps_growth_yoy":       1470,     # EPS (Quarter YoY Growth)
    "eps_growth_annual":    1471,     # EPS (Annual YoY Growth)
    "eps_growth_3y":        1473,     # EPS (3 Year CAGR)
    "eps_streak":           13417,    # EPS Growth Streak
    "eps_streak_annual":    16475,    # EPS Growth Streak (Annual)
    "eps_forward_growth":   13429,    # EPS Forward Growth

    # ── Solvency ────────────────────────────────────────
    "der":                  1508,     # Debt to Equity Ratio (Quarter)
    "current_ratio":        1498,     # Current Ratio (Quarter)
    "quick_ratio":          1500,     # Quick Ratio (Quarter)
    "altman_z":             13402,    # Altman Z-Score (Modified)
    "icr":                  1484,     # Interest Coverage (TTM)
    "fin_leverage":         1502,     # Financial Leverage (Quarter)
    "debt_assets":          1512,     # Total Debt/Total Assets (Quarter)
    "liab_equity":          1573,     # Total Liabilities/Equity (Quarter)

    # ── Dividend ────────────────────────────────────────
    "div_yield":            2915,     # Dividend Yield
    "payout_ratio":         2916,     # Payout Ratio
    "div_streak":           16474,    # Dividend Payment Streak (Annual)
    "div_avg_3y":           16469,    # Average Dividend Yield (3 Year)
    "div_avg_5y":           16470,    # Average Dividend Yield (5 Year)

    # ── Per Share ───────────────────────────────────────
    "eps_ttm":              13200,    # Current EPS (TTM)
    "bvps":                 15718,    # Current Book Value Per Share
    "cashps":               15630,    # Cash Per Share (Quarter)
    "eps_forward":          16587,    # EPS (Forward)

    # ── Cash Flow ───────────────────────────────────────
    "cfo_ttm":              2545,     # Cash From Operations (TTM)
    "cfi_ttm":              2544,     # Cash From Investing (TTM)
    "cff_ttm":              2543,     # Cash From Financing (TTM)
    "capex_ttm":            2534,     # Capital expenditure (TTM)
    "fcf_ttm":              2538,     # Free cash flow (TTM)
    "fcf_q":                2536,     # Free cash flow (Quarter)
    "pcf_ttm":              16533,    # Current Price To Cashflow (TTM)
    "pfcf_ttm":             15881,    # Current Price To Free Cashflow (TTM)

    # ── Size ────────────────────────────────────────────
    "market_cap":           2892,     # Market Cap
    "enterprise_value":     2895,     # Enterprise Value
    "free_float":           21535,    # Free Float

    # ── Shareholders ────────────────────────────────────
    "shareholders":         21334,    # Number of Shareholders
    "shareholders_chg_1m":  21337,    # (% changes 1M)
    "shareholders_chg_3m":  21338,    # (% changes 3M)
    "shareholders_chg_6m":  21530,    # (% changes 6M)
    "shareholders_chg_1y":  21531,    # (% changes 1Y)

    # ── Rankings ────────────────────────────────────────
    "rank_rs3m":            13403,    # Rank (RS 3m)
    "rank_rs6m":            13404,    # Rank (RS 6m)
    "rank_rs1y":            13406,    # Rank (RS 1yr)
    "rank_magic":           13474,    # Rank (Magic Formula)(%)
    "rank_roe":             15275,    # Rank ROE
    "rank_roic":            15276,    # Rank ROIC
    "rank_mcap":            13423,    # Rank (Market Cap)
    "rank_pe":              13426,    # Rank (Current PE Ratio TTM)
    "rank_near52w":         13422,    # Rank (Near 52 Weeks High)

    # ── Beta / Volatility ───────────────────────────────
    "beta_3y":              16495,    # Beta (3 Year)
    "stdev_3y":             16490,    # Standard Deviation (3 Year)

    # ── ATH/ATL ─────────────────────────────────────────
    "ath":                  16546,    # All Time High (Year 2000)
    "atl":                  16547,    # All Time Low (Year 2000)

    # ── Social ──────────────────────────────────────────
    "followers":            16467,    # Followers
    "popularity":           16487,    # Popularity
}

# ─────────────────────────────────────────────────────────
# METRIC DISPLAY NAMES — Official ScopeBit Labels
# For human-readable formula display & cross-checking
# ─────────────────────────────────────────────────────────

METRIC_DISPLAY_NAMES = {
    METRIC["price"]: "Price",
    METRIC["value"]: "Value",
    METRIC["volume"]: "Volume",
    METRIC["prev_volume"]: "Previous Volume",
    METRIC["prev_price"]: "Previous Price",
    METRIC["ret_1d_pct"]: "1D Returns (%)",
    METRIC["ret_1m"]: "1M Returns (%)",
    METRIC["ret_3m"]: "3M Returns (%)",
    METRIC["ret_6m"]: "6M Returns (%)",
    METRIC["market_cap"]: "Market Cap",
    METRIC["ma20"]: "Price MA 20",
    METRIC["ma50"]: "Price MA 50",
    METRIC["ma200"]: "Price MA 200",
    METRIC["vma20"]: "Volume MA 20",
    METRIC["near_52w_high"]: "Near 52W High",
    METRIC["bandar_value"]: "Bandar Value",
    METRIC["bandar_accum"]: "Bandar Accum/Dist",
    METRIC["net_foreign"]: "Net Foreign Buy/Sell",
    METRIC["foreign_buy_streak"]: "Foreign Buy Streak",
    METRIC["foreign_1w"]: "1W Net Foreign Flow",
    METRIC["foreign_1m"]: "1M Net Foreign Flow",
    METRIC["freq_analyzer"]: "Frequency Analyzer",
    METRIC["freq_spike"]: "Frequency Spike",
    METRIC["fscore"]: "Piotroski F-Score",
    METRIC["pe_ttm"]: "PE Ratio (TTM)",
    METRIC["pbv"]: "Price to Book Value",
    METRIC["roe"]: "Return on Equity (TTM)",
    METRIC["der"]: "Debt to Equity Ratio",
    METRIC["current_ratio"]: "Current Ratio",
    METRIC["altman_z"]: "Altman Z-Score",
    METRIC["npm_ttm"]: "Net Profit Margin (TTM) %",
    METRIC["npm_q"]: "Net Profit Margin (Quarter) %",
    METRIC["ni_growth_yoy"]: "Net Income Growth (Quarterly YoY) %",
    METRIC["ni_growth_qoq"]: "Net Income Growth (QoQ) %",
    METRIC["eps_growth_yoy"]: "EPS Growth (Quarterly YoY) %",
    METRIC["rev_growth_yoy"]: "Revenue Growth (Quarterly YoY) %",
    METRIC["ni_streak"]: "NI Growth Streak",
    METRIC["eps_streak"]: "EPS Growth Streak",
    METRIC["insider_3m_pct"]: "Net Insider Buy/Sell (3M) %",
    METRIC["insider_6m_pct"]: "Net Insider Buy/Sell (6M) %",
    METRIC["insider_1y_pct"]: "Net Insider Buy/Sell (1Y) %",
    METRIC["div_yield"]: "Dividend Yield",
    METRIC["payout_ratio"]: "Payout Ratio",
    METRIC["div_streak"]: "Dividend Streak",
    METRIC["rs_3m"]: "Relative Strength 3M",
    METRIC["rs_6m"]: "Relative Strength 6M",
    METRIC["free_float"]: "Free Float",
}


# ─────────────────────────────────────────────────────────
# INFINITY STONES — 7 Screening Passes
# ─────────────────────────────────────────────────────────

def _bf(item_id, operator, value):
    """Basic filter: item vs constant value."""
    return {
        "item1": int(item_id), "item1_name": "", "item2": str(value),
        "item2_name": "", "multiplier": "0", "operator": operator, "type": "basic"
    }

def _cf(item1_id, operator, item2_id):
    """Compare filter: item vs another item."""
    return {
        "item1": int(item1_id), "item1_name": "", "item2": str(int(item2_id)),
        "item2_name": "", "multiplier": "0", "operator": operator, "type": "compare"
    }

JARVIS_STONES = {
    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 1: PRE-MARKET                            ║
    # ║  Foreign accumulation overnight + fundamentally  ║
    # ║  sound. Catches stocks being quietly accumulated ║
    # ║  by foreign institutions before market open.     ║
    # ╚══════════════════════════════════════════════════╝
    "pre_market": {
        "name": "Pre-Market Scanner",
        "time": "08:55",
        "description": "Foreign accumulation + fundamental quality",
        "filters": [
            _bf(METRIC["foreign_1w"], ">", 0),                   # Foreign buy last week
            _bf(METRIC["market_cap"], ">", 5_000_000_000),     # Liquid enough
            _bf(METRIC["fscore"], ">=", 4),                       # F-Score >= 4
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"], METRIC["bandar_value"],
            METRIC["net_foreign"], METRIC["foreign_1w"], METRIC["foreign_1m"],
            METRIC["fscore"], METRIC["value"], METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 2: MONEY (BPJS / Day Trading)            ║
    # ║  Ride morning momentum: Foreign + Bandar Buy,    ║
    # ║  high liquidity, active freq for scalping.       ║
    # ╚══════════════════════════════════════════════════╝
    "money": {
        "name": "Money Stone",
        "time": "09:30",
        "description": "BPJS (Beli Pagi Jual Sore) — Asing & Bandar akumulasi serentak",
        "filters": [
            _bf(METRIC["net_foreign"], ">", 0),                  # Asing Net Buy
            _bf(METRIC["bandar_value"], ">", 0),                 # Bandar positif (akumulasi)
            _bf(METRIC["value"], ">", 2_000_000_000),            # Value > 2 Miliar
            _bf(METRIC["freq_analyzer"], ">", 0),                # Freq Analyzer untuk copet pagi
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"],
            METRIC["net_foreign"], METRIC["bandar_value"],
            METRIC["value"], METRIC["freq_analyzer"], METRIC["freq_spike"],
            METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 3: MOMENTUM (Breakout)                   ║
    # ║  Intraday breakout: price > prev close, volume   ║
    # ║  surge vs yesterday, at least +1% green.         ║
    # ╚══════════════════════════════════════════════════╝
    "momentum": {
        "name": "Momentum Stone",
        "time": "10:30",
        "description": "Breakout Momentum — Tembus resistensi harga & volume",
        "filters": [
            _cf(METRIC["price"], ">", METRIC["prev_price"]),     # Harga tembus penutupan kemaren
            _cf(METRIC["volume"], ">", METRIC["prev_volume"]),   # Volume surge vs kemaren
            _bf(METRIC["ret_1d_pct"], ">=", 1),                  # Kenaikan minimal +1%
            _bf(METRIC["value"], ">", 2_000_000_000),            # Value > 2 Miliar
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"],
            METRIC["volume"], METRIC["prev_volume"],
            METRIC["value"], METRIC["bandar_value"],
            METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 4: VALUE (Serok Bawah / Reversal)        ║
    # ║  High fundamental quality at a brutal discount,  ║
    # ║  confirmed by INSIDER buying.                   ║
    # ╚══════════════════════════════════════════════════╝
    "value": {
        "name": "Value Stone",
        "time": "11:30",
        "description": "Bullish Reversal (Serok Bawah) — Diskon fundamental + Insider Buy",
        "filters": [
            _bf(METRIC["fscore"], ">=", 5),                      # F-Score >= 5 (Sangat Sehat)
            _bf(METRIC["pe_ttm"], "<", 20),                      # PE < 20
            _bf(METRIC["pbv"], "<", 3),                          # PBV < 3
            _bf(METRIC["insider_3m_pct"], ">", 0),               # Cheat code: Insider serok
            _bf(METRIC["net_foreign"], ">", 0),                  # Timing: Asing mulai masuk hari ini
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"],
            METRIC["fscore"], METRIC["pe_ttm"], METRIC["pbv"],
            METRIC["roe"], METRIC["der"], METRIC["insider_3m_pct"],
            METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 5: QUALITY                               ║
    # ║  Growth compounders: NI growing, good margins,   ║
    # ║  high ROE.                                       ║
    # ╚══════════════════════════════════════════════════╝
    "quality": {
        "name": "Quality Stone",
        "time": "12:30",
        "description": "Consistent growth, strong profitability, uptrend MA50",
        "filters": [
            _bf(METRIC["ni_growth_yoy"], ">", 5),               # NI YoY > 5%
            _bf(METRIC["npm_ttm"], ">", 5),                     # NPM > 5%
            _bf(METRIC["roe"], ">", 8),                          # ROE > 8%
            _bf(METRIC["value"], ">", 500_000_000),              # Value > 500M
            _cf(METRIC["price"], ">", METRIC["ma50"]),           # Timing: Di atas MA50 (Bulls in control)
            _bf(METRIC["bandar_value"], ">", 0),                 # Timing: Diakumulasi
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"], METRIC["ni_growth_yoy"],
            METRIC["eps_growth_yoy"], METRIC["rev_growth_yoy"],
            METRIC["npm_ttm"], METRIC["roe"],
            METRIC["ni_streak"], METRIC["eps_streak"], METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 6: INSIDER                               ║
    # ║  Insider buying — uses VERIFIED IDs (21365-68).  ║
    # ║  Rare but high-conviction signal.                ║
    # ╚══════════════════════════════════════════════════╝
    "insider": {
        "name": "Insider Stone",
        "time": "13:30",
        "description": "Insider buying + smart money accumulation",
        "filters": [
            _bf(METRIC["insider_3m_pct"], ">", 0),              # Insider net buy 3M
            _bf(METRIC["pe_ttm"], "<", 25),                     # Not overvalued
            _bf(METRIC["value"], ">", 500_000_000),             # Value > 500M
            _bf(METRIC["net_foreign"], ">", 0),                 # Timing: Asing ikutan masuk
            _bf(METRIC["ret_1d_pct"], ">", 0),                  # Timing: Hari ini hijau
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"], METRIC["insider_3m_pct"],
            METRIC["insider_6m_pct"], METRIC["insider_1y_pct"],
            METRIC["bandar_value"], METRIC["net_foreign"],
            METRIC["pe_ttm"], METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 7: CLOSING (BSJP)                        ║
    # ║  End-of-day markup: price > MA20, green,         ║
    # ║  bandar positive. Confirms intraday strength.    ║
    # ╚══════════════════════════════════════════════════╝
    "closing": {
        "name": "Closing Stone",
        "time": "14:30",
        "description": "BSJP (Beli Sore Jual Pagi) — Harga > MA20 & Bandar positif",
        "filters": [
            _cf(METRIC["price"], ">", METRIC["ma20"]),
            _bf(METRIC["ret_1d_pct"], ">", 0),
            _bf(METRIC["bandar_value"], ">", 0),
            _bf(METRIC["value"], ">", 2_000_000_000),
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"], METRIC["ma20"],
            METRIC["bandar_value"], METRIC["value"], METRIC["volume"],
            METRIC["near_52w_high"], METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 8: LIQUID — Liquidity Guard              ║
    # ║  Only highly tradable stocks. Ensures safe       ║
    # ║  entry/exit with tight spread & high frequency.  ║
    # ╚══════════════════════════════════════════════════╝
    "liquid": {
        "name": "Liquid Stone",
        "time": "09:10",
        "description": "Likuiditas tinggi — Value >5B, Volume surge, Free float lebar",
        "filters": [
            _bf(METRIC["value"], ">", 5_000_000_000),
            _cf(METRIC["volume"], ">", METRIC["vma20"]),
            _bf(METRIC["market_cap"], ">", 1_000_000_000_000),
            _bf(METRIC["freq_analyzer"], ">", 0),
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"], METRIC["value"],
            METRIC["volume"], METRIC["freq_analyzer"], METRIC["freq_spike"],
            METRIC["bandar_value"], METRIC["net_foreign"],
            METRIC["market_cap"], METRIC["free_float"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 9: SMART MONEY — Confluence Signal       ║
    # ║  Foreign + Bandar BUY simultaneously for 3+     ║
    # ║  days. Triple confirmation of smart money flow.  ║
    # ╚══════════════════════════════════════════════════╝
    "smart_money": {
        "name": "Smart Money Stone",
        "time": "10:00",
        "description": "Asing + Bandar akumulasi bersamaan >= 3 hari berturut-turut",
        "filters": [
            _bf(METRIC["net_foreign"], ">", 0),
            _bf(METRIC["bandar_value"], ">", 0),
            _bf(METRIC["foreign_buy_streak"], ">=", 3),
            _bf(METRIC["value"], ">", 2_000_000_000),
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"],
            METRIC["net_foreign"], METRIC["bandar_value"], METRIC["bandar_accum"],
            METRIC["foreign_buy_streak"], METRIC["foreign_1w"], METRIC["foreign_1m"],
            METRIC["value"], METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 10: DANGER — Red Flag / Bearish Alert    ║
    # ║  Stocks to AVOID: distressed balance sheet,     ║
    # ║  losing money, foreign dumping.                  ║
    # ╚══════════════════════════════════════════════════╝
    "danger": {
        "name": "Danger Stone",
        "time": "11:00",
        "description": "RED FLAG — Saham bermasalah, hutang tinggi, rugi, asing jual",
        "filters": [
            _bf(METRIC["altman_z"], "<", 2),
            _bf(METRIC["der"], ">", 2),
            _bf(METRIC["npm_ttm"], "<", 0),
            _bf(METRIC["ret_1m"], "<", -10),
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"], METRIC["altman_z"],
            METRIC["der"], METRIC["current_ratio"], METRIC["npm_ttm"],
            METRIC["ni_growth_yoy"], METRIC["net_foreign"],
            METRIC["ret_1m"], METRIC["ret_3m"], METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 11: DIVIDEND — Income Play               ║
    # ║  High-yield dividend stocks with sustainable     ║
    # ║  payout, low debt, and good profitability.       ║
    # ╚══════════════════════════════════════════════════╝
    "dividend": {
        "name": "Dividend Stone",
        "time": "12:00",
        "description": "Dividen tinggi >3%, payout stabil, utang rendah, MA20 uptrend",
        "filters": [
            _bf(METRIC["div_yield"], ">", 3),
            _bf(METRIC["payout_ratio"], ">", 20),
            _bf(METRIC["payout_ratio"], "<", 100),
            _bf(METRIC["der"], "<", 2),
            _bf(METRIC["npm_ttm"], ">", 5),
            _cf(METRIC["price"], ">", METRIC["ma20"]),          # Timing: Harga uptrend jangka pendek
            _bf(METRIC["bandar_value"], ">", 0),                # Timing: Ada akumulasi saat ini
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"], METRIC["div_yield"],
            METRIC["payout_ratio"], METRIC["div_streak"],
            METRIC["pe_ttm"], METRIC["roe"], METRIC["npm_ttm"],
            METRIC["der"], METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 12: BAGGER — Multi-Bagger Candidate      ║
    # ║  High growth + cheap valuation + insider buy     ║
    # ║  = potential 2x-10x return.                      ║
    # ╚══════════════════════════════════════════════════╝
    "bagger": {
        "name": "Bagger Stone",
        "time": "13:00",
        "description": "Calon Multi-Bagger — Growth >20%, ROE >15%, PE <15, mulai diakumulasi",
        "filters": [
            _bf(METRIC["ni_growth_yoy"], ">", 20),
            _bf(METRIC["rev_growth_yoy"], ">", 15),
            _bf(METRIC["roe"], ">", 15),
            _bf(METRIC["pe_ttm"], "<", 15),
            _bf(METRIC["market_cap"], "<", 10_000_000_000_000),
            _bf(METRIC["foreign_buy_streak"], ">=", 1),         # Timing: Asing mulai lirik
            _bf(METRIC["bandar_value"], ">", 0),                # Timing: Bandar akumulasi
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"],
            METRIC["ni_growth_yoy"], METRIC["rev_growth_yoy"], METRIC["eps_growth_yoy"],
            METRIC["roe"], METRIC["pe_ttm"], METRIC["pbv"],
            METRIC["ni_streak"], METRIC["insider_3m_pct"], METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 13: TURNAROUND — Recovery Play           ║
    # ║  Stocks rebounding from poor performance:       ║
    # ║  NI surging, price still cheap, fundamentals    ║
    # ║  improving rapidly.                              ║
    # ╚══════════════════════════════════════════════════╝
    "turnaround": {
        "name": "Turnaround Stone",
        "time": "14:00",
        "description": "Recovery — Laba membaik signifikan, RS menguat, volume surge",
        "filters": [
            _bf(METRIC["ni_growth_yoy"], ">", 25),
            _bf(METRIC["ret_3m"], "<", 0),
            _bf(METRIC["pbv"], "<", 2),
            _bf(METRIC["fscore"], ">=", 5),
            _cf(METRIC["volume"], ">", METRIC["vma20"]),        # Timing: Ledakan volume
            _bf(METRIC["ret_1d_pct"], ">", 0),                  # Timing: Hari ini hijau
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"],
            METRIC["ni_growth_yoy"], METRIC["ni_growth_qoq"], METRIC["npm_q"],
            METRIC["npm_ttm"], METRIC["fscore"], METRIC["pbv"],
            METRIC["ret_3m"], METRIC["ret_6m"], METRIC["market_cap"],
        ],
    },

    # ╔══════════════════════════════════════════════════╗
    # ║  STONE 14: TECHNICAL — Golden Cross & Trend     ║
    # ║  MA20 crosses above MA50, price above both,     ║
    # ║  strong relative strength, near 52-week high.   ║
    # ╚══════════════════════════════════════════════════╝
    "technical": {
        "name": "Technical Stone",
        "time": "15:00",
        "description": "Golden Cross — MA20 > MA50, harga uptrend, RS kuat",
        "filters": [
            _cf(METRIC["price"], ">", METRIC["ma50"]),
            _cf(METRIC["ma20"], ">", METRIC["ma50"]),
            _bf(METRIC["ret_1d_pct"], ">", 0),
            _bf(METRIC["value"], ">", 1_000_000_000),
            _bf(METRIC["near_52w_high"], ">", -20),
        ],
        "sequence": [
            METRIC["price"], METRIC["ret_1d_pct"],
            METRIC["ma20"], METRIC["ma50"], METRIC["ma200"],
            METRIC["near_52w_high"], METRIC["rs_3m"], METRIC["rs_6m"],
            METRIC["volume"], METRIC["value"], METRIC["market_cap"],
        ],
    },
}

# Stone short codes for display
STONE_CODES = {
    "pre_market": "P",
    "money": "M",
    "momentum": "Mo",
    "value": "V",
    "quality": "Q",
    "insider": "I",
    "closing": "C",
    "liquid": "L",
    "smart_money": "SM",
    "danger": "D",
    "dividend": "Dv",
    "bagger": "B",
    "turnaround": "T",
    "technical": "Te",
}

STONE_ORDER = [
    "pre_market", "money", "momentum", "value", "quality", "insider", "closing",
    "liquid", "smart_money", "danger", "dividend", "bagger", "turnaround", "technical",
]

PRIMARY_METRIC_NAMES = {
    METRIC["bandar_value"]: "B.Val",
    METRIC["volume"]: "Vol",
    METRIC["pe_ttm"]: "PE",
    METRIC["insider_3m_pct"]: "Ins.3M",
    METRIC["foreign_1w"]: "F.1W",
    METRIC["fscore"]: "F-Score",
    METRIC["value"]: "Val",
    METRIC["eps_growth_yoy"]: "EPS.YoY",
    METRIC["ni_growth_yoy"]: "NI.YoY",
    METRIC["altman_z"]: "AltZ",
    METRIC["div_yield"]: "Div.Y",
    METRIC["rs_3m"]: "RS.3M",
    METRIC["foreign_buy_streak"]: "F.BY.S",
    METRIC["der"]: "DER",
    METRIC["ret_3m"]: "Ret.3M",
}


# ─────────────────────────────────────────────────────────
# TRACKER PERSISTENCE
# ─────────────────────────────────────────────────────────

TRACKER_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "jarvis_tracker.json")


def _load_tracker() -> dict:
    """Load tracker from disk. Returns empty structure if not found."""
    try:
        if os.path.exists(TRACKER_PATH):
            with open(TRACKER_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.error(f"JARVIS: Failed to load tracker: {e}")
    return {"stocks": {}, "daily_stone_results": {}}


def _save_tracker(data: dict):
    """Save tracker to disk."""
    try:
        os.makedirs(os.path.dirname(TRACKER_PATH), exist_ok=True)
        with open(TRACKER_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error(f"JARVIS: Failed to save tracker: {e}")


# ─────────────────────────────────────────────────────────
# STONE EXECUTION
# ─────────────────────────────────────────────────────────

def _parse_display(raw) -> float:
    """Robustly parse a display value from ScopeBit API.
    API can return int, float, str with commas, or None."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).replace(",", "").replace("%", "").strip()
    if not s or s == "-":
        return 0.0
        
    multiplier = 1.0
    s_upper = s.upper()
    if s_upper.endswith("T"):
        multiplier = 1_000_000_000_000.0
        s = s_upper[:-1].strip()
    elif s_upper.endswith("B"):
        multiplier = 1_000_000_000.0
        s = s_upper[:-1].strip()
    elif s_upper.endswith("M"):
        multiplier = 1_000_000.0
        s = s_upper[:-1].strip()
    elif s_upper.endswith("K"):
        multiplier = 1_000.0
        s = s_upper[:-1].strip()
        
    try:
        return float(s) * multiplier
    except (ValueError, TypeError):
        return 0.0


async def run_stone(stone_name: str) -> list[dict]:
    """
    Execute a single stone's screener and return list of stock dicts.
    Fetches multiple pages (up to MAX_PAGES) to capture all results.
    Each dict has: symbol, price, change_pct.
    """
    MAX_PAGES = 4  # Up to 100 stocks per stone

    if stone_name not in JARVIS_STONES:
        log.error(f"JARVIS: Unknown stone '{stone_name}'")
        return []

    stone = JARVIS_STONES[stone_name]
    log.info(f"JARVIS: Running {stone['name']} ({stone_name})...")

    try:
        all_symbols = []
        seen_codes = set()

        req_seq = list(stone.get("sequence", []))
        if METRIC["price"] not in req_seq: req_seq.append(METRIC["price"])
        if METRIC["ret_1d_pct"] not in req_seq: req_seq.append(METRIC["ret_1d_pct"])

        for page in range(1, MAX_PAGES + 1):
            result = await run_screener(
                filters=stone.get("filters", []),
                sequence=req_seq,
                ordercol=METRIC["value"],
                ordertype="desc",
                page=page,
            )

            calcs = result.get("calcs", [])
            if not calcs:
                break  # No more results

            primary_id = stone.get("sequence", [])[2] if len(stone.get("sequence", [])) > 2 else 0
            primary_name = PRIMARY_METRIC_NAMES.get(primary_id, "")

            for calc in calcs:
                company = calc.get("company", {})
                code = company.get("symbol", "")
                if not code or len(code) != 4 or code in seen_codes:
                    continue
                seen_codes.add(code)

                # Extract price and change from results array
                price = 0.0
                change_pct = 0.0
                primary_val = 0.0
                raw_metrics = {}
                
                results = calc.get("results", [])
                for r in results:
                    rid = r.get("id", 0)
                    raw_display = r.get("display")
                    raw_value = r.get("value")
                    parsed = _parse_display(raw_display)
                    if parsed == 0 and raw_value is not None:
                        parsed = _parse_display(raw_value)
                        
                    raw_metrics[rid] = parsed

                    if rid == METRIC["price"]:
                        price = parsed
                    elif rid == METRIC["ret_1d_pct"]:
                        change_pct = parsed
                        
                    if rid == primary_id:
                        primary_val = parsed

                # Fallback: try company.lastPrice if price still 0
                if price == 0:
                    last_price = company.get("lastPrice") or company.get("last_price") or company.get("price")
                    if last_price is not None:
                        price = _parse_display(last_price)

                all_symbols.append({
                    "symbol": code,
                    "price": price,
                    "change_pct": change_pct,
                    "primary_val": primary_val,
                    "primary_name": primary_name,
                    "raw_metrics": raw_metrics
                })

            # If this page had fewer than 25, no more pages
            if len(calcs) < 25:
                break

            # Small delay between page requests to be polite
            await asyncio.sleep(0.5)

        symbols = all_symbols

        # ── Diagnostic: metric coverage analysis ──
        seq_ids = stone.get("sequence", [])
        diag = {}  # metric_id -> {"name": str, "has_data": int, "zero": int}
        for rid in seq_ids:
            rev_name = {v: k for k, v in METRIC.items()}.get(rid, str(rid))
            diag[rid] = {"name": rev_name, "has_data": 0, "zero": 0}

        for s in symbols:
            rm = s.get("raw_metrics", {})
            for rid in seq_ids:
                if rid in rm and rm[rid] != 0:
                    diag[rid]["has_data"] += 1
                else:
                    diag[rid]["zero"] += 1

        total = len(symbols)
        missing_metrics = []
        for rid, info in diag.items():
            pct = (info["has_data"] / max(total, 1)) * 100
            if info["has_data"] == 0 and total > 0:
                missing_metrics.append(info["name"])
                log.warning(f"JARVIS DIAG [{stone_name}]: metric '{info['name']}' (ID:{rid}) returned ZERO data for ALL {total} stocks")
            elif pct < 50:
                log.warning(f"JARVIS DIAG [{stone_name}]: metric '{info['name']}' (ID:{rid}) only {info['has_data']}/{total} stocks have data ({pct:.0f}%)")

        if missing_metrics:
            log.warning(f"JARVIS DIAG [{stone_name}]: MISSING METRICS: {missing_metrics}")

        # Attach diagnostics to the result for report generation
        for s in symbols:
            s["_diagnostics"] = diag

        log.info(f"JARVIS: {stone['name']} found {len(symbols)} stocks: {[s['symbol'] for s in symbols[:10]]}")
        return symbols

    except Exception as e:
        log.error(f"JARVIS: Error running {stone_name}: {e}")
        import traceback
        log.error(f"JARVIS: Traceback: {traceback.format_exc()}")
        return []


def save_stone_result(stone_name: str, stocks: list[dict]):
    """
    Persist stone results to tracker.
    - Updates daily_stone_results for today
    - Updates each stock's history and streak
    """
    tz = pytz.timezone("Asia/Jakarta")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    now_str = datetime.now(tz).strftime("%H:%M")

    tracker = _load_tracker()

    # Ensure daily structure
    if today not in tracker.get("daily_stone_results", {}):
        tracker.setdefault("daily_stone_results", {})[today] = {}

    # Save this stone's results for today
    symbol_list = [s["symbol"] for s in stocks]
    tracker["daily_stone_results"][today][stone_name] = {
        "symbols": symbol_list,
        "run_at": now_str,
        "count": len(symbol_list),
    }

    # Update each stock's profile
    for s in stocks:
        sym = s["symbol"]
        if sym not in tracker["stocks"]:
            tracker["stocks"][sym] = {
                "first_seen": today,
                "last_seen": today,
                "total_appearances": 0,
                "current_streak": 0,
                "max_streak": 0,
                "daily_log": {},
            }

        stock = tracker["stocks"][sym]
        stock["last_seen"] = today

        # Initialize today's log if needed
        if today not in stock["daily_log"]:
            stock["daily_log"][today] = {
                "stones": [],
                "price": s.get("price", 0.0),
                "change_pct": s.get("change_pct", 0.0),
            }

        # Add stone to today's list (deduplicate)
        if stone_name not in stock["daily_log"][today]["stones"]:
            stock["daily_log"][today]["stones"].append(stone_name)
            stock["total_appearances"] = stock.get("total_appearances", 0) + 1

        # Update price (latest stone wins)
        if s.get("price", 0.0) > 0:
            stock["daily_log"][today]["price"] = s.get("price", 0.0)
            stock["daily_log"][today]["change_pct"] = s.get("change_pct", 0.0)

    _save_tracker(tracker)
    return len(symbol_list)


def _update_streaks():
    """
    Recalculate streaks for all stocks based on daily_log.
    A streak is the number of consecutive recent trading days the stock appeared in ANY stone.
    Safeguarded against dropping to 0 on Weekends or early intaday before scans complete.
    """
    tz = pytz.timezone("Asia/Jakarta")
    today = datetime.now(tz).date()
    tracker = _load_tracker()

    for sym, data in tracker["stocks"].items():
        daily_log = data.get("daily_log", {})
        
        # Determine the latest trading day vs previous
        latest_t_day = today
        while latest_t_day.weekday() >= 5:
            latest_t_day -= timedelta(days=1)
            
        prev_t_day = latest_t_day - timedelta(days=1)
        while prev_t_day.weekday() >= 5:
            prev_t_day -= timedelta(days=1)

        latest_str = latest_t_day.strftime("%Y-%m-%d")
        prev_str = prev_t_day.strftime("%Y-%m-%d")
        
        has_latest = latest_str in daily_log and len(daily_log[latest_str].get("stones", [])) > 0
        has_prev = prev_str in daily_log and len(daily_log[prev_str].get("stones", [])) > 0

        # Start from yesterday if today hasn't triggered yet (to prevent 0 mid-day drops)
        if not has_latest and has_prev:
            start_date = prev_t_day
        else:
            start_date = latest_t_day

        streak = 0
        check_date = start_date

        for _ in range(365):
            date_str = check_date.strftime("%Y-%m-%d")
            if date_str in daily_log and len(daily_log[date_str].get("stones", [])) > 0:
                streak += 1
                check_date -= timedelta(days=1)
                while check_date.weekday() >= 5:
                    check_date -= timedelta(days=1)
            else:
                break

        data["current_streak"] = streak
        data["max_streak"] = max(data.get("max_streak", 0), streak)

    _save_tracker(tracker)


def _prune_tracker():
    """
    Remove stocks that haven't appeared in any stone for the last 30 days.
    This prevents the tracker JSON from growing infinitely.
    Also cleans up daily_stone_results older than 7 days.
    """
    tz = pytz.timezone("Asia/Jakarta")
    today_date = datetime.now(tz).date()
    tracker = _load_tracker()
    
    # 1. Prune old stocks (> 30 days inactive)
    to_delete = []
    for sym, data in tracker.get("stocks", {}).items():
        last_seen_str = data.get("last_seen", "")
        if not last_seen_str:
            to_delete.append(sym)
            continue
            
        try:
            last_seen_date = datetime.strptime(last_seen_str, "%Y-%m-%d").date()
            days_inactive = (today_date - last_seen_date).days
            if days_inactive > 30:
                to_delete.append(sym)
        except ValueError:
            pass

    for sym in to_delete:
        del tracker["stocks"][sym]
    if to_delete:
        log.info(f"JARVIS: Pruned {len(to_delete)} inactive stocks from tracker.")

    # 2. Prune old daily_stone_results (> 7 days)
    to_delete_days = []
    for date_str in tracker.get("daily_stone_results", {}).keys():
        try:
            record_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if (today_date - record_date).days > 7:
                to_delete_days.append(date_str)
        except ValueError:
            pass
            
    for d in to_delete_days:
        del tracker["daily_stone_results"][d]

    # 3. Deep Prune: Remove old daily_log entries from active stocks (> 45 days)
    logs_pruned = 0
    for sym, data in tracker.get("stocks", {}).items():
        daily_log = data.get("daily_log", {})
        old_log_dates = []
        for log_date_str in daily_log.keys():
            try:
                ld = datetime.strptime(log_date_str, "%Y-%m-%d").date()
                if (today_date - ld).days > 45:
                    old_log_dates.append(log_date_str)
            except ValueError:
                pass
        for old_d in old_log_dates:
            del daily_log[old_d]
            logs_pruned += 1

    if logs_pruned > 0:
        log.info(f"JARVIS: Pruned {logs_pruned} old daily_log entries.")

    # Save only if modified
    if to_delete or to_delete_days or logs_pruned > 0:
        _save_tracker(tracker)


# ─────────────────────────────────────────────────────────
# CONVICTION CALCULATOR
# ─────────────────────────────────────────────────────────

def calc_conviction(stock_data: dict) -> float:
    """
    Calculate conviction score (0-100) for a stock.
    Based on:
    - stones_today: how many stones passed today (weight: 15 per stone)
    - streak: consecutive days appearing (weight: 12 per day, capped at 30)
    - consistency_30d: % of last 30 trading days appeared
    - rising: score increase vs yesterday
    """
    tz = pytz.timezone("Asia/Jakarta")
    today = datetime.now(tz).strftime("%Y-%m-%d")

    daily_log = stock_data.get("daily_log", {})
    streak = stock_data.get("current_streak", 0)

    # Stones today
    today_entry = daily_log.get(today, {})
    stones_today = len(today_entry.get("stones", []))

    # Consistency: count days with appearances in last 30 calendar days
    today_date = datetime.now(tz).date()
    days_with_appearance = 0
    trading_days_checked = 0
    check = today_date

    for _ in range(45):  # ~30 trading days in 45 calendar days
        if check.weekday() < 5:  # Weekday
            trading_days_checked += 1
            ds = check.strftime("%Y-%m-%d")
            if ds in daily_log and len(daily_log[ds].get("stones", [])) > 0:
                days_with_appearance += 1
            if trading_days_checked >= 30:
                break
        check -= timedelta(days=1)

    consistency = (days_with_appearance / max(trading_days_checked, 1)) * 100

    # Rising delta: stones today vs yesterday
    yesterday = today_date - timedelta(days=1)
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    yesterday_entry = daily_log.get(yesterday_str, {})
    stones_yesterday = len(yesterday_entry.get("stones", []))
    rising = max(0, stones_today - stones_yesterday)

    # Conviction formula (rebalanced for 100-point scale)
    # Stones: 45% | Streak: 25% | Consistency: 15% | Momentum/Rising: 15%
    raw = (
        (stones_today / 14.0) * 45
        + (min(streak, 15) / 15.0) * 25
        + (consistency / 100.0) * 15
        + (min(rising, 5) / 5.0) * 15
    )

    return round(min(100.0, raw), 1)


def classify_stock(conviction: float, stock_data: dict) -> str:
    """Classify stock based on conviction and trajectory."""
    tz = pytz.timezone("Asia/Jakarta")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    daily_log = stock_data.get("daily_log", {})

    today_stones = len(daily_log.get(today, {}).get("stones", []))
    streak = stock_data.get("current_streak", 0)

    # Check if streak just broke (was active yesterday but not today)
    yesterday = (datetime.now(tz).date() - timedelta(days=1))
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    was_active_yesterday = len(daily_log.get(yesterday_str, {}).get("stones", [])) > 0

    if today_stones == 0 and was_active_yesterday:
        prev_streak = 0
        # Calculate what the streak was before it broke
        check = yesterday
        for _ in range(365):
            ds = check.strftime("%Y-%m-%d")
            if ds in daily_log and len(daily_log[ds].get("stones", [])) > 0:
                prev_streak += 1
                check -= timedelta(days=1)
                while check.weekday() >= 5:
                    check -= timedelta(days=1)
            else:
                break
        if prev_streak >= 3:
            return "FADING"

    # Check if it's brand new (first seen today or yesterday)
    first_seen = stock_data.get("first_seen", today)
    try:
        first_date = datetime.strptime(first_seen, "%Y-%m-%d").date()
        days_known = (datetime.now(tz).date() - first_date).days
    except:
        days_known = 999

    if days_known <= 2 and today_stones >= 2:
        if conviction >= 65:
            return "HOT"
        elif conviction >= 40:
            return "WARM"
        return "RISING"

    # Score-based classification
    if conviction >= 75:
        return "HOT"
    elif conviction >= 40:
        return "WARM"
    else:
        return "COLD"


# ─────────────────────────────────────────────────────────
# VERDICT GENERATOR
# ─────────────────────────────────────────────────────────

def _fmt_price(val) -> str:
    if not val or val <= 0:
        return "-"
    return f"{int(val):,}".replace(",", ".")


def _generate_glacier_image(stone_name: str, code: str, stocks: list[dict], now_str: str, top_emoji: str):
    if not stocks: return None
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    
    fig, ax = plt.subplots(figsize=(10.24, 7.68), dpi=100)
    fig.patch.set_facecolor('#020617')
    ax.set_facecolor('#020617')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    ax.scatter(0.2, 0.8, s=200000, color='#0ea5e9', alpha=0.15, edgecolors='none', zorder=0)
    ax.scatter(0.8, 0.2, s=250000, color='#2563eb', alpha=0.1, edgecolors='none', zorder=0)

    main_panel = patches.FancyBboxPatch(
        (0.05, 0.05), 0.9, 0.9,
        boxstyle="round,pad=0.03,rounding_size=0.05",
        facecolor='#ffffff', alpha=0.03, edgecolor='#38bdf8', lw=1, zorder=1
    )
    ax.add_patch(main_panel)
    
    glow_panel = patches.FancyBboxPatch(
        (0.05, 0.05), 0.9, 0.9,
        boxstyle="round,pad=0.03,rounding_size=0.05",
        facecolor='none', edgecolor='#38bdf8', lw=10, alpha=0.05, zorder=0
    )
    ax.add_patch(glow_panel)

    ax.text(0.08, 0.88, stone_name.upper(), fontsize=36, weight='bold', color='#7dd3fc', zorder=2, va='center')
    ax.text(0.92, 0.89, "STATUS REPORT", fontsize=12, color='#94a3b8', weight='bold', ha='right', zorder=2)
    ax.text(0.92, 0.85, now_str, fontsize=20, color='#e2e8f0', weight='bold', ha='right', zorder=2)

    ax.plot([0.08, 0.92], [0.78, 0.78], color='#38bdf8', alpha=0.2, lw=1, zorder=2)

    y_start = 0.65
    y_step = 0.13
    
    for i, s in enumerate(stocks[:5]):
        y = y_start - (i * y_step)
        row_bg = patches.FancyBboxPatch(
            (0.08, y-0.05), 0.84, 0.10,
            boxstyle="round,pad=0.01,rounding_size=0.03",
            facecolor='#ffffff', alpha=0.04, edgecolor='none', zorder=2
        )
        ax.add_patch(row_bg)

        idx_ellipse = patches.Ellipse((0.12, y), width=0.04, height=0.0533, facecolor='#020617', edgecolor='#7dd3fc', lw=1.5, alpha=0.9, zorder=3)
        ax.add_patch(idx_ellipse)
        ax.text(0.12, y-0.005, str(i+1), fontsize=20, color='#7dd3fc', weight='bold', ha='center', va='center', zorder=4)

        sym = s.get("symbol", "-")
        price = s.get("price", 0.0)
        chg = s.get("change_pct", 0.0)
        
        ax.text(0.18, y, sym, fontsize=28, color='#f8fafc', weight='bold', va='center', zorder=3)
        
        price_str = _fmt_price(price)
        if price > 0:
            ax.text(0.66, y+0.015, price_str, fontsize=20, color='#cbd5e1', weight='bold', ha='right', va='center', zorder=3)
            
            color_chg = '#34d399' if chg > 0 else '#fb7185' if chg < 0 else '#94a3b8'
            sign = "+" if chg > 0 else ""
            ax.text(0.66, y-0.025, f"{sign}{chg:.1f}%", fontsize=15, color=color_chg, weight='bold', ha='right', va='center', zorder=3)

            label_text = "STEADY" if chg > 0 else "PULLBACK" if chg < 0 else "NEUTRAL"
            pill_bg = '#10b981' if chg > 0 else '#f43f5e' if chg < 0 else '#64748b'
            
            ax.text(0.83, y, f" {label_text} ", fontsize=13, color=pill_bg, weight='bold',
                    ha='center', va='center', zorder=3,
                    bbox=dict(facecolor=pill_bg, alpha=0.15, edgecolor=pill_bg, boxstyle='round,pad=0.3', lw=1.5))

    ax.text(0.5, 0.02, "ScopeBit Intelligence Suite • Strictly Auto-Generated Output", fontsize=10, color='#64748b', weight='bold', ha='center', zorder=2)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor='#020617', bbox_inches='tight', pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return buf

def generate_stone_report(stone_name: str, stocks: list[dict]):
    """
    Generate stone report. 
    Returns a tuple: (caption_html_string, bytes_io_image, bytes_io_txt_document)
    """
    import io
    stone = JARVIS_STONES.get(stone_name, {})
    code = STONE_CODES.get(stone_name, "?")
    tz = pytz.timezone("Asia/Jakarta")
    now_str = datetime.now(tz).strftime("%d %b, %H:%M WIB")

    tracker = _load_tracker()

    L = "━" * 38
    
    # Determine appropriate emoji based on Stone code
    top_emoji = "⚡"
    if code == "D":
        top_emoji = "⚠️"
    elif code in ["Mo", "SM", "P", "B", "Te"]:
        top_emoji = "🚀"

    caption_lines = [
        f"<b>{top_emoji} JARVIS [{code}] {stone.get('name', stone_name)}</b>",
        f"<code>{L}</code>",
    ]

    if not stocks:
        caption_lines.append("<code>Tidak ada saham yang lolos filter.</code>")
        caption_lines.append(f"<code>{L}</code>")
        
        # Create an empty txt file to satisfy the tuple return type reliably
        txt_buffer = io.BytesIO()
        txt_buffer.write(b"Tidak ada saham yang memenuhi kriteria screener pada sesi ini.\n")
        txt_buffer.seek(0)
        return "\n".join(caption_lines), None, txt_buffer

    # Save to tracker before generating report
    save_stone_result(stone_name, stocks)

    caption_lines.append(f"<code>Lolos: {len(stocks)} saham | {now_str}</code>")
    
    # Build human-readable filter descriptions using METRIC_DISPLAY_NAMES
    import html
    filter_texts = []
    for f in stone.get("filters", []):
        try:
            op = f.get("operator", "")
            if f.get("type") == "basic":
                mid = int(f.get("item1"))
                # Use official ScopeBit label, fallback to internal name
                item_label = METRIC_DISPLAY_NAMES.get(mid, "")
                if not item_label:
                    item_label = {v: k for k, v in METRIC.items()}.get(mid, f"ID:{mid}")
                val = f.get("item2")
                # Format value with units
                val_display = str(val)
                if isinstance(val, str) and val.replace("-", "").isdigit():
                    num = int(val)
                    if num >= 1_000_000_000_000:
                        val_display = f"{num/1e12:.1f}T".replace(".0T", "T")
                    elif num >= 1_000_000_000:
                        val_display = f"{num/1e9:.1f}B".replace(".0B", "B")
                    elif num >= 1_000_000:
                        val_display = f"{num/1e6:.0f}M"
                    else:
                        val_display = str(num)
                    # Add % suffix for percentage metrics
                    if "%" in item_label or "Growth" in item_label or "Margin" in item_label or "Return" in item_label or "Yield" in item_label:
                        val_display += "%"
                filter_texts.append(html.escape(f"{item_label} {op} {val_display}"))
            elif f.get("type") == "compare":
                mid1 = int(f.get("item1"))
                mid2 = int(f.get("item2"))
                label1 = METRIC_DISPLAY_NAMES.get(mid1, {v: k for k, v in METRIC.items()}.get(mid1, f"ID:{mid1}"))
                label2 = METRIC_DISPLAY_NAMES.get(mid2, {v: k for k, v in METRIC.items()}.get(mid2, f"ID:{mid2}"))
                filter_texts.append(html.escape(f"{label1} {op} {label2}"))
        except Exception:
            pass

    if filter_texts:
        caption_lines.append(f"<b>📊 Kriteria Metric:</b>")
        caption_lines.append("<code>" + "\n".join([f" • {ft}" for ft in filter_texts]) + "</code>")
        caption_lines.append(f"<code>{L}</code>")

    caption_lines.append(f"<b>{top_emoji} Top 5 Emiten Teratas:</b>")
    caption_lines.append("<code>")
    for i, s in enumerate(stocks[:5]):
        sym = s.get("symbol", "")
        price = s.get("price", 0.0)
        chg = s.get("change_pct", 0.0)
        
        if price > 0:
            sign = "+" if chg > 0 else ""
            caption_lines.append(f" {i+1}. {sym:<4} | {_fmt_price(price):>6} | {sign}{chg:.1f}%")
        else:
            caption_lines.append(f" {i+1}. {sym:<4}")
    caption_lines.append("</code>")
    caption_lines.append(f"<code>{L}</code>")

    caption_lines.append("⚡ <i>Unduh file .txt lengkap di bawah.</i>")
    
    # Generate full TXT report natively based on stone sequence
    seq = stone.get("sequence", [])
    
    # Generate headers
    # We always start with KODE | STREAK
    col_headers = ["KODE", "STREAK"]
    col_widths = [6, 6]
    
    # We will build mapping from seq element to col index, ignoring ID if we can't map it
    # We use PRIMARY_METRIC_NAMES for a short readable name. If none, we use generic ID.
    dynamic_name_map = {
        # 1. Price & Volume
        METRIC["price"]: "HARGA",
        METRIC["ret_1d_pct"]: "%CHG",
        METRIC["volume"]: "VOL",
        METRIC["prev_volume"]: "P.VOL",
        METRIC["value"]: "VALUE",
        METRIC["vol_chg_1d"]: "%VOL",
        METRIC["price_change"]: "P.CHG",
        
        # 2. Bandarmology & Foreign
        METRIC["bandar_value"]: "B.VAL",
        METRIC["bandar_accum"]: "B.ACC",
        METRIC["net_foreign"]: "N.FOR",
        METRIC["foreign_1w"]: "F.1W",
        METRIC["foreign_1m"]: "F.1M",
        METRIC["foreign_buy_streak"]: "F.BY.S",
        METRIC["foreign_sell_streak"]: "F.SL.S",
        
        # 3. Size / Market Cap
        METRIC["market_cap"]: "MCAP",
        
        # 4. Insider & Shareholders
        METRIC["insider_3m_pct"]: "IN.3M",
        METRIC["insider_6m_pct"]: "IN.6M",
        METRIC["insider_1y_pct"]: "IN.1Y",
        METRIC["shareholders_chg_1m"]: "%SH.1M",
        # Note: 3M and 6M shareholders changes aren't tracked officially but we map if added
        METRIC.get("shareholders_chg_3m", 0): "%SH.3M",
        METRIC.get("shareholders_chg_6m", 0): "%SH.6M",
        
        # 5. Technical & Momentum
        METRIC["ma20"]: "MA20",
        METRIC["ma50"]: "MA50",
        METRIC["ma200"]: "MA200",
        METRIC["near_52w_high"]: "52W.Hi",
        METRIC["freq_analyzer"]: "FQ.ANZ",
        METRIC["freq_spike"]: "FQ.SPK",
        
        # 6. Fundamental & Quality
        METRIC["fscore"]: "F.SCR",
        METRIC["pe_ttm"]: "PE",
        METRIC["pbv"]: "PBV",
        METRIC["roe"]: "ROE",
        METRIC["der"]: "DER",
        METRIC["current_ratio"]: "CR",
        METRIC["altman_z"]: "ALT.Z",
        METRIC["npm_ttm"]: "NPM",
        METRIC["npm_q"]: "NPM.Q",
        METRIC["div_yield"]: "DIV",
        METRIC["payout_ratio"]: "PAYOUT",
        METRIC["div_streak"]: "DIV.S",
        METRIC["ni_growth_yoy"]: "NI.YOY",
        METRIC["ni_growth_qoq"]: "NI.QOQ",
        METRIC["eps_growth_yoy"]: "EPS.YOY",
        METRIC["rev_growth_yoy"]: "REV.YOY",
        METRIC["ni_streak"]: "NI.S",
        METRIC["eps_streak"]: "EPS.S",
        
        # 7. Returns & RS
        METRIC["ret_1m"]: "R.1M",
        METRIC["ret_3m"]: "R.3M",
        METRIC["ret_6m"]: "R.6M",
        METRIC["rs_3m"]: "RS.3M",
        METRIC["rs_6m"]: "RS.6M",
        
        # 8. Free Float
        METRIC["free_float"]: "F.FLT",
    }
    
    dynamic_cols = [] # stores (rid, name, width)
    
    for rid in seq:
        name = dynamic_name_map.get(rid, str(rid))
        width = max(len(name) + 1, 7)
        if name in ["HARGA", "VALUE", "MCAP"]:
            width = max(width, 8)
        dynamic_cols.append((rid, name, width))
        col_headers.append(name)
        col_widths.append(width)

    # Prepare columns
    all_rows = []
    
    for s in stocks:
        sym = s["symbol"]
        
        # Get streak info from tracker
        stock_data = tracker.get("stocks", {}).get(sym, {})
        streak = stock_data.get("current_streak", 0)
        streak_str = f"{streak}d" if streak >= 1 else "-"
        
        row_vals = [sym, streak_str]
        raw_metrics = s.get("raw_metrics", {})
        
        for rid, name, width in dynamic_cols:
            # Check if metric was actually present in API response
            metric_present = rid in raw_metrics
            try:
                val = float(raw_metrics.get(rid, 0.0))
            except (ValueError, TypeError):
                val = 0.0
            
            if not metric_present:
                # Metric was NOT in the API response at all
                formatted_val = "-"
            elif name in ["HARGA", "MA20", "MA50", "MA200"]:
                formatted_val = _fmt_price(val)
            elif name in ["VALUE", "MCAP", "B.VAL", "N.FOR", "F.1W", "F.1M"]:
                if abs(val) >= 1_000_000_000:
                    formatted_val = f"{val/1e9:.1f}B".replace(".0B", "B")
                elif abs(val) >= 1_000_000:
                    formatted_val = f"{val/1e6:.1f}M".replace(".0M", "M")
                else:
                    formatted_val = f"{val:.0f}"
                if name != "MCAP" and val > 0 and name != "VALUE":
                    formatted_val = "+" + formatted_val
            elif name in ["VOL", "P.VOL"]:
                if val >= 1_000_000:
                    formatted_val = f"{val/1e6:.1f}M".replace(".0M", "M")
                elif val >= 1_000:
                    formatted_val = f"{val/1e3:.1f}K".replace(".0K", "K")
                else:
                    formatted_val = f"{val:.0f}"
            elif "%" in name or name in ["%CHG", "%VOL", "ROE", "NPM", "DIV", "NI.YOY", "EPS.YOY", "REV.YOY", "IN.3M", "IN.6M", "IN.1Y", "52W.Hi", "B.ACC", "%SH.1M", "%SH.3M", "%SH.6M"]:
                sign = "+" if val > 0 and name != "52W.Hi" else ""
                formatted_val = f"{sign}{val:.1f}%"
            elif name in ["PE", "PBV", "DER", "F.SCR", "NI.S", "EPS.S", "F.BY.S", "F.SL.S", "FQ.ANZ", "FQ.SPK"]:
                formatted_val = f"{val:.1f}".replace(".0", "")
            else:
                formatted_val = f"{val}"
                
            row_vals.append(formatted_val)
            
        all_rows.append(row_vals)

    # Filter out empty columns
    # We never filter out KODE (idx 0) and STREAK (idx 1)
    cols_to_keep = [0, 1]
    num_cols = len(col_headers)
    
    for c_idx in range(2, num_cols):
        is_empty = all(row[c_idx] == "-" for row in all_rows)
        if not is_empty:
            cols_to_keep.append(c_idx)

    # Reconstruct headers and widths
    filtered_headers = [col_headers[i] for i in cols_to_keep]
    filtered_widths = [col_widths[i] for i in cols_to_keep]
    
    header_line = " | ".join(f"{h:>{w}}" if i > 0 else f"{h:<{w}}" for i, (h, w) in enumerate(zip(filtered_headers, filtered_widths)))
    dash_len = len(header_line)

    txt_lines = [
        f"JARVIS [{code}] {stone.get('name', stone_name)}",
        f"Waktu Scan: {now_str}",
        f"Total Lolos: {len(stocks)} saham",
        "-" * dash_len,
        header_line,
        "-" * dash_len
    ]
    
    for row in all_rows:
        filtered_row = [row[i] for i in cols_to_keep]
        row_line = " | ".join(f"{v:>{w}}" if i > 0 else f"{v:<{w}}" for i, (v, w) in enumerate(zip(filtered_row, filtered_widths)))
        txt_lines.append(row_line)

    txt_lines.append("-" * dash_len)
    txt_lines.append("⚠️ Disclaimer: Bukan ajakan jual/beli. Laporan JARVIS dihasilkan otomatis.")
    

    
    # Write to BytesIO
    txt_content = "\n".join(txt_lines)
    txt_buffer = io.BytesIO()
    txt_buffer.write(txt_content.encode("utf-8"))
    txt_buffer.seek(0)

    img_buffer = _generate_glacier_image(stone_name, code, stocks, now_str, top_emoji)
    return "\n".join(caption_lines), img_buffer, txt_buffer


def generate_daily_verdict() -> str:
    """Generate the full JARVIS Daily Verdict report."""
    _update_streaks()
    _prune_tracker()

    tz = pytz.timezone("Asia/Jakarta")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    now_str = datetime.now(tz).strftime("%H:%M WIB")

    tracker = _load_tracker()
    today_results = tracker.get("daily_stone_results", {}).get(today, {})

    # Calculate conviction for all stocks that appeared today
    scored_stocks = []
    for sym, data in tracker["stocks"].items():
        daily_log = data.get("daily_log", {})
        today_entry = daily_log.get(today, {})
        if not today_entry or not today_entry.get("stones"):
            continue

        conviction = calc_conviction(data)
        classification = classify_stock(conviction, data)
        data["conviction_score"] = conviction
        data["classification"] = classification

        scored_stocks.append({
            "symbol": sym,
            "score": conviction,
            "class": classification,
            "stones_today": today_entry.get("stones", []),
            "price": today_entry.get("price", 0),
            "change_pct": today_entry.get("change_pct", 0),
            "streak": data.get("current_streak", 0),
            "first_seen": data.get("first_seen", "?"),
            "consistency_30d": _calc_consistency_30d(data, tz),
        })

    _save_tracker(tracker)

    # Sort by score descending
    scored_stocks.sort(key=lambda x: x["score"], reverse=True)

    # Detect fading stocks (were active yesterday but not today)
    fading = _detect_fading(tracker, tz)

    # Build output
    L = "━" * 38
    date_fmt = datetime.now(tz).strftime("%d %b %Y")

    lines = [
        "<b>JARVIS INTELLIGENCE REPORT</b>",
        f"<code>{date_fmt} | {now_str}</code>",
        f"<code>{L}</code>",
    ]

    hot = [s for s in scored_stocks if s["class"] == "HOT"]
    warm = [s for s in scored_stocks if s["class"] == "WARM"]
    rising = [s for s in scored_stocks if s["class"] == "RISING"]
    cold = [s for s in scored_stocks if s["class"] == "COLD"]

    rank = 1

    if hot:
        lines.append("<b>HOT — High Conviction</b>")
        lines.append("<code>")
        for s in hot[:10]:
            lines.extend(_format_stock_line(s, rank))
            rank += 1
        lines.append("</code>")
        lines.append(f"<code>{L}</code>")

    if warm:
        lines.append("<b>WARM — Building Momentum</b>")
        lines.append("<code>")
        for s in warm[:10]:
            lines.extend(_format_stock_line(s, rank))
            rank += 1
        lines.append("</code>")
        lines.append(f"<code>{L}</code>")

    if rising:
        lines.append("<b>RISING — New Entries</b>")
        lines.append("<code>")
        for s in rising[:10]:
            lines.extend(_format_stock_line(s, rank, new=True))
            rank += 1
        lines.append("</code>")
        lines.append(f"<code>{L}</code>")

    if fading:
        lines.append("<b>FADING — Streak Broken</b>")
        lines.append("<code>")
        for f_item in fading[:10]:
            lines.append(f"  {f_item['symbol']:<5} Streak {f_item['prev_streak']}d ended. Last: {f_item['last_date']}")
        lines.append("</code>")
        lines.append(f"<code>{L}</code>")

    if not hot and not warm and not rising:
        lines.append("<code>Belum ada saham yang terdeteksi hari ini.</code>")
        lines.append(f"<code>{L}</code>")

    # Coverage stats
    total_unique = len(scored_stocks)

    lines.append("<code>")
    lines.append(f"Total Terdeteksi: {total_unique} Emiten")
    lines.append(f"HOT: {len(hot)} | WARM: {len(warm)} | RISING: {len(rising)}")
    lines.append("</code>")
    lines.append(f"<code>{L}</code>")
    lines.append("<i>⚠️ Disclaimer: Bukan ajakan jual/beli. Laporan Otomatis JARVIS.</i>")

    return "\n".join(lines)


def _format_stock_line(s: dict, rank: int, new: bool = False) -> list[str]:
    """Format a single stock entry for the verdict."""
    sym = s["symbol"]
    price_str = _fmt_price(s["price"])
    chg = s["change_pct"]
    sign = "+" if chg >= 0 else ""
    score = s["score"]

    # Build active stone names
    active_stones_names = []
    for sn in s["stones_today"]:
        if sn in JARVIS_STONES:
            n = JARVIS_STONES[sn]["name"].replace(" Stone", "").replace(" Scanner", "")
            active_stones_names.append(n)
            
    context_str = ", ".join(active_stones_names)
    if not context_str:
        context_str = "Unknown"

    # Emoji badge logic
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    badge = medals.get(rank, "🏅") if s["class"] in ["HOT", "WARM"] else "🎯"

    line1 = f" {badge} {sym:<4} {_fmt_price(s['price']):>6} ({sign}{chg:.1f}%)"
    line2 = f"    Score: {score:.1f} | Lolos: {context_str}"

    if new:
        line3 = f"    Info : Pantauan Perdana Hari Ini"
    else:
        line3 = f"    Info : Mode Pantau (Hari ke-{s['streak']} | Presisi {s['consistency_30d']:.0f}%)"

    return [line1, line2, line3, ""]


def _calc_consistency_30d(stock_data: dict, tz) -> float:
    """Calculate % of last 30 trading days the stock appeared."""
    today_date = datetime.now(tz).date()
    daily_log = stock_data.get("daily_log", {})
    appeared = 0
    checked = 0
    check = today_date

    for _ in range(45):
        if check.weekday() < 5:
            checked += 1
            ds = check.strftime("%Y-%m-%d")
            if ds in daily_log and len(daily_log[ds].get("stones", [])) > 0:
                appeared += 1
            if checked >= 30:
                break
        check -= timedelta(days=1)

    return (appeared / max(checked, 1)) * 100


def _detect_fading(tracker: dict, tz) -> list[dict]:
    """Find stocks that were active yesterday (or recently) but not today."""
    today = datetime.now(tz).strftime("%Y-%m-%d")
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")

    fading = []
    for sym, data in tracker["stocks"].items():
        dl = data.get("daily_log", {})
        today_stones = dl.get(today, {}).get("stones", [])
        yest_stones = dl.get(yesterday_str, {}).get("stones", [])

        if len(today_stones) == 0 and len(yest_stones) >= 2:
            # Calculate what the streak was
            prev_streak = 0
            check = yesterday
            for _ in range(365):
                ds = check.strftime("%Y-%m-%d")
                if ds in dl and len(dl[ds].get("stones", [])) > 0:
                    prev_streak += 1
                    check -= timedelta(days=1)
                    while check.weekday() >= 5:
                        check -= timedelta(days=1)
                else:
                    break

            if prev_streak >= 2:
                fading.append({
                    "symbol": sym,
                    "prev_streak": prev_streak,
                    "last_date": yesterday_str,
                })

    fading.sort(key=lambda x: x["prev_streak"], reverse=True)
    return fading


# ─────────────────────────────────────────────────────────
# STOCK INTEL (for /jarvis SYMBOL)
# ─────────────────────────────────────────────────────────

def get_stock_intel(symbol: str) -> str | None:
    """Generate detailed intelligence report for a single stock."""
    symbol = symbol.upper().strip()
    tracker = _load_tracker()

    if symbol not in tracker.get("stocks", {}):
        return None

    _update_streaks()
    tracker = _load_tracker()  # Reload after streak update

    data = tracker["stocks"][symbol]
    tz = pytz.timezone("Asia/Jakarta")
    conviction = calc_conviction(data)
    classification = classify_stock(conviction, data)
    consistency = _calc_consistency_30d(data, tz)

    L = "━" * 38
    lines = [
        f"<b>JARVIS INTEL: {symbol}</b>",
        f"<code>{L}</code>",
    ]

    lines.append("<code>")
    lines.append(f"Classification : {classification}")
    lines.append(f"Conviction     : {conviction:.0f}/100")
    lines.append(f"Current Streak : {data.get('current_streak', 0)} days")
    lines.append(f"Max Streak     : {data.get('max_streak', 0)} days")
    lines.append(f"30D Consistency: {consistency:.0f}% ({int(consistency * 30 / 100)}/30 days)")
    lines.append(f"First Detected : {data.get('first_seen', '?')}")
    lines.append(f"Total Appear.  : {data.get('total_appearances', 0)}")
    lines.append("</code>")

    # Price journey
    daily_log = data.get("daily_log", {})
    sorted_dates = sorted(daily_log.keys())
    if len(sorted_dates) >= 2:
        first_price = daily_log[sorted_dates[0]].get("price", 0)
        last_price = daily_log[sorted_dates[-1]].get("price", 0)
        if first_price > 0 and last_price > 0:
            journey_pct = ((last_price - first_price) / first_price) * 100
            sign = "+" if journey_pct >= 0 else ""
            lines.append(f"<code>Price Journey  : {_fmt_price(first_price)} > {_fmt_price(last_price)} ({sign}{journey_pct:.1f}%)</code>")

    lines.append(f"<code>{L}</code>")

    # Stone history (last 10 days)
    lines.append("<b>Stone History</b>")
    lines.append("<code>")

    today_date = datetime.now(tz).date()
    check = today_date
    shown = 0

    for _ in range(20):  # Look back up to 20 calendar days
        if check.weekday() >= 5:
            check -= timedelta(days=1)
            continue

        ds = check.strftime("%Y-%m-%d")
        entry = daily_log.get(ds, {})
        stones = entry.get("stones", [])
        price = entry.get("price", 0)
        chg = entry.get("change_pct", 0)

        date_short = check.strftime("%d %b")

        # Build stone visualization
        stone_vis = []
        for sn in STONE_ORDER:
            if sn in stones:
                stone_vis.append(STONE_CODES[sn])
            else:
                stone_vis.append("-")
        vis_str = ".".join(stone_vis)

        count = len(stones)
        if count > 0:
            sign = "+" if chg >= 0 else ""
            lines.append(f"{date_short}: {vis_str}  {count}/7  {_fmt_price(price)} {sign}{chg:.1f}%")
        else:
            lines.append(f"{date_short}: -.-.-.-.-.-.-.  0/7  (tidak terdeteksi)")

        shown += 1
        if shown >= 10:
            break
        check -= timedelta(days=1)

    lines.append("</code>")
    lines.append(f"<code>{L}</code>")

    # Legend
    legend_parts = []
    for sn in STONE_ORDER:
        legend_parts.append(f"{STONE_CODES[sn]}={JARVIS_STONES[sn]['name'].replace(' Stone', '').replace(' Scanner', '')}")  # type: ignore
    lines.append(f"<code>{'  '.join(legend_parts[:4])}</code>")
    lines.append(f"<code>{'  '.join(legend_parts[4:])}</code>")
    lines.append(f"<code>{L}</code>")
    lines.append("<i>⚠️ Disclaimer: Bukan ajakan jual/beli.</i>")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# LEADERBOARD (for /jarvis without args)
# ─────────────────────────────────────────────────────────

def get_leaderboard() -> str:
    """Get the latest JARVIS verdict or leaderboard."""
    _update_streaks()
    tracker = _load_tracker()
    tz = pytz.timezone("Asia/Jakarta")
    today = datetime.now(tz).strftime("%Y-%m-%d")

    # Check if we have today's data
    today_results = tracker.get("daily_stone_results", {}).get(today, {})

    if today_results:
        # Generate live verdict
        return generate_daily_verdict()

    # No today data — show historical leaderboard
    all_stocks = []
    for sym, data in tracker.get("stocks", {}).items():
        conviction = calc_conviction(data)
        if conviction > 0:
            all_stocks.append({
                "symbol": sym,
                "score": conviction,
                "streak": data.get("current_streak", 0),
                "last_seen": data.get("last_seen", "?"),
            })

    all_stocks.sort(key=lambda x: x["score"], reverse=True)

    L = "━" * 38
    lines = [
        "<b>JARVIS LEADERBOARD</b>",
        f"<code>{L}</code>",
    ]

    if not all_stocks:
        lines.append("<code>Belum ada data. Stones akan berjalan otomatis setiap hari bursa.</code>")
    else:
        lines.append("<code>")
        for i, s in enumerate(all_stocks[:15], 1):  # type: ignore
            lines.append(f"#{i:<3} {s['symbol']:<5}  Score: {s['score']:.0f}  Streak: {s['streak']}d  Last: {s['last_seen']}")  # type: ignore
        lines.append("</code>")

    lines.append(f"<code>{L}</code>")
    lines.append("<i>⚠️ Disclaimer: Bukan ajakan jual/beli.</i>")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# EVALUATION ENGINE (Post-Market)
# ─────────────────────────────────────────────────────────

async def generate_evaluation_report() -> str:
    from api.market import get_market_movers_exodus, get_orderbook
    import asyncio
    
    _update_streaks()
    tracker = _load_tracker()
    tz = pytz.timezone("Asia/Jakarta")
    
    # 1. Determine "yesterday" (last active trading day before today)
    today_date = datetime.now(tz).date()
    yesterday = today_date - timedelta(days=1)
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    
    # 2. Get yesterday's HOT and WARM picks
    yesterdays_picks = [] 
    for sym, data in tracker.get("stocks", {}).items():
        daily_log = data.get("daily_log", {})
        if yesterday_str in daily_log:
            y_stones = daily_log[yesterday_str].get("stones", [])
            if len(y_stones) == 0: continue
            
            # Recalculate conviction roughly based on yesterday's profile
            stones_yesterday = len(y_stones)
            streak = max(1, data.get("current_streak", 0) - 1)  # yesterday's streak approximation
            
            # Simple fallback formula for yesterday's score
            raw = stones_yesterday * 15 + min(streak, 30) * 12 + 80 + 5
            normalized = min(100, (raw / 5.0))
            
            if normalized >= 40:
                y_class = "HOT" if normalized >= 75 else "WARM"
                yesterdays_picks.append({
                    "symbol": sym,
                    "score": normalized,
                    "class": y_class,
                    "stones": y_stones
                })
                
    if not yesterdays_picks:
        return "<b>JARVIS Evaluation Engine</b>\n<code>Tidak ada rekomendasi HOT/WARM kemarin untuk dievaluasi hari ini.</code>"
        
    # 3. Fetch real-time closing prices today for those picks
    tasks = [get_orderbook(p["symbol"]) for p in yesterdays_picks]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    validated_picks = []
    for pick, res in zip(yesterdays_picks, results):
        if isinstance(res, dict):
            chg_pct = res.get("change_pct", 0.0)
            pick["today_chg"] = chg_pct
            validated_picks.append(pick)
            
    if not validated_picks:
        return "<b>JARVIS Evaluation Engine</b>\n<code>Gagal mengambil data performa hari ini untuk evaluasi.</code>"
        
    # Calculate accuracy
    green_count = sum(1 for p in validated_picks if p["today_chg"] > 0)
    total_count = len(validated_picks)
    accuracy = (green_count / total_count) * 100
    
    # Best Call
    validated_picks.sort(key=lambda x: x["today_chg"], reverse=True)
    best_call = validated_picks[0]
    
    # Biggest failure
    worst_call = validated_picks[-1]
    
    date_str = datetime.now(tz).strftime("%d %b %Y")
    
    L = "━" * 38
    lines = [
        "<b>JARVIS EVALUATION ENGINE</b>",
        f"<code>Review Performa (Rekomendasi {yesterday.strftime('%d %b')})</code>",
        f"<code>{L}</code>",
        f"<code>Akurasi: {accuracy:.1f}% ({green_count}/{total_count} saham hijau)</code>"
    ]
    
    if accuracy >= 70:
        lines.append("\n<b>Verdict JARVIS</b>: <i>\"Analisa valid. Smart money flow terbukti mendorong harga secara konsisten.\"</i>")
    elif accuracy >= 40:
        lines.append("\n<b>Verdict JARVIS</b>: <i>\"Kinerja rata-rata. Volatilitas tinggi membuat sebagian setup terpental.\"</i>")
    else:
        lines.append("\n<b>Verdict JARVIS</b>: <i>\"Analisa gagal. Distribusi ritel dan guyuran institusi menghancurkan setup. Saya akan melakukan kalibrasi ulang pada Engine.\"</i>")
    
    lines.append(f"<code>{L}</code>")
    
    if best_call["today_chg"] > 0:
        lines.append(f"<b>BEST CALL: {best_call['symbol']} (+{best_call['today_chg']:.1f}%)</b>")
        stones_caught = " & ".join([STONE_CODES.get(s, s) for s in best_call['stones'][:3]])
        lines.append(f"<code>Detail: Setup {best_call['class']} terdeteksi oleh {stones_caught}.</code>\n")
        
    if worst_call["today_chg"] < 0:
        lines.append(f"<b>BIGGEST FAILURE: {worst_call['symbol']} ({worst_call['today_chg']:.1f}%)</b>")
        lines.append(f"<code>Detail: False signal pada {worst_call['class']}. Gagal mengantisipasi tekanan jual agresif hari ini secara jujur.</code>")
        
    lines.append(f"<code>{L}</code>")
    return "\n".join(lines)

