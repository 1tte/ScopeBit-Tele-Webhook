"""
Shared Technical Analysis Module
=================================
Implements institutional-grade technical analysis inspired by ScopeBit Extension:
- Fractal S&R detection with volume-weighted strength scoring
- Hurst Exponent (R/S Analysis) for regime detection
- ATR with volatility regime classification
- Market structure classification

Reference: knowledge.txt (ScopeBit Extension Knowledge Base)
"""
import math
import numpy as np
import pandas as pd
from typing import Optional


# ──────────────────────────────────────────────
# Fractional Tick System (Fraksi Harga BEI)
# ──────────────────────────────────────────────

def _get_idx_tick(price: float) -> int:
    """Get the tick size for a given price level."""
    if price <= 0: return 1
    elif price < 200: return 1
    elif price < 500: return 2
    elif price < 2000: return 5
    elif price < 5000: return 10
    else: return 25


def round_to_idx_tick(price: float) -> int:
    """Rounds a price to the nearest valid IDX tick fraction."""
    if price <= 0: return 0
    tick = _get_idx_tick(price)
    return int(round(price / tick) * tick)


def round_to_idx_tick_floor(price: float) -> int:
    """Rounds DOWN to nearest valid IDX tick (safer for SL & TP)."""
    if price <= 0: return 0
    tick = _get_idx_tick(price)
    return int(math.floor(price / tick) * tick)


def round_to_idx_tick_ceil(price: float) -> int:
    """Rounds UP to nearest valid IDX tick (conservative for buy_high)."""
    if price <= 0: return 0
    tick = _get_idx_tick(price)
    return int(math.ceil(price / tick) * tick)


# ──────────────────────────────────────────────
# Data Sanitization (Zero-Volume Bar Filtering)
# ──────────────────────────────────────────────

