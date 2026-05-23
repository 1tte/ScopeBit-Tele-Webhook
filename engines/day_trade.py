import os
import tempfile
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import mplfinance as mpf
import pandas as pd
import numpy as np
import random
from PIL import Image

from engines.technical import (
    calc_ema, calc_atr, calc_rsi, calc_hurst,
    detect_support_resistance, classify_regime, generate_trading_levels,
    calc_majority_rule_14, calc_bull_bear_vol,
    calc_zigzag_swings, label_dow_theory, classify_price_action_scenario,
    sanitize_ohlcv, detect_vsa_signals, detect_scalp_setups, round_to_idx_tick, _get_idx_tick)
from engines.trading_patterns import (
    aggregate_smc_signals, detect_early_smart_money, detect_institutional_setups
)
from engines.fundamental import parse_keystats, _safe_num, grade_pe, grade_pbv, grade_der, grade_npm, grade_roa
from engines.chart_drawing import (
    draw_advanced_ta, LabelRegistry, get_astronacci_style, get_modern_style, calculate_y_limits
)


# ──────────────────────────────────────────────
# Technical Indicators (Day Trading)
# ──────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

# Simple moving average helper
def _ma(series: pd.Series, period: int) -> pd.Series:
    """Calculate simple moving average using rolling mean."""
    return series.rolling(window=period, min_periods=1).mean()

def _check_ma_confluence(price, ma5, ma20, ma9, ma21):
    """
    Dual MA Confluence Check (Backend Engine).
    
    Sistem 1 (Primary/Display): MA5 vs MA20
    Sistem 2 (Konfirmasi/Backend): MA9 vs MA21
    
    BUY hanya diizinkan jika KEDUA sistem setuju bullish.
    Ini mencegah sinyal palsu saat guyuran / haircut potential.
    
    Returns:
        dict with keys: confirmed (bool), sys1 (str), sys2 (str), detail (str)
    """
    # Default: confirmed jika data tidak cukup (graceful fallback)
    result = {"confirmed": True, "sys1": "N/A", "sys2": "N/A", "detail": "Data kurang"}
    
    # Sistem 1: MA5 vs MA20
    sys1_bull = False
    if ma5 is not None and ma20 is not None:
        sys1_bull = ma5 > ma20
        result["sys1"] = "BULL" if sys1_bull else "BEAR"
    else:
        return result  # Data kurang, default confirmed=True
    
    # Sistem 2: MA9 vs MA21
    sys2_bull = False
    if ma9 is not None and ma21 is not None:
        sys2_bull = ma9 > ma21
        result["sys2"] = "BULL" if sys2_bull else "BEAR"
    else:
        return result  # Data kurang, default confirmed=True
    
    # Price position check (bonus confirmation)
    price_above_mas = (price > ma5 and price > ma9) if price else False
    
    # Confluence logic:
    # - BOTH bullish = CONFIRMED ✅
    # - Only one bullish = NOT confirmed ⚠️ (guyuran risk)
    # - BOTH bearish = NOT confirmed ❌
    both_bull = sys1_bull and sys2_bull
    
    if both_bull:
        result["confirmed"] = True
        result["detail"] = "MA5 &gt; 20 ✓ MA9 &gt; 21 ✓"
    elif sys1_bull and not sys2_bull:
        result["confirmed"] = False
        result["detail"] = "MA5 &gt; 20 ✓ tapi MA9 &lt; 21 ✗"
    elif not sys1_bull and sys2_bull:
        result["confirmed"] = False
        result["detail"] = "MA5 &lt; 20 ✗ tapi MA9 &gt; 21 ✓"
    else:
        result["confirmed"] = False
        result["detail"] = "MA5 &lt; 20 ✗ MA9 &lt; 21 ✗"
    
    return result


def _vwap(df: pd.DataFrame) -> pd.Series:
    """Daily Anchored VWAP: Reset kalkulasi setiap pergantian hari/pagi."""
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    tp_vol = typical_price * df["Volume"]
    
    # .groupby(df.index.date) memastikan VWAP di-reset setiap hari baru
    cum_vol = df["Volume"].groupby(df.index.date).cumsum()
    cum_tp_vol = tp_vol.groupby(df.index.date).cumsum()
    
    return cum_tp_vol / cum_vol


def _stoch(df: pd.DataFrame, period: int = 14, smooth_k: int = 3, smooth_d: int = 3):
    lowest_low = df["Low"].rolling(window=period).min()
    highest_high = df["High"].rolling(window=period).max()
    fast_k = 100 * ((df["Close"] - lowest_low) / (highest_high - lowest_low))
    slow_k = fast_k.rolling(window=smooth_k).mean()
    slow_d = slow_k.rolling(window=smooth_d).mean()
    return slow_k, slow_d


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def detect_pivot_extrema(df: pd.DataFrame, left_bars=5, right_bars=5):
    window = left_bars + right_bars + 1
    df['rolling_max'] = df['High'].rolling(window=window, center=True).max()
    df['is_peak'] = df['High'] == df['rolling_max']
    df['rolling_min'] = df['Low'].rolling(window=window, center=True).min()
    df['is_trough'] = df['Low'] == df['rolling_min']
    swings = []
    for i in range(len(df)):
        if df['is_peak'].iloc[i]:
            swings.append({'idx': i, 'price': df['High'].iloc[i], 'type': 'peak'})
        elif df['is_trough'].iloc[i]:
            swings.append({'idx': i, 'price': df['Low'].iloc[i], 'type': 'trough'})
    df.drop(columns=['rolling_max', 'is_peak', 'rolling_min', 'is_trough'], inplace=True)
    if not swings: return []
    filtered = [swings[0]]
    for s in swings[1:]:
        last_s = filtered[-1]
        if s['type'] != last_s['type']:
            filtered.append(s)
        else:
            if s['type'] == 'peak' and s['price'] > last_s['price']:
                filtered[-1] = s
            elif s['type'] == 'trough' and s['price'] < last_s['price']:
                filtered[-1] = s
    return filtered



def calc_indicators(df: pd.DataFrame) -> dict:
    """Calculate day trading indicators: MA5, MA20, VWAP, RSI, Stochastic, MACD, ATR, Hurst, S&R."""
    # Data Sanitization: remove zero-volume dead bars
    df = sanitize_ohlcv(df)
    
    df["ma5"] = _ma(df["Close"], 5)
    df["ma20"] = _ma(df["Close"], 20)
    df["vwap"] = _vwap(df)
    df["rsi"] = calc_rsi(df["Close"], 14)
    df["stoch_k"], df["stoch_d"] = _stoch(df)
    df["macd"], df["macd_signal"], df["macd_hist"] = _macd(df["Close"])
    df["bull_vol"], df["bear_vol"] = calc_bull_bear_vol(df)
    atr_series, atr_info = calc_atr(df, 14)
    df["atr"] = atr_series

    latest = df.iloc[-1]
    price = latest["Close"]
    atr_val = atr_info["atr"]

    # Hurst Exponent for regime detection (now returns confidence)
    hurst, hurst_confidence = calc_hurst(df["Close"], max_lag=20)

    # S&R Detection
    snr = detect_support_resistance(df, atr_val, price)

    from engines.technical import detect_gaps
    unfilled_gaps = detect_gaps(df, min_gap_pct=0.3)

    best_swings = []
    best_labels = []
    best_scenario = None
    
    # Intraday pattern scanner
    for mult in [2.5, 2.0, 1.5, 1.2]:
        test_swings = calc_zigzag_swings(df, atr_series, threshold_mult=mult)
        test_labels = label_dow_theory(test_swings)
        test_scenario = classify_price_action_scenario(
            labeled_swings=test_labels,
            supports=snr["supports"],
            resistances=snr["resistances"],
            gaps=unfilled_gaps,
            stoch_k=latest.get("stoch_k"),
            stoch_d=latest.get("stoch_d"),
            current_price=price,
            atr=atr_val,
        )
        if test_scenario is not None:
            best_swings = test_swings
            best_labels = test_labels
            best_scenario = test_scenario
            break
            
    if best_scenario is None:
        # Cek 8 candle ke kiri dan kanan (16 candle total) untuk mencari P/T yang benar-benar pucuk
        best_swings = detect_pivot_extrema(df, left_bars=8, right_bars=8)
        best_labels = label_dow_theory(best_swings)
        best_scenario = None

    swings = best_swings
    dow_labels = best_labels
    scenario = best_scenario
    
    if scenario is None:
        scenario = classify_price_action_scenario(
            labeled_swings=dow_labels,
            supports=snr["supports"],
            resistances=snr["resistances"],
            gaps=unfilled_gaps,
            stoch_k=latest.get("stoch_k"),
            stoch_d=latest.get("stoch_d"),
            current_price=price,
            atr=atr_val,
        )

    # Regime classification (Day Trade uses daily MAs for alignment with Stockbit/TV)
    # Resample 1H → Daily untuk mendapat MA daily yang akurat
    daily_ma5 = None
    daily_ma20 = None
    daily_ma9 = None
    daily_ma21 = None
    try:
        df_daily = df.resample('1D').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min',
            'Close': 'last', 'Volume': 'sum'
        }).dropna(subset=['Close'])
        if len(df_daily) >= 5:
            daily_ma5 = float(df_daily["Close"].rolling(5).mean().iloc[-1])
        if len(df_daily) >= 9:
            daily_ma9 = float(df_daily["Close"].rolling(9).mean().iloc[-1])
        if len(df_daily) >= 20:
            daily_ma20 = float(df_daily["Close"].rolling(20).mean().iloc[-1])
        if len(df_daily) >= 21:
            daily_ma21 = float(df_daily["Close"].rolling(21).mean().iloc[-1])
    except Exception:
        pass

    # ── Dual MA Confluence Check (Backend Only — tidak ditampilkan) ──
    # Sistem 1: MA5 vs MA20 (primary display)
    # Sistem 2: MA9 vs MA21 (backend confirmation)
    # BUY hanya jika KEDUA sistem setuju bullish
    ma_confluence = _check_ma_confluence(price, daily_ma5, daily_ma20, daily_ma9, daily_ma21)

    # Use daily MAs for regime (fallback ke 1H MA jika daily belum cukup data)
    regime_ma_short = daily_ma5 if daily_ma5 else latest.get("ma5")
    regime_ma_long = daily_ma20 if daily_ma20 else latest.get("ma20")

    regime = classify_regime(
        hurst=hurst,
        rsi=latest.get("rsi"),
        ema20=regime_ma_short,   # Daily MA5 (short-term MA)
        ema50=regime_ma_long,    # Daily MA20 (medium-term MA)
        price=price,
        ma200=latest.get("vwap"),   # VWAP as long-term anchor
        macd=latest.get("macd"),
        macd_signal=latest.get("macd_signal"),
    )

    # 1. BUNGKUS KE DALAM DICTIONARY DULU
    res_dict = {
        "price": price,
        "ma5": latest.get("ma5"),
        "ma20": latest.get("ma20"),
        "daily_ma5": daily_ma5,
        "daily_ma20": daily_ma20,
        "ma_confluence": ma_confluence,
        "vwap": latest.get("vwap"),
        "rsi": latest.get("rsi"),
        "stoch_k": latest.get("stoch_k"),
        "stoch_d": latest.get("stoch_d"),
        "macd": latest.get("macd"),
        "macd_signal": latest.get("macd_signal"),
        "atr": atr_val,
        "atr_info": atr_info,
        "hurst": hurst,
        "swings": swings,
        "dow_labels": dow_labels,
        "scenario": scenario,
        "snr": snr,
        "regime": regime,
        "majority": calc_majority_rule_14(df),
        "gaps": unfilled_gaps,
        "hurst_confidence": hurst_confidence,
        "vsa_signals": detect_vsa_signals(df),
        "scalp_setups": detect_scalp_setups(df, snr),
    }

    # 2. EKSEKUSI EARLY SETUP SEBELUM RETURN
    
    # Early detection of smart money footprints
    early_setup = detect_early_smart_money(df, snr, hurst, is_intraday=True) 
    res_dict["early_setup"] = early_setup

    # 3. SMC / INSTITUTIONAL ENGINE SUITE (7 Engines)
    res_dict["smc_signals"] = aggregate_smc_signals(df, snr)
    
    return res_dict


