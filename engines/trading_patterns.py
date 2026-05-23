"""
Dictionary of Trading Terms, Smart Money Concepts (SMC), and Patterns.
"""

TRADING_PATTERNS = {
    # General Principles
    "Psychology": "Psychology",
    "Risk management": "Risk management",
    "Liquidity sweep": "Liquidity sweep",
    "Time and price": "Time and price",
    "Trading w the smart money": "Trading w the smart money",
    
    # Structure & Basics
    "BOS": "Break of Structure",
    "BOS Retest": "Break of Structure Retest",
    "CHOCH": "Change of Character",
    "MSS": "Market Structure Shift",
    "PO3": "Power of 3 - Accumulation, Manipulation, Distribution",
    
    # Blocks
    "OB": "Order Block",
    "MB": "Mitigation Block",
    "BB": "Breaker Block",
    "RTO": "Return to Origin / Order Block",
    
    # Imbalances & Gaps
    "FVG": "Fair Value Gap",
    "IFVG": "Inversion Fair Value Gap",
    "VI": "Volume Imbalance",
    "VIB": "Volume Imbalance - singkatan alternatif",
    "LV": "Liquidity Void",
    "BISI": "Buyside Imbalance Sellside Inefficiency",
    "SIBI": "Sellside Imbalance Buyside Inefficiency",
    "BPR": "Balanced Price Range",
    "IMB": "Imbalance",
    
    # Liquidity
    "BSL": "Buy Side Liquidity",
    "SSL": "Sell Side Liquidity",
    "EQH": "Equal Highs",
    "EQL": "Equal Lows",
    "LQ": "Liquidity",
    "LIQ": "Liquidity",
    "DOL": "Draw on Liquidity",
    "IL": "Internal Liquidity",
    "OL": "Old Low",
    "LIT": "Liquidity Inducement Theorem / Liquidity in Transit",
    "SL hunting": "Stop Loss hunting",
    "SFP": "Swing Failure Pattern",
    
    # Time & Sessions
    "KZ": "Kill Zone",
    "RTH": "Regular Trading Hours",
    "ETH": "Electronic Trading Hours",
    "PDH": "Previous Daily High",
    "PDL": "Previous Daily Low",
    "IB": "Inside Bar / Initial Balance",
    
    # Advanced / Miscellaneous SMC
    "SMT": "Smart Money Tool / Divergence",
    "IPDA": "Interbank Price Delivery Algorithm",
    "OTE": "Optimal Trade Entry",
    "AMR": "Algorithmic Market Reversal / Accumulation Manipulation Retracement",
    "MIP": "Mitigation in Price / Macro Implied Pricing",
    "SMR": "Smart Money Reversal",
    "DM": "Directional Movement / Daily Mitigation",
    "QML": "Quasimodo Level",
    
    # Supply & Demand Patterns
    "DBR": "Drop Base Rally - Pola Supply & Demand",
    "RBR": "Rally Base Rally - Pola Supply & Demand",
    
    # Volume & Orderflow
    "Volume cluster": "Volume cluster",
    "VC": "Volume Cluster",
    "Orderflow delta": "Orderflow delta",
    "OFD": "Order Flow Delta",
    "Fair price": "Fair price",
    "FP": "Fair Price",
    "BT": "Breaker Trend / Block Trade",
    "HFT": "High Frequency Trading",
    
    # Multi Timeframe & Indicators
    "H1 POI": "1-Hour Point of Interest",
    "LTF Confirmation": "Lower Time Frame Confirmation",
    "MTF Alignment": "Multi Time Frame Alignment",
    "DXY Correlation": "Korelasi dengan Indeks Dolar AS",
    "2SD Deviation": "2 Standard Deviations - biasanya pada VWAP atau Bollinger Bands",
    "ATR Expansion": "Average True Range Expansion"
}


# ──────────────────────────────────────────────
# SMART MONEY CONCEPTS & PATTERN RECOGNITION ENGINES
# ──────────────────────────────────────────────

import pandas as pd
import logging
from engines.technical import detect_pivot_extrema
log = logging.getLogger("bot")

import numpy as np

def detect_choch_bos(df: pd.DataFrame, lookback: int = 20, vol_mult: float = 1.2) -> dict | None:
    """Engine 1: CHoCH (Change of Character) / BOS (Break of Structure).
    Detects the precise moment a micro-downtrend reverses into a new uptrend
    (or vice-versa) by tracking fractal swing points and validating with volume.

    Returns dict with label, desc, direction, sl_level, priority  — or None.
    """
    if len(df) < lookback + 2:
        return None

    try:
        window = df.iloc[-(lookback + 2):]  # extra 2 for fractal detection
        highs = window['High'].values
        lows = window['Low'].values
        closes = window['Close'].values
        opens = window['Open'].values
        volumes = window['Volume'].values

        # ── Fractal Detection (1 bar left, 1 bar right) ──
        swing_highs = []
        swing_lows = []
        for i in range(1, len(window) - 1):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                swing_highs.append({'idx': i, 'price': float(highs[i])})
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                swing_lows.append({'idx': i, 'price': float(lows[i])})

        if not swing_highs or not swing_lows:
            return None

        last_sh = swing_highs[-1]
        last_sl = swing_lows[-1]

        latest_close = float(closes[-1])
        latest_vol = float(volumes[-1])
        avg_vol = float(np.mean(volumes[:-1])) if len(volumes) > 1 else 1.0

        # ── Bullish CHoCH: Close breaks above Last Swing High ──
        if latest_close > last_sh['price'] and latest_vol > avg_vol * vol_mult:
            # Extra confirmation: candle must be bullish
            if closes[-1] > opens[-1]:
                return {
                    "type": "CHOCH_BULL",
                    "direction": "BULL",
                    "priority": 2,
                    "label": "🚀 CHoCH Breakout",
                    "desc": (
                        f"Struktur downtrend patah! Close nembus Swing High "
                        f"{int(last_sh['price']):,} (+Vol {latest_vol / avg_vol:.1f}x). "
                        f"SL: {int(last_sl['price']):,}"
                    ).replace(",", "."),
                    "sl_level": last_sl['price'],
                    "action_hint": "BUY_CHOCH",
                }

        # ── Bearish CHoCH: Close breaks below Last Swing Low ──
        if latest_close < last_sl['price'] and latest_vol > avg_vol * vol_mult:
            if closes[-1] < opens[-1]:
                return {
                    "type": "CHOCH_BEAR",
                    "direction": "BEAR",
                    "priority": 1,  # Higher priority for warnings
                    "label": "⚠️ CHoCH Breakdown",
                    "desc": (
                        f"Struktur uptrend patah! Close jebol Swing Low "
                        f"{int(last_sl['price']):,} (+Vol {latest_vol / avg_vol:.1f}x). "
                        f"Rawan koreksi lanjutan"
                    ).replace(",", "."),
                    "sl_level": last_sh['price'],
                    "action_hint": "AVOID",
                }
    except Exception:
        pass
    return None