def sanitize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Remove zero-volume bars (dead bars) common in IDX low-liquidity stocks.
    Forward-fills any resulting gaps to maintain series continuity.
    Returns a sanitized copy of the DataFrame."""
    if df.empty:
        return df
    
    original_len = len(df)
    
    # Drop bars where Volume is 0 or NaN
    mask = df['Volume'].fillna(0) > 0
    df_clean = df[mask].copy()
    
    dropped = original_len - len(df_clean)
    
    # If too many bars dropped (>50%), keep original to avoid data starvation
    if len(df_clean) < 20 or dropped > original_len * 0.5:
        return df
    
    return df_clean


# ──────────────────────────────────────────────
# EMA (Exponential Moving Average)
# ──────────────────────────────────────────────

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """EMA = (Close - EMA_prev) × 2/(N+1) + EMA_prev"""
    return series.ewm(span=period, adjust=False).mean()


# ──────────────────────────────────────────────
# ATR (Average True Range) + Volatility Regime
# ──────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, dict]:
    """
    Calculate ATR and classify volatility regime.
    
    Returns:
        (atr_series, info_dict)
        info_dict keys: atr, regime, atr_pct
    """
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_series = tr.ewm(span=period, adjust=False).mean()
    
    latest_atr = atr_series.iloc[-1]
    latest_price = close.iloc[-1]
    
    # Cap ATR at 20% of price (prevent insane values on penny stocks)
    if latest_price > 0:
        max_atr = latest_price * 0.20
        latest_atr = min(latest_atr, max_atr)
    
    atr_pct = (latest_atr / latest_price * 100) if latest_price > 0 else 0
    
    # Classify volatility regime
    if atr_pct > 5:
        regime = "HIGH"
    elif atr_pct < 1:
        regime = "LOW"
    else:
        regime = "NORMAL"
    
    return atr_series, {
        "atr": latest_atr,
        "regime": regime,
        "atr_pct": atr_pct,
    }


# ──────────────────────────────────────────────
# RSI (Relative Strength Index) — Wilder Smoothing
# ──────────────────────────────────────────────

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ──────────────────────────────────────────────
# Hurst Exponent (Rescaled Range Analysis)
# ──────────────────────────────────────────────

def calc_hurst(closes: pd.Series, max_lag: int = 20) -> tuple[float, str]:
    """
    Calculate Hurst Exponent via R/S Analysis.
    
    Interpretation:
        H > 0.6  → TRENDING (Persistent)
        H ≈ 0.5  → RANDOM WALK
        H < 0.45 → MEAN REVERTING
    
    Returns:
        tuple[float, str]: (hurst_value, confidence)
        confidence: "HIGH" if data >= 2*max_lag, "LOW" otherwise.
    """
    prices = closes.dropna().values
    n_bars = len(prices)
    confidence = "HIGH" if n_bars >= 2 * max_lag else "LOW"
    
    if n_bars < max_lag + 5:
        return 0.5, confidence  # insufficient data
    
    lags = range(2, max_lag + 1)
    rs_values = []
    lag_values = []
    
    for lag in lags:
        # Split into sub-series of length 'lag'
        n_subseries = n_bars // lag
        if n_subseries < 1:
            continue
        
        rs_for_lag = []
        for i in range(n_subseries):
            subseries = prices[i * lag:(i + 1) * lag]
            if len(subseries) < 2:
                continue
            
            mean_val = np.mean(subseries)
            deviations = subseries - mean_val
            cumulative_dev = np.cumsum(deviations)
            
            r = np.max(cumulative_dev) - np.min(cumulative_dev)
            s = np.std(subseries, ddof=1)
            
            if s > 0 and r > 0:
                rs_for_lag.append(r / s)
        
        if rs_for_lag:
            rs_values.append(np.log(np.mean(rs_for_lag)))
            lag_values.append(np.log(lag))
    
    if len(rs_values) < 3:
        return 0.5, confidence
    
    # Linear regression: log(R/S) = H * log(lag) + c
    rs_arr = np.array(rs_values)
    lag_arr = np.array(lag_values)
    
    n = len(rs_arr)
    sum_x = np.sum(lag_arr)
    sum_y = np.sum(rs_arr)
    sum_xy = np.sum(lag_arr * rs_arr)
    sum_xx = np.sum(lag_arr * lag_arr)
    
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-10:
        return 0.5, confidence
    
    hurst = (n * sum_xy - sum_x * sum_y) / denom
    
    # Clamp to valid range
    return max(0.01, min(0.99, hurst)), confidence


# ──────────────────────────────────────────────
# Support & Resistance Detection (Fractal + Volume + Clustering)
# ──────────────────────────────────────────────

def detect_gaps(df: pd.DataFrame, min_gap_pct: float = 0.5) -> list:
    """
    Detect unfilled gaps (up and down) in the recent price history.
    Gap Up: Low of Day T > High of Day T-1
    Gap Down: High of Day T < Low of Day T-1
    
    Returns a list of gap dictionaries:
    [{"type": "gap_up", "top": level, "bottom": level, "strength": 90, "filled": False, "date": date}]
    """
    gaps = []
    if len(df) < 2:
        return gaps
        
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    dates = df.index
    
    for i in range(1, len(df)):
        prev_high = highs[i-1]
        prev_low = lows[i-1]
        prev_close = closes[i-1]
        
        curr_high = highs[i]
        curr_low = lows[i]
        curr_open = df["Open"].iloc[i]
        
        # Gap Up: Gap between prev_high and curr_low
        if curr_low > prev_high:
            gap_size_pct = ((curr_low - prev_high) / prev_high) * 100
            if gap_size_pct >= min_gap_pct:
                gaps.append({
                    "type": "gap_up",
                    "top": float(curr_low),
                    "bottom": float(prev_high),
                    "strength": 80,  # Gaps act as strong support/resistance
                    "idx": i,
                    "date": dates[i]
                })
                
        # Gap Down: Gap between prev_low and curr_high
        elif curr_high < prev_low:
            gap_size_pct = ((prev_low - curr_high) / curr_high) * 100
            if gap_size_pct >= min_gap_pct:
                gaps.append({
                    "type": "gap_down",
                    "top": float(prev_low),
                    "bottom": float(curr_high),
                    "strength": 80,
                    "idx": i,
                    "date": dates[i]
                })
                
    # Check if gaps were filled by subsequent price action
    active_gaps = []
    for gap in gaps:
        gap_idx = gap["idx"]
        is_filled = False
        
        # Look at all days AFTER the gap
        subsequent_lows = lows[gap_idx+1:]
        subsequent_highs = highs[gap_idx+1:]
        
        if gap["type"] == "gap_up":
            # Gap up is filled if price drops below the initial prev_high (gap bottom)
            if len(subsequent_lows) > 0 and np.min(subsequent_lows) <= gap["bottom"]:
                is_filled = True
            # Or partially filled/touched
            elif len(subsequent_lows) > 0 and np.min(subsequent_lows) <= gap["top"]:
                # Reduce strength if partially filled
                gap["strength"] -= 20
        else: # gap_down
            # Gap down is filled if price rises above the initial prev_low (gap top)
            if len(subsequent_highs) > 0 and np.max(subsequent_highs) >= gap["top"]:
                is_filled = True
            # Or partially filled/touched
            elif len(subsequent_highs) > 0 and np.max(subsequent_highs) >= gap["bottom"]:
                gap["strength"] -= 20
                
        if not is_filled:
            active_gaps.append(gap)
            
    return active_gaps

def detect_support_resistance(df: pd.DataFrame, atr: float, current_price: float) -> dict:
    """
    Detect support and resistance levels using hybrid approach:
    1. Fractal pivot detection (2-bar swing high/low)
    2. Volume-weighted strength scoring
    3. Cluster nearby levels (tolerance = ATR × 0.5)
    4. Recency scoring
    
    Returns:
        dict with keys: supports, resistances
        Each is a list of {level, strength, touches, type} sorted by strength desc
    """
    if len(df) < 10 or atr <= 0:
        return {"supports": [], "resistances": []}
    
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    volumes = df["Volume"].values
    
    total_bars = len(df)
    avg_vol = np.mean(volumes) if np.mean(volumes) > 0 else 1
    
    # Clustering tolerance: narrower for precision
    tolerance = atr * 0.5
    tolerance_pct = tolerance / current_price if current_price > 0 else 0.02
    
    # Precompute rolling minima and maxima for timeframe analysis
    monthly_lows = df["Low"].rolling(window=41, center=True, min_periods=1).min().values
    weekly_lows = df["Low"].rolling(window=11, center=True, min_periods=1).min().values
    monthly_highs = df["High"].rolling(window=41, center=True, min_periods=1).max().values
    weekly_highs = df["High"].rolling(window=11, center=True, min_periods=1).max().values
    
    # ── Step 1: Detect Fractal Pivots ──
    raw_supports = []
    raw_resistances = []
    
    for i in range(2, total_bars - 2):
        # Fractal swing low (support candidate) - Relaxed to allow flat bottoms
        if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] and lows[i] <= lows[i+1] and lows[i] <= lows[i+2]:
            vol_score = volumes[i] / avg_vol if avg_vol > 0 else 1
            recency = (i / total_bars)  # 0.0 = oldest, 1.0 = newest
            
            is_monthly = bool(lows[i] <= monthly_lows[i])
            is_weekly = False if is_monthly else bool(lows[i] <= weekly_lows[i])
            timeframe = "Monthly" if is_monthly else ("Weekly" if is_weekly else "Daily")
            
            raw_supports.append({
                "level": float(lows[i]),
                "vol_score": vol_score,
                "recency": recency,
                "bar_idx": i,
                "timeframe": timeframe,
            })
        
        # Fractal swing high (resistance candidate) - Relaxed to allow flat tops
        if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
            vol_score = volumes[i] / avg_vol if avg_vol > 0 else 1
            recency = (i / total_bars)
            
            is_monthly = bool(highs[i] >= monthly_highs[i])
            is_weekly = False if is_monthly else bool(highs[i] >= weekly_highs[i])
            timeframe = "Monthly" if is_monthly else ("Weekly" if is_weekly else "Daily")
            
            raw_resistances.append({
                "level": float(highs[i]),
                "vol_score": vol_score,
                "recency": recency,
                "bar_idx": i,
                "timeframe": timeframe,
            })
            
    # Fallbacks if no fractals found (e.g. straight line trend)
    if not raw_supports:
        min_idx = np.argmin(lows)
        raw_supports.append({
            "level": float(lows[min_idx]),
            "vol_score": 1,
            "recency": min_idx / total_bars,
            "bar_idx": min_idx,
            "timeframe": "Monthly"
        })
        
    if not raw_resistances:
        max_idx = np.argmax(highs)
        raw_resistances.append({
            "level": float(highs[max_idx]),
            "vol_score": 1,
            "recency": max_idx / total_bars,
            "bar_idx": max_idx,
            "timeframe": "Monthly"
        })
        
    # ── Step 1.5: Incorporate Gaps ──
    unfilled_gaps = detect_gaps(df, min_gap_pct=0.5)
    for gap in unfilled_gaps:
        recency = gap["idx"] / total_bars
        if gap["type"] == "gap_up":
            # Gap Up acts as support (top of gap is first support, bottom is second)
            raw_supports.append({
                "level": gap["top"],
                "vol_score": 2.0,  # High weighting for gaps
                "recency": recency,
                "bar_idx": gap["idx"],
                "is_gap": True,
                "timeframe": "Daily"
            })
        else:
            # Gap Down acts as resistance (bottom of gap is first resistance)
            raw_resistances.append({
                "level": gap["bottom"],
                "vol_score": 2.0,
                "recency": recency,
                "bar_idx": gap["idx"],
                "is_gap": True,
                "timeframe": "Daily"
            })
    
    # ── Step 2: Cluster Nearby Levels ──
    supports = _cluster_levels(raw_supports, tolerance, df, atr, is_support=True)
    resistances = _cluster_levels(raw_resistances, tolerance, df, atr, is_support=False)
    
    # ── Step 3: Filter by relevance to current price ──
    # Supports: only below or at current price (within 50%)
    supports = [s for s in supports if s["level"] <= current_price and s["level"] > current_price * 0.70]
    # Resistances: only above or at current price (within 50%)
    resistances = [r for r in resistances if r["level"] >= current_price and r["level"] < current_price * 1.30]
    
    # Sort by strength descending
    supports.sort(key=lambda x: x["strength"], reverse=True)
    resistances.sort(key=lambda x: x["strength"], reverse=True)
    
    return {
        "supports": supports[:5],
        "resistances": resistances[:5],
    }


def _cluster_levels(raw_levels: list, tolerance: float, df: pd.DataFrame, atr: float, is_support: bool) -> list:
    """Cluster nearby levels and compute strength scores."""
    if not raw_levels:
        return []
    
    # Sort by level
    sorted_levels = sorted(raw_levels, key=lambda x: x["level"])
    
    clusters = []
    used = set()
    
    for i, level_data in enumerate(sorted_levels):
        if i in used:
            continue
        
        cluster = [level_data]
        used.add(i)
        
        for j in range(i + 1, len(sorted_levels)):
            if j in used:
                continue
            if abs(sorted_levels[j]["level"] - level_data["level"]) <= tolerance:
                cluster.append(sorted_levels[j])
                used.add(j)
        
        # Compute cluster properties
        avg_level = sum(c["level"] for c in cluster) / len(cluster)
        touches = len(cluster)
        max_vol_score = max(c["vol_score"] for c in cluster)
        max_recency = max(c["recency"] for c in cluster)
        
        tfs = [c.get("timeframe", "Daily") for c in cluster]
        if "Monthly" in tfs:
            cluster_tf = "Monthly"
        elif "Weekly" in tfs:
            cluster_tf = "Weekly"
        else:
            cluster_tf = "Daily"
        
        # ── Density scoring: count additional touches across full history ──
        band_upper = avg_level + tolerance * 0.5
        band_lower = avg_level - tolerance * 0.5
        
        if is_support:
            price_data = df["Low"].values
        else:
            price_data = df["High"].values
        
        density_touches = sum(1 for p in price_data if band_lower <= p <= band_upper)
        
        # ── Strength formula ──
        # strength = touches × (1 + vol_score + recency) + density 
        base_strength = touches * (1 + max_vol_score) * (1 + max_recency)
        density_bonus = density_touches * 2.5
        strength = (base_strength * 5) + density_bonus
        
        # Check if cluster contains a gap
        has_gap = any(c.get("is_gap", False) for c in cluster)
        
        clusters.append({
            "level": round(avg_level),  # IDX stocks are integers
            "strength": round(strength, 1),
            "touches": touches + density_touches,
            "type": "gap" if has_gap else "fractal",
            "timeframe": cluster_tf,
        })
    
    return clusters


# ──────────────────────────────────────────────
# Regime Classification (Simple HMM-Lite)
# ──────────────────────────────────────────────

def classify_regime(hurst: float, rsi: float, ema20: float, ema50: float, 
                    price: float, ma200: Optional[float] = None,
                    macd: Optional[float] = None, macd_signal: Optional[float] = None) -> dict:
    """
    Classify market regime based on technical indicators.
    
    Returns:
        dict with keys: state, bias, confidence, description
    """
    bias_score = 0
    reasons = []
    
    # 1. Hurst contribution
    if hurst > 0.60:
        bias_score += 30
        reasons.append(f"Hurst {hurst:.2f} (Trending)")
    elif hurst > 0.50:
        bias_score += 10
        reasons.append(f"Hurst {hurst:.2f} (Slight Trend)")
    elif hurst < 0.45:
        bias_score -= 20
        reasons.append(f"Hurst {hurst:.2f} (Mean Reverting)")
    
    # 2. EMA alignment
    if ema20 is not None and ema50 is not None:
        if not (pd.isna(ema20) or pd.isna(ema50)):
            if ema20 > ema50:
                bias_score += 25
                reasons.append("MA20 > MA50")
            else:
                bias_score -= 25
                reasons.append("MA50 > MA20")
    
    # 3. Price vs EMAs
    if ema20 is not None and not pd.isna(ema20):
        if price > ema20:
            bias_score += 10
            reasons.append("Price > MA20")
        else:
            bias_score -= 10
    
    if ma200 is not None and not pd.isna(ma200):
        if price > ma200:
            bias_score += 15
            reasons.append("Price > MA200")
        else:
            bias_score -= 15
    
    # 4. RSI contribution
    if rsi is not None and not pd.isna(rsi):
        if rsi > 70:
            bias_score -= 10  # overbought = caution
            reasons.append("RSI Overbought")
        elif rsi < 30:
            bias_score += 5  # oversold can be opportunity
            reasons.append("RSI Oversold")
    
    # Classify
    if bias_score >= 40:
        state = "MARKUP"
        bias = "BULLISH"
        desc = "Strong markup / uptrend confirmed"
    elif bias_score >= 15:
        state = "ACCUMULATION"
        bias = "BULLISH (Early)"
        desc = "Early bullish signs / Accumulation"
    elif bias_score <= -40:
        state = "MARKDOWN"
        bias = "BEARISH"
        desc = "Strong markdown / downtrend confirmed"
    elif bias_score <= -15:
        state = "DISTRIBUTION"
        bias = "BEARISH (Caution)"
        desc = "Distribution phase / Bearish signs"
    else:
        state = "RANGING"
        bias = "SIDEWAYS"
        desc = "Neutral / Ranging market"
    
    confidence = "HIGH" if abs(bias_score) >= 40 else "MEDIUM" if abs(bias_score) >= 20 else "LOW"
    
    # ── Reversal Candidate Detection ──
    # Saat regime DISTRIBUTION (bukan MARKDOWN), cek apakah ada sinyal reversal dini:
    # 1. MACD Bullish Cross (MACD > Signal) — leading momentum indicator
    # 2. RSI < 50 — masih ada ruang naik, belum overbought
    reversal_candidate = False
    reversal_reason = ""
    
    if state == "DISTRIBUTION":
        has_macd_bull = (macd is not None and macd_signal is not None 
                        and not pd.isna(macd) and not pd.isna(macd_signal)
                        and macd > macd_signal)
        has_rsi_room = (rsi is not None and not pd.isna(rsi) and rsi < 50)
        
        if has_macd_bull and has_rsi_room:
            reversal_candidate = True
            reversal_reason = "MACD Bullish Cross + RSI < 50"
    
    return {
        "state": state,
        "bias": bias,
        "confidence": confidence,
        "score": bias_score,
        "description": desc,
        "reasons": reasons,
        "reversal_candidate": reversal_candidate,
        "reversal_reason": reversal_reason,
    }


# ──────────────────────────────────────────────
# Majority Rule 14 (Stockbit/TradingView Style Summary)
# ──────────────────────────────────────────────

def calc_majority_rule_14(df: pd.DataFrame) -> dict:
    """
    Calculates Technical Rating based on 14 common moving averages and oscillators.
    Returns: dict with 'bias', 'buy', 'sell', 'neutral', 'detail'
    """
    if len(df) < 5:
        return {"bias": "Neutral", "buy": 0, "sell": 0, "neutral": 14, "detail": "0B | 0S | 14N"}
        
    close = df['Close']
    price = close.iloc[-1]
    
    buy = 0
    sell = 0
    neutral = 0

    def add_signal(val, condition_buy, condition_sell):
        nonlocal buy, sell, neutral
        if pd.isna(val):
            neutral += 1
            return
        if condition_buy: buy += 1
        elif condition_sell: sell += 1
        else: neutral += 1

    try:
        # MAs (8)
        sma10 = close.rolling(10).mean().iloc[-1]
        add_signal(sma10, price > sma10, price < sma10)

        ema10 = close.ewm(span=10, adjust=False).mean().iloc[-1]
        add_signal(ema10, price > ema10, price < ema10)

        sma20 = close.rolling(20).mean().iloc[-1]
        add_signal(sma20, price > sma20, price < sma20)

        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        add_signal(ema20, price > ema20, price < ema20)

        sma50 = close.rolling(50).mean().iloc[-1]
        add_signal(sma50, price > sma50, price < sma50)

        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        add_signal(ema50, price > ema50, price < ema50)

        sma100 = close.rolling(100).mean().iloc[-1]
        add_signal(sma100, price > sma100, price < sma100)

        ema100 = close.ewm(span=100, adjust=False).mean().iloc[-1]
        add_signal(ema100, price > ema100, price < ema100)

        # Oscillators (6)
        # MACD (12, 26, 9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_val = macd.iloc[-1]
        add_signal(macd_val, macd_val > signal.iloc[-1], macd_val < signal.iloc[-1])

        # RSI (14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_val = rsi.iloc[-1]
        add_signal(rsi_val, rsi_val > 50, rsi_val < 50)
        
        # Stochastic (14, 3, 3)
        low_14 = df['Low'].rolling(14).min()
        high_14 = df['High'].rolling(14).max()
        k = 100 * ((close - low_14) / (high_14 - low_14))
        d = k.rolling(3).mean()
        add_signal(k.iloc[-1], k.iloc[-1] > d.iloc[-1], k.iloc[-1] < d.iloc[-1])

        # Momentum (10)
        if len(close) > 11:
            mom = close.iloc[-1] - close.iloc[-11]
            add_signal(mom, mom > 0, mom < 0)
        else:
            neutral += 1

        # CCI (14)
        tp = (df['High'] + df['Low'] + df['Close']) / 3
        sma_tp = tp.rolling(14).mean()
        mad = tp.rolling(14).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        cci = (tp - sma_tp) / (0.015 * mad)
        cci_val = cci.iloc[-1]
        add_signal(cci_val, cci_val > 0, cci_val < 0)
        
        # SMA 200
        sma200 = close.rolling(200).mean().iloc[-1]
        add_signal(sma200, price > sma200, price < sma200)
    except Exception:
        pass # fallback

    total_valid = buy + sell
    if total_valid == 0:
        bias_str = "Neutral"
    else:
        if buy >= 10:
            bias_str = "Strong Bullish"
        elif buy >= sell + 2:
            bias_str = "Bullish"
        elif sell >= 10:
            bias_str = "Strong Bearish"
        elif sell >= buy + 2:
            bias_str = "Bearish"
        else:
            bias_str = "Neutral"
            
    # Normalize if some indicators failed
    remaining_neutral = 14 - (buy + sell + neutral)
    if remaining_neutral > 0:
        neutral += remaining_neutral

    return {
        "bias": bias_str,
        "buy": buy,
        "sell": sell,
        "neutral": neutral,
        "detail": f"{buy}+ | {sell}- | {neutral}.",
    }


# ──────────────────────────────────────────────
# Nick Molchanoff Bull/Bear Volume (2004)
# ──────────────────────────────────────────────

def calc_bull_bear_vol(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Calculate Bull and Bear Volume based on typical Nick Molchanoff rules."""
    C = df['Close']
    O = df['Open']
    H = df['High']
    L = df['Low']
    V = df['Volume']
    C_prev = C.shift(1).fillna(O)
    
    cond_eq = (C == O)
    cond_gt_prev = (C > C_prev)
    cond_lt_prev = (C < C_prev)
    cond_gt_o = (C > O)
    cond_lt_o = (C < O)
    
    div_gt = (H - L) + (C - O)
    div_gt = np.where(div_gt <= 0, 1e-5, div_gt)
    bull_gt = V * ((C - L) / div_gt)
    
    div_lt = (H - L) + (O - C)
    div_lt = np.where(div_lt <= 0, 1e-5, div_lt)
    bull_lt = V * ((H - C) / div_lt)
    
    bull_eq = np.where(cond_gt_prev, V, np.where(cond_lt_prev, 0, V * 0.5))
    
    bull = np.where(cond_eq, bull_eq, 
                    np.where(cond_gt_o, bull_gt, 
                             np.where(cond_lt_o, bull_lt, 0)))
                             
    bull_vol = pd.Series(bull, index=df.index).fillna(0)
    bear_vol = V - bull_vol
    return bull_vol, bear_vol