# ──────────────────────────────────────────────
# Micro-Structure Engine (5M Scalping Detector)
# ──────────────────────────────────────────────

def calc_micro_signals(df_5m: pd.DataFrame, snr_1h: dict) -> list[dict]:
    """Engine 2: Sang Pasukan — Detects micro scalping anomalies on raw 5M data.
    Uses 1H S&R as structural reference.
    """
    signals = []
    if len(df_5m) < 15:
        return signals

    # Calculate 5M-native indicators
    df_5m = df_5m.copy()
    df_5m["ma5"] = _ma(df_5m["Close"], 5)
    df_5m["ma20"] = _ma(df_5m["Close"], 20)
    df_5m["ema21"] = _ema(df_5m["Close"], 21)
    df_5m["vwap"] = _vwap(df_5m)
    df_5m["rsi"] = calc_rsi(df_5m["Close"], 14)

    latest = df_5m.iloc[-1]
    prev = df_5m.iloc[-2]
    close = float(latest["Close"])
    open_ = float(latest["Open"])
    high = float(latest["High"])
    low = float(latest["Low"])
    vol = float(latest["Volume"])
    body = abs(close - open_)
    lower_wick = min(close, open_) - low
    upper_wick = high - max(close, open_)
    candle_range = high - low if high > low else 1
    is_bullish = close > open_

    avg_vol = float(df_5m["Volume"].iloc[-40:].mean()) if len(df_5m) >= 40 else float(df_5m["Volume"].mean())
    vol_ratio = vol / avg_vol if avg_vol > 0 else 1.0

    vwap = float(latest["vwap"]) if not pd.isna(latest.get("vwap")) else None
    ma5 = float(latest["ma5"]) if not pd.isna(latest.get("ma5")) else None
    ma20 = float(latest["ma20"]) if not pd.isna(latest.get("ma20")) else None
    rsi = float(latest["rsi"]) if not pd.isna(latest.get("rsi")) else None

    # ── 1. VWAP Bounce (5M precision) ──
    if vwap and vwap > 0:
        dist_pct = (close - vwap) / vwap
        if (0 < dist_pct < 0.015
            and low <= vwap * 1.003
            and close > vwap
            and lower_wick >= body * 0.5
            and body > 0):
            signals.append({
                "type": "VWAP_BOUNCE_5M",
                "direction": "BULL",
                "label": "⚡ VWAP Bounce 5M",
                "desc": "Pantulan presisi dari VWAP pada timeframe 5 Menit",
            })

    # ── 2. Bull Flag Breakout (5M) ──
    if len(df_5m) >= 15 and ma5 is not None and close > ma5:
        recent_5 = df_5m.iloc[-6:-1]
        if len(recent_5) >= 3:
            ranges = (recent_5["High"] - recent_5["Low"]).values
            avg_range_recent = float(np.mean(ranges[-3:]))
            avg_range_prior = float(np.mean((df_5m["High"] - df_5m["Low"]).iloc[-20:-6].values)) if len(df_5m) >= 20 else avg_range_recent * 2
            is_contracting = avg_range_recent < avg_range_prior * 0.70
            consol_high = float(recent_5["High"].max())
            is_breakout = close > consol_high and is_bullish

            if is_contracting and is_breakout and vol_ratio > 1.2:
                signals.append({
                    "type": "BULL_FLAG_5M",
                    "direction": "BULL",
                    "label": "🚀 Bull Flag 5M",
                    "desc": "Breakout konsolidasi ketat pada chart 5 Menit",
                })

    # ── 3. Liquidity Sweep / Spring at 1H Support (5M precision) ──
    supports_1h = snr_1h.get("supports", [])
    if supports_1h:
        for sup in supports_1h[:3]:
            sup_level = float(sup["level"])
            pierced = low <= sup_level * 1.005
            recovered = close > sup_level
            long_wick = lower_wick >= body * 1.5 if body > 0 else lower_wick > candle_range * 0.4
            if pierced and recovered and long_wick and vol_ratio > 1.0:
                signals.append({
                    "type": "SPRING_5M",
                    "direction": "BULL",
                    "label": "⚡ Spring 5M",
                    "desc": f"Liquidity sweep di Support 1H ({int(sup_level)}), harga recover",
                })
                break

    # ── 4. Fair Value Gap / Imbalance (5M) ──
    if len(df_5m) >= 5:
        c_t = df_5m.iloc[-1]
        c_t1 = df_5m.iloc[-2]
        c_t2 = df_5m.iloc[-3]
        low_t = float(c_t["Low"])
        high_t2 = float(c_t2["High"])
        close_t1 = float(c_t1["Close"])
        open_t1 = float(c_t1["Open"])
        is_bull_t1 = close_t1 > open_t1

        if low_t > high_t2 and is_bull_t1:
            gap_pct = (low_t - high_t2) / close if close > 0 else 0
            if gap_pct > 0.002:
                signals.append({
                    "type": "FVG_5M",
                    "direction": "BULL",
                    "label": "⚡ FVG 5M",
                    "desc": f"Fair Value Gap {gap_pct*100:.1f}% terdeteksi di 5 Menit",
                })

        high_t = float(c_t["High"])
        low_t2 = float(c_t2["Low"])
        is_bear_t1 = close_t1 < open_t1
        if high_t < low_t2 and is_bear_t1:
            gap_pct = (low_t2 - high_t) / close if close > 0 else 0
            if gap_pct > 0.002:
                signals.append({
                    "type": "FVG_BEAR_5M",
                    "direction": "BEAR",
                    "label": "⚠️ FVG Bear 5M",
                    "desc": f"Bearish FVG {gap_pct*100:.1f}% terdeteksi di 5 Menit",
                })

    # ── 5. HOD Momentum Break (5M) ──
    lookback = min(40, len(df_5m) - 1)
    if lookback >= 10:
        hod_before = float(df_5m["High"].iloc[-(lookback+1):-1].max())
        if close > hod_before and is_bullish and vol_ratio > 1.0:
            signals.append({
                "type": "HOD_BREAK_5M",
                "direction": "BULL",
                "label": "🚀 HOD Break 5M",
                "desc": "Harga tembus High of Day pada chart 5 Menit",
            })

    # ── 6. Momentum Surge (5M) ──
    if is_bullish and body > 0:
        body_pct = body / close
        if body_pct > 0.01 and upper_wick < body * 0.3 and vol_ratio > 1.5:
            signals.append({
                "type": "MOMENTUM_5M",
                "direction": "BULL",
                "label": "🚀 Momentum 5M",
                "desc": "Candle kuat dengan volume tinggi pada 5 Menit",
            })

    # ── 7-9. SMC Micro Signals (5M precision) ──
    from engines.trading_patterns import detect_choch_bos, detect_equal_level_sweep, detect_three_bar_play
    
    choch = detect_choch_bos(df_5m, lookback=15, vol_mult=1.2)
    if choch:
        signals.append({
            "type": f"CHOCH_5M_{choch['direction']}",
            "direction": choch["direction"],
            "label": f"{choch['label']} 5M",
            "desc": choch["desc"],
        })

    eql = detect_equal_level_sweep(df_5m, lookback=20, tolerance_pct=0.002)
    if eql:
        signals.append({
            "type": f"EQL_5M_{eql['direction']}",
            "direction": eql["direction"],
            "label": f"{eql['label']} 5M",
            "desc": eql["desc"],
        })

    tbp = detect_three_bar_play(df_5m)
    if tbp:
        signals.append({
            "type": f"TBP_5M_{tbp['direction']}",
            "direction": tbp["direction"],
            "label": f"{tbp['label']} 5M",
            "desc": tbp["desc"],
        })

    return signals


# ──────────────────────────────────────────────
# Cross-Validation Gatekeeper (5M ↔ 1H)
# ──────────────────────────────────────────────

def cross_validate(micro_signals: list[dict], regime_1h: dict, snr_1h: dict, price: float) -> list[dict]:
    """The Gatekeeper: Validates 5M micro signals against 1H macro context.

    Returns list of validated signals with 'verdict' key:
      ALLOW  = Sinergi sempurna, signal ditampilkan
      DENY   = Signal ditolak oleh konteks 1H
    """
    if not micro_signals:
        return []

    state_1h = regime_1h.get("state", "RANGING")
    bias_1h = regime_1h.get("bias", "SIDEWAYS")
    supports = snr_1h.get("supports", [])
    sup_levels = [s["level"] for s in supports[:3]]

    # Apakah harga sedang menyentuh support mayor 1H?
    near_major_support = False
    if sup_levels and price > 0:
        for sl in sup_levels:
            if abs(price - sl) / price < 0.02:  # within 2%
                near_major_support = True
                break

    validated = []
    for sig in micro_signals:
        direction = sig.get("direction", "BULL")
        sig_type = sig.get("type", "")

        # ── BULLISH SIGNALS ──
        if direction == "BULL":
            if state_1h in ("MARKUP", "ACCUMULATION"):
                # Sinergi Sempurna: 5M Bull + 1H Bullish
                sig["verdict"] = "ALLOW"
                sig["verdict_reason"] = "Sinergi 1H " + state_1h
                sig["verdict_icon"] = "🚀"
            elif state_1h == "RANGING":
                # Netral, izinkan dengan catatan
                sig["verdict"] = "ALLOW"
                sig["verdict_reason"] = "1H Sideways, scalp cepat"
                sig["verdict_icon"] = "⚡"
            elif state_1h in ("MARKDOWN", "DISTRIBUTION"):
                # Counter-trend: hanya ALLOW jika Spring/Sweep di support mayor
                is_spring = "SPRING" in sig_type or "SWEEP" in sig_type
                if near_major_support and (is_spring or "VWAP" in sig_type):
                    sig["verdict"] = "ALLOW"
                    sig["verdict_reason"] = "Pantulan Support Mayor 1H"
                    sig["verdict_icon"] = "⚡"
                else:
                    sig["verdict"] = "DENY"
                    sig["verdict_reason"] = f"Tren 1H {state_1h}"
                    sig["verdict_icon"] = "⚠️"
            else:
                sig["verdict"] = "ALLOW"
                sig["verdict_reason"] = "Default"
                sig["verdict_icon"] = "⚡"

        # ── BEARISH SIGNALS ──
        elif direction == "BEAR":
            if state_1h in ("MARKDOWN", "DISTRIBUTION"):
                sig["verdict"] = "ALLOW"
                sig["verdict_reason"] = "Sinergi 1H " + state_1h
                sig["verdict_icon"] = "⚠️"
            elif state_1h in ("MARKUP", "ACCUMULATION"):
                sig["verdict"] = "DENY"
                sig["verdict_reason"] = "Tren 1H Bullish"
                sig["verdict_icon"] = "⚠️"
            else:
                sig["verdict"] = "ALLOW"
                sig["verdict_reason"] = "1H Netral"
                sig["verdict_icon"] = "⚠️"

        validated.append(sig)

    return validated


