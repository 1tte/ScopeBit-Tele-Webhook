"""
Breakout & ATH Detection Engine with Continuation/Reversal Logic

Detects:
- All-Time High (ATH) and near-ATH levels
- Breakout patterns and their strength
- Continuation vs reversal probability
- Next-day bias prediction
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime


def detect_ath_level(df: pd.DataFrame, lookback_days: int = 252) -> Dict[str, Any]:
    """
    Detect All-Time High and near-ATH levels.

    Returns:
        Dict with ath_price, ath_date, distance_from_ath, ath_strength
    """
    if len(df) < 20:
        return {"is_ath": False, "ath_price": 0, "ath_date": None, "distance_pct": 0}

    recent_df = df.tail(lookback_days)
    highs = recent_df["High"].values
    dates = recent_df.index

    ath_price = np.max(highs)
    ath_idx = np.argmax(highs)
    ath_date = dates[ath_idx]

    current_price = recent_df["Close"].iloc[-1]
    distance_from_ath = ((ath_price - current_price) / ath_price) * 100

    # Determine if we're at/near ATH
    is_near_ath = distance_from_ath <= 2.0  # Within 2% of ATH
    is_at_ath = distance_from_ath <= 0.5   # Within 0.5% of ATH

    return {
        "ath_price": float(ath_price),
        "ath_date": ath_date,
        "current_price": float(current_price),
        "distance_pct": float(distance_from_ath),
        "is_near_ath": is_near_ath,
        "is_at_ath": is_at_ath,
    }


def detect_recent_resistance_levels(df: pd.DataFrame, lookback: int = 20) -> List[Dict[str, Any]]:
    """
    Detect recent resistance levels that could act as ATH or breakout points.
    Returns multiple potential resistance levels sorted by strength.
    """
    if len(df) < lookback:
        return []

    recent = df.tail(lookback)
    highs = recent["High"].values
    volumes = recent["Volume"].values

    resistances = []

    # Find local peaks (3-bar pattern)
    for i in range(1, len(recent) - 1):
        if highs[i] > highs[i-1] and highs[i] >= highs[i+1]:
            level = float(highs[i])
            volume = float(volumes[i])
            avg_volume = float(np.mean(volumes))

            strength = (volume / avg_volume) * 1.5 if avg_volume > 0 else 1.0

            resistances.append({
                "level": level,
                "volume_ratio": volume / avg_volume if avg_volume > 0 else 1.0,
                "strength": strength,
                "bars_ago": len(recent) - i
            })

    # Sort by strength (volume-weighted)
    resistances.sort(key=lambda x: x["strength"], reverse=True)
    return resistances[:3]


def analyze_breakout_strength(df: pd.DataFrame, level: float, volume_threshold: float = 1.2) -> Dict[str, Any]:
    """
    Analyze if a breakout above a level is strong or weak.

    Strong breakout: High volume, sustained price, bullish candles
    Weak breakout: Low volume, quick rejection, indecision
    """
    if len(df) < 5:
        return {"strength": "UNKNOWN", "score": 0}

    recent = df.tail(5)
    closes = recent["Close"].values
    volumes = recent["Volume"].values
    opens = recent["Open"].values

    current_price = closes[-1]
    above_level = current_price > level

    # Volume analysis
    avg_vol = float(np.mean(volumes[:-1])) if len(volumes) > 1 else float(np.mean(volumes))
    current_vol = float(volumes[-1])
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

    # Price momentum
    price_change = ((current_price - closes[0]) / closes[0]) * 100

    # Candle strength (% of candle that's body)
    body_size = abs(current_price - opens[-1])
    candle_range = recent["High"].iloc[-1] - recent["Low"].iloc[-1]
    body_ratio = body_size / candle_range if candle_range > 0 else 0.5

    # Score calculation
    score = 0

    # Volume component (0-40 points)
    if vol_ratio >= 2.0:
        score += 40
    elif vol_ratio >= 1.5:
        score += 30
    elif vol_ratio >= volume_threshold:
        score += 20
    elif vol_ratio >= 1.0:
        score += 10

    # Price continuation (0-35 points)
    if price_change >= 3.0:
        score += 35
    elif price_change >= 2.0:
        score += 25
    elif price_change >= 1.0:
        score += 15

    # Candle strength (0-25 points)
    if body_ratio >= 0.7:
        score += 25
    elif body_ratio >= 0.5:
        score += 15

    # Classification
    if score >= 70:
        strength = "STRONG"
        outlook = "CONTINUATION"
    elif score >= 50:
        strength = "MODERATE"
        outlook = "LIKELY_CONT"
    elif score >= 30:
        strength = "WEAK"
        outlook = "RETEST_NEEDED"
    else:
        strength = "FAILED"
        outlook = "REVERSAL"

    return {
        "level": float(level),
        "current_price": float(current_price),
        "above_level": above_level,
        "volume_ratio": round(vol_ratio, 2),
        "volume_vs_avg": current_vol,
        "avg_volume": avg_vol,
        "price_change_pct": round(price_change, 2),
        "body_ratio": round(body_ratio, 2),
        "strength": strength,
        "outlook": outlook,
        "score": score
    }


def detect_breakout_scenario(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Detect breakout scenario and predict next day bias.

    Returns:
        scenario: "BREAKOUT_STRONG", "BREAKOUT_WEAK", "NEAR_ATH", "RETEST_NEEDED"
        bias: "BULLISH", "BEARISH", "NEUTRAL"
        confidence: 0-100
        levels: List of relevant S/R levels
    """
    result = {
        "scenario": "NEUTRAL",
        "bias": "NEUTRAL",
        "confidence": 0,
        "levels": [],
        "notes": []
    }

    # Get ATH info
    ath_info = detect_ath_level(df)

    # Get recent resistances
    resistances = detect_recent_resistance_levels(df)

    if ath_info["is_at_ath"]:
        result["scenario"] = "AT_ATH"
        result["notes"].append("Price at All-Time High")

        # Analyze breakout strength at ATH
        breakout = analyze_breakout_strength(df, ath_info["ath_price"])
        result["levels"].append(
            {
                "type": "ATH",
                "level": breakout["level"],
                "strength": breakout["strength"],
                "outlook": breakout["outlook"],
                "score": breakout["score"]
            }
        )

        # Determine bias
        if breakout["strength"] == "STRONG":
            result["bias"] = "BULLISH"
            result["confidence"] = 85
            result["notes"].append(f"Strong breakout at ATH: {breakout['strength']}")
        elif breakout["strength"] == "MODERATE":
            result["bias"] = "CAUTIOUS_BULLISH"
            result["confidence"] = 60
            result["notes"].append(f"Moderate breakout: expect retest")
        else:
            result["bias"] = "BEARISH"
            result["confidence"] = 70
            result["notes"].append(f"Weak breakout: likely reversal to {breakout['level']}")

    elif ath_info["is_near_ath"]:
        result["scenario"] = "NEAR_ATH"
        result["notes"].append(f"Price near ATH ({ath_info['distance_pct']:.1f}% below)")

        # Check if it's likely to break ATH
        recent_momentum = detect_momentum(df)

        if recent_momentum["strength"] == "STRONG":
            result["bias"] = "BULLISH"
            result["confidence"] = 75
            result["notes"].append("Strong momentum suggests ATH breakout likely")
        else:
            result["bias"] = "NEUTRAL"
            result["confidence"] = 50
            result["notes"].append("Consolidating near ATH, watch for volume")

    elif resistances:
        # Not near ATH, but check major resistances
        top_resistance = resistances[0]

        # Check if we're breaking this level now
        current_price = ath_info["current_price"]
        if current_price > top_resistance["level"]:
            breakout = analyze_breakout_strength(df, top_resistance["level"])

            result["scenario"] = "BREAKOUT_RESISTANCE"
            result["levels"].append(
                {
                    "type": "RESISTANCE",
                    "level": breakout["level"],
                    "strength": breakout["strength"],
                    "outlook": breakout["outlook"]
                }
            )

            if breakout["strength"] == "STRONG":
                result["bias"] = "BULLISH"
                result["confidence"] = 80
            elif breakout["strength"] == "MODERATE":
                result["bias"] = "CAUTIOUS_BULLISH"
                result["confidence"] = 60
            else:
                result["bias"] = "BEARISH"
                result["confidence"] = 65

        else:
            result["scenario"] = "BELOW_RESISTANCE"
            result["bias"] = "NEUTRAL"
            result["confidence"] = 40
            result["notes"].append(f"Below resistance at {top_resistance['level']}")

    else:
        result["scenario"] = "RANGING"
        result["bias"] = "NEUTRAL"
        result["confidence"] = 30
        result["notes"].append("No clear ATH or resistance levels detected")

    return result