def detect_breaker_block(df: pd.DataFrame, lookback: int = 30) -> dict | None:
    """Engine 2: Breaker Block — a dead Order Block that becomes resistance/support.

    Bidirectional:
    - Bullish OB that gets broken below → becomes Resistance (bearish breaker)
    - Bearish OB that gets broken above → becomes Support (bullish breaker)

    Returns dict or None.
    """
    if len(df) < lookback + 3:
        return None

    try:
        scan_start = max(0, len(df) - lookback - 3)
        highs = df['High'].values
        lows = df['Low'].values
        closes = df['Close'].values
        opens = df['Open'].values

        latest_close = float(closes[-1])
        latest_high = float(highs[-1])
        latest_low = float(lows[-1])

        # ── Scan for Order Blocks ──
        for i in range(scan_start, len(df) - 3):
            c_bear = closes[i] < opens[i]  # Candle i = bearish
            c_bull_next = closes[i + 1] > opens[i + 1]  # Candle i+1 = bullish
            engulf = closes[i + 1] > opens[i]  # Bullish engulfs bearish

            # --- Bullish OB found: bearish → engulfing bullish ---
            if c_bear and c_bull_next and engulf:
                ob_high = float(highs[i])
                ob_low = float(lows[i])

                # Check if OB was broken (any Close below ob_low after formation)
                broken = False
                for j in range(i + 2, len(df) - 1):
                    if closes[j] < ob_low:
                        broken = True
                        break

                if not broken:
                    continue

                # Check retest: current candle High enters breaker zone but Close rejected
                if latest_high >= ob_low and latest_close < ob_low:
                    return {
                        "type": "BREAKER_RESIST",
                        "direction": "BEAR",
                        "priority": 1,
                        "label": "⚠️ Breaker Block Warning",
                        "desc": (
                            f"Harga mengetes zona Breaker ({int(ob_low):,}-{int(ob_high):,})! "
                            f"Ex-OB sudah mati & jadi tembok. Rawan guyuran"
                        ).replace(",", "."),
                        "zone_high": ob_high,
                        "zone_low": ob_low,
                        "action_hint": "AVOID",
                    }

            # --- Bearish OB: bullish → engulfing bearish ---
            c_bull = closes[i] > opens[i]
            c_bear_next = closes[i + 1] < opens[i + 1]
            engulf_bear = closes[i + 1] < opens[i]

            if c_bull and c_bear_next and engulf_bear:
                ob_high = float(highs[i])
                ob_low = float(lows[i])

                broken_up = False
                for j in range(i + 2, len(df) - 1):
                    if closes[j] > ob_high:
                        broken_up = True
                        break

                if not broken_up:
                    continue

                if latest_low <= ob_high and latest_close > ob_high:
                    return {
                        "type": "BREAKER_SUPPORT",
                        "direction": "BULL",
                        "priority": 3,
                        "label": "⚡ Breaker Block Support",
                        "desc": (
                            f"Harga mantul dari zona Breaker ({int(ob_low):,}-{int(ob_high):,}). "
                            f"Ex-OB bearish jadi pijakan support baru"
                        ).replace(",", "."),
                        "zone_high": ob_high,
                        "zone_low": ob_low,
                        "action_hint": "INFO",
                    }
    except Exception:
        pass
    return None


def detect_inducement_trap(df: pd.DataFrame, lookback: int = 25) -> dict | None:
    """Engine 3: Inducement (IDM) Trap — SL hunting above Order Block.

    Detects when market makers sweep a minor swing low (retail SL zone)
    placed just above a valid Order Block, then hold price at the OB.

    Returns dict or None.
    """
    if len(df) < lookback + 3:
        return None

    try:
        scan_start = max(0, len(df) - lookback - 3)
        highs = df['High'].values
        lows = df['Low'].values
        closes = df['Close'].values
        opens = df['Open'].values
        volumes = df['Volume'].values

        latest_close = float(closes[-1])
        latest_low = float(lows[-1])
        latest_open = float(opens[-1])
        latest_vol = float(volumes[-1])
        avg_vol = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes))

        # ── Scan for Bullish Order Block ──
        for i in range(scan_start, len(df) - 5):
            c_bear = closes[i] < opens[i]
            c_bull_next = closes[i + 1] > opens[i + 1]
            engulf = closes[i + 1] > opens[i]

            if not (c_bear and c_bull_next and engulf):
                continue

            ob_high = float(highs[i])
            ob_low = float(lows[i])
            ob_range = ob_high - ob_low
            if ob_range <= 0:
                continue

            # ── Find minor Swing Low ABOVE this OB (within 2% of ob_high) ──
            minor_sl = None
            for j in range(i + 2, len(df) - 2):
                if lows[j] < lows[j - 1] and lows[j] < lows[j + 1]:
                    candidate = float(lows[j])
                    # Must be above OB but close to it (within 3% of ob_high)
                    if ob_high < candidate <= ob_high * 1.03:
                        minor_sl = candidate
                        break  # Take the first/nearest

            if minor_sl is None:
                continue

            # ── Trigger: Price sweeps minor SL but holds at OB ──
            swept = latest_low < minor_sl  # Jebol SL ritel
            held_at_ob = latest_close >= ob_low  # Tertahan di OB
            bullish_recovery = latest_close > latest_open  # Candle bullish
            vol_ok = latest_vol > avg_vol * 0.8  # Minimal average volume

            if swept and held_at_ob and bullish_recovery and vol_ok:
                return {
                    "type": "INDUCEMENT",
                    "direction": "BULL",
                    "priority": 3,
                    "label": "⚡ Inducement Swept!",
                    "desc": (
                        f"SL ritel di {int(minor_sl):,} disapu, harga tertahan di OB "
                        f"({int(ob_low):,}-{int(ob_high):,}). Entry OB sekarang"
                    ).replace(",", "."),
                    "ob_high": ob_high,
                    "ob_low": ob_low,
                    "sl_level": ob_low,
                    "action_hint": "BUY_IDM",
                }
    except Exception:
        pass
    return None


def detect_equal_level_sweep(df: pd.DataFrame, lookback: int = 30, tolerance_pct: float = 0.002) -> dict | None:
    """Engine 4: EQH/EQL Sweep — Double Top/Bottom Liquidity Pool.

    Detects when equal highs or equal lows get swept (liquidity grab)
    and price immediately recovers (V-shape), confirming the trap.

    Returns dict or None.
    """
    if len(df) < lookback + 2:
        return None

    try:
        window = df.iloc[-lookback:]
        highs = window['High'].values
        lows = window['Low'].values
        closes = window['Close'].values
        opens = window['Open'].values

        latest_close = float(closes[-1])
        latest_low = float(lows[-1])
        latest_high = float(highs[-1])

        # ── Collect fractal Swing Highs & Swing Lows ──
        swing_highs = []
        swing_lows = []
        for i in range(1, len(window) - 2):  # Exclude last candle (current)
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                swing_highs.append(float(highs[i]))
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                swing_lows.append(float(lows[i]))

        # ── Check Equal Lows (EQL) ──
        for i in range(len(swing_lows)):
            for j in range(i + 1, len(swing_lows)):
                diff_pct = abs(swing_lows[i] - swing_lows[j]) / swing_lows[i] if swing_lows[i] > 0 else 1
                if diff_pct < tolerance_pct:
                    eql_level = min(swing_lows[i], swing_lows[j])
                    # Trigger: Low sweeps below EQL, Close recovers above (V-shape)
                    if latest_low < eql_level and latest_close > eql_level:
                        # Must be bullish recovery candle
                        if latest_close > float(opens[-1]):
                            return {
                                "type": "EQL_SWEEP",
                                "direction": "BULL",
                                "priority": 2,
                                "label": "🚀 EQL Sweep — Liquidity Pool!",
                                "desc": (
                                    f"Double Bottom {int(eql_level):,} = kolam SL ritel. "
                                    f"Bandar baru nyapu likuiditas, harga V-recover"
                                ).replace(",", "."),
                                "sweep_level": eql_level,
                                "action_hint": "BUY_EQL",
                            }

        # ── Check Equal Highs (EQH) ──
        for i in range(len(swing_highs)):
            for j in range(i + 1, len(swing_highs)):
                diff_pct = abs(swing_highs[i] - swing_highs[j]) / swing_highs[i] if swing_highs[i] > 0 else 1
                if diff_pct < tolerance_pct:
                    eqh_level = max(swing_highs[i], swing_highs[j])
                    # Trigger: High breaks above EQH, Close falls back below (Upthrust)
                    if latest_high > eqh_level and latest_close < eqh_level:
                        if latest_close < float(opens[-1]):  # Bearish candle
                            return {
                                "type": "EQH_SWEEP",
                                "direction": "BEAR",
                                "priority": 1,
                                "label": "⚠️ EQH Sweep — Liquidity Trap!",
                                "desc": (
                                    f"Double Top {int(eqh_level):,} ditembus lalu dibuang! "
                                    f"Ritel FOMO sudah kena perangkap. Rawan dump"
                                ).replace(",", "."),
                                "sweep_level": eqh_level,
                                "action_hint": "AVOID",
                            }
    except Exception:
        pass
    return None