# ──────────────────────────────────────────────
# Trading Plan Generator (Day Trading)
# ──────────────────────────────────────────────

import re

def _safe_truncate(text: str, max_len: int) -> str:
    """Safely truncate HTML text without leaving unclosed tags."""
    if not text or len(text) <= max_len:
        return text
    truncated = text[:max_len]
    # Remove partially opened tag at the end (e.g. "<b", "<code")
    truncated = re.sub(r'<[^>]*$', '', truncated)
    
    # Track open tags using a stack
    tags = re.findall(r'</?(?:b|i|code|a|strong|em)(?:\s+[^>]*)?>', truncated, flags=re.IGNORECASE)
    stack = []
    for tag in tags:
        is_closing = tag.startswith('</')
        tag_name_match = re.match(r'</?([a-zA-Z]+)', tag)
        if tag_name_match:
            tag_name = tag_name_match.group(1).lower()
            if is_closing:
                if stack and stack[-1] == tag_name:
                    stack.pop()
            else:
                stack.append(tag_name)
                
    for tag in reversed(stack):
        truncated += f"</{tag}>"
    return truncated + "..."


def _fmt_price(val) -> str:
    if val is None or pd.isna(val):
        return "-"
    if val >= 100:
        return f"{val:,.0f}".replace(",", ".")
    elif val >= 1:
        return f"{val:.2f}".replace(".", ",")
    elif val >= 0.0001:
        return f"{val:.4f}".replace(".", ",")
    else:
        return f"{val:.8f}".replace(".", ",")


def generate_plan(symbol: str, df: pd.DataFrame, indicators: dict) -> str:
    """Build a Telegram-formatted day trading plan caption."""
    price = indicators.get("price")
    ma5 = indicators.get("daily_ma5") or indicators.get("ma5")
    ma20 = indicators.get("daily_ma20") or indicators.get("ma20")
    vwap = indicators.get("vwap")
    rsi = indicators.get("rsi")
    macd_val = indicators.get("macd")
    macd_sig = indicators.get("macd_signal")
    atr = indicators.get("atr", 0)
    hurst = indicators.get("hurst", 0.5)
    snr = indicators.get("snr") or {"supports": [], "resistances": []}
    regime = indicators.get("regime") or {}

    # ── Regime & Bias ──
    mr14 = indicators.get("majority", {})
    bias_desc = mr14.get("bias", "Neutral")
    bias_detail = mr14.get("detail", "0B | 0S | 0N")
    bias = f"{bias_desc} ({bias_detail})"
        
    regime_desc = regime.get("description", "")

    # Hurst interpretation
    hurst_confidence = indicators.get("hurst_confidence", "HIGH")
    if hurst > 0.60:
        hurst_label = "Trending"
    elif hurst > 0.50:
        hurst_label = "Slight Trend"
    elif hurst < 0.45:
        hurst_label = "Mean Reverting"
    else:
        hurst_label = "Random Walk"
    hurst_warn = " ⚠️Low Data" if hurst_confidence == "LOW" else ""
    hurst_str = f"{hurst:.2f} ({hurst_label}{hurst_warn})"
    
    # VSA Signals
    vsa_signals = indicators.get("vsa_signals", [])
    vsa_line = ""
    if vsa_signals:
        vsa_texts = [s["label"] for s in vsa_signals[:2]]  # Max 2 for caption space
        vsa_line = "\n".join(vsa_texts)

    # VWAP position
    if vwap is not None and not pd.isna(vwap):
        if price > vwap:
            vwap_label = "Above Bullish"
        elif price < vwap:
            vwap_label = "Below Bearish"
        else:
            vwap_label = "At VWAP"
        vwap_str = f"{_fmt_price(vwap)} ({vwap_label})"
    else:
        vwap_str = "-"

    # RSI interpretation
    if rsi is not None and not pd.isna(rsi):
        if rsi >= 70:
            rsi_label = "Overbought"
        elif rsi <= 30:
            rsi_label = "Oversold"
        else:
            rsi_label = "Netral"
        rsi_str = f"{rsi:.1f} ({rsi_label})"
    else:
        rsi_str = "-"

    # MACD interpretation
    if macd_val is not None and macd_sig is not None and not pd.isna(macd_val) and not pd.isna(macd_sig):
        if macd_val > macd_sig:
            macd_label = "Bullish Cross"
        else:
            macd_label = "Bearish Cross"
        macd_str = f"{macd_val:.1f} ({macd_label})"
    else:
        macd_str = "-"

    # ── Generate Trading Levels (Day Trade mode) ──
    # Use daily MA5 as fallback anchor when VWAP unavailable
    daily_ma5_anchor = indicators.get("daily_ma5") or ma5
    ema_anchor = vwap if (vwap is not None and not pd.isna(vwap)) else daily_ma5_anchor
    
    levels = generate_trading_levels(
        current_price=price,
        supports=snr["supports"],
        resistances=snr["resistances"],
        atr=atr,
        atr_info=indicators.get("atr_info", {"regime": "NORMAL"}),
        hurst=hurst,
        mode="daytrade",
        ema_anchor=ema_anchor,
        ma200=vwap,  # VWAP as long-term anchor for SL/TP validation
        scenario=indicators.get("scenario"),
        labeled_swings=indicators.get("dow_labels", []),
    )
    indicators["levels"] = levels
    # Use buy_low (bottom of entry zone) as anchor for display percentages
    buy_low = levels.get("buy_low")
    buy_high = levels.get("buy_high")
    # TP TARGET PRICES: anchor on buy_high (top of entry zone)
    # Ensures TPs always CLEAR the entry zone — no overlap with buy zone
    tp_base = buy_high if buy_high else (buy_low if buy_low else price)

    if tp_base is not None and not pd.isna(tp_base) and tp_base > 0:
        levels["tp1"] = round_to_idx_tick(tp_base * 1.03)
        levels["tp2"] = round_to_idx_tick(tp_base * 1.06)
        
        # Use the dynamic SL from technical.py for risk calculations
        cut_loss_price = levels["sl"] - _get_idx_tick(levels["sl"])
        risk = (buy_low if buy_low else tp_base) - cut_loss_price
        
        levels["tp1_pct"] = round(((levels["tp1"] - buy_low) / buy_low) * 100, 2)
        levels["tp2_pct"] = round(((levels["tp2"] - buy_low) / buy_low) * 100, 2)
        # Recalculate SL% from buy_low for consistency
        levels["sl_pct"] = round(((buy_low - cut_loss_price) / buy_low) * 100, 1)
        
        if risk > 0:
            levels["rr1"] = round((levels["tp1"] - buy_low) / risk, 1)
            levels["rr2"] = round((levels["tp2"] - buy_low) / risk, 1)

    # ── S&R Display ──
    support_level = levels.get("support_level")
    resist_level = levels.get("resist_level")
    
    sup_strs = []
    if snr["supports"]:
        for s in snr["supports"][:3]:
            mark = "*" if support_level and s["level"] == support_level else ""
            type_label = " (Gap)" if s.get("type") == "gap" else ""
            tf = s.get('timeframe', 'Daily').lower()
            tf_shorthand = "[w]" if "weekly" in tf else "[m]" if "monthly" in tf else "[d]"
            sup_strs.append(f"{tf_shorthand} {_fmt_price(s['level'])}{type_label} (str: {s['strength']:.0f}{mark})")
        sup_str = "\n".join(sup_strs)
    else:
        sup_str = "Support Unknown / ATL"

    res_strs = []
    if snr["resistances"]:
        for r in snr["resistances"][:3]:
            mark = "*" if resist_level and r["level"] == resist_level else ""
            type_label = " (Gap)" if r.get("type") == "gap" else ""
            tf = r.get('timeframe', 'Daily').lower()
            tf_shorthand = "[w]" if "weekly" in tf else "[m]" if "monthly" in tf else "[d]"
            res_strs.append(f"{tf_shorthand} {_fmt_price(r['level'])}{type_label} (str: {r['strength']:.0f}{mark})")
        res_str = "\n".join(res_strs)
    else:
        from engines.breakout_detector import detect_breakout_scenario
        breakout = detect_breakout_scenario(df)
        conf = breakout.get("confidence", 0)
        res_str = f"Resist ATH/Breakout (Conf: {conf}%)"

    # Convert action keys to proper text
    action_key = levels.get("action", "")
    sup_level_fmt = _fmt_price(levels.get("support_level"))
    res_level_fmt = _fmt_price(levels.get("resist_level"))
    
    is_gap_sup = any(s["level"] == levels.get("support_level") and s.get("type") == "gap" for s in snr.get("supports", []))
    
    # ── Dual MA Confluence Gate ──
    # Downgrade BUY signals jika MA9+MA21 belum konfirmasi arah bullish
    confluence = indicators.get("ma_confluence", {})
    is_confirmed = confluence.get("confirmed", True)  # default True jika data kurang
    confluence_detail = confluence.get("detail", "")
    
    BUY_ACTIONS = {"BUY_NOW", "BUY_BREAKOUT_RETEST", "BUY_BREAKOUT", "BUY_MOMENTUM"}
    
    if action_key in BUY_ACTIONS and not is_confirmed:
        # Downgrade: BUY → WAIT (MA belum konfirmasi)
        action_key = "WAIT_MA_CONFLUENCE"
    
    if action_key == "BUY_NOW":
        if is_gap_sup:
            action_str = f"BUY NOW (Ada gap di {sup_level_fmt})"
        else:
            action_str = f"BUY NOW (Dekat support {sup_level_fmt})"
    elif action_key == "WAIT_MA_CONFLUENCE":
        action_str = f"⚠️ WAIT (MA belum konfirmasi — {confluence_detail})"
    elif action_key == "WAIT_PULLBACK":
        if is_gap_sup:
            action_str = f"WAIT (Tunggu tutup gap di {sup_level_fmt})"
        else:
            action_str = f"WAIT (Pantul di support {sup_level_fmt})"
    elif action_key == "BUY_IF_BREAKOUT":
        action_str = f"WAIT TO BUY (Breakout di {res_level_fmt})"
    elif action_key == "BUY_BREAKOUT_RETEST":
        action_str = f"BUY NOW (Retest support {sup_level_fmt})"
    elif action_key == "BUY_BREAKOUT":
        action_str = f"BUY (Breakout {res_level_fmt})"
    elif action_key == "POOR_RR_AVOID":
        action_str = "AVOID (RR Buruk)"
    elif action_key == "BUY_MOMENTUM":
        action_str = "BUY NOW (Momentum Break 🚀)"
    else:
        action_str = action_key.replace("_", " ")

    # Check regime veto
    is_explicit_setup = action_key in ("BUY_REVERSAL", "BUY_PULLBACK", "BUY_MOMENTUM", "BUY_IF_BREAKOUT", "BUY_BREAKOUT_RETEST", "WAIT_FALSE_BREAK")
    if not is_explicit_setup and regime.get("state") in ("MARKDOWN", "DISTRIBUTION"):
        if regime.get("reversal_candidate") and regime.get("state") == "DISTRIBUTION":
            action_str = "WAIT (Reversal Candidate ⚡)"
        else:
            action_str = "AVOID (" + regime.get("state", "") + ")"

    # Detect institutional setups
    institutional_setups = detect_institutional_setups(df, snr, atr, is_intraday=True)
    L_separator = "━" * 34
    
    institutional_text = ""
    if institutional_setups:
        institutional_text = f"\n<code>{L_separator}</code>\n" + "\n\n".join(institutional_setups)

    # ── SMC ENGINE SUITE (7 Engines) ──
    smc_signals = indicators.get("smc_signals", [])
    if smc_signals:
        smc_lines = []
        has_bull_smc = 0
        has_bear_smc = False
        for sig in smc_signals:
            smc_lines.append(f"<b>{sig['label']}</b>\n{sig['desc']}")
            if sig.get('direction') == 'BULL' and sig.get('action_hint', '').startswith('BUY'):
                has_bull_smc += 1
            if sig.get('action_hint') == 'AVOID':
                has_bear_smc = True

        smc_text = "\n\n".join(smc_lines)
        if institutional_text:
            institutional_text += f"\n\n{smc_text}"
        else:
            institutional_text = f"\n<code>{L_separator}</code>\n{smc_text}"

        # ── STRICT ACTION OVERRIDE ──
        if has_bear_smc:
            action_str = "AVOID (SMC Warning ⚠️)"
        elif has_bull_smc >= 2:
            action_str = "BUY NOW (SMC Confirmed 🧬)"

    early_setup = indicators.get("early_setup")
    if early_setup:
        action_str = early_setup["action"] + " ⚡"
        if not institutional_text:
            institutional_text = f"\n<code>{L_separator}</code>\n{early_setup['desc']}"
        else:
            institutional_text += f"\n\n{early_setup['desc']}"

    tactical_hint = ""
    scenario_hint = ""
    scenario_obj = indicators.get("scenario")
    if scenario_obj:
        scenario_hint = f"\n{scenario_obj.get('description', '-')}"
        tactical_hint = f" — {scenario_obj.get('name', '-')}"
    else:
        if action_key == "BUY_IF_BREAKOUT":
            tactical_hint = f" — Tunggu breakout {res_level_fmt} untuk konfirmasi trend"
        elif action_key == "BUY_NOW":
            tactical_hint = " — buy now"
        elif action_key == "WAIT_PULLBACK":
            tactical_hint = " — wait for pullback"
        elif action_key == "BUY_BREAKOUT_RETEST":
            tactical_hint = " — buy on retest"
        elif action_key == "BUY_BREAKOUT":
            tactical_hint = " — buy breakout momentum"
    
    full_desc = f"{regime_desc}{tactical_hint}{scenario_hint}"

    momentum_desc = scenario_obj.get("momentum", "") if scenario_obj else ""
    momentum_line = f"<i>{momentum_desc}</i>\n" if momentum_desc else ""
    if vsa_line:
        momentum_line += f"<i>{vsa_line}</i>\n"

    L = "━" * 34
    
    is_ihsg = (symbol == "COMPOSITE")
    title_label = "Market Outlook" if is_ihsg else "Day Trade Setup"
    

    lines = [
        f"<b>#{symbol} - {title_label}</b>",
        f"<code>{L}</code>",
        f"<b>MARKET STRUCTURE</b>",
        f"<code>"
        f"Bias     : {bias} (Majority Rule)\n"
        f"Hurst    : {hurst_str}\n"
        f"RSI(14)  : {rsi_str}\n"
        f"MACD     : {macd_str}\n"
        f"MA5      : {_fmt_price(ma5)}\n"
        f"MA20     : {_fmt_price(ma20)}\n"
        f"VWAP     : {vwap_str}\n"
        f"Support  : \n{sup_str}\n"
        f"Resist   : \n{res_str}"
        f"</code>",
        f"<code>{L}</code>",
    ]
    
    rr1_str = f" | RR {levels.get('rr1')}x" if levels.get('rr1') else ""
    rr2_str = f" | RR {levels.get('rr2')}x" if levels.get('rr2') else ""

    if not is_ihsg:
        lines.extend([
            f"<b>TRADING PLAN</b>",
            f"<code>"
            f"Action    : {action_str}\n"
            f"Entry Zone: {_fmt_price(levels['buy_low'])} - {_fmt_price(levels['buy_high'])}\n"
            f"TP 1      : {_fmt_price(levels['tp1'])} (+{levels.get('tp1_pct', '-')}%{rr1_str})\n"
            f"TP 2      : {_fmt_price(levels['tp2'])} (+{levels.get('tp2_pct', '-')}%{rr2_str})\n"
            f"Stop Loss : {'&lt; ' + _fmt_price(levels['sl'])} (-{levels.get('sl_pct','-')}%)"
            f"</code>",
            f"<code>{L}</code>",
        ])
        
    if len(full_desc) > 200: full_desc = _safe_truncate(full_desc, 197)
    if len(institutional_text) > 300: institutional_text = _safe_truncate(institutional_text, 297)

    # ── MTF SCALP RADAR (Dual-Engine Output) ──
    scalp_setups = indicators.get("scalp_setups", [])
    mtf_text = ""
    if scalp_setups and not is_ihsg:
        mtf_lines = []
        for sig in scalp_setups[:3]:
            label = sig.get("label", "")
            action = sig.get("action", "")
            sl = sig.get("sl_hint", "")
            mtf_lines.append(f"<b>{action}</b>\n{label}\n<i>⚠️ {sl}</i>")
        mtf_text = "\n\n".join(mtf_lines)

    # ── SAFE CAPTION ASSEMBLY ──
    momentum_plain = momentum_desc if momentum_desc else ""
    desc_part = f"{momentum_plain}\n{full_desc}" if momentum_plain else full_desc
    
    from engines.breakout_detector import generate_breakout_caption
    if "Momentum Break" in action_str:
        breakout_text = generate_breakout_caption(symbol, df)
        if breakout_text:
            lines.append(breakout_text)

    core_lines = lines.copy()
    core_lines.append(f"<i>{desc_part}</i>")
    core_lines.append(f"<i>⚠️ Disclaimer: Bukan ajakan jual/beli.</i>")
    
    opt_institutional = institutional_text if institutional_text else ""
    opt_mtf = f"<code>{L_separator}</code>\n<b>MTF SCALP RADAR (5M → 1H)</b>\n<code>{mtf_text}</code>" if mtf_text else ""
    
    all_parts = list(core_lines)
    if opt_institutional:
        all_parts.insert(-1, opt_institutional)
    if opt_mtf:
        all_parts.insert(-1, opt_mtf)
    
    final_caption = "\n".join(all_parts)
    
    # Progressive trimming if over 1024 Telegram limit
    if len(final_caption) > 1010:
        all_parts = list(core_lines)
        if opt_mtf:
            all_parts.insert(-1, opt_mtf)
        final_caption = "\n".join(all_parts)
    
    if len(final_caption) > 1010:
        all_parts = list(core_lines)
        if opt_institutional:
            all_parts.insert(-1, opt_institutional)
        final_caption = "\n".join(all_parts)
    
    if len(final_caption) > 1010:
        final_caption = "\n".join(core_lines)
    
    if len(final_caption) > 1010:
        final_caption = _safe_truncate(final_caption, 1000)
    return final_caption