# ──────────────────────────────────────────────
# Volume Spread Analysis (VSA) Signal Detection
# ──────────────────────────────────────────────

def detect_vsa_signals(df: pd.DataFrame, lookback: int = 10) -> list[dict]:
    """Detect key VSA patterns from recent price-volume behavior.
    Returns list of signal dicts: {"type": str, "label": str, "bar_idx": int}"""
    signals = []
    if len(df) < lookback + 5:
        return signals
    
    recent = df.iloc[-lookback:]
    avg_vol = df['Volume'].iloc[-(lookback * 2):].mean() if len(df) >= lookback * 2 else df['Volume'].mean()
    if avg_vol <= 0:
        return signals
    
    closes = recent['Close'].values
    opens = recent['Open'].values
    highs = recent['High'].values
    lows = recent['Low'].values
    volumes = recent['Volume'].values
    
    for i in range(1, len(recent)):
        vol = volumes[i]
        body = closes[i] - opens[i]
        rng = highs[i] - lows[i]
        vol_ratio = vol / avg_vol if avg_vol > 0 else 1.0
        is_narrow = rng < (highs[i-1] - lows[i-1]) * 0.5 if rng > 0 else True
        
        # No Supply: bearish bar but volume drying up (seller exhaustion)
        if body < 0 and vol_ratio < 0.6:
            signals.append({"type": "NO_SUPPLY", "label": "Seller Exhaustion: Volume mengering saat harga turun", "bar_idx": i})
        
        # No Demand: bullish bar but volume drying up (buyer exhaustion)
        elif body > 0 and vol_ratio < 0.6:
            signals.append({"type": "NO_DEMAND", "label": "Buyer Exhaustion: Volume mengering saat harga naik", "bar_idx": i})
        
        # Stopping Volume: after downtrend, huge volume on narrow range
        if i >= 3 and closes[i-1] < closes[i-2] < closes[i-3]:  # 3-bar downtrend
            if vol_ratio > 2.0 and is_narrow:
                signals.append({"type": "STOPPING_VOL", "label": "Stopping Volume: Volume spike besar di rentang sempit setelah penurunan", "bar_idx": i})
        
        # Climax Volume: extreme volume after extended move
        if vol_ratio > 3.0:
            if i >= 5:
                trend_up = all(closes[j] > closes[j-1] for j in range(i-4, i))
                trend_down = all(closes[j] < closes[j-1] for j in range(i-4, i))
                if trend_up or trend_down:
                    signals.append({"type": "CLIMAX", "label": "Climax Volume: Potensi reversal setelah lonjakan volume ekstrem", "bar_idx": i})
    
    # Only return the most recent signal of each type
    seen_types = set()
    unique_signals = []
    for s in reversed(signals):
        if s["type"] not in seen_types:
            seen_types.add(s["type"])
            unique_signals.append(s)
    
    # Mutual exclusion: if both NO_SUPPLY and NO_DEMAND fire,
    # volume is simply drying up on ALL sides = consolidation, not directional.
    has_no_supply = any(s["type"] == "NO_SUPPLY" for s in unique_signals)
    has_no_demand = any(s["type"] == "NO_DEMAND" for s in unique_signals)
    if has_no_supply and has_no_demand:
        unique_signals = [s for s in unique_signals if s["type"] not in ("NO_SUPPLY", "NO_DEMAND")]
        unique_signals.insert(0, {
            "type": "LOW_LIQUIDITY",
            "label": "Volume mengering (Konsolidasi): Tekanan jual/beli tidak dominan",
            "bar_idx": -1
        })
    
    return unique_signals[:3]  # Max 3 signals