def detect_momentum(df: pd.DataFrame, lookback: int = 7) -> Dict[str, Any]:
    """Detect recent price momentum strength."""
    if len(df) < lookback:
        return {"strength": "UNKNOWN", "score": 0}

    recent = df.tail(lookback)
    closes = recent["Close"].values
    volumes = recent["Volume"].values

    # Price change
    price_change = ((closes[-1] - closes[0]) / closes[0]) * 100

    # Average volume over period
    avg_vol_ratio = float(np.mean(volumes[-3:]) / np.mean(volumes[:-3])) if len(volumes) > 3 else 1.0

    # Count green days
    if len(closes) > 1:
        daily_returns = np.diff(closes) / closes[:-1] * 100
        green_days = np.sum(daily_returns > 0)
    else:
        green_days = 0

    score = 0

    # Price component
    if price_change >= 5:
        score += 40
    elif price_change >= 3:
        score += 30
    elif price_change >= 1:
        score += 15

    # Volume component
    if avg_vol_ratio >= 1.5:
        score += 30
    elif avg_vol_ratio >= 1.2:
        score += 20

    # Consistency component
    if green_days >= 5:
        score += 30
    elif green_days >= 4:
        score += 20

    if score >= 70:
        strength = "STRONG"
    elif score >= 50:
        strength = "MODERATE"
    elif score >= 30:
        strength = "WEAK"
    else:
        strength = "NONE"

    return {
        "strength": strength,
        "price_change_pct": round(price_change, 2),
        "avg_volume_ratio": round(avg_vol_ratio, 2),
        "green_days": green_days,
        "score": score
    }