# ──────────────────────────────────────────────
# Chart Renderer
# ──────────────────────────────────────────────

def render_chart(symbol: str, df: pd.DataFrame, indicators: dict | None = None, show_plan: bool = True, extra_data: dict = None) -> str:
    """Render a clean classic pro trading chart with S&R."""

    # ── 5-Day Structure-Based Anchor System ──
    full_df = df.copy()
    total_len = len(full_df)
    
    # Ambil daftar tanggal unik dari data yang ada
    recent_dates = pd.Series(full_df.index.date).unique()
    
    # Pastikan mengambil tepat 5 hari perdagangan ke belakang
    days_to_show = 5
    if len(recent_dates) >= days_to_show:
        target_date = recent_dates[-days_to_show]
        # Cari index pertama di mana tanggalnya adalah target_date
        mask = full_df.index.date >= target_date
        anchor_idx = int(np.argmax(mask))
    else:
        anchor_idx = 0
        
    # HAPUS batas maksimal 130 candle agar chart 5 hari utuh bisa dirender 
    # (data intraday bisa mencapai ratusan candle dalam 5 hari).
    # Kita hanya menyisakan batas minimum agar chart tidak kosong jika data harian terputus.
    candles_to_show = total_len - anchor_idx
    if candles_to_show < 45:
        anchor_idx = max(0, total_len - 45)
    
    # Potong DataFrame secara dinamis berdasarkan Anchor yang terpilih
    historical_df = full_df.iloc[anchor_idx:].copy()
    
    # ── Inject Future Whitespace (Hanya untuk /tps) ──
    if show_plan:
        future_bars = int(len(historical_df) * (30 / 70))
        last_date = historical_df.index[-1]
        freq = historical_df.index[-1] - historical_df.index[-2] if len(historical_df) > 1 else pd.Timedelta(minutes=15)
        if freq == pd.Timedelta(0):
            freq = pd.Timedelta(minutes=15)
        future_dates = pd.date_range(start=last_date + freq, periods=future_bars, freq=freq)
        future_df = pd.DataFrame(index=future_dates, columns=historical_df.columns).astype(float)
        plot_df = pd.concat([historical_df, future_df])
    else:
        plot_df = historical_df.copy() # /sw tidak butuh ruang kosong di kanan

    # ────── 2. Extract Structural Levels (Dow Theory) ──────
    last_price = historical_df["Close"].iloc[-1]
    
    # Golden Rule: Sync to trading levels fundamentally
    levels = indicators.get("levels", {}) if indicators else {}
    target_price = levels.get("tp1")
    if not target_price:
        target_price = levels.get("tp2")
        
    snr_info = indicators.get("snr", {})
    supports = snr_info.get("supports", [])
    
    sorted_supports = sorted([s["level"] for s in supports], reverse=True)
    
    sup_1 = sorted_supports[0] if len(sorted_supports) > 0 else (levels.get("support_level") or levels.get("sl"))
    sup_2 = sorted_supports[1] if len(sorted_supports) > 1 else None
    
    minor_res_price = None
    target_capped = False
    
    atr_val = historical_df['High'].iloc[-14:] - historical_df['Low'].iloc[-14:]
    atr = atr_val.mean() if not atr_val.empty else 100
    
    if show_plan and indicators:
        dow_labels = indicators.get("dow_labels", [])
        
        # Golden Rule: Minor Resistance Cluster
        resistances = snr_info.get("resistances", [])
        if resistances:
            minor_res_price = resistances[0]["level"]
            
        # Fallbacks:
        if not sup_1:
            sup_1 = historical_df["Low"].tail(20).min()
        if not minor_res_price or minor_res_price < last_price:
            for s in reversed(dow_labels):
                if s["type"] == "peak":
                    minor_res_price = s["price"]
                    break
            if not minor_res_price:
                minor_res_price = last_price + atr
        
        # Day Trade Target Fallback logic
        if not target_price:
            peaks_above = [s for s in dow_labels if s["type"] == "peak" and s["price"] > last_price]
            if peaks_above:
                target_price = min(peaks_above, key=lambda x: x["price"])["price"]
            else:
                target_price = last_price + (atr * 1.5)

    # ────── 3. Setup Tema & Y-Limits (SWITCH DINAMIS) ──────
    if show_plan:
        style, up_color, down_color, bg_color, text_color = get_astronacci_style()
        chart_type = "hollow_and_filled"
        fig_size = (14, 10)
        padding_pct = 0.18
        bottom_padding_pct = 0.15
    else:
        style, up_color, down_color, bg_color, text_color = get_modern_style()
        chart_type = "candle"
        fig_size = (14, 12) # Lebih tinggi karena ada 3 panel (Harga, Stoch, MACD)
        padding_pct = 0.15
        bottom_padding_pct = 0.10
        
    is_premium = bool(extra_data)
    
    y_bottom, y_top = calculate_y_limits(historical_df, padding_pct=padding_pct, bottom_padding_pct=bottom_padding_pct)
    
    # ── PENGAMANAN PADDING ATAS UNTUK TARGET PRICE ──
    if show_plan:
        if target_price:
            min_headroom = (y_top - y_bottom) * 0.15  # Wajib ada ruang awan/langit 15% di atas target
            if target_price + min_headroom > y_top:
                y_top = target_price + min_headroom
                
        # Lebarkan y_bottom jika support di bawah area layar
        lowest_sup = sup_2 if sup_2 else sup_1
        if lowest_sup and lowest_sup <= y_bottom + ((y_top - y_bottom) * 0.05):
            # Berikan padding ekstra sebesar 12% dari rentang layar agar teks aman
            y_bottom = lowest_sup - ((y_top - lowest_sup) * 0.12)
        
        cap_limit = last_price * 2.0
        if y_top > cap_limit:
            y_top = cap_limit
            if target_price and target_price > cap_limit:
                target_capped = True

    # 4. Stochastic Setup (Full length, no NaN cut-off)
    full_low_14 = full_df['Low'].rolling(14).min()
    full_high_14 = full_df['High'].rolling(14).max()
    full_stoch_k = 100 * ((full_df['Close'] - full_low_14) / (full_high_14 - full_low_14))
    full_stoch_d = full_stoch_k.rolling(3).mean()
    
    # Pindahkan nilainya ke plot_df (otomatis menyesuaikan full-width untuk /sw, atau 70:30 untuk /tps)
    plot_df['stoch_k'] = full_stoch_k.reindex(plot_df.index)
    plot_df['stoch_d'] = full_stoch_d.reindex(plot_df.index)

    apds = []
    
    if show_plan:
        # Untuk /tps (Stochastic saja, Style Klasik)
        apds.append(mpf.make_addplot(plot_df["stoch_k"], color="#F23645", width=1.5, panel=1, ylabel="Stochastic"))
        apds.append(mpf.make_addplot(plot_df["stoch_d"], color="#FF9800", width=1.2, linestyle="-", panel=1))
        panel_ratios = (6, 1.5)
    else:
        # Untuk /sw (Candlestick, MACD + Stoch Style Modern)
        full_macd, full_macd_signal, full_macd_hist = _macd(full_df["Close"])
        plot_df['macd'] = full_macd.reindex(plot_df.index)
        plot_df['macd_signal'] = full_macd_signal.reindex(plot_df.index)
        plot_df['macd_hist'] = full_macd_hist.reindex(plot_df.index)
        
        macd_hist_colors = ['#26A69A' if val >= 0 else '#EF5350' if pd.notna(val) else '#00000000' for val in plot_df['macd_hist']]
        
        apds.append(mpf.make_addplot(plot_df["stoch_k"], color="#2962FF", width=1.5, panel=1, ylabel="Stoch (14,3)"))
        apds.append(mpf.make_addplot(plot_df["stoch_d"], color="#FF6D00", width=1.2, linestyle="-", panel=1))
        
        apds.append(mpf.make_addplot(plot_df["macd_hist"], type='bar', color=macd_hist_colors, panel=2, ylabel="MACD"))
        apds.append(mpf.make_addplot(plot_df["macd"], color="#2962FF", width=1.5, panel=2))
        apds.append(mpf.make_addplot(plot_df["macd_signal"], color="#FF6D00", width=1.2, linestyle="-", panel=2))
        
        panel_ratios = (5, 1.2, 1.2)

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix=f"dt_{symbol}_")
    tmp_path = tmp.name
    tmp.close()

    fig, axes = mpf.plot(
        plot_df,
        type=chart_type,      # <--- DINAMIS
        style=style,          # <--- DINAMIS
        volume=False,
        addplot=apds,
        figsize=fig_size,     # <--- DINAMIS
        panel_ratios=panel_ratios,
        tight_layout=True,
        ylim=(y_bottom, y_top),
        returnfig=True,
        datetime_format='%b %d %H:%M',
        xrotation=0,
        ylabel="",
        ylabel_lower="",
    )

    # Modifikasi "Super Rapih" (Spines & Ticks)
    for ax in axes:
        if ax is not None:
            for spine in ax.spines.values():
                spine.set_visible(True)
                if show_plan:
                    spine.set_color('#2A2E39')
                    spine.set_linewidth(0.8)
                else:
                    spine.set_color('#2A2E39') # Explicit separator for TV Style
                    spine.set_linewidth(1.2)
            ax.tick_params(axis='both', direction='in', length=4, colors=text_color, grid_alpha=0.0)

    if show_plan:
        fig.subplots_adjust(hspace=0.0)
    else:
        fig.subplots_adjust(top=0.95, bottom=0.05, left=0.05, right=0.90, hspace=0.10)
    ax_price = axes[0]
    stoch_ax = axes[2] if len(axes) > 2 else None
    macd_ax = axes[4] if len(axes) > 4 else None

    # Header & Overlay Styling
    company_name = (extra_data or {}).get("company_name", "IDX Company")
    if symbol == "EMTK":
        company_name = "PT Elang Mahkota Teknologi Tbk"
    elif symbol == "EXCL":
        company_name = "PT XLSMART Telecom Sejahtera Tbk"

    last_row = historical_df.iloc[-1]
    o, h, l, c = int(last_row["Open"]), int(last_row["High"]), int(last_row["Low"]), int(last_row["Close"])
    
    if show_plan:
        ohlc_str = f"    O: {o:,}  H: {h:,}  L: {l:,}  C: {c:,}".replace(",", ".")
        ax_price.set_title(
            f"{symbol} · {company_name} · INTRA · IDX{ohlc_str}",
            loc='left',
            fontsize=11,
            fontweight='bold',
            family='sans-serif',
            color='#D1D4DC',
            pad=15
        )
    else:
        # TradingView Dark Style Embedded Title
        title_str = f"{symbol} - 1d - SCOPEBIT"
        ohlc_str = f"O {o:,}  H {h:,}  L {l:,}  C {c:,}".replace(",", ".")
        ax_price.text(0.015, 0.95, title_str, transform=ax_price.transAxes, color="#D1D4DC", fontsize=14, fontweight="bold", family="sans-serif", va="top", zorder=20)
        ax_price.text(0.015, 0.90, ohlc_str, transform=ax_price.transAxes, color="#A3A6AF", fontsize=11, family="monospace", va="top", zorder=20)
        
        # Red Current Price Line matching TradingView style
        ax_price.axhline(y=last_price, color='#F23645', linestyle=':', linewidth=1.5, alpha=0.9, zorder=5)
        # Current Price Box on Y-axis
        fmt_price = f"{last_price:,.2f}".replace(",", ".") if "." not in str(last_price) else str(last_price)
        ax_price.text(1.0, last_price, f" {fmt_price} ", transform=ax_price.get_yaxis_transform(), 
                      color="#FFFFFF", fontsize=9, fontweight="bold", family="sans-serif",
                      va="center", ha="left", bbox=dict(boxstyle="square,pad=0.2", facecolor="#F23645", edgecolor="none"), zorder=20)

    # Ekstrak data teks DILUAR blok show_plan agar Footer /sw tidak error
    scenario_obj = indicators.get("scenario") if indicators else None
    scenario_name = scenario_obj.get("name", "W Pattern") if scenario_obj else "W Pattern"
    momentum_desc = scenario_obj.get("momentum", "") if scenario_obj else ""

    # ── Watermark Background ──
    # Logo path resolution: extra_data > relative data folder
    logo_path = (extra_data or {}).get("logo_path")
    if not logo_path:
        # Fallback to standard relative path c:\Users\logfu\Documents\ScopeBit Research\ScopeBit Telegram\data\logo.jpeg
        # Based on current engine file at engines/day_trade.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(os.path.dirname(current_dir), "data", "logo.jpeg")

    if logo_path and os.path.exists(logo_path):
        try:
            img = Image.open(logo_path)
            ax_logo = ax_price.inset_axes([0.3, 0.25, 0.4, 0.5], zorder=0)
            ax_logo.axis('off')
            ax_logo.patch.set_alpha(0.0)
            ax_logo.imshow(img, alpha=0.18, zorder=0)
        except Exception as e:
            pass
            
    ax_price.text(0.5, 0.18, "ScopeBit Trading Helper", transform=ax_price.transAxes, 
                  fontsize=42, color='#FFFFFF', alpha=0.04, 
                  ha='center', va='center', rotation=0, 
                  fontstyle='italic', fontweight='light', zorder=0)

    # ── Astronacci Manual Annotations (Garis-garis hanya untuk /tps) ──
    if show_plan and indicators:
        dow_labels = indicators.get("dow_labels", [])
        
        # 1. Historical ZigZag Lines & Dow Labels
        swings = indicators.get("swings", [])
        hist_start_idx = len(df) - len(historical_df)

        # 0. Render Orange Gap Boxes (Unfilled Gaps)
        chart_gaps = indicators.get("gaps", [])
        for g in chart_gaps:
            gap_top = g["top"]
            gap_bottom = g["bottom"]
            gap_size_pct = abs(gap_top - gap_bottom) / gap_bottom * 100 if gap_bottom > 0 else 0
            if gap_size_pct >= 1.5 and gap_bottom <= y_top and gap_top >= y_bottom:
                # HITUNG INDEX RELATIF KE PLOT_DF
                gap_plot_idx = g["idx"] - hist_start_idx
                if gap_plot_idx >= 0 and gap_plot_idx < len(plot_df):
                    x_start_gap = max(0, gap_plot_idx)
                    x_end_gap = len(plot_df) - 1
                    
                    # Clip coordinates to Y-Limits bounds manually to prevent huge expansion
                    render_bottom = max(gap_bottom, y_bottom)
                    render_top = min(gap_top, y_top)
                    
                    ax_price.fill_between([x_start_gap, x_end_gap], render_bottom, render_top, 
                                          facecolor='#FFB74D', alpha=0.15, zorder=0)
                    
                    gap_label = g.get('type', 'GAP_DOWN').upper().replace('_', ' ')
                    if not gap_label.startswith("GAP"): gap_label = "GAP " + gap_label
                    
                    ax_price.text(x_start_gap + 1, (render_bottom + render_top) / 2,
                                 gap_label,
                                 color='#FFB74D', fontsize=9, fontweight='bold',
                                 ha='left', va='center', alpha=0.6, zorder=1, clip_on=True)

        if dow_labels and len(swings) > 0:
            # ON-THE-FLY RELABELING
            hist_swings = [s for s in swings if (s['idx'] - hist_start_idx) >= 0]
            
            # ── SMART PATTERN FILTERING (Prioritas Range S&R) ──
            is_rbs = "Resistance Becomes Support" in scenario_name
            
            # Beri toleransi (agar ekor jarum/bocor sedikit tetap dianggap di dalam range)
            toleransi = atr * 0.5
            batas_bawah = (sup_1 - toleransi) if sup_1 else 0
            batas_atas = (target_price + toleransi) if target_price else float('inf')
            
            if is_rbs:
                # Jika RBS, struktur mendobrak masa lalu, ambil ayunan standar
                valid_swings = hist_swings[-5:] if len(hist_swings) >= 5 else hist_swings
            else:
                # Telusuri dari yang paling baru (kanan) ke masa lalu (kiri)
                temp_swings = []
                for s in reversed(hist_swings):
                    if batas_bawah <= s["price"] <= batas_atas:
                        temp_swings.insert(0, s)
                        if len(temp_swings) == 6: # Cukup maksimal 6 titik pembentuk pola
                            break
                    else:
                        # Jika menemukan titik di luar kotak channel S&R:
                        if len(temp_swings) >= 3:
                            # Jika sudah punya minimal 3 titik valid di dalam channel, 
                            # PUTUS sambungan dari masa lalu. (P/T akan tereset di dalam channel)
                            break
                        else:
                            # Jika titik baru saja tembus (misal: False Breakout/Breakdown),
                            # terpaksa diikutkan agar algoritma tetap punya ujung garis.
                            temp_swings.insert(0, s)
                
                # Batasi hasil akhir agar tidak kepanjangan
                valid_swings = temp_swings[-5:] if len(temp_swings) > 5 else temp_swings
            if not valid_swings:
                valid_swings = hist_swings[-5:]
            
            # ── SAFETY FILTER: Cegah glitch garis ganda/patah ──
            if valid_swings:
                clean_swings = [valid_swings[0]]
                for s in valid_swings[1:]:
                    last_s = clean_swings[-1]
                    # Pastikan pola selalu selang-seling (Peak -> Trough -> Peak)
                    if s['type'] != last_s['type']:
                        clean_swings.append(s)
                    else:
                        # Jika ada 2 peak berurutan, ambil ujung yang paling tinggi
                        if s['type'] == 'peak' and s['price'] > last_s['price']:
                            clean_swings[-1] = s
                        # Jika ada 2 trough berurutan, ambil ujung yang paling rendah
                        elif s['type'] == 'trough' and s['price'] < last_s['price']:
                            clean_swings[-1] = s
                visible_swings = clean_swings
            else:
                visible_swings = []
            # ──────────────────────────────────────────────────
            
            last_peak = None
            last_trough = None
            
            relabeled_swings = []
            for s in visible_swings:
                new_label = ""
                if s["type"] == "peak":
                    if last_peak is None:
                        new_label = "P"
                    else:
                        new_label = "HP" if s["price"] >= last_peak else "LP"
                    last_peak = s["price"]
                else:
                    if last_trough is None:
                        new_label = "T"
                    else:
                        new_label = "HT" if s["price"] >= last_trough else "LT"
                    last_trough = s["price"]
                
                relabeled_s = dict(s)
                relabeled_s["label"] = new_label
                relabeled_swings.append(relabeled_s)
                
            # Siapkan penangkap koordinat untuk pelurusan garis
            actual_last_x = len(historical_df) - 1
            actual_last_y = last_price

            if len(relabeled_swings) > 1:
                for i in range(1, len(relabeled_swings)):
                    s1 = relabeled_swings[i-1]
                    s2 = relabeled_swings[i]
                    idx1 = s1['idx'] - hist_start_idx
                    idx2 = s2['idx'] - hist_start_idx
                    
                    l_color = "#2CA02C" if s2['price'] >= s1['price'] else "#D62728"
                    ax_price.plot([idx1, idx2], [s1['price'], s2['price']], color=l_color, linewidth=2.0, zorder=3, linestyle='-')

                # ── PENJEJAKAN AYUNAN TERAKHIR (Live Tail Tracking) ──
                last_s = relabeled_swings[-1]
                idx_last = last_s['idx'] - hist_start_idx
                x_curr_live = len(historical_df) - 1
                
                # Cek sisa ruang dari titik swing terakhir hingga candle hari ini
                if idx_last < x_curr_live:
                    search_df = historical_df.iloc[idx_last+1:x_curr_live+1]
                    y_offset = (y_top - y_bottom) * 0.02
                    
                    if last_s["type"] == "peak":
                        # Cari lembah menggunakan argmin Numpy agar index absolut tidak meleset
                        min_val = search_df['Low'].min()
                        min_pos = (idx_last + 1) + search_df['Low'].values.argmin()
                        
                        # Syarat 1: Lembah tidak terjadi tepat di candle hari ini, DAN harga sudah mantul naik
                        bounce_up = last_price > min_val
                        is_valid_trough = (min_pos <= x_curr_live) and bounce_up
                        
                        # Syarat 2: Penurunannya lumayan dalam (Minimal 0.2x ATR)
                        is_deep_trough = (last_s["price"] - min_val) >= (atr * 0.2)
                        
                        if (is_valid_trough or is_deep_trough) and min_val < last_s["price"]:
                            last_trough = next((s["price"] for s in reversed(relabeled_swings) if s["type"] == "trough"), None)
                            trough_label = "HT" if (last_trough is not None and min_val >= last_trough) else "LT"
                            ax_price.plot([idx_last, min_pos], [last_s['price'], min_val], color="#D62728", linewidth=2.0, zorder=3, linestyle='-')
                            ax_price.text(min_pos, min_val - y_offset, trough_label, color='#D1D4DC', fontweight='bold', ha='center', va='top', fontsize=14, family="sans-serif", zorder=6, bbox=dict(facecolor='#1E222D', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.2'))
                            
                            idx_last = min_pos
                            last_s = {'price': min_val, 'type': 'trough'}
                            
                    elif last_s["type"] == "trough":
                        max_val = search_df['High'].max()
                        max_pos = (idx_last + 1) + search_df['High'].values.argmax()
                        
                        bounce_down = last_price < max_val
                        is_valid_peak = (max_pos <= x_curr_live) and bounce_down
                        is_deep_peak = (max_val - last_s["price"]) >= (atr * 0.2)
                        
                        if (is_valid_peak or is_deep_peak) and max_val > last_s["price"]:
                            last_peak = next((s["price"] for s in reversed(relabeled_swings) if s["type"] == "peak"), None)
                            peak_label = "HP" if (last_peak is not None and max_val >= last_peak) else "LP"
                            ax_price.plot([idx_last, max_pos], [last_s['price'], max_val], color="#2CA02C", linewidth=2.0, zorder=3, linestyle='-')
                            ax_price.text(max_pos, max_val + y_offset, peak_label, color='#D1D4DC', fontweight='bold', ha='center', va='bottom', fontsize=14, family="sans-serif", zorder=6, bbox=dict(facecolor='#1E222D', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.2'))
                            
                            idx_last = max_pos
                            last_s = {'price': max_val, 'type': 'peak'}

                # Sambungkan ujung terakhir ke harga hari ini secara mulus
                if idx_last < x_curr_live:
                    l_color_live = "#2CA02C" if last_price >= last_s['price'] else "#D62728"
                    ax_price.plot([idx_last, x_curr_live], [last_s['price'], last_price], color=l_color_live, linewidth=2.0, zorder=3, linestyle='-')
                
                # SIMPAN TITIK ASAL UNTUK MENGHITUNG KEMIRINGAN
                actual_last_x = idx_last
                actual_last_y = last_s['price']

            # DRAW NEW LABELS
            for s in relabeled_swings:
                idx = s['idx'] - hist_start_idx
                label = s.get("label", "")
                price = s["price"]
                if y_bottom <= price <= y_top:
                    y_offset = (y_top - y_bottom) * 0.02
                    if s["type"] == "peak":
                        ax_price.text(idx, price + y_offset, label, color='#D1D4DC', fontweight='bold', ha='center', va='bottom', fontsize=14, family="sans-serif", zorder=6, bbox=dict(facecolor='#1E222D', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.2'))
                    else:
                        ax_price.text(idx, price - y_offset, label, color='#D1D4DC', fontweight='bold', ha='center', va='top', fontsize=14, family="sans-serif", zorder=6, bbox=dict(facecolor='#1E222D', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.2'))
        # 2. Support & Target Lines (Manual)
        y_offset_text = (y_top - y_bottom) * 0.008 

        if target_price:
            draw_y = y_top if target_capped else target_price
            ax_price.axhline(y=draw_y, color='#E53935', linewidth=2.0, linestyle='-', zorder=4)
            ax_price.axhline(y=draw_y, color='#E53935', linewidth=8.0, alpha=0.15, linestyle='-', zorder=3)
            target_str = " TARGET "
            if target_capped:
                target_str += "(Off-Chart) "
            
            ax_price.text(0.99, draw_y, target_str, 
                         transform=ax_price.get_yaxis_transform(), 
                         color='white', fontsize=10, fontweight='bold', ha='right', va='center',
                         bbox=dict(boxstyle="round,pad=0.3", facecolor='#E53935', edgecolor='none', alpha=0.9), zorder=5)
            
            ax_price.text(1.0, draw_y, f" {int(target_price)} ", 
                         transform=ax_price.get_yaxis_transform(), 
                         color='white', fontsize=10, fontweight='bold', ha='left', va='center',
                         bbox=dict(boxstyle="round,pad=0.3", facecolor='#E53935', edgecolor='none'))

        if sup_1:
            ax_price.axhline(y=sup_1, color='#00C853', linewidth=2.0, linestyle='-', zorder=4)
            ax_price.axhline(y=sup_1, color='#00C853', linewidth=8.0, alpha=0.15, linestyle='-', zorder=3)
            
            ax_price.text(0.99, sup_1, " SUPPORT ", 
                         transform=ax_price.get_yaxis_transform(), 
                         color='#131722', fontsize=10, fontweight='bold', ha='right', va='center',
                         bbox=dict(boxstyle="round,pad=0.3", facecolor='#00C853', edgecolor='none', alpha=0.9), zorder=5)
            
            ax_price.text(1.0, sup_1, f" {int(sup_1)} ", 
                         transform=ax_price.get_yaxis_transform(), 
                         color='#131722', fontsize=10, fontweight='bold', ha='left', va='center',
                         bbox=dict(boxstyle="round,pad=0.3", facecolor='#00C853', edgecolor='none'))

        # SUPPORT 2 VISUALIZATION
        if sup_2:
            ax_price.axhline(y=sup_2, color='#00E676', linewidth=1.5, linestyle='--', zorder=4, alpha=0.8)
            ax_price.axhline(y=sup_2, color='#00E676', linewidth=6.0, alpha=0.1, linestyle='--', zorder=3)
            
            ax_price.text(0.99, sup_2, " SUPPORT 2 ", 
                         transform=ax_price.get_yaxis_transform(), 
                         color='#131722', fontsize=9, fontweight='bold', ha='right', va='center',
                         bbox=dict(boxstyle="round,pad=0.3", facecolor='#00E676', edgecolor='none', alpha=0.8), zorder=4)
                         
            ax_price.text(1.0, sup_2, f" {int(sup_2)} ", 
                         transform=ax_price.get_yaxis_transform(), 
                         color='#131722', fontsize=9, fontweight='bold', ha='left', va='center',
                         bbox=dict(boxstyle="round,pad=0.3", facecolor='#00E676', edgecolor='none', alpha=0.9))

        # 3. Future Projection (N-Shape Lightning) - Start from last valid swing node
        x_curr = len(historical_df) - 1
        y_curr = last_price
        avail_future = len(plot_df) - 1 - x_curr 
        
        # Ekstrak kemiringan (slope) absolut dari garis historis terakhir
        x_start = actual_last_x if 'actual_last_x' in locals() else x_curr
        y_start = actual_last_y if 'actual_last_y' in locals() else y_curr
        past_slope = None
        if x_curr > x_start:
            past_slope = (last_price - y_start) / (x_curr - x_start)

        if target_price and sup_1:
            is_false_break = "False Break" in scenario_name 
            
            if target_price <= last_price * 1.02 or is_false_break:
                # Override: Tarik garis lurus V-Shape Recovery
                x_2_fb = x_curr + int(avail_future * 0.9)
                
                # Memaksa lurus dengan masa lalu (jika arahnya sama-sama naik)
                if past_slope is not None and past_slope > 0 and target_price > last_price:
                    x_2_fb = x_curr + int(round((target_price - last_price) / past_slope))
                    if x_2_fb > x_curr + int(avail_future * 0.9): 
                        x_2_fb = x_curr + int(avail_future * 0.9)
                        
                ax_price.plot([x_curr, x_2_fb], [y_curr, target_price], color='#00BFFF', linewidth=7.0, alpha=0.15, zorder=3)
                ax_price.plot([x_curr, x_2_fb], [y_curr, target_price], color='#00BFFF', linewidth=2.0, zorder=4)
            else:
                # ═══════════════════════════════════════════════════════════════════
                # ── SMART PROJECTION ENGINE v4 (Proportional Symmetrical Pathing) ─
                # ═══════════════════════════════════════════════════════════════════
                
                # ── Step 1: Identify Minor Resistance (key_level) ──
                last_peak_y = None
                last_peak_x = None
                if dow_labels:
                    for s in reversed(dow_labels):
                        if s["type"] == "peak":
                            last_peak_y = s["price"]
                            last_peak_x = s["idx"] - hist_start_idx
                            break

                key_level = minor_res_price if minor_res_price else last_peak_y
                
                if key_level is None or key_level >= target_price or key_level <= last_price:
                    key_level = last_price + ((target_price - last_price) * 0.6)
                    last_peak_x = None

                # ── Step 2: Volume-Weighted Support Strength Detection ──
                strong_sup = sup_1
                sup_label = "S1"
                if sup_2 and sup_1:
                    zone_radius = atr * 0.7
                    vol_s1 = 0.0
                    vol_s2 = 0.0
                    touch_s1 = 0
                    touch_s2 = 0
                    for _, row in historical_df.iterrows():
                        r_low = row.get('Low', 0)
                        r_high = row.get('High', 0)
                        r_vol = row.get('Volume', 0) or 0
                        if r_low - zone_radius <= sup_1 <= r_high + zone_radius:
                            vol_s1 += r_vol
                            touch_s1 += 1
                        if r_low - zone_radius <= sup_2 <= r_high + zone_radius:
                            vol_s2 += r_vol
                            touch_s2 += 1
                    
                    if vol_s2 > vol_s1 * 1.3 and touch_s2 >= touch_s1:
                        strong_sup = sup_2
                        sup_label = "S2"
                    elif touch_s1 <= 1 and touch_s2 >= 3:
                        strong_sup = sup_2
                        sup_label = "S2"

                # ── Step 3: Momentum Detection ──
                momentum_down = False
                if past_slope is not None and past_slope < 0:
                    momentum_down = True
                elif len(historical_df) >= 5:
                    c5 = historical_df['Close'].iloc[-5:].values
                    if c5[-1] < c5[0]:
                        momentum_down = True

                # ── Step 4: Build Y-points list based on scenario ──
                # y_pts = [y_curr, y_2, y_3, ..., y_target]
                y_pts = None  # Will be set by scenario router

                # === PATH 1: BREAKOUT ===
                if "Breaking" in scenario_name:
                    y_pts = [y_curr, target_price]
                    # Seamless slope
                    if past_slope is not None and past_slope > 0 and target_price > last_price:
                        calc_x = x_curr + int(round((target_price - last_price) / past_slope))
                        end_x = min(calc_x, x_curr + int(avail_future * 0.9))
                    else:
                        end_x = x_curr + int(avail_future * 0.85)
                    ax_price.plot([x_curr, end_x], [y_curr, target_price], color='#00BFFF', linewidth=7.0, alpha=0.15, zorder=3)
                    ax_price.plot([x_curr, end_x], [y_curr, target_price], color='#00BFFF', linewidth=2.0, zorder=4)
                    y_pts = None  # Already rendered

                # === PATH 2: REVERSAL / W-PATTERN ===
                elif "W Pattern" in scenario_name or "Reversal" in scenario_name:
                    bounce_sup = strong_sup if strong_sup and strong_sup < last_price else (sup_1 if sup_1 and sup_1 < last_price else last_price - atr)
                    y_pts = [y_curr, bounce_sup, key_level, target_price]

                # === PATH 3: REBOUND FROM SUPPORT ===
                elif "Rebound" in scenario_name:
                    pullback = strong_sup if strong_sup and strong_sup < key_level else (last_price + (key_level - last_price) * 0.3)
                    y_pts = [y_curr, key_level, pullback, target_price]

                # === PATH 4: RBS / PULLBACK ===
                elif "Resistance Becomes Support" in scenario_name:
                    rbs_level = strong_sup if strong_sup and strong_sup > last_price * 0.95 else (last_price - atr * 0.5)
                    y_pts = [y_curr, last_price + atr * 0.5, rbs_level, target_price]

                # === PATH 5: DISTRIBUTION / MARKDOWN ===
                elif momentum_down and strong_sup and strong_sup < last_price:
                    drop_pct = (last_price - strong_sup) / last_price if last_price > 0 else 0
                    if drop_pct > 0.08:
                        deep_sup = sup_2 if sup_2 and sup_2 < strong_sup else strong_sup
                        y_pts = [y_curr, deep_sup, key_level * 0.95, target_price]
                    else:
                        y_pts = [y_curr, strong_sup, key_level, target_price]

                # === PATH 6: POTENTIAL BREAKOUT ===
                elif "Potential" in scenario_name:
                    rejection = last_price + (key_level - last_price) * 0.3
                    y_pts = [y_curr, key_level, rejection, target_price]

                # === DEFAULT PATH ===
                else:
                    if last_price >= key_level:
                        swing_up = min(target_price - last_price, atr * 3)
                        pull_y = strong_sup if strong_sup and strong_sup < (last_price + swing_up) else max(last_price, (last_price + swing_up) - (atr * 1.5))
                        if pull_y < key_level and key_level >= last_price: pull_y = key_level
                        y_pts = [y_curr, last_price + swing_up, pull_y, target_price]
                    else:
                        pull_y = strong_sup if strong_sup and strong_sup < key_level else (key_level - min(key_level - last_price, atr * 1.5))
                        if sup_1 and pull_y < sup_1 and sup_label == "S1": pull_y = sup_1 + ((key_level - sup_1) * 0.2)
                        y_pts = [y_curr, key_level, pull_y, target_price]

                # ── Step 5: Proportional Euclidean X-Distribution & Render ──
                if y_pts is not None and len(y_pts) >= 3:
                    # Calculate absolute Y-distance per segment
                    seg_dists = [abs(y_pts[i+1] - y_pts[i]) for i in range(len(y_pts) - 1)]
                    total_dist = sum(seg_dists)
                    
                    # Reserve 10% buffer at end
                    usable_future = int(avail_future * 0.9)
                    
                    if total_dist > 0:
                        # Distribute X proportionally based on Y-distance
                        x_pts = [x_curr]
                        cumulative_x = 0
                        for i, d in enumerate(seg_dists):
                            proportion = d / total_dist
                            # Minimum 15% per segment to avoid ultra-thin segments
                            proportion = max(proportion, 0.15)
                            seg_x = int(usable_future * proportion)
                            # Ensure minimum 2 candles width
                            seg_x = max(seg_x, 2)
                            cumulative_x += seg_x
                            x_pts.append(x_curr + cumulative_x)
                        
                        # Normalize: scale all x_pts so last point = x_curr + usable_future
                        if cumulative_x > 0:
                            scale = usable_future / cumulative_x
                            x_pts = [x_curr] + [x_curr + max(1, int((xp - x_curr) * scale)) for xp in x_pts[1:]]
                        
                        # Enforce strictly increasing X
                        for i in range(1, len(x_pts)):
                            if x_pts[i] <= x_pts[i-1]:
                                x_pts[i] = x_pts[i-1] + 1
                    else:
                        # Fallback: equal spacing
                        n_seg = len(y_pts) - 1
                        x_pts = [x_curr + int(usable_future * i / n_seg) for i in range(n_seg + 1)]
                        x_pts[0] = x_curr
                    
                    # Render neon glow + solid line
                    ax_price.plot(x_pts, y_pts, color='#00BFFF', linewidth=7.0, alpha=0.15, zorder=3)
                    ax_price.plot(x_pts, y_pts, color='#00BFFF', linewidth=2.0, zorder=4)
                             
                # ── Step 6: RENDER GARIS HORIZONTAL MINOR RESISTANCE ──
                start_x_res = last_peak_x if (last_peak_x is not None and last_peak_y is not None and key_level == last_peak_y) else x_curr 
                end_x_res = x_curr + int(avail_future * 0.9) 
                
                ax_price.plot([start_x_res, end_x_res], [key_level, key_level], color='#2962FF', linewidth=1.5, linestyle='-', zorder=4)
                ax_price.plot([start_x_res, end_x_res], [key_level, key_level], color='#2962FF', linewidth=6.0, alpha=0.15, linestyle='-', zorder=3)
                
                ax_price.text(0.99, key_level, " MINOR RESISTANCE ", 
                             transform=ax_price.get_yaxis_transform(), 
                             color='white', fontsize=10, fontweight='bold', ha='right', va='center',
                             bbox=dict(boxstyle="round,pad=0.3", facecolor='#2962FF', edgecolor='none', alpha=0.8), zorder=5)
                
                ax_price.text(1.0, key_level, f" {int(key_level)} ", 
                             transform=ax_price.get_yaxis_transform(), 
                             color='white', fontsize=9, fontweight='bold', ha='left', va='center',
                             bbox=dict(boxstyle="round,pad=0.3", facecolor='#2962FF', edgecolor='none', alpha=0.9))

            # 4. Vertical Separator (Today's Line)
            ax_price.axvline(x=x_curr, color='#FF9800', linewidth=1.5, linestyle="--", zorder=1)
            
            x_end_future = len(plot_df) - 1
            
            # Terapkan batas dan warna background future ke semua panel
            ax_price.axvspan(x_curr, x_end_future, facecolor='#1E222D', alpha=0.4, zorder=0)
            
            if stoch_ax is not None:
                stoch_ax.axvline(x=x_curr, color='#FF9800', linewidth=1.5, linestyle="--", zorder=1)
                stoch_ax.axvspan(x_curr, x_end_future, facecolor='#1E222D', alpha=0.4, zorder=0)
                
            if macd_ax is not None:
                macd_ax.axvline(x=x_curr, color='#FF9800', linewidth=1.5, linestyle="--", zorder=1)
                macd_ax.axvspan(x_curr, x_end_future, facecolor='#1E222D', alpha=0.4, zorder=0)
                
        # 8j. Current Price Y-Axis Box (Black)
        # X diubah jadi 1.0 agar menempel persis dengan batas grafik seperti kotak lainnya
        ax_price.text(1.0, last_price, f" {int(last_price):,} ".replace(",", "."),
                 transform=ax_price.get_yaxis_transform(),
                 color='#FFFFFF', fontsize=10, fontweight='bold', ha='left', va='center',
                 bbox=dict(boxstyle="round,pad=0.3", facecolor='#434651', edgecolor='none'), zorder=10)


    # Footer Branding has been moved to the Telegram caption text (generate_plan)

    # ── Clean Pivot Annotations for Modern /dt Terminal ──
    if not show_plan and indicators:
        swings = indicators.get("swings", [])
        hist_start_idx = len(df) - len(historical_df)
        
        for s in swings:
            idx = s['idx'] - hist_start_idx
            if 0 <= idx < len(plot_df):
                price = s['price']
                if s['type'] == 'peak':
                    ax_price.annotate(f"{price:.2f}\n↓", xy=(idx, price), xycoords='data',
                                      xytext=(0, 6), textcoords="offset points",
                                      fontsize=10, color='#FFFFFF', ha='center', va='bottom',
                                      family='sans-serif', weight='bold', alpha=0.9, zorder=10)
                else:
                    ax_price.annotate(f"↑\n{price:.2f}", xy=(idx, price), xycoords='data',
                                      xytext=(0, -6), textcoords="offset points",
                                      fontsize=10, color='#FFFFFF', ha='center', va='top',
                                      family='sans-serif', weight='bold', alpha=0.9, zorder=10)

    # ── MTF Signal Badges on Stochastic Panel (Kanan Bawah) ──
    if indicators:
        # Find target Stochastic panel
        target_ax = None
        for ax_idx in [2, 1]:
            if ax_idx < len(axes) and axes[ax_idx] is not None:
                target_ax = axes[ax_idx]
                break

        if target_ax is not None:
            micro_signals = indicators.get("micro_signals", [])
            allowed = [s for s in micro_signals if s.get("verdict") == "ALLOW"]
            denied = [s for s in micro_signals if s.get("verdict") == "DENY"]

            # Row 1: ALLOW badges (hijau, kanan bawah atas) — max 3
            if allowed:
                allow_text = "  ".join([f"{s.get('verdict_icon', '⚡')} {s.get('label', '')}" for s in allowed[:3]])
                target_ax.text(
                    0.98, 0.18, allow_text,
                    transform=target_ax.transAxes,
                    color='#26A69A', fontsize=9, fontweight='bold',
                    ha='right', va='bottom', family='sans-serif',
                    bbox=dict(
                        boxstyle='round,pad=0.4',
                        facecolor='#131722', edgecolor='#26A69A',
                        alpha=0.95, linewidth=1.2
                    ),
                    zorder=20
                )

            # Row 2: DENY badge (merah, kanan paling bawah) — max 1
            if denied:
                deny_sig = denied[0]
                deny_text = f"⚠️ DENY: {deny_sig.get('label', '')} ({deny_sig.get('verdict_reason', '')})"
                target_ax.text(
                    0.98, 0.03, deny_text,
                    transform=target_ax.transAxes,
                    color='#EF5350', fontsize=7.5, fontweight='normal',
                    ha='right', va='bottom', family='sans-serif',
                    bbox=dict(
                        boxstyle='round,pad=0.3',
                        facecolor='#131722', edgecolor='#EF5350',
                        alpha=0.85, linewidth=0.8
                    ),
                    zorder=20
                )

            # Fallback: show VSA/Early setup if no micro signals
            if not micro_signals:
                badge_items = []
                early = indicators.get("early_setup")
                if early and isinstance(early, dict):
                    label = early.get("label", "")
                    if label:
                        if "⚡" not in label and "🚀" not in label and "⚠️" not in label:
                            label = f"⚡ {label}"
                        badge_items.append(label)
                
                vsa = indicators.get("vsa_signals", [])
                for v in vsa[:1]:
                    vtype = v.get("type", "")
                    if "SELLER_EXHAUSTION" in vtype:
                        badge_items.append("⚡ Seller Exhausted")
                    elif "STOPPING" in vtype:
                        badge_items.append("⚡ Stopping Vol")
                    elif "CLIMAX" in vtype:
                        badge_items.append("⚠️ Climax Vol")
                
                if badge_items:
                    badge_text = "  ".join(badge_items[:3])
                    target_ax.text(
                        0.98, 0.08, badge_text,
                        transform=target_ax.transAxes,
                        color='#D1D4DC', fontsize=9, fontweight='bold',
                        ha='right', va='bottom', family='sans-serif',
                        bbox=dict(
                            boxstyle='round,pad=0.4',
                            facecolor='#1E222D', edgecolor='#2A2E39',
                            alpha=0.95
                        ),
                        zorder=20
                    )

    fig.savefig(tmp_path, dpi=120, bbox_inches="tight", facecolor=bg_color)
    plt.close(fig)

    return tmp_path


# ──────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────

def analyze_day_trade(symbol: str, ohlcv_data: list, show_plan: bool = True, extra_data: dict = None) -> tuple[str | None, str | None]:
    """
    Main function: takes raw OHLCV list (intraday or daily), returns (chart_path, caption).
    Returns (None, error_message) on failure.
    """
    if not ohlcv_data or len(ohlcv_data) < 10:
        return None, f"Data intraday untuk <b>{symbol}</b> tidak cukup (min 10 candle)."

    records = []
    for d in ohlcv_data:
        raw_date = d.get("date", "")
        dt = None
        
        # Try parsing various date formats
        try:
            # Format 1: "YYYY-MM-DD HH:MM:SS" (ScopeBit Intraday)
            dt = datetime.strptime(str(raw_date), "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                # Format 2: "YYYY-MM-DD" (daily)
                dt = datetime.strptime(str(raw_date), "%Y-%m-%d")
            except (ValueError, TypeError):
                try:
                    # Format 3: "YYYY-MM-DDTHH:MM:SS..." (ISO with time)
                    dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    try:
                        # Format 4: Unix timestamp (int or string of digits)
                        ts = int(raw_date) if isinstance(raw_date, str) and raw_date.isdigit() else raw_date
                        if isinstance(ts, (int, float)) and ts > 1_000_000_000:
                            dt = datetime.fromtimestamp(ts)
                    except (ValueError, TypeError, OSError):
                        pass
        
        if dt is None:
            continue
            
        o = float(d.get("open", 0))
        h = float(d.get("high", 0))
        l = float(d.get("low", 0))
        c = float(d.get("close", 0))
        v = float(d.get("volume", 0))
        
        # Skip zero/invalid candles
        if h <= 0 or l <= 0 or c <= 0:
            continue
            
        records.append({
            "Date": dt,
            "Open": o,
            "High": h,
            "Low": l,
            "Close": c,
            "Volume": v,
        })

    if len(records) < 10:
        return None, f"Data intraday untuk <b>{symbol}</b> tidak cukup setelah parsing ({len(records)} candle)."

    df = pd.DataFrame(records)
    df.set_index("Date", inplace=True)
    df.index = pd.DatetimeIndex(df.index)
    df.sort_index(inplace=True)

    # ═══════════════════════════════════════════════════════════════
    # DUAL-ENGINE MTF SPLIT STREAM
    # ═══════════════════════════════════════════════════════════════
    
    # Aliran A: Raw 5M (Micro-Structure Engine — Sang Pasukan)
    df_5m = df.copy()
    
    # Aliran B: Resampled 1H (Macro-Structure Engine — Sang Jenderal)
    if not df.empty:
        df = df.resample('1h').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna(subset=['Close'])
    df_1h = df

    # ── Engine 1: Sang Jenderal (1H Macro — Konteks & Bias) ──
    # Daily MA5/MA20 sudah dihitung di dalam calc_indicators()
    indicators = calc_indicators(df_1h)
    # ── Engine 2: Sang Pasukan (5M Micro — Scalp Anomaly) ──
    micro_signals_raw = calc_micro_signals(df_5m, snr_1h=indicators.get("snr", {}))

    # ── Gatekeeper: Validasi Silang (5M ↔ 1H) ──
    micro_validated = cross_validate(
        micro_signals=micro_signals_raw,
        regime_1h=indicators.get("regime", {}),
        snr_1h=indicators.get("snr", {}),
        price=indicators.get("price", 0),
    )
    indicators["micro_signals"] = micro_validated
    
    # Slice chart untuk visual (sekitar 14 hari kerja -> ~85 bar 1H)
    recent_bars = 85
    offset = max(0, len(df_1h) - recent_bars)
    df_chart = df_1h.iloc[-recent_bars:].copy() if len(df_1h) > recent_bars else df_1h.copy()
    
    if offset > 0:
        if "swings" in indicators:
            indicators["swings"] = [{**s, "idx": s["idx"] - offset} for s in indicators["swings"]]
        if "dow_labels" in indicators:
            indicators["dow_labels"] = [{**s, "idx": s["idx"] - offset} for s in indicators["dow_labels"]]
        if "gaps" in indicators:
            indicators["gaps"] = [{**g, "idx": g["idx"] - offset} for g in indicators["gaps"]]
    # ═══════════════════════════════════════════════════════════════

    caption = generate_plan(symbol, df_chart, indicators)
    chart_path = render_chart(symbol, df_chart, indicators, show_plan=show_plan, extra_data=extra_data)

    return chart_path, caption