# ──────────────────────────────────────────────
# Scalping Pattern Detection Engine (Intraday)
# ──────────────────────────────────────────────

def detect_scalp_setups(df: pd.DataFrame, snr: dict | None = None) -> list[dict]:
    """Detect intraday scalping patterns from OHLCV data.
    
    Patterns detected:
    1. VWAP Bounce / EMA9 Bounce — price bounces off dynamic support
    2. Bull Flag Breakout — consolidation breakout after strong trend
    3. Liquidity Sweep (Spring) — false breakdown with long wick
    4. HOD Breakout — High of Day momentum break with volume
    """
    signals = []
    if len(df) < 10:
        return signals
    
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest
    
    close = float(latest['Close'])
    open_ = float(latest['Open'])
    high = float(latest['High'])
    low = float(latest['Low'])
    vol = float(latest['Volume'])
    body = abs(close - open_)
    lower_wick = min(close, open_) - low
    upper_wick = high - max(close, open_)
    candle_range = high - low if high > low else 1
    is_bullish = close > open_
    
    # Volume context
    avg_vol_20 = float(df['Volume'].iloc[-20:].mean()) if len(df) >= 20 else float(df['Volume'].mean())
    vol_ratio = vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
    
    # VWAP and EMA
    vwap = float(latest['vwap']) if 'vwap' in df.columns and not pd.isna(latest.get('vwap')) else None
    ema9 = float(latest['ema9']) if 'ema9' in df.columns and not pd.isna(latest.get('ema9')) else None
    
    # Check if VWAP is reasonable (within 5% of price). 1H cumulative VWAP can be very far.
    vwap_reliable = False
    if vwap is not None and vwap > 0 and close > 0:
        vwap_dist = abs(close - vwap) / close
        vwap_reliable = vwap_dist < 0.05
    
    # ── 1. VWAP Bounce / EMA9 Bounce ──
    # Try VWAP first, but fallback to EMA9 as dynamic support anchor
    bounce_anchor = None
    bounce_label = ""
    if vwap_reliable and vwap is not None:
        bounce_anchor = vwap
        bounce_label = "VWAP"
    elif ema9 is not None:
        bounce_anchor = ema9
        bounce_label = "EMA9"
    
    if bounce_anchor is not None and bounce_anchor > 0:
        dist_pct = (close - bounce_anchor) / bounce_anchor
        # Close slightly above anchor (<2%), Low touched/near anchor, has lower wick
        if (0 < dist_pct < 0.02
            and low <= bounce_anchor * 1.005  # Low at or below anchor
            and close > bounce_anchor
            and lower_wick >= body * 0.5  # decent wick rejection
            and body > 0):
            signals.append({
                "type": "VWAP_BOUNCE",
                "label": f"⚡ {bounce_label} Bounce — Pantulan dari rata-rata modal institusi",
                "action": f"POTENTIAL SCALP: {bounce_label} Bounce",
                "sl_hint": f"SL ketat jika candle tutup di bawah {bounce_label}",
            })
    
    # ── 2. Micro Bull Flag / Intraday Base Breakout ──
    # Only requires above EMA9 (NOT VWAP — VWAP on 1H data is unreliable)
    if len(df) >= 10 and ema9 is not None and close > ema9:
        # Volatility contraction in last 3-5 candles
        recent_5 = df.iloc[-6:-1]
        if len(recent_5) >= 3:
            ranges = (recent_5['High'] - recent_5['Low']).values
            avg_range_recent = float(np.mean(ranges[-3:])) if len(ranges) >= 3 else 0
            avg_range_prior = float(np.mean((df['High'] - df['Low']).iloc[-15:-6].values)) if len(df) >= 15 else avg_range_recent * 2
            is_contracting = avg_range_recent < avg_range_prior * 0.75  # 25%+ contraction
            
            # Volume drying up in consolidation
            vol_recent = float(recent_5['Volume'].mean())
            vol_dry = vol_recent < avg_vol_20 * 0.8 if avg_vol_20 > 0 else False
            
            # Current candle breaks above consolidation high
            consol_high = float(recent_5['High'].max())
            is_breakout = close > consol_high and is_bullish
            
            if is_contracting and is_breakout and (vol_dry or vol_ratio > 1.3):
                signals.append({
                    "type": "BULL_FLAG",
                    "label": "🚀 Bull Flag Breakout — Breakout setelah konsolidasi ketat",
                    "action": "POTENTIAL SCALP: Bull Flag Breakout",
                    "sl_hint": "TP cepat 1-3%, SL di bawah base konsolidasi",
                })
    
    # ── 3. Liquidity Sweep / Spring ──
    if snr and snr.get("supports"):
        supports = snr["supports"]
        sups_at_or_below = [s for s in supports if s["level"] <= close * 1.02]
        if sups_at_or_below:
            nearest_sup = max(sups_at_or_below, key=lambda x: x["level"])
            sup_level = float(nearest_sup["level"])
            
            # Low pierces or touches support, Close recovers, long wick, volume
            support_pierced = low <= sup_level * 1.005
            close_recovered = close > sup_level
            long_wick = lower_wick >= body * 1.5 if body > 0 else lower_wick > candle_range * 0.4
            high_vol = vol_ratio > 1.2
            
            if support_pierced and close_recovered and long_wick and high_vol:
                signals.append({
                    "type": "LIQUIDITY_SWEEP",
                    "label": "⚡ Liquidity Sweep (Spring) — False breakdown, serok bawah!",
                    "action": "POTENTIAL SCALP: Liquidity Sweep",
                    "sl_hint": f"SL sedikit di bawah ekor ({int(low)})",
                })
    
    # ── 4. HOD (High of Day) Breakout ──
    # Use last 20 bars (realistic intraday window) instead of entire history
    lookback_hod = min(20, len(df) - 1)
    if lookback_hod >= 5:
        hod_before = float(df['High'].iloc[-(lookback_hod+1):-1].max())
        
        # Close > recent HOD, bullish candle, volume confirmation
        is_hod_break = close > hod_before
        has_volume = vol_ratio > 1.0
        
        if is_hod_break and is_bullish and has_volume:
            signals.append({
                "type": "HOD_BREAKOUT",
                "label": "🚀 HOD Momentum Break — Harga tembus High of Day dengan volume!",
                "action": "POTENTIAL SCALP: HOD Momentum Break",
                "sl_hint": "SL di bawah HOD sebelumnya",
            })
    
    # ── 5. Momentum Surge — Strong bullish candle with above-average volume ──
    if is_bullish and body > 0:
        body_pct = body / close
        is_strong_body = body_pct > 0.015  # >1.5% body
        is_small_wick = upper_wick < body * 0.3  # strong close near high
        
        if is_strong_body and is_small_wick and vol_ratio > 1.5:
            signals.append({
                "type": "MOMENTUM_SURGE",
                "label": "🚀 Momentum Surge — Candle kuat dengan volume tinggi!",
                "action": "POTENTIAL SCALP: Momentum Surge",
                "sl_hint": "SL di bawah Open candle ini",
            })
    
    # ── 6. Fair Value Gap (FVG) / Imbalance ──
    # 3-Candle Rule: Low[T] > High[T-2] = Bullish FVG (institutional gap)
    if len(df) >= 5:
        c_t = df.iloc[-1]   # Current candle (T)
        c_t1 = df.iloc[-2]  # Middle candle (T-1)
        c_t2 = df.iloc[-3]  # Reference candle (T-2)
        
        low_t = float(c_t['Low'])
        high_t2 = float(c_t2['High'])
        close_t1 = float(c_t1['Close'])
        open_t1 = float(c_t1['Open'])
        body_t1 = abs(close_t1 - open_t1)
        is_bullish_t1 = close_t1 > open_t1
        
        # Bullish FVG: Gap exists, middle candle is strong bullish
        if low_t > high_t2 and is_bullish_t1 and body_t1 > 0:
            gap_size = low_t - high_t2
            gap_pct = gap_size / close if close > 0 else 0
            if gap_pct > 0.003:  # Gap > 0.3% to be meaningful
                signals.append({
                    "type": "FVG_BULLISH",
                    "label": f"⚡ Fair Value Gap — Jejak institusi, gap {gap_pct*100:.1f}% belum tertutup",
                    "action": "POTENTIAL SCALP: FVG Pullback Entry",
                    "sl_hint": f"Entry pullback ke area {int(high_t2)}-{int(low_t)}, SL di bawah gap",
                })
        
        # Bearish FVG: High[T] < Low[T-2]
        high_t = float(c_t['High'])
        low_t2 = float(c_t2['Low'])
        is_bearish_t1 = close_t1 < open_t1
        
        if high_t < low_t2 and is_bearish_t1 and body_t1 > 0:
            gap_size = low_t2 - high_t
            gap_pct = gap_size / close if close > 0 else 0
            if gap_pct > 0.003:
                signals.append({
                    "type": "FVG_BEARISH",
                    "label": f"⚠️ Bearish FVG — Gap distribusi {gap_pct*100:.1f}%, hati-hati rejection",
                    "action": "WARNING: Bearish FVG Zone",
                    "sl_hint": f"Resistance area {int(high_t)}-{int(low_t2)}",
                })
    
    # ── 7. Micro Order Block (OB) ──
    # Bearish candle → explosive bullish candle with high volume = institutional accumulation
    if len(df) >= 4:
        ob_bear = df.iloc[-2]  # Previous candle (should be bearish)
        ob_bull = df.iloc[-1]  # Current candle (should be explosive bullish)
        
        ob_close_bear = float(ob_bear['Close'])
        ob_open_bear = float(ob_bear['Open'])
        ob_high_bear = float(ob_bear['High'])
        ob_low_bear = float(ob_bear['Low'])
        
        ob_close_bull = float(ob_bull['Close'])
        ob_open_bull = float(ob_bull['Open'])
        ob_vol_bull = float(ob_bull['Volume'])
        
        is_ob_bear = ob_close_bear < ob_open_bear  # Bearish prev candle
        is_ob_engulf = ob_close_bull > ob_high_bear  # Current closes above prev high (engulfing)
        is_ob_bullish = ob_close_bull > ob_open_bull  # Current is bullish
        is_ob_vol = ob_vol_bull > avg_vol_20 * 1.3 if avg_vol_20 > 0 else False
        
        if is_ob_bear and is_ob_engulf and is_ob_bullish and is_ob_vol:
            signals.append({
                "type": "ORDER_BLOCK",
                "label": f"⚡ Order Block — Zona akumulasi bandar di {int(ob_low_bear)}-{int(ob_high_bear)}",
                "action": "POTENTIAL SCALP: Order Block Entry",
                "sl_hint": f"Entry pullback ke {int(ob_low_bear)}-{int(ob_high_bear)}, SL di bawah OB",
            })
    
    # ── 8. ATR-Based Liquidity Sweep (Dynamic Rejection) ──
    if len(df) >= 15:
        # Calculate ATR(14)
        tr_series = pd.DataFrame({
            'hl': df['High'] - df['Low'],
            'hc': (df['High'] - df['Close'].shift(1)).abs(),
            'lc': (df['Low'] - df['Close'].shift(1)).abs()
        }).max(axis=1)
        atr_14 = float(tr_series.iloc[-14:].mean())
        
        if atr_14 > 0 and candle_range > 0:
            # Lower wick must be > 0.8 × ATR (extreme rejection)
            wick_vs_atr = lower_wick / atr_14
            body_vs_range = body / candle_range
            
            # Strong rejection: long wick > 0.8 ATR, small body < 30% of range
            if wick_vs_atr > 0.8 and body_vs_range < 0.3 and is_bullish:
                # Must be near support for context
                near_support = False
                if snr and snr.get("supports"):
                    for s in snr["supports"]:
                        if abs(low - s["level"]) / close < 0.02:
                            near_support = True
                            break
                
                if near_support:
                    signals.append({
                        "type": "ATR_SWEEP",
                        "label": f"⚡ ATR Reject — Ekor {wick_vs_atr:.1f}x ATR di support!",
                        "action": "POTENTIAL SCALP: ATR Rejection",
                        "sl_hint": f"SL di bawah {int(low)}, body kecil = rejection kuat",
                    })
    
    return signals