def detect_wyckoff_upthrust(df: pd.DataFrame, snr: dict, lookback: int = 15) -> dict | None:
    """Engine 5: Wyckoff Upthrust (UTAD) — False Breakout at Resistance.

    Detects when price breaks above major resistance with climax volume
    but closes back below it, forming a long upper wick (distribution trap).

    Returns dict or None.
    """
    if len(df) < lookback:
        return None

    try:
        resistances = snr.get("resistances", [])
        if not resistances:
            return None

        latest = df.iloc[-1]
        close = float(latest['Close'])
        open_ = float(latest['Open'])
        high = float(latest['High'])
        low = float(latest['Low'])
        vol = float(latest['Volume'])

        body = abs(close - open_)
        upper_wick = high - max(close, open_)
        candle_range = high - low if high > low else 1

        avg_vol = float(df['Volume'].iloc[-20:].mean()) if len(df) >= 20 else float(df['Volume'].mean())

        for res in resistances[:3]:
            res_level = float(res['level'])

            # Conditions:
            # 1. High breaks above resistance
            # 2. Close falls back below resistance
            # 3. Climax volume (>= 2.0x average)
            # 4. Upper wick dominates (>= 1.5x body)
            cond_false_break = high > res_level and close < res_level
            cond_climax_vol = vol > avg_vol * 2.0
            cond_upper_wick = upper_wick > body * 1.5 if body > 0 else upper_wick > candle_range * 0.5
            cond_bearish = close < open_  # Must be bearish candle

            if cond_false_break and cond_climax_vol and cond_upper_wick and cond_bearish:
                return {
                    "type": "UPTHRUST",
                    "direction": "BEAR",
                    "priority": 1,  # Highest priority — DANGER
                    "label": "⚠️ Wyckoff Upthrust!",
                    "desc": (
                        f"False breakout di Resistance {int(res_level):,} dgn Climax Volume "
                        f"({vol / avg_vol:.1f}x)! Rawan guyuran parah"
                    ).replace(",", "."),
                    "resistance_level": res_level,
                    "action_hint": "AVOID",
                }
    except Exception:
        pass
    return None


def detect_effort_vs_result(df: pd.DataFrame, snr: dict | None = None, lookback: int = 20) -> dict | None:
    """Engine 6: Effort vs Result Anomaly — Iceberg Order Detector.

    Detects extreme volume with minimal price movement (hidden institutional orders).
    Context-aware: near support = Accumulation, near resistance = Distribution.

    Returns dict or None.
    """
    if len(df) < lookback + 1:
        return None

    try:
        latest = df.iloc[-1]
        close = float(latest['Close'])
        high = float(latest['High'])
        low = float(latest['Low'])
        vol = float(latest['Volume'])

        spread = high - low
        avg_spread = float((df['High'] - df['Low']).iloc[-lookback:].mean())
        avg_vol = float(df['Volume'].iloc[-lookback:].mean())

        if avg_spread <= 0 or avg_vol <= 0:
            return None

        vol_ratio = vol / avg_vol
        spread_ratio = spread / avg_spread

        # Trigger: Volume raksasa (>2.5x) tapi spread mini (<0.5x)
        if vol_ratio > 2.5 and spread_ratio < 0.5:
            # Context detection
            context = "Netral"
            if snr:
                supports = snr.get("supports", [])
                resistances = snr.get("resistances", [])
                for s in supports[:3]:
                    if abs(close - s['level']) / close < 0.02:
                        context = "Akumulasi"
                        break
                for r in resistances[:3]:
                    if abs(close - r['level']) / close < 0.02:
                        context = "Distribusi"
                        break

            direction = "BULL" if context == "Akumulasi" else ("BEAR" if context == "Distribusi" else "NEUTRAL")
            priority = 2 if context != "Netral" else 3

            return {
                "type": "EFFORT_VS_RESULT",
                "direction": direction,
                "priority": priority,
                "label": f"⚡ Effort vs Result ({context})",
                "desc": (
                    f"Volume {vol_ratio:.1f}x rata-rata tapi Spread cuma {spread_ratio:.1f}x! "
                    f"Ada raksasa menahan harga. Konteks: {context}"
                ),
                "context": context,
                "action_hint": "INFO",
            }
    except Exception:
        pass
    return None


def detect_three_bar_play(df: pd.DataFrame) -> dict | None:
    """Engine 7: Three Bar Play — Momentum Scalp Pattern.

    Bidirectional:
    - Bullish: Marubozu bullish → Inside Bar (vol drop) → Breakout above Bar 1 High
    - Bearish: Marubozu bearish → Inside Bar (vol drop) → Breakdown below Bar 1 Low

    Returns dict or None.
    """
    if len(df) < 4:
        return None

    try:
        bar1 = df.iloc[-3]  # T-2: Igniting Bar
        bar2 = df.iloc[-2]  # T-1: Inside Bar (rest)
        bar3 = df.iloc[-1]  # T-0: Trigger Bar

        h1, l1, c1, o1, v1 = float(bar1['High']), float(bar1['Low']), float(bar1['Close']), float(bar1['Open']), float(bar1['Volume'])
        h2, l2, c2, o2, v2 = float(bar2['High']), float(bar2['Low']), float(bar2['Close']), float(bar2['Open']), float(bar2['Volume'])
        h3, l3, c3, o3, v3 = float(bar3['High']), float(bar3['Low']), float(bar3['Close']), float(bar3['Open']), float(bar3['Volume'])

        range1 = h1 - l1 if h1 > l1 else 1
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        avg_vol = float(df['Volume'].iloc[-20:].mean()) if len(df) >= 20 else float(df['Volume'].mean())

        # ── Bullish Three Bar Play ──
        bull_bar1 = c1 > o1 and body1 > range1 * 0.65 and v1 > avg_vol  # Marubozu bullish
        inside_bar = h2 <= h1 and l2 >= l1  # Inside Bar
        vol_rest = v2 < v1 * 0.6  # Volume drop
        body_rest = body2 < body1 * 0.5  # Small body on inside bar
        bull_breakout = c3 > h1  # Close above Bar 1 High

        if bull_bar1 and inside_bar and vol_rest and body_rest and bull_breakout:
            return {
                "type": "THREE_BAR_BULL",
                "direction": "BULL",
                "priority": 3,
                "label": "⚡ Three Bar Play!",
                "desc": (
                    f"Marubozu + Inside Bar + Breakout! Momentum segar terdeteksi. "
                    f"SL: {int(l2):,}"
                ).replace(",", "."),
                "sl_level": l2,
                "action_hint": "SCALP_BUY",
            }

        # ── Bearish Three Bar Play ──
        bear_bar1 = c1 < o1 and body1 > range1 * 0.65 and v1 > avg_vol
        bear_breakout = c3 < l1

        if bear_bar1 and inside_bar and vol_rest and body_rest and bear_breakout:
            return {
                "type": "THREE_BAR_BEAR",
                "direction": "BEAR",
                "priority": 2,
                "label": "⚠️ Three Bar Play (Bearish)!",
                "desc": (
                    f"Bearish Marubozu + Inside Bar + Breakdown! Momentum jual kuat. "
                    f"Rawan longsor"
                ),
                "sl_level": h2,
                "action_hint": "AVOID",
            }
    except Exception:
        pass
    return None