def generate_breakout_caption(symbol: str, df: pd.DataFrame) -> str:
    """
    Generate breakout analysis caption for Telegram.
    Returns the formatted breakout analysis string or empty string.
    """
    breakout = detect_breakout_scenario(df) # Improved engine

    ath_info = detect_ath_level(df)
    momentum = detect_momentum(df)

    # Build breakout analysis section
    breakout_lines = []

    # ATH detection
    if ath_info["is_at_ath"]:
        breakout_lines.append(f"ATH Breakout")
    elif ath_info["is_near_ath"]:
        breakout_lines.append(f"Near ATH ({ath_info['distance_pct']:.1f}% below)")

    # Breakout strength
    if breakout["levels"]:
        level = breakout["levels"][0]
        breakout_lines.append(f"{level['strength']} Breakout at {int(level['level']):,}")
        breakout_lines.append(f"   Outlook: {level['outlook'].replace('_', ' ')}")

    # Bias and confidence
    if breakout["confidence"] > 60:
        emoji = "🚀"
    elif breakout["confidence"] > 40:
        emoji = "⚡"
    else:
        emoji = "⚠️"

    breakout_lines.append(f"{emoji} Next Day Bias: {breakout['bias'].replace('_', ' ')}")
    breakout_lines.append(f"   Confidence: {breakout['confidence']}%")

    # Momentum
    breakout_lines.append(f"Momentum: {momentum['strength']} ({momentum['price_change_pct']:.1f}% in {len(df.tail(7))}d)")

    # Notes
    if breakout["notes"]:
        breakout_lines.append(f" Note: {breakout['notes'][0]}")

    # Separator
    if breakout_lines:
        separator = "━" * 34
        full_caption = (
            f"<b>BREAKOUT ANALYSIS</b>\n" +
            "<code>" +
            "\n".join(breakout_lines) +
            "\n" +
            separator +
            "</code>"
        )
        return full_caption

    return ""