# ──────────────────────────────────────────────
# Dow Theory Price Action Engine
# ──────────────────────────────────────────────
def detect_pivot_extrema(df: pd.DataFrame, window: int = 5) -> list[dict]:
    """
    Mechanism 1 (V2): Rolling Window Pivot Detection
    Returns alternating list of absolute peaks and troughs exactly at the wicks.
    """
    if len(df) < window * 2 + 1:
        return []

    highs = df['High'].values
    lows = df['Low'].values
    dates = df.index
    
    raw_pivots = []
    
    for i in range(window, len(df) - window):
        left = max(0, i - window)
        right = min(len(df), i + window + 1)
        
        is_peak = True
        is_trough = True
        
        for j in range(left, right):
            if j == i:
                continue
            if highs[j] > highs[i]:
                is_peak = False
            if lows[j] < lows[i]:
                is_trough = False
                
        if is_peak:
            raw_pivots.append({"type": "peak", "idx": i, "price": float(highs[i]), "date": dates[i]})
        if is_trough:
            raw_pivots.append({"type": "trough", "idx": i, "price": float(lows[i]), "date": dates[i]})
            
    if not raw_pivots:
        return []
        
    # Enforce strict alternation by discarding identical consecutive types (keeping the more extreme one)
    raw_pivots.sort(key=lambda x: x["idx"])
    
    clean_swings = [raw_pivots[0]]
    for s in raw_pivots[1:]:
        prev = clean_swings[-1]
        if s["type"] == prev["type"]:
            if s["type"] == "peak":
                if s["price"] > prev["price"]:
                    clean_swings[-1] = s
            else:
                if s["price"] < prev["price"]:
                    clean_swings[-1] = s
        else:
            clean_swings.append(s)
            
    return clean_swings


