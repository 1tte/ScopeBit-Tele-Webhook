import os
import tempfile
from datetime import datetime
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
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
    sanitize_ohlcv, detect_vsa_signals, round_to_idx_tick, _get_idx_tick
)
from engines.trading_patterns import (
    aggregate_smc_signals, detect_early_smart_money, detect_institutional_setups
)
from engines.fundamental import parse_keystats, _safe_num, grade_pe, grade_pbv, grade_der, grade_npm, grade_roa
from engines.chart_drawing import (
    draw_advanced_ta, LabelRegistry, get_astronacci_style, get_modern_style, calculate_y_limits
)



# ──────────────────────────────────────────────
# Technical Indicators
# ──────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def detect_pivot_extrema(df: pd.DataFrame, left_bars=5, right_bars=5):
    """Mendeteksi pucuk ekstrem absolut (Pivot High/Low) dalam rentang N candle."""
    window = left_bars + right_bars + 1
    
    # Deteksi pucuk atas (Pivot High) -> Harus menjadi MAX dari window
    df['rolling_max'] = df['High'].rolling(window=window, center=True).max()
    df['is_peak'] = df['High'] == df['rolling_max']
    
    # Deteksi pucuk bawah (Pivot Low) -> Harus menjadi MIN dari window
    df['rolling_min'] = df['Low'].rolling(window=window, center=True).min()
    df['is_trough'] = df['Low'] == df['rolling_min']
    
    swings = []
    for i in range(len(df)):
        if df['is_peak'].iloc[i]:
            swings.append({'idx': i, 'price': df['High'].iloc[i], 'type': 'peak'})
        elif df['is_trough'].iloc[i]:
            swings.append({'idx': i, 'price': df['Low'].iloc[i], 'type': 'trough'})
            
    # Bersihkan kolom bantuan
    df.drop(columns=['rolling_max', 'is_peak', 'rolling_min', 'is_trough'], inplace=True)
    
    # Filter agar polanya selalu bergantian (Peak -> Trough -> Peak)
    if not swings: return []
    filtered = [swings[0]]
    for s in swings[1:]:
        last_s = filtered[-1]
        if s['type'] != last_s['type']:
            filtered.append(s)
        else:
            # Jika ada 2 peak berurutan, ambil yang paling tinggi (pucuk absolut)
            if s['type'] == 'peak' and s['price'] > last_s['price']:
                filtered[-1] = s
            # Jika ada 2 trough berurutan, ambil yang paling rendah
            elif s['type'] == 'trough' and s['price'] < last_s['price']:
                filtered[-1] = s
    return filtered