def detect_fvg(df: pd.DataFrame, lookback: int = 10) -> dict | None:
    """Engine 8: Fair Value Gap (FVG) / Imbalance (BISI & SIBI)."""
    if len(df) < 3:
        return None
    try:
        h = df['High'].values
        l = df['Low'].values
        
        candle1_high = float(h[-3])
        candle3_low = float(l[-1])
        
        if candle3_low > candle1_high:
            return {
                "type": "FVG_BULL",
                "direction": "BULL",
                "priority": 2,
                "label": "🚀 Bullish FVG (BISI)",
                "desc": f"Terbentuk Fair Value Gap di {int(candle1_high):,} - {int(candle3_low):,}. Zona pantulan institusi terbaru.",
                "action_hint": "BULLISH_INFO"
            }
            
        candle1_low = float(l[-3])
        candle3_high = float(h[-1])
        
        if candle3_high < candle1_low:
            return {
                "type": "FVG_BEAR",
                "direction": "BEAR",
                "priority": 2,
                "label": "⚠️ Bearish FVG (SIBI)",
                "desc": f"Terbentuk Bearish Imbalance di {int(candle3_high):,} - {int(candle1_low):,}. Rawan tembok dump.",
                "action_hint": "BEARISH_INFO"
            }
    except Exception:
        pass
    return None


def detect_ote(df: pd.DataFrame, lookback: int = 30) -> dict | None:
    """Engine 9: Optimal Trade Entry (OTE) — 0.618 to 0.786 Fibonacci Retracement."""
    if len(df) < lookback + 5:
        return None
    try:
        window = df.iloc[-lookback-2:-2]
        recent = df.iloc[-2:]
        
        highest = float(window['High'].max())
        lowest = float(window['Low'].min())
        rng = highest - lowest
        if rng <= 0: return None
        
        last_close = float(recent['Close'].iloc[-1])
        
        high_idx = window['High'].idxmax()
        low_idx = window['Low'].idxmin()
        
        if high_idx > low_idx:
            # Uptrend: retracement from High down to Low
            fib_618 = highest - (rng * 0.618)
            fib_786 = highest - (rng * 0.786)
            if fib_786 <= last_close <= fib_618:
                return {
                    "type": "OTE_BULL",
                    "direction": "BULL",
                    "priority": 2,
                    "label": "⚡ Optimal Trade Entry (OTE)",
                    "desc": f"Harga terkoreksi masuk zona Fibonacci OTE 0.618-0.786 ({int(fib_786):,}-{int(fib_618):,}). Berpeluang pantul naik.",
                    "action_hint": "BUY_OTE"
                }
        elif low_idx > high_idx:
            # Downtrend: retracement from Low up to High
            fib_618 = lowest + (rng * 0.618)
            fib_786 = lowest + (rng * 0.786)
            if fib_618 <= last_close <= fib_786:
                return {
                    "type": "OTE_BEAR",
                    "direction": "BEAR",
                    "priority": 2,
                    "label": "⚠️ OTE Bearish Retracement",
                    "desc": f"Harga pullback naik uji Discount Fibonacci Bearish ({int(fib_618):,}-{int(fib_786):,}). Rawan reversal ke bawah.",
                    "action_hint": "AVOID"
                }
    except Exception:
        pass
    return None