def calc_zigzag_swings(df: pd.DataFrame, atr_series: pd.Series, threshold_mult: float = 1.5) -> list[dict]:
    """
    Mechanism 1: ATR-based ZigZag Swing Detection
    Returns alternating list of peaks and troughs.
    """
    if len(df) < 3:
        return []
        
    swings = []
    
    # Track extremes
    last_extreme_idx = 0
    # Start with midpoint for neutral start
    last_extreme_price = (df['High'].iloc[0] + df['Low'].iloc[0]) / 2 
    
    # State: 1 for looking for Peak, -1 for looking for Trough, 0 initial
    state = 0
    
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    dates = df.index
    atrs = atr_series.values
    
    for i in range(1, len(df)):
        current_high = highs[i]
        current_low = lows[i]
        current_atr = atrs[i] if not pd.isna(atrs[i]) else (closes[i] * 0.05)
        threshold = current_atr * threshold_mult
        
        if state == 0:
            # Determine initial direction by comparing with the very first candle
            if current_high >= last_extreme_price + threshold:
                state = 1
                last_extreme_price = current_high
                last_extreme_idx = i
            elif current_low <= last_extreme_price - threshold:
                state = -1
                last_extreme_price = current_low
                last_extreme_idx = i
                
        elif state == 1:
            # Looking for Peak, tracking Highest High
            if current_high > last_extreme_price:
                last_extreme_price = current_high
                last_extreme_idx = i
            # Check for drop exceeding threshold (Confirm Peak -> Switch to looking for Trough)
            if current_low <= last_extreme_price - threshold:
                swings.append({
                    "type": "peak",
                    "idx": last_extreme_idx,
                    "price": float(last_extreme_price),
                    "date": dates[last_extreme_idx]
                })
                state = -1
                last_extreme_price = current_low
                last_extreme_idx = i
                
        elif state == -1:
            # Looking for Trough, tracking Lowest Low
            if current_low < last_extreme_price:
                last_extreme_price = current_low
                last_extreme_idx = i
            # Check for rise exceeding threshold (Confirm Trough -> Switch to looking for Peak)
            if current_high >= last_extreme_price + threshold:
                swings.append({
                    "type": "trough",
                    "idx": last_extreme_idx,
                    "price": float(last_extreme_price),
                    "date": dates[last_extreme_idx]
                })
                state = 1
                last_extreme_price = current_high
                last_extreme_idx = i

    # Enforce strict alternation by discarding identical consecutive types (keeping the more extreme one)
    # The ZigZag logic above inherently alternates due to state switching, but we do one pass just in case.
    if not swings:
        return []
        
    clean_swings = [swings[0]]
    for s in swings[1:]:
        prev = clean_swings[-1]
        if s["type"] == prev["type"]:
            if s["type"] == "peak":
                if s["price"] > prev["price"]:
                    clean_swings[-1] = s
            else:
                if s["price"] < prev["price"]:
                    clean_swings[-1] = s
        else:
            clean_swings.append(s)
            
    return clean_swings


def label_dow_theory(swings: list[dict]) -> list[dict]:
    """
    Mechanism 2: Label P, T, HP, HT, LP, LT.
    """
    if not swings:
        return []
        
    labeled = []
    last_peak = None
    last_trough = None
    
    for s in swings:
        item = s.copy()
        
        if item["type"] == "peak":
            if last_peak is None:
                item["label"] = "P"
            else:
                if item["price"] > last_peak["price"]:
                    item["label"] = "HP"
                else:
                    item["label"] = "LP"
            last_peak = item
            
        elif item["type"] == "trough":
            if last_trough is None:
                item["label"] = "T"
            else:
                if item["price"] > last_trough["price"]:
                    item["label"] = "HT"
                else:
                    item["label"] = "LT"
            last_trough = item
            
        labeled.append(item)
        
    return labeled


def classify_price_action_scenario(
    labeled_swings: list[dict],
    supports: list[dict],
    resistances: list[dict],
    gaps: list[dict],
    stoch_k: float | None,
    stoch_d: float | None,
    current_price: float,
    atr: float
) -> dict | None:
    """
    Mechanism 3: State Machine Price Action Scenarios & Momentum.
    """
    # ── 1. Momentum Classification ──
    momentum_desc = ""
    if stoch_k is not None and stoch_d is not None:
        if stoch_k > 80:
            momentum_desc = "Momentum indikator berada di area overbought."
        elif stoch_k > stoch_d and 50 <= stoch_k <= 80:
            momentum_desc = "Momentum indikator mengarah ke atas mendekati area overbought."
        elif stoch_k > stoch_d and stoch_k < 50:
            momentum_desc = "Momentum indikator mengarah ke atas pada area netral/oversold."
        elif stoch_k < stoch_d and stoch_k > 50:
            momentum_desc = "Momentum indikator melandai/turun dari area overbought."

    if len(labeled_swings) < 3:
        return {"name": "Normal", "action": "WAIT", "buy_zone": current_price, "target_level": None, "description": "Data belum terbentuk.", "momentum": momentum_desc}
        
    labels = [s["label"] for s in labeled_swings[-4:]]
    last_swings = labeled_swings[-4:]
    
    pa_name = "Price Action Normal"
    pa_desc = "Konsolidasi normal."
    action = "WAIT"

    peaks = [s for s in labeled_swings if s["type"] == "peak"]
    previous_peak = peaks[-1]["price"] if peaks else None
    
    nearest_supp = supports[0]["level"] if supports else None

    is_w_pattern = (len(labels) >= 3 and labels[-3:] == ["LT", "LP", "HT"])
    ht_price = last_swings[-1]["price"] if is_w_pattern else None

    if previous_peak is not None:
        if current_price > previous_peak:
            # Resistance Becomes Support / Breaking
            if current_price <= previous_peak + (atr * 1.5):
                pa_name = "Resistance Becomes Support"
                pa_desc = "Harga pullback mendekati previous resistance."
                action = "BUY_PULLBACK"
            else:
                pa_name = "Breaking the Resistance"
                pa_desc = "Harga menembus tajam resistance dan belum turun."
                action = "BUY_MOMENTUM"
        else:
            dist_to_peak_pct = (previous_peak - current_price) / current_price
            if dist_to_peak_pct < 0.05:
                pa_name = "Potential to Reach the Classic Resistance"
                pa_desc = "Jarak harga &lt; 5% dari classic resistance."
                action = "BUY_IF_BREAKOUT"
            elif is_w_pattern:
                pa_name = "W Pattern"
                pa_desc = "Base reversal pattern formed."
                action = "BUY_REVERSAL"
            elif nearest_supp:
                dist_to_supp_pct = (current_price - nearest_supp) / current_price
                if 0 <= dist_to_supp_pct <= 0.02:
                    pa_name = "Rebound from Support"
                    pa_desc = "Harga memantul dari Support Mayor."
                    action = "BUY_NOW"
    else:
        # Fallback if no peak
        if is_w_pattern:
            pa_name = "W Pattern"
            pa_desc = "Base reversal pattern formed."
            action = "BUY_REVERSAL"
        elif nearest_supp:
            dist_to_supp_pct = (current_price - nearest_supp) / current_price
            if 0 <= dist_to_supp_pct <= 0.02:
                pa_name = "Rebound from Support"
                pa_desc = "Harga memantul dari Support Mayor."
                action = "BUY_NOW"

    # Support False Break check
    if pa_name == "Price Action Normal" and labels and labels[-1] in ["LT", "T"]:
        last_trough = last_swings[-1]["price"]
        if nearest_supp and last_trough < nearest_supp and current_price < nearest_supp:
            if stoch_k is not None and stoch_k < 20: 
                pa_name = "FALSE_BREAK_WAIT"
                pa_desc = "Price broke support but deeply oversold. Wait for close above support."
                action = "WAIT_FALSE_BREAK"

    return {
        "name": pa_name,
        "action": action,
        "buy_zone": previous_peak if pa_name == "Resistance Becomes Support" else current_price,
        "target_level": previous_peak if previous_peak and previous_peak > current_price else None,
        "description": pa_desc,
        "momentum": momentum_desc
    }

# ──────────────────────────────────────────────
# Trading Plan Generator Core
# ──────────────────────────────────────────────