def calc_indicators(df: pd.DataFrame) -> dict:
    """Calculate EMA21, EMA50, EMA200, RSI14, MACD, ATR, Hurst, S&R."""
    
    df["ema21"] = _ema(df["Close"], 21)
    df["ema50"] = _ema(df["Close"], 50)
    df["ema200"] = _ema(df["Close"], 200)
    df["rsi"] = calc_rsi(df["Close"], 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = _macd(df["Close"])
    df["bull_vol"], df["bear_vol"] = calc_bull_bear_vol(df)
    atr_series, atr_info = calc_atr(df, 14)
    df["atr"] = atr_series

    latest = df.iloc[-1]
    price = latest["Close"]
    atr_val = atr_info["atr"]

    # Hurst Exponent for regime detection (now returns confidence)
    hurst, hurst_confidence = calc_hurst(df["Close"], max_lag=20)

    # Stochastic K & D (14, 3)
    low_14 = df['Low'].rolling(14).min()
    high_14 = df['High'].rolling(14).max()
    k_series = 100 * ((df['Close'] - low_14) / (high_14 - low_14))
    d_series = k_series.rolling(3).mean()
    stoch_k = k_series.iloc[-1] if not k_series.empty and not pd.isna(k_series.iloc[-1]) else None
    stoch_d = d_series.iloc[-1] if not d_series.empty and not pd.isna(d_series.iloc[-1]) else None

    # S&R Detection
    snr = detect_support_resistance(df, atr_val, price)
    
    # State Machine Scenarios (Mechanism 3)
    gaps = [] # Currently gaps are calculated in chart_drawing or technical, but technical doesn't return them directly. Let's rely on empty gaps for now until we move detect_gaps back. Let's just import detect_gaps... Wait, detect_gaps is in technical.py!
    # ── DYNAMIC THRESHOLD & PATTERN SCANNER ──
    from engines.technical import detect_gaps
    unfilled_gaps = detect_gaps(df, min_gap_pct=0.5)

    best_swings = []
    best_labels = []
    best_scenario = None
    
    # Algoritma memindai dari threshold paling kaku (2.5) ke paling sensitif (1.0)
    # Ia akan berhenti begitu menemukan pola valid (seperti W_PATTERN atau RBS)
    for mult in [2.5, 2.0, 1.5, 1.0, 0.7, 0.5]:
        test_swings = calc_zigzag_swings(df, atr_series, threshold_mult=mult)
        test_labels = label_dow_theory(test_swings)
        test_scenario = classify_price_action_scenario(
            labeled_swings=test_labels,
            supports=snr["supports"],
            resistances=snr["resistances"],
            gaps=unfilled_gaps,
            stoch_k=stoch_k,
            stoch_d=stoch_d,
            current_price=price,
            atr=atr_val,
        )
        if test_scenario is not None:
            best_swings = test_swings
            best_labels = test_labels
            best_scenario = test_scenario
            break # Pola ditemukan, hentikan scanning!
            
    # Ganti fallback ZigZag dengan Pivot Pucuk Absolut 10 Candle (5 kiri, 5 kanan)
    if best_scenario is None:
        best_swings = detect_pivot_extrema(df, left_bars=5, right_bars=5)
        best_labels = label_dow_theory(best_swings)
        best_scenario = None

    swings = best_swings
    dow_labels = best_labels
    scenario = best_scenario
    # ──────────────────────────────────────────

    # Only re-classify if the loop didn't find a valid scenario
    if scenario is None:
        scenario = classify_price_action_scenario(
            labeled_swings=dow_labels,
            supports=snr["supports"],
            resistances=snr["resistances"],
            gaps=unfilled_gaps,
            stoch_k=stoch_k,
            stoch_d=stoch_d,
            current_price=price,
            atr=atr_val,
        )

    # Regime classification (Swing uses daily EMAs)
    regime = classify_regime(
        hurst=hurst,
        rsi=latest.get("rsi"),
        ema20=latest.get("ema21"),   # Swing: EMA21 as short-term MA
        ema50=latest.get("ema50"),   # Swing: EMA50 as medium-term MA
        price=price,
        ma200=latest.get("ema200"),  # Swing: EMA200 as long-term MA
        macd=latest.get("macd"),
        macd_signal=latest.get("macd_signal"),
    )

    # 1. BUNGKUS KE DALAM DICTIONARY DULU
    res_dict = {
        "price": price,
        "ema21": latest.get("ema21"),
        "ema50": latest.get("ema50"),
        "ema200": latest.get("ema200"),
        "rsi": latest.get("rsi"),
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
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
    }

    # 2. EKSEKUSI EARLY SETUP SEBELUM RETURN
    # Gunakan is_intraday=False untuk swing.py (daily data)
    early_setup = detect_early_smart_money(df, snr, hurst, is_intraday=False) 
    res_dict["early_setup"] = early_setup

    # 3. SMC / INSTITUTIONAL ENGINE SUITE (7 Engines)
    res_dict["smc_signals"] = aggregate_smc_signals(df, snr)
    
    return res_dict # 4. RETURN DICTIONARY FINAL


# ──────────────────────────────────────────────
# Trading Plan Generator
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
    """Build a Telegram-formatted swing trading plan caption."""
    price = indicators.get("price")
    ema21 = indicators.get("ema21")
    ema50 = indicators.get("ema50")
    ema200 = indicators.get("ema200")
    rsi = indicators.get("rsi")
    macd_val = indicators.get("macd")
    macd_sig = indicators.get("macd_signal")
    atr = indicators.get("atr", 0)
    hurst = indicators.get("hurst", 0.5)
    snr = indicators.get("snr") or {"supports": [], "resistances": []}
    regime = indicators.get("regime") or {}

    # ── Trend & Regime ──
    mr14 = indicators.get("majority") or {}
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
        vsa_texts = [s["label"] for s in vsa_signals[:2]]
        vsa_line = "\n".join(vsa_texts)

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

    # ── Generate Trading Levels ──
    levels = generate_trading_levels(
        current_price=price,
        supports=snr["supports"],
        resistances=snr["resistances"],
        atr=atr,
        atr_info=indicators.get("atr_info", {"regime": "NORMAL"}),
        hurst=hurst,
        mode="swing",
        ema_anchor=ema21,
        ma200=ema200,
        scenario=indicators.get("scenario"),
        labeled_swings=indicators.get("dow_labels", []),
    )
    
    # Use buy_low (bottom of entry zone) as anchor for display percentages
    # Trader targets buy_low, so TP%/SL% should be relative to that price
    buy_low = levels.get("buy_low")
    buy_high = levels.get("buy_high")

    indicators["levels"] = levels

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
    
    if action_key == "BUY_NOW":
        if is_gap_sup:
            action_str = f"BUY NOW (Ada gap di {sup_level_fmt})"
        else:
            action_str = f"BUY NOW (Dekat support {sup_level_fmt})"
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
    institutional_setups = detect_institutional_setups(df, snr, atr)
    L_separator = "━" * 34
    
    institutional_text = ""
    if institutional_setups:
        institutional_text = f"\n<code>{L_separator}</code>\n" + "\n\n".join(institutional_setups)

    # ── SMC ENGINE SUITE (7 Engines) ──
    smc_signals = indicators.get("smc_signals", [])
    if smc_signals:
        smc_lines = []
        has_bull_smc = 0  # Counter for BUY NOW override gating
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
        # WARNING/AVOID: fires with 1 signal (protect capital)
        if has_bear_smc:
            action_str = "AVOID (SMC Warning ⚠️)"
        # BUY NOW: requires 2+ bullish SMC confirmations (strict verification)
        elif has_bull_smc >= 2:
            action_str = "BUY NOW (SMC Confirmed 🧬)"

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
    
    early_setup = indicators.get("early_setup")
    if early_setup:
        action_str = early_setup["action"] + " ⚡"
        if not institutional_text:
            institutional_text = f"\n<code>{L_separator}</code>\n{early_setup['desc']}"
        else:
            institutional_text += f"\n\n{early_setup['desc']}"

    L = "━" * 34
    is_ihsg = (symbol == "COMPOSITE")
    title_label = "Market Outlook" if is_ihsg else "Swing Setup"
    
    lines = [
        f"<b>#{symbol} - {title_label}</b>",
        f"<code>{L}</code>",
        f"<b>MARKET STRUCTURE</b>",
        f"<code>"
        f"Bias     : {bias} (Majority Rule)\n"
        f"Hurst    : {hurst_str}\n"
        f"RSI(14)  : {rsi_str}\n"
        f"MACD     : {macd_str}\n"
        f"EMA21    : {_fmt_price(ema21)}\n"
        f"EMA50    : {_fmt_price(ema50)}\n"
        f"EMA200   : {_fmt_price(ema200)}\n"
        f"Support  : \n{sup_str}\n"
        f"Resist   : \n{res_str}"
        f"</code>",
        f"<code>{L}</code>",
    ]
    
    tp1_pct = ((levels['tp1'] - buy_low) / buy_low * 100) if buy_low and buy_low > 0 else 0
    tp2_pct = ((levels['tp2'] - buy_low) / buy_low * 100) if buy_low and buy_low > 0 else 0
    # Recalculate SL% from buy_low for consistency (includes 1-tick cut-loss buffer)
    cut_loss_display = levels['sl'] - _get_idx_tick(levels['sl']) if levels.get('sl') and levels['sl'] > 0 else levels.get('sl', 0)
    sl_pct_display = round(((buy_low - cut_loss_display) / buy_low * 100), 1) if buy_low and buy_low > 0 else levels.get('sl_pct', '-')

    rr1_str = f" | RR {levels.get('rr1')}x" if levels.get('rr1') else ""
    rr2_str = f" | RR {levels.get('rr2')}x" if levels.get('rr2') else ""

    if not is_ihsg:
        lines.extend([
            f"<b>TRADING PLAN</b>",
            f"<code>"
            f"Action    : {action_str}\n"
            f"Entry Zone: {_fmt_price(levels['buy_low'])} - {_fmt_price(levels['buy_high'])}\n"
            f"TP 1      : {_fmt_price(levels['tp1'])} (+{tp1_pct:.2f}%{rr1_str})\n"
            f"TP 2      : {_fmt_price(levels['tp2'])} (+{tp2_pct:.2f}%{rr2_str})\n"
            f"Stop Loss : {'&lt; ' + _fmt_price(levels['sl'])} (-{sl_pct_display}%)"
            f"</code>",
            f"<code>{L}</code>",
        ])
        
    if len(full_desc) > 200: full_desc = _safe_truncate(full_desc, 197)
    
    if len(institutional_text) > 300:
        institutional_text = _safe_truncate(institutional_text, 297)

    from engines.breakout_detector import generate_breakout_caption
    if "Momentum Break" in action_str:
        breakout_text = generate_breakout_caption(symbol, df)
        if breakout_text:
            lines.append(breakout_text)

    lines.extend([
        f"{momentum_line}<i>{full_desc}</i>{institutional_text}",
        f"<i>⚠️ Disclaimer: Bukan ajakan jual/beli.</i>",
    ])
    
    # Ensure total caption is within Telegram limits (1024 chars for media captions)
    final_caption = "\n".join(lines)
    if len(final_caption) > 1000:
        # Strip institutional text first if too long
        lines[-2] = f"{momentum_line}<i>{full_desc}</i>"
        final_caption = "\n".join(lines)
        if len(final_caption) > 1000:
            final_caption = _safe_truncate(final_caption, 990)
            
    return final_caption





# ──────────────────────────────────────────────
# Chart Renderer
# ──────────────────────────────────────────────

def render_chart(symbol: str, df: pd.DataFrame, indicators: dict | None = None, show_plan: bool = True, extra_data: dict = None) -> str:
    """Render a clean classic pro trading chart with S&R."""

    # ── Structure-Based Anchor System ──
    full_df = df.copy()
    total_len = len(full_df)
    
    if show_plan:
        # ── LOGIKA /tps (Dynamic Anchor berdasarkan Pola/Gap) ──
        anchor_idx = max(0, total_len - 55)
        lookback_max = max(0, total_len - 65)
        
        gaps = indicators.get("gaps", []) if indicators else []
        major_gaps_3pct = []
        for g in gaps:
            if g.get("idx", 0) >= lookback_max:
                g_b, g_t = g["bottom"], g["top"]
                pct = abs(g_t - g_b) / g_b * 100 if g_b > 0 else 0
                if pct >= 3.0:
                    major_gaps_3pct.append(g)
                    
        recent_swings = []
        if indicators and indicators.get("swings"):
            recent_swings = [s for s in indicators["swings"] if s["idx"] >= lookback_max]
            
        if major_gaps_3pct:
            latest_major_gap = major_gaps_3pct[-1]
            anchor_idx = max(0, latest_major_gap["idx"] - 4)
        elif recent_swings:
            highest_swing = max(recent_swings, key=lambda s: s["price"])
            lowest_swing = min(recent_swings, key=lambda s: s["price"])
            last_price_temp = full_df["Close"].iloc[-1]
            
            if last_price_temp < highest_swing["price"] * 0.95:
                anchor_idx = max(0, highest_swing["idx"] - 5)
            elif last_price_temp > lowest_swing["price"] * 1.05:
                anchor_idx = max(0, lowest_swing["idx"] - 5)
                
        # Proteksi Mutlak /tps: 45 hingga 65 candle
        if total_len - anchor_idx > 65:
            anchor_idx = total_len - 65
        elif total_len - anchor_idx < 45:
            anchor_idx = max(0, total_len - 45)
            
    else:
        # ── LOGIKA /sw (Fix Lookback untuk View Instan) ──
        # Tampilkan 75 candle terakhir secara statis (sekitar 3.5 bulan trading)
        # Angka ini sangat ideal untuk melihat trend MACD & Stochastic
        anchor_idx = max(0, total_len - 75)
    
    # Potong DataFrame secara dinamis berdasarkan Anchor yang terpilih
    historical_df = full_df.iloc[anchor_idx:].copy()
    
    # ── Inject Future Whitespace (Hanya untuk /tps) ──
    if show_plan:
        future_bars = int(len(historical_df) * (30 / 70))
        last_date = historical_df.index[-1]
        freq = historical_df.index[-1] - historical_df.index[-2] if len(historical_df) > 1 else pd.Timedelta(days=1)
        if freq == pd.Timedelta(0):
            freq = pd.Timedelta(days=1)
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
        
        # Swing Target Fallback logic
        if not target_price:
            peaks_above = [s for s in dow_labels if s["type"] == "peak" and s["price"] > last_price]
            if peaks_above:
                target_price = max(peaks_above, key=lambda x: x["price"])["price"]
            else:
                target_price = last_price + (atr * 3)

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

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix=f"swing_{symbol}_")
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
        datetime_format='%d %b',
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
            f"{symbol} · {company_name} · 1D · IDX{ohlc_str}",
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
        # Based on current engine file at engines/swing.py
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
            
            # Intersection Check: Only render if the gap is literally visible on the current Y-axis
            if gap_size_pct >= 1.5 and gap_bottom <= y_top and gap_top >= y_bottom:
                gap_plot_idx = g["idx"] - hist_start_idx
                if gap_plot_idx < len(plot_df):
                    x_start_gap = max(0, gap_plot_idx)
                    x_end_gap = len(plot_df) - 1
                    
                    # Clip coordinates to Y-Limits to prevent bleeding outside the plot
                    render_bottom = max(gap_bottom, y_bottom)
                    render_top = min(gap_top, y_top)
                    
                    ax_price.fill_between([x_start_gap, x_end_gap], render_bottom, render_top, 
                                          facecolor='#FFB74D', alpha=0.15, zorder=0)
                    
                    # Fix label grammar
                    gap_label = g.get('type', 'GAP_DOWN').upper().replace('_', ' ')
                    if not gap_label.startswith("GAP"): gap_label = "GAP " + gap_label
                    
                    ax_price.text(x_start_gap + 1, (render_bottom + render_top) / 2,
                                 gap_label,
                                 color='#FFB74D', fontsize=9, fontweight='bold',
                                 ha='left', va='center', alpha=0.6, zorder=1, clip_on=True)

        if dow_labels and len(swings) > 0:
            # ON-THE-FLY RELABELING
            hist_swings = swings # Gunakan seluruh history agar garis bersambung dari kiri
            
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
                    ax_price.plot([idx1, idx2], [s1['price'], s2['price']], color=l_color, linewidth=1.5, zorder=3, linestyle='-', alpha=0.7)

                # ── PENJEJAKAN AYUNAN TERAKHIR (Live Tail Tracking) ──
                last_s = relabeled_swings[-1]
                idx_last = last_s['idx'] - hist_start_idx
                x_curr_live = len(historical_df) - 1
                
                # Cek sisa ruang dari titik swing terakhir hingga candle hari ini
                if idx_last < x_curr_live:
                    search_start_idx = max(0, idx_last + 1)
                    search_df = historical_df.iloc[search_start_idx:x_curr_live+1]
                    y_offset = (y_top - y_bottom) * 0.02
                    
                    if last_s["type"] == "peak":
                        # Cari lembah menggunakan argmin Numpy agar index absolut tidak meleset
                        min_val = search_df['Low'].min()
                        min_pos = search_start_idx + search_df['Low'].values.argmin()
                        
                        # Syarat 1: Lembah tidak terjadi tepat di candle hari ini, DAN harga sudah mantul naik
                        bounce_up = last_price > min_val
                        is_valid_trough = (min_pos <= x_curr_live) and bounce_up
                        
                        # Syarat 2: Penurunannya lumayan dalam (Minimal 0.2x ATR)
                        is_deep_trough = (last_s["price"] - min_val) >= (atr * 0.2)
                        
                        if (is_valid_trough or is_deep_trough) and min_val < last_s["price"]:
                            last_trough = next((s["price"] for s in reversed(relabeled_swings) if s["type"] == "trough"), None)
                            trough_label = "HT" if (last_trough is not None and min_val >= last_trough) else "LT"
                            ax_price.plot([idx_last, min_pos], [last_s['price'], min_val], color="#D62728", linewidth=1.5, zorder=3, linestyle='-', alpha=0.7)
                            label_idx = max(0, min_pos)
                            if y_bottom <= min_val <= y_top:
                                ax_price.text(label_idx, min_val - y_offset, trough_label, color='#D1D4DC', fontweight='bold', ha='center', va='top', fontsize=14, family="sans-serif", zorder=6, bbox=dict(facecolor='#1E222D', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.2'))
                            
                            idx_last = min_pos
                            last_s = {'price': min_val, 'type': 'trough'}
                            
                    elif last_s["type"] == "trough":
                        max_val = search_df['High'].max()
                        max_pos = search_start_idx + search_df['High'].values.argmax()
                        
                        bounce_down = last_price < max_val
                        is_valid_peak = (max_pos <= x_curr_live) and bounce_down
                        is_deep_peak = (max_val - last_s["price"]) >= (atr * 0.2)
                        
                        if (is_valid_peak or is_deep_peak) and max_val > last_s["price"]:
                            last_peak = next((s["price"] for s in reversed(relabeled_swings) if s["type"] == "peak"), None)
                            peak_label = "HP" if (last_peak is not None and max_val >= last_peak) else "LP"
                            ax_price.plot([idx_last, max_pos], [last_s['price'], max_val], color="#2CA02C", linewidth=1.5, zorder=3, linestyle='-', alpha=0.7)
                            label_idx = max(0, max_pos)
                            if y_bottom <= max_val <= y_top:
                                ax_price.text(label_idx, max_val + y_offset, peak_label, color='#D1D4DC', fontweight='bold', ha='center', va='bottom', fontsize=14, family="sans-serif", zorder=6, bbox=dict(facecolor='#1E222D', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.2'))
                            
                            idx_last = max_pos
                            last_s = {'price': max_val, 'type': 'peak'}

                # Sambungkan ujung terakhir ke harga hari ini secara mulus
                if idx_last < x_curr_live:
                    l_color_live = "#2CA02C" if last_price >= last_s['price'] else "#D62728"
                    ax_price.plot([idx_last, x_curr_live], [last_s['price'], last_price], color=l_color_live, linewidth=1.5, zorder=3, linestyle='--', alpha=0.5)
                
                # SIMPAN TITIK ASAL UNTUK MENGHITUNG KEMIRINGAN
                actual_last_x = idx_last
                actual_last_y = last_s['price']

            # DRAW NEW LABELS
            for s in relabeled_swings:
                idx = s['idx'] - hist_start_idx
                label = s.get("label", "")
                price = s["price"]
                if y_bottom <= price <= y_top and idx >= 0:
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
                y_pts = None

                # === PATH 1: BREAKOUT ===
                if "Breaking" in scenario_name:
                    y_pts = [y_curr, target_price]
                    if past_slope is not None and past_slope > 0 and target_price > last_price:
                        calc_x = x_curr + int(round((target_price - last_price) / past_slope))
                        end_x = min(calc_x, x_curr + int(avail_future * 0.9))
                    else:
                        end_x = x_curr + int(avail_future * 0.85)
                    ax_price.plot([x_curr, end_x], [y_curr, target_price], color='#00BFFF', linewidth=7.0, alpha=0.15, zorder=3)
                    ax_price.plot([x_curr, end_x], [y_curr, target_price], color='#00BFFF', linewidth=2.0, zorder=4)
                    y_pts = None

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
                    seg_dists = [abs(y_pts[i+1] - y_pts[i]) for i in range(len(y_pts) - 1)]
                    total_dist = sum(seg_dists)
                    
                    usable_future = int(avail_future * 0.9)
                    
                    if total_dist > 0:
                        x_pts = [x_curr]
                        cumulative_x = 0
                        for i, d in enumerate(seg_dists):
                            proportion = d / total_dist
                            proportion = max(proportion, 0.15)
                            seg_x = int(usable_future * proportion)
                            seg_x = max(seg_x, 2)
                            cumulative_x += seg_x
                            x_pts.append(x_curr + cumulative_x)
                        
                        if cumulative_x > 0:
                            scale = usable_future / cumulative_x
                            x_pts = [x_curr] + [x_curr + max(1, int((xp - x_curr) * scale)) for xp in x_pts[1:]]
                        
                        for i in range(1, len(x_pts)):
                            if x_pts[i] <= x_pts[i-1]:
                                x_pts[i] = x_pts[i-1] + 1
                    else:
                        n_seg = len(y_pts) - 1
                        x_pts = [x_curr + int(usable_future * i / n_seg) for i in range(n_seg + 1)]
                        x_pts[0] = x_curr
                    
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

    # ── Clean Pivot Annotations for Modern /sw Terminal ──
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

    fig.savefig(tmp_path, dpi=120, bbox_inches="tight", facecolor=bg_color)
    plt.close(fig)

    return tmp_path


# ──────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────

def analyze_swing(symbol: str, ohlcv_data: list, show_plan: bool = True, extra_data: dict = None) -> tuple[str | None, str | None]:
    """
    Main function: takes raw OHLCV list, returns (chart_path, caption).
    Returns (None, error_message) on failure.
    """
    if not ohlcv_data or len(ohlcv_data) < 20: 
        return None, f"Data historis untuk <b>{symbol}</b> tidak cukup (min 20 hari)."

    # Build pandas DataFrame
    records = []
    for d in ohlcv_data:
        try:
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        records.append({
            "Date": dt,
            "Open": float(d["open"]),
            "High": float(d["high"]),
            "Low": float(d["low"]),
            "Close": float(d["close"]),
            "Volume": float(d["volume"]),
        })

    if len(records) < 20:
        return None, f"Data historis untuk <b>{symbol}</b> tidak cukup setelah parsing."

    df = pd.DataFrame(records)
    df.set_index("Date", inplace=True)
    df.index = pd.DatetimeIndex(df.index)
    df.sort_index(inplace=True)
    
    # Data Sanitization: remove zero-volume dead bars sebelum dilempar ke calc & render
    df = sanitize_ohlcv(df)

    # Calculate indicators
    indicators = calc_indicators(df)

    # Generate plan text
    caption = generate_plan(symbol, df, indicators)

    # Render chart image
    chart_path = render_chart(symbol, df, indicators, show_plan=show_plan, extra_data=extra_data)

    return chart_path, caption