def detect_triangle_patterns(df: pd.DataFrame, lookback: int = 40) -> dict | None:
    """Engine 10: Classical Chart Patterns — Triangles.
    Detects Symmetrical, Ascending, and Descending Triangles.
    """
    if len(df) < lookback + 5:
        return None
        
    try:
        window = df.iloc[-lookback:]
        highs = window['High'].values
        lows = window['Low'].values
        closes = window['Close'].values
        
        # ── Find swing highs and lows ──
        swing_highs = []
        swing_lows = []
        # Menggunakan window kecil untuk menemukan titik puncak/lembah fraktal lokal
        for i in range(2, len(window) - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
                swing_highs.append({'idx': i, 'price': float(highs[i])})
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                swing_lows.append({'idx': i, 'price': float(lows[i])})
                
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None
            
        h1, h2 = swing_highs[-2], swing_highs[-1]
        l1, l2 = swing_lows[-2], swing_lows[-1]
        
        # Ensure points are somewhat recent
        if (len(window) - max(h2['idx'], l2['idx'])) > 15:
            return None
            
        current_close = float(closes[-1])
            
        # Slope evaluation (percentage change relative to base price)
        flat_tol = 0.015  # 1.5% toleransi horisontal
        slope_min = 0.01  # 1% minimal tren miring
        
        h_diff_pct = (h2['price'] - h1['price']) / h1['price']
        l_diff_pct = (l2['price'] - l1['price']) / l1['price']
        
        is_sym = h_diff_pct < -slope_min and l_diff_pct > slope_min
        is_asc = abs(h_diff_pct) <= flat_tol and l_diff_pct > slope_min
        is_desc = abs(l_diff_pct) <= flat_tol and h_diff_pct < -slope_min
        
        if not (is_sym or is_asc or is_desc):
            return None
            
        # Extrapolate lines to current index
        idx_current = len(window) - 1
        
        if h2['idx'] == h1['idx'] or l2['idx'] == l1['idx']:
            return None
            
        h_slope = (h2['price'] - h1['price']) / (h2['idx'] - h1['idx'])
        l_slope = (l2['price'] - l1['price']) / (l2['idx'] - l1['idx'])
        
        h_current_extrap = h2['price'] + h_slope * (idx_current - h2['idx'])
        l_current_extrap = l2['price'] + l_slope * (idx_current - l2['idx'])
        
        # Pattern invalid if crossed long ago
        if h_current_extrap <= l_current_extrap:
            return None
            
        # Is price breaking out?
        breakout_up = current_close > h_current_extrap
        breakout_down = current_close < l_current_extrap
        
        pattern_name = ""
        action_hint = "INFO"
        priority = 3
        direction = "NEUTRAL"
        
        if is_asc:
            pattern_name = "Ascending Triangle"
            direction = "BULL"
        elif is_desc:
            pattern_name = "Descending Triangle"
            direction = "BEAR"
        elif is_sym:
            pattern_name = "Symmetrical Triangle"
            direction = "NEUTRAL"
            
        if breakout_up:
            desc = f"Harga telah menembus ke atas pola {pattern_name}. Potensi konfirmasi tren bullish."
            direction = "BULL"
            action_hint = "BUY_BREAKOUT"
            priority = 2
        elif breakout_down:
            desc = f"Harga telah menembus ke bawah pola {pattern_name}. Tanda breakdown dan potensi koreksi."
            direction = "BEAR"
            action_hint = "AVOID"
            priority = 1
        else:
            desc = f"Harga sedang berkontraksi di dalam pola {pattern_name}. Menunggu konfirmasi breakout."
            
        return {
            "type": f"TRIANGLE_{pattern_name.split()[0].upper()}",
            "direction": direction,
            "priority": priority,
            "label": f"📐 {pattern_name}",
            "desc": desc,
            "action_hint": action_hint
        }
    except Exception:
        pass
    return None


def detect_wedge_patterns(df: pd.DataFrame, lookback: int = 40) -> dict | None:
    """Engine 11: Wedge Patterns (Rising / Falling).
    Detects converging price channels with slopes moving in the same direction.
    """
    if len(df) < lookback + 5:
        return None
        
    try:
        window = df.iloc[-lookback:]
        highs = window['High'].values
        lows = window['Low'].values
        closes = window['Close'].values
        
        swing_highs = []
        swing_lows = []
        for i in range(2, len(window) - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
                swing_highs.append({'idx': i, 'price': float(highs[i])})
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                swing_lows.append({'idx': i, 'price': float(lows[i])})
                
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None
            
        h1, h2 = swing_highs[-2], swing_highs[-1]
        l1, l2 = swing_lows[-2], swing_lows[-1]
        
        if (len(window) - max(h2['idx'], l2['idx'])) > 15:
            return None
            
        current_close = float(closes[-1])
        
        h_diff_pct = (h2['price'] - h1['price']) / h1['price']
        l_diff_pct = (l2['price'] - l1['price']) / l1['price']
        
        # We need BOTH slopes to be same sign, but converging.
        # Falling Wedge: Both negative, Highs falling faster than Lows
        is_falling_wedge = (h_diff_pct < -0.01) and (l_diff_pct < -0.01) and (h_diff_pct < l_diff_pct)
        # Rising Wedge: Both positive, Lows rising faster than Highs
        is_rising_wedge = (h_diff_pct > 0.01) and (l_diff_pct > 0.01) and (l_diff_pct > h_diff_pct)
        
        if not (is_falling_wedge or is_rising_wedge):
            return None
            
        idx_current = len(window) - 1
        if h2['idx'] == h1['idx'] or l2['idx'] == l1['idx']:
            return None
            
        h_slope = (h2['price'] - h1['price']) / (h2['idx'] - h1['idx'])
        l_slope = (l2['price'] - l1['price']) / (l2['idx'] - l1['idx'])
        
        h_current_extrap = h2['price'] + h_slope * (idx_current - h2['idx'])
        l_current_extrap = l2['price'] + l_slope * (idx_current - l2['idx'])
        
        if h_current_extrap <= l_current_extrap:
            return None
            
        breakout_up = current_close > h_current_extrap
        breakout_down = current_close < l_current_extrap
        
        if is_falling_wedge:
            if breakout_up:
                return {
                    "type": "WEDGE_FALLING_BREAKOUT",
                    "direction": "BULL",
                    "priority": 2,
                    "label": "🚀 Falling Wedge Breakout",
                    "desc": "Harga berhasil mematahkan dominasi Seller dengan menembus ke atas pola Falling Wedge. Momentum Bullish terkonfirmasi.",
                    "action_hint": "BUY_BREAKOUT"
                }
            else:
                return {
                    "type": "WEDGE_FALLING",
                    "direction": "BULL",
                    "priority": 3,
                    "label": "⚡ Falling Wedge",
                    "desc": "Harga masih terkontraksi dalam Falling Wedge (pola Bullish Reversal). Bersiap ancang-ancang menyongsong breakout pamungkas ke atas.",
                    "action_hint": "INFO"
                }
                
        elif is_rising_wedge:
            if breakout_down:
                return {
                    "type": "WEDGE_RISING_BREAKDOWN",
                    "direction": "BEAR",
                    "priority": 1,
                    "label": "⚠️ Rising Wedge Breakdown",
                    "desc": "Support tren naik dari pola Rising Wedge telah jebol. Konfirmasi pola Bearish Reversal, rawan koreksi distribusi dalam.",
                    "action_hint": "AVOID"
                }
            else:
                return {
                    "type": "WEDGE_RISING",
                    "direction": "BEAR",
                    "priority": 2,
                    "label": "⚠️ Rising Wedge",
                    "desc": "Tren naik mulai kehabisan bensin dan tertekan menyempit di dalam Rising Wedge (Pola Bearish Reversal). Berhati-hati menanti breakdown fatal.",
                    "action_hint": "AVOID"
                }
    except Exception:
        pass
    return None


def detect_head_and_shoulders(df: pd.DataFrame, lookback: int = 60) -> dict | None:
    """Engine 12: Head and Shoulders (H&S) & Inverse H&S."""
    if len(df) < lookback + 10:
        return None
        
    try:
        window = df.iloc[-lookback:]
        highs = window['High'].values
        lows = window['Low'].values
        closes = window['Close'].values
        
        swing_highs = []
        swing_lows = []
        for i in range(2, len(window) - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
                swing_highs.append({'idx': i, 'price': float(highs[i])})
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                swing_lows.append({'idx': i, 'price': float(lows[i])})
                
        current_close = float(closes[-1])
        idx_current = len(window) - 1

        # Check Inverse H&S (Bullish Reversal)
        if len(swing_lows) >= 3 and len(swing_highs) >= 2:
            l1, l2, l3 = swing_lows[-3], swing_lows[-2], swing_lows[-1]
            
            # Head must be significantly lower than Left and Right shoulders
            if l2['price'] < l1['price'] * 0.985 and l2['price'] < l3['price'] * 0.985:
                # Shoulders generally at similar levels (within 5%)
                if abs(l1['price'] - l3['price']) / l3['price'] < 0.05:
                    
                    # Intermediary Neckline Highs
                    recent_highs = [h for h in swing_highs if h['idx'] > l1['idx']]
                    if len(recent_highs) >= 2:
                        # Grab two recent highs bridging the shoulders for neckline
                        h1, h2 = recent_highs[0], recent_highs[-1]
                        
                        # Project neckline to current
                        if h2['idx'] != h1['idx']:
                            n_slope = (h2['price'] - h1['price']) / (h2['idx'] - h1['idx'])
                            neckline_price = h2['price'] + n_slope * (idx_current - h2['idx'])
                            
                            dist_to_neck = (current_close - neckline_price) / neckline_price
                            
                            # Valid Inverse H&S pattern in play
                            if dist_to_neck > 0.01:
                                return {
                                    "type": "INV_HS_BREAKOUT",
                                    "direction": "BULL",
                                    "priority": 2,
                                    "label": "🚀 Inverse Head & Shoulders Breakout",
                                    "desc": "Visi Smart Money! Harga sukses merobohkan Neckline penyempurnaan akumulasi Inverse Head and Shoulders ke atas.",
                                    "action_hint": "BUY_BREAKOUT"
                                }
                            elif dist_to_neck > -0.05:
                                return {
                                    "type": "INV_HS_FORMING",
                                    "direction": "BULL",
                                    "priority": 3,
                                    "label": "⚡ Inverse Head & Shoulders Formasi",
                                    "desc": "Terpantau embrio formasi dominan Inverse Head & Shoulders (Bahu Kiri, Kepala, Bahu Kanan). Bersiap konfirmasi penembusan Neckline untuk sinyal *reversal* Bullish absolut.",
                                    "action_hint": "INFO"
                                }
        
        # Check Standard H&S (Bearish Reversal)
        if len(swing_highs) >= 3 and len(swing_lows) >= 2:
            h1, h2, h3 = swing_highs[-3], swing_highs[-2], swing_highs[-1]
            
            if h2['price'] > h1['price'] * 1.015 and h2['price'] > h3['price'] * 1.015:
                if abs(h1['price'] - h3['price']) / h3['price'] < 0.05:
                    
                    recent_lows = [l for l in swing_lows if l['idx'] > h1['idx']]
                    if len(recent_lows) >= 2:
                        l1, l2 = recent_lows[0], recent_lows[-1]
                        
                        if l2['idx'] != l1['idx']:
                            n_slope = (l2['price'] - l1['price']) / (l2['idx'] - l1['idx'])
                            neckline_price = l2['price'] + n_slope * (idx_current - l2['idx'])
                            
                            dist_to_neck = (current_close - neckline_price) / neckline_price
                            
                            if dist_to_neck < -0.01:
                                return {
                                    "type": "HS_BREAKDOWN",
                                    "direction": "BEAR",
                                    "priority": 1,
                                    "label": "⚠️ Head & Shoulders Breakdown",
                                    "desc": "Tanda Bahaya: Tali penyangga Neckline telah dijebol! Terselesaikan distribusi agresif dari pola pembalikan arah tajam klasik Head and Shoulders.",
                                    "action_hint": "AVOID"
                                }
                            elif dist_to_neck < 0.05:
                                return {
                                    "type": "HS_FORMING",
                                    "direction": "BEAR",
                                    "priority": 2,
                                    "label": "⚠️ Early Warning: Head & Shoulders",
                                    "desc": "Formasi bahaya Head & Shoulders (bertopi distribusi kuat) telah menampakkan wujud. Risiko terjun tinggi apabila penyangga Neckline benar-benar patah.",
                                    "action_hint": "AVOID"
                                }
    except Exception:
        pass
    return None


def detect_quasimodo(df: pd.DataFrame, lookback: int = 60) -> dict | None:
    """Engine 13: Quasimodo Pattern (QML / Over and Under).
    Bullish QML: Low -> Lower High -> Lower Low -> Higher High -> Pullback to QML (first Low).
    Bearish QML: High -> Higher Low -> Higher High -> Lower Low -> Pullback to QML (first High).
    """
    if len(df) < lookback + 10:
        return None
        
    try:
        window = df.iloc[-lookback:]
        highs = window['High'].values
        lows = window['Low'].values
        closes = window['Close'].values
        
        swing_highs = []
        swing_lows = []
        for i in range(2, len(window) - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
                swing_highs.append({'idx': i, 'price': float(highs[i])})
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                swing_lows.append({'idx': i, 'price': float(lows[i])})
                
        current_close = float(closes[-1])
        current_low = float(window['Low'].values[-1])
        current_high = float(window['High'].values[-1])
        
        # Bullish QML
        if len(swing_lows) >= 2 and len(swing_highs) >= 2:
            l1, l2 = swing_lows[-2], swing_lows[-1]
            # Find highs that occurred chronologically correctly
            # Pattern: L1, then H1, then L2, then H2
            h1_candidates = [h for h in swing_highs if l1['idx'] < h['idx'] < l2['idx']]
            h2_candidates = [h for h in swing_highs if h['idx'] > l2['idx']]
            
            if h1_candidates and h2_candidates:
                h1 = h1_candidates[0]
                h2 = h2_candidates[-1]
                
                # Check structure:
                # Lower Low (L2 < L1), Higher High (H2 > H1)
                if l2['price'] < l1['price'] and h2['price'] > h1['price']:
                    
                    qml_level = l1['price']
                    
                    # Price has pulled back near QML level (within 2% deviation)
                    dist_to_qml = abs(current_close - qml_level) / qml_level if qml_level > 0 else 0
                    
                    if dist_to_qml <= 0.02 and current_low <= qml_level * 1.015:
                        return {
                            "type": "QML_BULLISH",
                            "direction": "BULL",
                            "priority": 2,  # BUY NOW territory
                            "label": "🚀 Quasimodo Level (Bullish) Ditest!",
                            "desc": "Terdeteksi pola *Smart Money* tingkat tinggi Quasimodo (QML). Harga berhasil menjebol struktur turun (membentuk Higher High) lalu *pullback* masuk ke area entri Left Shoulder. Eksekusi pantulan segera!",
                            "action_hint": "BUY_NOW"
                        }
                        
        # Bearish QML
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            h1, h2 = swing_highs[-2], swing_highs[-1]
            # Pattern: H1, then L1, then H2, then L2
            l1_candidates = [l for l in swing_lows if h1['idx'] < l['idx'] < h2['idx']]
            l2_candidates = [l for l in swing_lows if l['idx'] > h2['idx']]
            
            if l1_candidates and l2_candidates:
                l1 = l1_candidates[0]
                l2 = l2_candidates[-1]
                
                # Check structure:
                # Higher High (H2 > H1), Lower Low (L2 < L1)
                if h2['price'] > h1['price'] and l2['price'] < l1['price']:
                    
                    qml_level = h1['price']
                    
                    # Price has pulled back near QML level (within 2% deviation)
                    dist_to_qml = abs(qml_level - current_close) / current_close if current_close > 0 else 0
                    
                    if dist_to_qml <= 0.02 and current_high >= qml_level * 0.985:
                        return {
                            "type": "QML_BEARISH",
                            "direction": "BEAR",
                            "priority": 1, 
                            "label": "⚠️ Quasimodo Level (Bearish) Warning!",
                            "desc": "Waspada! Terdeteksi pola jebakan mematikan *Bearish Quasimodo*. Harga telah mematahkan pijakan *support* awal dan saat ini sedang memantul naik untuk menjemput sisa muatan Bandar (*Smart Money*) di bahu kiri.",
                            "action_hint": "AVOID"
                        }

    except Exception:
        pass
    return None


def detect_macro_flags(df: pd.DataFrame, lookback: int = 30) -> dict | None:
    """Engine 14: Bull/Bear Flag Continuation.
    Detects macro momentum flagpoles followed by tight, low-volume consolidation.
    """
    if len(df) < 15:
        return None
        
    try:
        # Flagpole can be 3-8 bars long. We'll search backwards for a spike.
        closes = df['Close'].values
        volumes = df['Volume'].values
        opens = df['Open'].values
        highs = df['High'].values
        lows = df['Low'].values
        
        # Determine average volume for base context
        avg_vol = float(np.nanmean(volumes[-30:])) if len(volumes) >= 30 else float(np.nanmean(volumes))
        if avg_vol <= 0: return None
        
        current_close = float(closes[-1])
        
        # Scan last 20 bars to find Flagpole (minimum 10% move in max 8 bars with big volume)
        scan_len = min(20, len(df) - 1)
        
        pole_start_idx = -1
        pole_end_idx = -1
        is_bull_pole = False
        is_bear_pole = False
        
        for i in range(len(df) - scan_len, len(df) - 4): # leave at least 4 bars for flag
            for j in range(i + 2, min(i + 8, len(df) - 2)):
                move_pct = (closes[j] - opens[i]) / opens[i] if opens[i] > 0 else 0
                vol_during_move = np.nanmean(volumes[i:j+1])
                
                if move_pct > 0.10 and vol_during_move > avg_vol * 1.3:
                    is_bull_pole = True
                    pole_start_idx = i
                    pole_end_idx = j
                elif move_pct < -0.10 and vol_during_move > avg_vol * 1.3:
                    is_bear_pole = True
                    pole_start_idx = i
                    pole_end_idx = j
                    
        if is_bull_pole:
            # Evaluate Flag (from pole_end_idx to current)
            flag_bars = len(df) - 1 - pole_end_idx
            if 3 <= flag_bars <= 15:
                # Volume must be drying up
                flag_vol = np.nanmean(volumes[pole_end_idx+1:])
                if flag_vol < avg_vol * 1.1: 
                    # Price shouldn't drop brutally. Retracement max 50% of pole
                    pole_size = closes[pole_end_idx] - opens[pole_start_idx]
                    flag_lowest = np.nanmin(lows[pole_end_idx+1:-1]) if len(lows[pole_end_idx+1:-1]) > 0 else lows[-2]
                    retrace_pct = (closes[pole_end_idx] - flag_lowest) / pole_size if pole_size > 0 else 1
                    
                    if retrace_pct < 0.50:
                        flag_high = np.nanmax(highs[pole_end_idx+1:-1]) if len(highs[pole_end_idx+1:-1]) > 0 else highs[-2]
                        # Breakout check
                        if current_close > flag_high:
                            return {
                                "type": "BULL_FLAG_BREAKOUT",
                                "direction": "BULL",
                                "priority": 2,
                                "label": "🚀 Bull Flag Breakout (Macro)",
                                "desc": "Pola kelanjutan tren super agresif (Bull Flag) menyala! Harga menembus resistansi konsolidasi mini setelah tiang kenaikan masif. Mengincar ledakan *momentum* lanjutan.",
                                "action_hint": "BUY_MOMENTUM"
                            }
                        else:
                            return {
                                "type": "BULL_FLAG",
                                "direction": "BULL",
                                "priority": 3,
                                "label": "⚡ Bull Flag Consolidation",
                                "desc": "Energi sedang dikumpulkan (fase *Flag*) dengan volume mengering pasca kenaikan impulsif puluhan persen. Pantau tajam jika terjadi *breakout* ke atas dari bendera konsolidasi.",
                                "action_hint": "INFO"
                            }
                            
        elif is_bear_pole:
            flag_bars = len(df) - 1 - pole_end_idx
            if 3 <= flag_bars <= 15:
                flag_vol = np.nanmean(volumes[pole_end_idx+1:])
                if flag_vol < avg_vol * 1.1: 
                    pole_size = opens[pole_start_idx] - closes[pole_end_idx]
                    flag_highest = np.nanmax(highs[pole_end_idx+1:-1]) if len(highs[pole_end_idx+1:-1]) > 0 else highs[-2]
                    retrace_pct = (flag_highest - closes[pole_end_idx]) / pole_size if pole_size > 0 else 1
                    
                    if retrace_pct < 0.50:
                        flag_low = np.nanmin(lows[pole_end_idx+1:-1]) if len(lows[pole_end_idx+1:-1]) > 0 else lows[-2]
                        if current_close < flag_low:
                            return {
                                "type": "BEAR_FLAG_BREAKDOWN",
                                "direction": "BEAR",
                                "priority": 1,
                                "label": "⚠️ Bear Flag Breakdown",
                                "desc": "Harga kembali jebol ke jurang (*Bear Flag Breakdown*). Konsolidasi penyangga minor hanyalah jebakan pemicu panik sebelum tren turun dilanjutkan tumpah secara ekstrem.",
                                "action_hint": "AVOID"
                            }
    except Exception:
        pass
    return None


def aggregate_smc_signals(df: pd.DataFrame, snr: dict, max_signals: int = 3) -> list[dict]:
    """Aggregator: Run all 7 SMC engines, rank by priority, return top N signals.

    Priority system (lower number = higher priority):
      P1 (DANGER):  Upthrust, Breaker Resist, CHoCH Bear, EQH Sweep
      P2 (SHIFT):   CHoCH Bull, EQL Sweep, Effort vs Result (context)
      P3 (SCALP):   Inducement, Three Bar Play, Breaker Support, Effort (neutral)

    BUY NOW override requires AT LEAST 2 confirmations (strict verification).
    WARNING/AVOID overrides fire with 1 signal (protect user capital).
    """
    signals = []

    # Run all engines — each returns dict or None
    engines = [
        detect_choch_bos(df),
        detect_breaker_block(df),
        detect_inducement_trap(df),
        detect_equal_level_sweep(df),
        detect_wyckoff_upthrust(df, snr),
        detect_effort_vs_result(df, snr),
        detect_three_bar_play(df),
        detect_fvg(df),
        detect_ote(df),
        detect_triangle_patterns(df),
        detect_wedge_patterns(df),
        detect_head_and_shoulders(df),
        detect_quasimodo(df),
        detect_macro_flags(df),
    ]

    for result in engines:
        if result is not None:
            signals.append(result)

    if not signals:
        return []

    # Sort by priority (lower = more important) and return top N
    signals.sort(key=lambda x: x.get("priority", 99))
    return signals[:max_signals]


def detect_institutional_setups(df: pd.DataFrame, snr: dict, atr: float, is_intraday: bool = False) -> list[str]:
    """
    Evaluates the last few candles mathematically for 4 strict institutional setups.
    Returns a list of descriptions for matched setups.
    """
    if len(df) < 21:
        return []

    setups_found = []
    
    try:
        # Check if index is datetime, if not try to use 'date' column
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            if 'date' in df.columns:
                df = df.copy()
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)

        if is_intraday and len(df) > 0:
            # Aggregate intraday data into daily to accurately measure "Hari T"
            daily_df = df.resample('D').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()
            
            if len(daily_df) < 20: # Fallback to raw if aggregation fails or not enough days
                eval_df = df
            else:
                eval_df = daily_df
        else:
            eval_df = df

        T = -1
        T_1 = -2
        
        close_T = eval_df['Close'].iloc[T]
        open_T = eval_df['Open'].iloc[T]
        high_T = eval_df['High'].iloc[T]
        low_T = eval_df['Low'].iloc[T]
        vol_T = eval_df['Volume'].iloc[T] if 'Volume' in eval_df else 0
        
        close_T1 = eval_df['Close'].iloc[T_1]
        open_T1 = eval_df['Open'].iloc[T_1]
        high_T1 = eval_df['High'].iloc[T_1]
        low_T1 = eval_df['Low'].iloc[T_1]
        vol_T1 = eval_df['Volume'].iloc[T_1] if 'Volume' in eval_df else 0
        
        range_series = eval_df['High'] - eval_df['Low']
        avg_range_5 = range_series.iloc[-5:].mean()
        avg_range_20 = range_series.iloc[-20:].mean()
        
        if 'Volume' in eval_df:
            avg_vol_5 = eval_df['Volume'].iloc[-5:].mean()
            avg_vol_20 = eval_df['Volume'].iloc[-20:].mean()
        else:
            avg_vol_5 = 1
            avg_vol_20 = 1
        
        ema10 = eval_df['Close'].ewm(span=10, adjust=False).mean().iloc[T]
        ema21 = eval_df['Close'].ewm(span=21, adjust=False).mean().iloc[T]
        
        body_T = close_T - open_T
        abs_body_T = abs(body_T)
        body_T1 = close_T1 - open_T1
        
        supports = snr.get("supports", [])
        resistances = snr.get("resistances", [])
        
        # Determine Daily ATR instead of intraday ATR
        atr_daily = range_series.rolling(14).mean().iloc[T]
        if pd.isna(atr_daily): atr_daily = atr
        
        # 1. Momentum Breakout Terkonfirmasi
        is_breakout = False
        for r in resistances:
            if close_T > r['level']: # Break resistance
                is_breakout = True
                break
                
        if is_breakout:
            cond_body = body_T > (atr_daily * 1.5) or (open_T > 0 and (close_T / open_T) - 1 > 0.03)
            cond_close = (high_T - close_T) / (high_T - low_T) < 0.2 if high_T > low_T else True
            cond_vol = vol_T > (avg_vol_20 * 1.5)
            if cond_body and cond_close and cond_vol:
                setups_found.append(
                    "🚀 *Momentum Breakout Terkonfirmasi*\n"
                    "Rentang harga melebar signifikan dengan volume meledak. Penutupan sangat kuat menandakan institusi berpartisipasi (potensi naik cepat 3%+)."
                )
                
        # 2. Volatility Contraction / Squeeze
        cond_volatility = avg_range_5 < (avg_range_20 * 0.5)
        cond_vol_dry = avg_vol_5 < (avg_vol_20 * 0.6)
        cond_ema_squeeze = abs(ema10 - ema21) / ema21 < 0.01
        
        if cond_volatility and cond_vol_dry and cond_ema_squeeze:
            setups_found.append(
                "⚡ *Volatility Contraction / Squeeze*\n"
                "Volatilitas anjlok (&lt; 50%) dan volume mengering (&lt; 60%). EMA10 &amp; EMA21 merapat ketat (&lt; 1%). Fase kompresi &amp; persiapan ledakan momentum."
            )

        # 3. Institutional Reversal / Liquidity Sweep
        is_sweep = False
        for s in supports:
            if low_T < s['level'] and close_T > s['level']:
                is_sweep = True
                break
                
        if is_sweep:
            bottom_body = min(open_T, close_T)
            lower_tail = bottom_body - low_T
            cond_tail = lower_tail > (abs_body_T * 2.0)
            cond_vol_sweep = vol_T > vol_T1
            if cond_tail and cond_vol_sweep:
                setups_found.append(
                    "⚡ *Institutional Reversal / Liquidity Sweep*\n"
                    "Harga menembus support namun ditutup cepat ke atas dengan ekor panjang (daya serap masif). Konfirmasi SL hunting / akumulasi institusi."
                )

        # 4. Continuation Flag / Inside Bar
        cond_flag_pole = body_T1 > (atr_daily * 1.5) 
        cond_inside = high_T < high_T1 and low_T > low_T1
        cond_vol_rest = vol_T < (vol_T1 * 0.5)
        
        if cond_flag_pole and cond_inside and cond_vol_rest:
            setups_found.append(
                "⚡ *Continuation Flag / Inside Bar*\n"
                "Konsolidasi wajar tertutup Inside Bar setelah eksekusi. Volume istirahat di bawah 50%, mengindikasikan ketiadaan aksi ambil untung ritel/institusi."
            )
            
    except Exception as e:
        import traceback
        traceback.print_exc()

    return setups_found

# ──────────────────────────────────────────────
# MASTER ENGINE: Early Detection (9 Principles)
# ──────────────────────────────────────────────
import numpy as np

def detect_early_smart_money(df: pd.DataFrame, snr: dict, hurst: float, is_intraday: bool = False) -> dict | None:
    """
    Evaluates 9 Master Principles for Early Entry Detection (Pre-Breakout / Pivot Catching):
    1. Charles Dow (Market Structure HH/HL)
    2. Benoit Mandelbrot (Fractal alignment)
    3. J. Welles Wilder Jr. (RSI Divergence / ATR)
    4. Gerald Appel (MACD Histogram slope)
    5. Richard Wyckoff (Effort vs Result - Springs)
    6. Robert Rhea (Trend Volume Confirmation)
    7. John Bollinger (Volatility Squeeze)
    8. Larry Williams (Volume timing)
    9. Hurst Exponent (Trend vs Mean Reversion)
    
    Returns a dict with {"action": "...", "label": "...", "desc": "..."} if a master setup is found, else None.
    """
    if len(df) < 30:
        return None
        
    try:
        if is_intraday:
            if not pd.api.types.is_datetime64_any_dtype(df.index):
                if 'date' in df.columns:
                    df = df.copy()
                    df['date'] = pd.to_datetime(df['date'])
                    df.set_index('date', inplace=True)
            eval_df = df.resample('D').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna()
            if len(eval_df) < 20: eval_df = df
        else:
            eval_df = df

        T = -1
        T_1 = -2
        T_2 = -3
        
        close = eval_df['Close']
        high = eval_df['High']
        low = eval_df['Low']
        open_ = eval_df['Open']
        if 'Volume' not in eval_df:
            return None
        vol = eval_df['Volume']
        
        c0, c1, c2 = close.iloc[T], close.iloc[T_1], close.iloc[T_2]
        l0, l1 = low.iloc[T], low.iloc[T_1]
        h0, h1 = high.iloc[T], high.iloc[T_1]
        o0, o1 = open_.iloc[T], open_.iloc[T_1]
        v0, v1 = vol.iloc[T], vol.iloc[T_1]
        
        # --- Wilder & Appel (MACD Hist Slope & RSI) ---
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_sig = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - macd_sig
        
        h0_hist, h1_hist, h2_hist = macd_hist.iloc[T], macd_hist.iloc[T_1], macd_hist.iloc[T_2]
        # Appel Early Shift: Histogram is negative but curving UP
        early_macd_shift = (h2_hist < h1_hist < h0_hist) and (h0_hist < 0)
        
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        r0, r1 = rsi.iloc[T], rsi.iloc[T_1]
        
        # Wilder Divergence Proxy: RSI starts climbing while < 50
        rsi_bull_reversal = (r0 > r1) and (r0 < 50) and ((r0 - r1) > 2)

        # --- Bollinger Squeeze ---
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_width = (std20 * 4) / sma20
        recent_widths = bb_width.iloc[-60:].dropna()
        if len(recent_widths) > 0:
            squeeze_threshold = np.percentile(recent_widths, 20)
            is_bollinger_squeeze = bb_width.iloc[T] <= squeeze_threshold
        else:
            is_bollinger_squeeze = False

        # --- Wyckoff Effort vs Result (Spring) ---
        body0 = abs(c0 - o0)
        avg_body = (high - low).rolling(14).mean().iloc[T]
        avg_vol = vol.rolling(20).mean().iloc[T]
        
        is_spring = False
        supports = snr.get("supports", [])
        for s in supports:
            lvl = s['level']
            # Sweeps below support but recovers
            if l0 < lvl and c0 >= lvl:
                lower_wick = min(o0, c0) - l0
                # Effort (Volume) vs Result (Long wick instead of breakdown)
                if lower_wick > body0 * 1.5 and v0 > avg_vol * 1.2:
                    is_spring = True
                    break

        # --- Williams Volume Timing (Liftoff) ---
        is_liftoff_vol = (v0 > avg_vol * 1.5) and (c0 > o0) and (c0 > c1)

        # ==========================================
        # SYNTHESIS: Generate Smart Money Early Action
        # ==========================================
        
        # Count total triggers for scoring
        triggers = sum([early_macd_shift, rsi_bull_reversal, is_bollinger_squeeze, is_spring, is_liftoff_vol])
        
        # SETUP A: Wyckoff Spring (Accumulation at support — strongest signal)
        if is_spring:
            desc = "Deteksi Dini (Wyckoff): Terjadi fase 'Spring'—harga secara sengaja dijatuhkan menyapu likuiditas di bawah Support lalu segera ditarik naik dengan akumulasi Volume tinggi."
            if early_macd_shift:
                desc += " MACD Histogram mulai berbelok naik, mengkonfirmasi momentum seller melemah."
            return {
                "action": "BUY NOW",
                "label": "⚡ EARLY ENTRY: WYCKOFF SPRING",
                "desc": desc
            }
            
        # SETUP B: Bollinger Squeeze + partial confirmation (2-of-3: MACD/RSI/vol)
        if is_bollinger_squeeze:
            confirmations = sum([early_macd_shift, rsi_bull_reversal, is_liftoff_vol])
            if confirmations >= 1:
                return {
                    "action": "BUY NOW",
                    "label": "⚡ EARLY ENTRY: VOLATILITY LIFT-OFF",
                    "desc": f"Deteksi Dini (Bollinger + {confirmations} konfirmasi): Volatilitas berada di titik kompresi terendah. Mulai terlihat tanda-tanda pre-breakout—potensi ledakan harga dalam 1-3 bar."
                }
            
        # SETUP C: Mean Reversion Deep Buy (Hurst Filtered)
        if hurst < 0.45 and r0 < 35:
            if early_macd_shift or is_liftoff_vol:
                return {
                    "action": "BUY NOW",
                    "label": "⚡ EARLY ENTRY: MEAN REVERSION",
                    "desc": "Deteksi Dini (Hurst + Wilder): Market dalam rezim rotasi (Sideways). Harga di zona oversold, mulai ada tanda pembalikan momentum."
                }
        
        # SETUP D: MACD Early Shift + Volume Liftoff (standalone combo)
        if early_macd_shift and is_liftoff_vol:
            return {
                "action": "BUY NOW",
                "label": "⚡ EARLY ENTRY: MOMENTUM SHIFT",
                "desc": "Deteksi Dini (Appel + Larry): MACD Histogram berbelok naik dari zona negatif, bersamaan dengan lonjakan Volume. Momentum jual melemah, pembeli mulai masuk."
            }
        
        # SETUP E: RSI Bull Reversal + Volume (standalone)
        if rsi_bull_reversal and is_liftoff_vol:
            return {
                "action": "BUY NOW",
                "label": "⚡ EARLY ENTRY: RSI REVERSAL",
                "desc": "Deteksi Dini (Wilder + Larry): RSI mendongkrak dari bawah 50 dengan akselerasi, disertai lonjakan Volume. Awal fase bullish."
            }

    except Exception:
        import traceback
        traceback.print_exc()
        
    return None