def generate_trading_levels(
    current_price: float,
    supports: list,
    resistances: list,
    atr: float,
    atr_info: dict,
    hurst: float = 0.5,
    mode: str = "swing",  # "swing" or "daytrade"
    ema_anchor: Optional[float] = None,
    ma200: Optional[float] = None,
    scenario: dict | None = None,
    labeled_swings: list[dict] | None = None,
) -> dict:
    """
    Generate intelligent buy area, stop loss, and take profit levels.
    
    Logic from knowledge.txt:
    - Buy Area: nearest actionable support with proximity check
    - SL: ATR-based with percentage cap (8% swing, 3% daytrade)
    - TP: Risk-multiple with resistance cap
    
    Returns:
        dict with: action, buy_low, buy_high, sl, tp1, tp2, rr1, rr2,
                   support_used, resistance_used, is_valid
    """
    is_swing = mode == "swing"
    
    # ── Configuration per mode ──
    if is_swing:
        sl_atr_mult = 1.5
        tp1_rr = 1.5
        tp2_rr = 3.0
        buy_now_dist = 0.03
        wait_dist = 0.08
    else:  # daytrade
        sl_atr_mult = 1.0
        tp1_rr = 1.0
        tp2_rr = 2.0
        buy_now_dist = 0.015
        wait_dist = 0.03
    
    # Adjust aggressiveness by Hurst
    if hurst > 0.60:
        buy_now_dist *= 1.5
        sl_atr_mult *= 0.85
    elif hurst < 0.45:
        buy_now_dist *= 0.7
        sl_atr_mult *= 1.2
    
    # ── Find best support ──
    support_level = None
    support_strength = 0
    
    if supports:
        # Prefer nearest support to current price that's actionable
        for s in sorted(supports, key=lambda x: abs(x["level"] - current_price)):
            dist_pct = (current_price - s["level"]) / current_price
            if 0 <= dist_pct <= wait_dist + 0.02: 
                support_level = s["level"]
                support_strength = s["strength"]
                break
    
    # Fallbacks
    if support_level is None:
        if ema_anchor is not None and not pd.isna(ema_anchor):
            ema_dist = (current_price - ema_anchor) / current_price
            if 0 < ema_dist < wait_dist:
                support_level = ema_anchor
                support_strength = 50 
        
        if support_level is None:
            pullback_pct = 0.02 if is_swing else 0.01
            support_level = current_price * (1 - pullback_pct)
            support_strength = 30
            
    # Normalize support
    support_level = round_to_idx_tick(support_level)
    current_tick = round_to_idx_tick(current_price)
    
    # ── Determine action and Buy Area ──
    dist_to_support = (current_price - support_level) / current_price if current_price > 0 else 0
    atr = max(atr, 1)  # floor ATR

    is_breakout = False
    breakout_mode = ""
    breakout_level = None
    breakout_strength = 0
    
    # ── Check for Breakout ──
    # If price is approaching a strong resistance (within 5%), propose a Breakout Plan
    # SKIP anticipated breakout if scenario already confirms momentum (BUY_MOMENTUM)
    # — price has already broken through, no point waiting for *another* breakout above
    scenario_action = scenario["action"] if scenario else None
    skip_anticipated_breakout = scenario_action == "BUY_MOMENTUM"
    
    if resistances:
        # Check for Anticipated Breakout (Resistance ABOVE current price)
        res_above = [r for r in resistances if r["level"] > current_price]
        if res_above and not skip_anticipated_breakout:
            nearest_res = min(res_above, key=lambda x: x["level"])
            dist_to_res_pct = (nearest_res["level"] - current_price) / current_price
            
            # If price is approaching resistance (within 6%), prefer breakout plan
            if 0 < dist_to_res_pct <= 0.06:
                # Veto breakout if the required Stop Loss would be too wide (> 7.5% risk)
                sl_est = support_level - (atr * max(sl_atr_mult * 0.5, 0.5))
                breakout_risk_pct = (nearest_res["level"] - sl_est) / nearest_res["level"]
                
                if breakout_risk_pct <= 0.06:
                    is_breakout = True
                    breakout_mode = "BUY_IF_BREAKOUT"
                    breakout_level = nearest_res["level"]
                    breakout_strength = nearest_res["strength"]
        
        # Check for Breakout Retest (Resistance just BELOW current price)
        res_below = [r for r in resistances if r["level"] <= current_price]
        if not is_breakout and res_below:
            nearest_res_below = max(res_below, key=lambda x: x["level"])
            dist_to_res_pct = (current_price - nearest_res_below["level"]) / current_price
            
            # If price just broke out and is retesting (up to 3% above resistance)
            if 0 <= dist_to_res_pct <= 0.03:
                is_breakout = True
                breakout_mode = "BUY_BREAKOUT_RETEST"
                breakout_level = nearest_res_below["level"]
                breakout_strength = nearest_res_below["strength"]

    if is_breakout and breakout_mode == "BUY_IF_BREAKOUT":
        action = "BUY_IF_BREAKOUT"
        breakout_tick = round_to_idx_tick(breakout_level)
        buy_low = breakout_tick
        buy_high = round_to_idx_tick(breakout_level + max(atr * 0.2, 1))
        entry_price = round_to_idx_tick((buy_low + buy_high) / 2)
    elif is_breakout and breakout_mode == "BUY_BREAKOUT_RETEST":
        action = "BUY_BREAKOUT_RETEST"
        buy_low = round_to_idx_tick(breakout_level)
        buy_high = round_to_idx_tick(max(current_tick, breakout_level + (atr * 0.2)))
        entry_price = round_to_idx_tick((buy_low + buy_high) / 2)
        support_level = buy_low
        support_strength = breakout_strength
    elif scenario is not None:
        action = scenario["action"]
        if action == "BUY_MOMENTUM":
            buy_low = round_to_idx_tick(current_price - atr * 0.3)
            buy_high = current_tick
            entry_price = current_tick
            support_level = buy_low
        elif action == "WAIT_FALSE_BREAK":
            buy_low = round_to_idx_tick(scenario["buy_zone"] - atr * 0.2)
            buy_high = round_to_idx_tick(scenario["buy_zone"])
            entry_price = buy_high
            support_level = buy_low
        elif action == "BUY_IF_BREAKOUT":
            breakout_target = scenario.get("target_level") or (current_price * 1.05)
            breakout_tick = round_to_idx_tick(breakout_target)
            buy_low = breakout_tick
            buy_high = round_to_idx_tick(breakout_target + max(atr * 0.2, 1))
            entry_price = round_to_idx_tick((buy_low + buy_high) / 2)
        else:
            buy_low = round_to_idx_tick(scenario["buy_zone"] - atr * 0.2)
            buy_high = round_to_idx_tick(scenario["buy_zone"] + atr * 0.2)
            entry_price = round_to_idx_tick((buy_low + buy_high) / 2)
            support_level = buy_low
    elif dist_to_support <= buy_now_dist:
        action = "BUY_NOW"
        buy_low = support_level
        buy_high = current_tick
        entry_price = current_tick
    elif dist_to_support <= wait_dist:
        action = "WAIT_PULLBACK"
        buy_low = support_level
        buy_high = round_to_idx_tick(support_level + atr * 0.3)
        entry_price = round_to_idx_tick(support_level + atr * 0.15)
    else:
        action = "BUY_NOW"
        buy_low = round_to_idx_tick(current_price - atr * 0.5)
        buy_high = current_tick
        support_level = buy_low
        entry_price = current_tick
        
    if action != "BUY_IF_BREAKOUT" and buy_low >= buy_high:
        if buy_low is not None and atr is not None:
            buy_high = round_to_idx_tick(buy_low + max(atr * 0.2, 1))

    # ── Stop Loss ──
    # If we are waiting for a breakout, use the actual support level (not entry) for SL baseline
    if action == "BUY_IF_BREAKOUT":
        # SL is below the immediate support structure, preventing tiny SL hits
        sl_raw = support_level - (atr * max(sl_atr_mult * 0.5, 0.5))
    else:
        sup_1 = supports[0]["level"] if len(supports) > 0 else (support_level or current_price)
        sup_2 = supports[1]["level"] if len(supports) > 1 else None
        
        if is_swing and sup_2 is not None:
            risk_to_sup2_pct = (entry_price - sup_2) / entry_price if entry_price > 0 else 0
            if risk_to_sup2_pct < 0.06:
                sl_raw = sup_2 - (atr * 0.3)
            else:
                # Risk > 6%, Fallback per instruksi
                sl_raw = sup_1 - (atr * 1.5)
        else:
            sl_raw = support_level - (atr * sl_atr_mult)
        
    if ma200 is not None and not pd.isna(ma200):
        if ma200 < support_level and ma200 > support_level * 0.90:
            sl_raw = min(sl_raw, ma200 * 0.99)
            
    sl = round_to_idx_tick_floor(sl_raw)
            
    # Cap SL risk: swing trades capped at 6% max risk, daytrade at 3.5%
    max_sl_pct = 0.94 if is_swing else 0.965
    max_sl = round_to_idx_tick_floor(entry_price * max_sl_pct)
    if sl < max_sl:
        sl = max_sl
        
    # Prevent tight logical errors where SL >= Buy Area or SL too close to entry
    min_sl_dist = entry_price * 0.01 # Minimum 1% SL
    if entry_price - sl < min_sl_dist:
        sl = round_to_idx_tick_floor(entry_price - min_sl_dist)
        
    if sl >= buy_low:
        sl = round_to_idx_tick_floor(buy_low - min_sl_dist)
        
    # Absolute fallback: strictly below buy_low
    if sl >= buy_low:
        sl = round_to_idx_tick_floor(buy_low * 0.99)
        if sl <= 0:
            sl = 0

    # Actual cut loss is 1 tick below SL for risk calculation
    cut_loss_price = sl - _get_idx_tick(sl) if sl > 0 else 0

    # ── Take Profit (Mechanism 4) ──
    # Risk: from buy_low (worst entry) to cut_loss
    risk = buy_low - cut_loss_price
    if risk <= 0:
        risk = buy_low * 0.02

    # TP anchored on buy_high (top of entry zone) to ensure TPs always CLEAR the zone
    tp1 = round_to_idx_tick_floor(buy_high * 1.03)
    tp2 = round_to_idx_tick_floor(buy_high * 1.06)
        
    # Calculate actual outcomes (reward from buy_low, not midpoint)
    actual_rr1 = (tp1 - buy_low) / risk if risk > 0 else 0
    actual_rr2 = (tp2 - buy_low) / risk if risk > 0 else 0
    sl_pct = ((buy_low - cut_loss_price) / buy_low * 100) if buy_low > 0 else 0
    
    # Strict RR validation: if RR < 1.0, flag as poor RR, unless in specific setup
    if actual_rr1 < 0.8:
        if action not in ["BUY_REVERSAL", "WAIT_FALSE_BREAK"]:
            action = "POOR_RR_AVOID"

    
    is_valid = actual_rr1 >= 0.8 and risk > 0

    resist_level = resistances[0]["level"] if resistances else None
    resist_strength = resistances[0]["strength"] if resistances else None
    
    return {
        "action": action,
        "buy_low": buy_low,
        "buy_high": buy_high,
        "sl": sl,
        "sl_pct": round(sl_pct, 1),
        "tp1": tp1,
        "tp2": tp2,
        "rr1": round(actual_rr1, 1),
        "rr2": round(actual_rr2, 1),
        "risk_per_share": int(risk),
        "support_level": support_level,
        "support_strength": round(support_strength, 1),
        "resist_level": int(resist_level) if resist_level else None,
        "resist_strength": round(resist_strength, 1) if resist_strength else None,
        "is_valid": is_valid,
    }


def generate_institutional_explanation(
    symbol: str, 
    bias: str, 
    hurst: float, 
    dow_labels: list[dict], 
    rsi: float | None, 
    stoch_k: float | None, 
    stoch_d: float | None, 
    macd_hist: float | None, 
    action: str, 
    buy_low: float, 
    buy_high: float, 
    tp1: float, 
    sl: float, 
    current_price: float,
    is_swing: bool = True
) -> dict:
    """
    Generates institutional-grade trading plan strings based on 
    Dow Theory, Vector Momentum, Market Regime, and Volatility parameters.
    Returns dictionary containing formatted strings for Telegram UI.
    """
    # 1. Bias Market
    bias_str = ""
    if hurst > 0.6:
        bias_str = f"Trending ({bias})"
    elif hurst < 0.45:
        bias_str = f"Mean Reverting ({bias})"
    else:
        bias_str = f"Konsolidasi / Sideways ({bias})"
        
    # 2. Struktur
    last_label = "P" # default
    if dow_labels:
        last_label = dow_labels[-1].get("label", "P")
    
    label_map = {
        "HP": "Higher Peak (HP)",
        "HT": "Higher Trough (HT)",
        "LP": "Lower Peak (LP)",
        "LT": "Lower Trough (LT)",
        "P": "Peak (P)",
        "T": "Trough (T)"
    }
    
    struktur_str = label_map.get(last_label, last_label)
    
    def _fmt(val):
        return f"{int(val)}" if val >= 100 else f"{val:.2f}".replace(".", ",")

    # 3. Entry
    entry_zone_str = f"{_fmt(buy_low)} - {_fmt(buy_high)}"
    
    # 4. Target
    target_str = f"{_fmt(tp1)}"
    
    # 5. Penjelasan (Synthesizing Wyckoff, Dow, Indicators)
    regime_text = "berada pada fase trending asimetris" if hurst > 0.6 else "menunjukkan perilaku rotasi bolak-balik (mean reversion)" if hurst < 0.45 else "sedang dalam fase keseimbangan volatilitas (sideways range)"
    
    struct_text = f"Pembentukan {struktur_str} mengindikasikan struktur market yang "
    if last_label in ["HP", "HT"]:
        struct_text += "sehat dan konstruktif searah trajektori Dow Theory uptrend."
    elif last_label in ["LP", "LT"]:
        struct_text += "berada dalam dominasi tekanan jual terindikasi struktur seri pelemahan."
    else:
        struct_text += "masih berupaya mencari pijakan arah kelanjutan."
        
    mom_text = []
    if stoch_k is not None:
        if stoch_k > 80: 
            mom_text.append("Osilator telah melampaui fase kompresi wajar dan mendekati *exhaustion level* (overbought), waspadai kontraksi minor.")
        elif stoch_k < 20: 
            mom_text.append("Momentum jual mengkerut di titik jenuh ekstrem (oversold), menyertakan probabilitas tinggi untuk terdistorsi absorpsi buyer (Wyckoff *Preliminary Support*).")
        elif 40 <= stoch_k <= 60: 
            mom_text.append("Momentum di persimpangan *equilibrium*, menanti suntikan partisipasi volume institusional.")
        elif stoch_d is not None and stoch_k > stoch_d and stoch_k < 50: 
            mom_text.append("Osilator mengonfirmasi *bullish divergence* dini (melengkung naik), mengisyaratkan rotasi rotasi siklus *markup*.")
            
    if macd_hist is not None:
        if macd_hist > 0:
            mom_text.append("Akselerasi MACD positif dan bar histogram yang ekspansif mengonfirmasi dorongan momentum sejalan siklus tren.")
        else:
            mom_text.append("Siklus MACD masih mengindikasikan pelemahan momentum utama, sehingga fase konsolidasi harga lebih rasional saat ini.")
            
    mom_str = " ".join(mom_text)
    
    act_text = ""
    if "WAIT" in action or action == "POOR_RR_AVOID":
        act_text = f"Secara teknikal, *risk-to-reward ratio* (*R:R*) tidak asimetris pada kisaran harga saat ini. Menungu volatilitas mendingin dan *pullback* mendekati zona {entry_zone_str} menjadi opsi teraman."
    elif action == "BUY_NOW":
        act_text = f"Terjadi konfluensi antara batas dasar struktur dengan pelemahan momentum *seller*, menyajikan titik *entry* bernilai tinggi. Invalidasi absolut dipatok jika garis pertahanan {sl} jebol (*cut-loss* disiplin)."
    elif action == "BUY_IF_BREAKOUT":
        act_text = f"Mengantisipasi pelepasan tekanan (*volatility expansion*), *momentum execution* di atas resisten {entry_zone_str} (dengan volume konfirmasi konkrit) jauh lebih logis demi meminimalkan _opportunity cost_."
    elif action == "BUY_PULLBACK" or action == "BUY_BREAKOUT_RETEST":
        act_text = f"Fase *retracement* merapat alami ke lintasan *Higher Trough* / pijakan dukungan historis (*RBS*). Setup eksekusi ditempatkan terukur di {entry_zone_str} untuk menyusul kembali laju tren makro."
    elif action == "BUY_MOMENTUM" or "BREAKOUT" in action:
        act_text = f"Aksi beli persisten (*effort*) mengeliminasi likuiditas *supply* (berlanjutnya *markup*). Partisipasi teraman diagendakan di rentang {entry_zone_str} selama level krusial tidak dijebol pasca *break*."
    elif action == "BUY_REVERSAL":
        act_text = f"Ditemukan indikasi kompresi pola pasca *markdown* bertubi-tubi (akumulasi dinamis). Pembukaan posisi agresif terjustifikasi karena batasan invalidasi struktur ({sl}) cukup defensif untuk melindungi ekuitas dari pergerakan raw *downside*."
    else:
        act_text = f"Sesuai parameter kuantitatif, atur limit *entry* wajar di rentang zona {entry_zone_str} dan amankan posisi jika basis struktur {sl} gagal dipertahankan oleh agregasi bid di lelang instrumen."

    penjelasan_str = f"{symbol} {regime_text}. {struct_text} {mom_str}\n\n{act_text}"
    
    return {
        "bias_str": bias_str,
        "struktur_str": struktur_str,
        "entry_zone_str": entry_zone_str,
        "target_str": target_str,
        "penjelasan_str": penjelasan_str.strip()
    }


# ══════════════════════════════════════════════
# SMC / WYCKOFF / MOMENTUM — 7 Detection Engines
# ══════════════════════════════════════════════


