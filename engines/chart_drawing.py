"""
Advanced Auto-Drawing Technical Analysis — chart overlay engine.

Draws directly on matplotlib axes (ax_price) after mpf.plot(returnfig=True).
All functions are fail-safe: exceptions are caught and logged, never crash the chart.
"""
import numpy as np
import pandas as pd
import logging
import mplfinance as mpf

log = logging.getLogger("bot")


def _fmt_price(val) -> str:
    if val is None or val == 0:
        return "-"
    return f"{int(val):,}".replace(",", ".")


# ══════════════════════════════════════════════
# Chart Style Profiles
# ══════════════════════════════════════════════

def get_astronacci_style() -> tuple[dict, str, str, str, str]:
    bg_color = "#131722"       # Dark Mode Premium
    text_color = "#D1D4DC"     # Abu-abu muda
    up_color = "#26A69A"       # Hijau Teal TradingView Pro
    down_color = "#EF5350"     # Merah Coral TradingView Pro
    
    mc = mpf.make_marketcolors(
        up=up_color, down=down_color,
        edge={'up': up_color, 'down': down_color},
        wick={'up': up_color, 'down': down_color},
        volume='#434651',
        hollow=bg_color,
    )
    
    style = mpf.make_mpf_style(
        marketcolors=mc,
        figcolor=bg_color,
        facecolor=bg_color,
        gridstyle="--",         
        gridcolor="#1E222D",
        y_on_right=True,        
        rc={
            "axes.labelcolor": text_color,
            "axes.edgecolor": "#2A2E39", 
            "xtick.color": "#787B86",
            "ytick.color": "#787B86",
            "axes.grid": True,           
            "font.size": 10,
            "font.family": "sans-serif",
            "font.weight": "normal",
            "axes.linewidth": 0.5,
        },
    )
    return style, up_color, down_color, bg_color, text_color

def get_modern_style() -> tuple[dict, str, str, str, str]:
    bg_color = "#131722"
    text_color = "#D1D4DC"     # Text color TradingView
    up_color = "#089981"       # Hijau Bullish TradingView
    down_color = "#F23645"     # Merah Bearish TradingView
    
    mc = mpf.make_marketcolors(
        up=up_color, down=down_color,
        edge={'up': up_color, 'down': down_color},
        wick={'up': up_color, 'down': down_color},
        volume={'up': up_color, 'down': down_color}
    )
    
    style = mpf.make_mpf_style(
        marketcolors=mc,
        figcolor=bg_color,
        facecolor=bg_color,
        gridstyle="--",
        gridcolor="#2A2E39",   # Grid tipis gelap TradingView
        y_on_right=True,
        rc={
            "axes.labelcolor": text_color,
            "axes.edgecolor": "#2A2E39",
            "xtick.color": "#A3A6AF",
            "ytick.color": "#A3A6AF",
            "axes.grid": True,
            "font.size": 10,
            "font.family": "sans-serif",
            "font.weight": "normal",
            "axes.linewidth": 1.0,
        },
    )
    return style, up_color, down_color, bg_color, text_color

def calculate_y_limits(df: pd.DataFrame, padding_pct: float = 0.1, bottom_padding_pct: float = None) -> tuple[float, float]:
    """Calculates deterministic Y-axis limits."""
    y_min = df['Low'].min()
    y_max = df['High'].max()
    y_range = y_max - y_min
    if y_range == 0:
        y_range = y_min * 0.05 if y_min > 0 else 1.0
    bot_pad = bottom_padding_pct if bottom_padding_pct is not None else padding_pct
    return y_min - (y_range * bot_pad), y_max + (y_range * padding_pct)


# ══════════════════════════════════════════════
# Smart Anti-Collision Label Registry
# ══════════════════════════════════════════════

class LabelRegistry:
    """
    Global registry for price-level text labels. Prevents collision by:
    1. Grouping labels at the same price into multiline text
    2. Vertically displacing overlapping labels
    3. Drawing thin connector lines when labels are displaced
    """

    def __init__(self, ax, y_bottom: float, y_top: float, threshold_pct: float = 0.03):
        self.ax = ax
        self.y_bottom = y_bottom
        self.y_top = y_top
        self.y_range = y_top - y_bottom
        self.min_dist = self.y_range * threshold_pct
        # Group tolerance: labels within 0.5% of price range are "same level"
        self.group_tol = self.y_range * 0.005
        self._entries = []

    def add(self, y_price: float, text: str, color: str = "#D1D4DC",
            side: str = "right", fontsize: float = 7, alpha: float = 0.7,
            priority: int = 5):
        """
        Register a label for deferred rendering.
        priority: lower = more important (S&R=1 > price=2 > zones=3 > fib=4 > gap=5)
        side: 'left' or 'right'
        """
        if y_price is None:
            return
        self._entries.append({
            "y": float(y_price),
            "text": str(text),
            "color": color,
            "side": side,
            "fontsize": fontsize,
            "alpha": alpha,
            "priority": priority,
        })

    def render(self):
        """Process all registered labels: group, displace, draw."""
        if not self._entries:
            return

        # Step 1: Group labels at the same price
        grouped = self._group_entries()

        # Step 2: Separate left and right labels
        left_labels = [e for e in grouped if e["side"] == "left"]
        right_labels = [e for e in grouped if e["side"] == "right"]

        # Step 3: Displace and draw each side independently
        self._displace_and_draw(left_labels, ha="left", x_pos=0.20)
        self._displace_and_draw(right_labels, ha="right", x_pos=0.995)

    def _group_entries(self):
        """Merge entries at virtually the same price into combined text."""
        if not self._entries:
            return []

        sorted_entries = sorted(self._entries, key=lambda e: e["y"])
        groups = []
        current_group = [sorted_entries[0]]

        for entry in sorted_entries[1:]:
            if abs(entry["y"] - current_group[0]["y"]) <= self.group_tol:
                current_group.append(entry)
            else:
                groups.append(current_group)
                current_group = [entry]
        groups.append(current_group)

        merged = []
        for group in groups:
            if len(group) == 1:
                merged.append(group[0])
            else:
                # Combine texts, use highest priority & dominant color
                texts = [e["text"] for e in group]
                combined_text = " | ".join(texts)
                best_entry = min(group, key=lambda e: e["priority"])
                merged.append({
                    "y": group[0]["y"],
                    "text": combined_text,
                    "color": best_entry["color"],
                    "side": best_entry["side"],
                    "fontsize": max(e["fontsize"] for e in group),
                    "alpha": max(e["alpha"] for e in group),
                    "priority": min(e["priority"] for e in group),
                })
        return merged

    def _displace_and_draw(self, labels: list, ha: str, x_pos: float):
        """Displace overlapping labels vertically and draw them."""
        if not labels:
            return

        # Sort by priority first, then y
        labels.sort(key=lambda e: (e["priority"], e["y"]))

        placed = []  # list of final_y values

        for entry in labels:
            original_y = entry["y"]
            final_y = original_y

            if not (self.y_bottom <= original_y <= self.y_top):
                continue

            # Find non-colliding position
            for _ in range(20):
                collision = False
                for py in placed:
                    if abs(final_y - py) < self.min_dist:
                        collision = True
                        final_y = py + self.min_dist
                        break
                if not collision:
                    break

            # Clamp to visible range
            final_y = max(self.y_bottom + self.min_dist,
                          min(final_y, self.y_top - self.min_dist))

            placed.append(final_y)

            displaced = abs(final_y - original_y) > (self.min_dist * 0.5)

            if displaced:
                # Draw with connector line
                self.ax.annotate(
                    entry["text"],
                    xy=(1.0 if ha == "right" else 0.0, original_y),
                    xycoords=self.ax.get_yaxis_transform(),
                    xytext=(x_pos, final_y),
                    textcoords=self.ax.get_yaxis_transform(),
                    fontsize=entry["fontsize"],
                    color=entry["color"],
                    alpha=entry["alpha"],
                    va="center", ha=ha,
                    family="monospace", weight="bold", zorder=10,
                    arrowprops=dict(arrowstyle="-", color="#2A2E39",
                                   lw=0.5, alpha=0.4),
                )
            else:
                self.ax.text(
                    x_pos, final_y, entry["text"],
                    transform=self.ax.get_yaxis_transform(),
                    color=entry["color"],
                    fontsize=entry["fontsize"],
                    alpha=entry["alpha"],
                    va="center", ha=ha,
                    family="monospace", weight="bold", zorder=10,
                )


# ──────────────────────────────────────────────
# 1. Swing High / Swing Low Detection (Pivots)
# ──────────────────────────────────────────────

def _detect_pivots(df: pd.DataFrame, order: int = 5) -> dict:
    highs = []
    lows = []
    high_arr = df["High"].values
    low_arr = df["Low"].values
    n = len(df)

    for i in range(order, n - order):
        if all(high_arr[i] >= high_arr[i - j] for j in range(1, order + 1)) and \
           all(high_arr[i] >= high_arr[i + j] for j in range(1, order + 1)):
            highs.append((i, float(high_arr[i])))
        if all(low_arr[i] <= low_arr[i - j] for j in range(1, order + 1)) and \
           all(low_arr[i] <= low_arr[i + j] for j in range(1, order + 1)):
            lows.append((i, float(low_arr[i])))

    def _dedup(pivots, is_high=True):
        if len(pivots) <= 1:
            return pivots
        result = [pivots[0]]
        for p in pivots[1:]:
            prev_price = result[-1][1]
            curr_price = p[1]
            tol = prev_price * 0.005
            if is_high:
                if curr_price >= prev_price - tol and abs(p[0] - result[-1][0]) <= order * 2:
                    if curr_price > prev_price:
                        result[-1] = p
                else:
                    result.append(p)
            else:
                if curr_price <= prev_price + tol and abs(p[0] - result[-1][0]) <= order * 2:
                    if curr_price < prev_price:
                        result[-1] = p
                else:
                    result.append(p)
        return result

    return {
        "highs": _dedup(highs, is_high=True),
        "lows": _dedup(lows, is_high=False),
    }


# ──────────────────────────────────────────────
# 2. Auto Trendline
# ──────────────────────────────────────────────

def _draw_trendlines(ax, df: pd.DataFrame, pivots: dict, n_bars: int):
    lows = pivots.get("lows", [])
    highs = pivots.get("highs", [])

    if len(lows) >= 2:
        p1, p2 = lows[-2], lows[-1]
        if p2[1] >= p1[1]:
            slope = (p2[1] - p1[1]) / (p2[0] - p1[0]) if p2[0] != p1[0] else 0
            x_end = n_bars - 1
            y_end = p2[1] + slope * (x_end - p2[0])
            ax.plot([p1[0], p2[0], x_end], [p1[1], p2[1], y_end],
                    color="#2EBD85", linewidth=1.0, linestyle="--", alpha=0.5, zorder=3)

    if len(highs) >= 2:
        p1, p2 = highs[-2], highs[-1]
        if p2[1] <= p1[1]:
            slope = (p2[1] - p1[1]) / (p2[0] - p1[0]) if p2[0] != p1[0] else 0
            x_end = n_bars - 1
            y_end = p2[1] + slope * (x_end - p2[0])
            ax.plot([p1[0], p2[0], x_end], [p1[1], p2[1], y_end],
                    color="#F23645", linewidth=1.0, linestyle="--", alpha=0.5, zorder=3)


# ──────────────────────────────────────────────
# 3. Auto Fibonacci Retracement
# ──────────────────────────────────────────────

def _draw_fibonacci(ax, df: pd.DataFrame, y_bottom: float, y_top: float, n_bars: int, registry=None):
    swing_high = float(df["High"].max())
    swing_low = float(df["Low"].min())
    price_range = swing_high - swing_low
    if price_range <= 0:
        return

    hi_pos = df.index.get_loc(df["High"].idxmax())
    lo_pos = df.index.get_loc(df["Low"].idxmin())
    is_uptrend = lo_pos < hi_pos

    fib_data = [
        ("0.382", 0.382, "#42A5F5"),
        ("0.500", 0.500, "#F8CE46"),
        ("0.618", 0.618, "#E08A3A"),
    ]

    for key, ratio, color in fib_data:
        level = (swing_high - price_range * ratio) if is_uptrend else (swing_low + price_range * ratio)
        if not (y_bottom <= level <= y_top):
            continue

        ax.axhline(y=level, xmin=0.7, xmax=1.0, color=color,
                   linewidth=0.8, linestyle=":", alpha=0.35, zorder=2)
        zone_h = level * 0.003
        ax.axhspan(level - zone_h, level + zone_h, xmin=0.7, xmax=1.0,
                   color=color, alpha=0.04, zorder=1)

        label_text = f"Fib {key}  {_fmt_price(level)}"
        if registry:
            registry.add(level, label_text, color, side="right",
                         fontsize=6.5, alpha=0.6, priority=4)
        else:
            ax.text(0.995, level, label_text, transform=ax.get_yaxis_transform(),
                    color=color, fontsize=6.5, alpha=0.6,
                    va="center", ha="right", family="monospace", zorder=10)


# ──────────────────────────────────────────────
# 4. Gap Up / Gap Down Detector
# ──────────────────────────────────────────────

def _draw_gaps(ax, df: pd.DataFrame, y_bottom: float, y_top: float, registry=None):
    gaps = []
    high_arr = df["High"].values
    low_arr = df["Low"].values
    n = len(df)

    for i in range(1, n):
        prev_high, prev_low = high_arr[i - 1], low_arr[i - 1]
        curr_high, curr_low = high_arr[i], low_arr[i]

        if curr_low > prev_high:
            gap_bottom, gap_top = prev_high, curr_low
            pct = ((gap_top - gap_bottom) / gap_bottom) * 100
            filled = any(low_arr[j] <= gap_bottom for j in range(i + 1, n))
            if not filled and pct > 0.3:
                gaps.append({"type": "up", "idx": i, "bottom": gap_bottom, "top": gap_top})

        elif curr_high < prev_low:
            gap_bottom, gap_top = curr_high, prev_low
            pct = ((gap_top - gap_bottom) / gap_top) * 100
            filled = any(high_arr[j] >= gap_top for j in range(i + 1, n))
            if not filled and pct > 0.3:
                gaps.append({"type": "down", "idx": i, "bottom": gap_bottom, "top": gap_top})

    for gap in gaps[-3:]:
        mid = (gap["bottom"] + gap["top"]) / 2
        if not (y_bottom <= mid <= y_top):
            continue

        color = "#2EBD85" if gap["type"] == "up" else "#F23645"
        label = "Gap ↑" if gap["type"] == "up" else "Gap ↓"

        ax.axhspan(gap["bottom"], gap["top"], color=color, alpha=0.06, zorder=1)

        if registry:
            registry.add(mid, label, color, side="right",
                         fontsize=6.5, alpha=0.7, priority=5)
        else:
            ax.annotate(label, xy=(gap["idx"], mid), xycoords="data",
                        fontsize=6.5, color=color, alpha=0.7,
                        ha="center", va="center", family="monospace",
                        weight="bold", zorder=10)


# ──────────────────────────────────────────────
# 5. Basic Chart Pattern Recognition
# ──────────────────────────────────────────────

def _detect_patterns(ax, df: pd.DataFrame, pivots: dict):
    lows = pivots.get("lows", [])
    highs = pivots.get("highs", [])
    patterns = []

    if len(lows) >= 2:
        l1, l2 = lows[-2], lows[-1]
        tol = l1[1] * 0.02
        if abs(l1[1] - l2[1]) <= tol and (l2[0] - l1[0]) >= 5:
            between_highs = [h for h in highs if l1[0] < h[0] < l2[0]]
            if between_highs:
                neckline = max(h[1] for h in between_highs)
                curr = float(df["Close"].iloc[-1])
                if curr > l2[1]:
                    patterns.append("DOUBLE BOTTOM ✓" if curr >= neckline else "DOUBLE BOTTOM (Forming)")

    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        tol = h1[1] * 0.02
        if abs(h1[1] - h2[1]) <= tol and (h2[0] - h1[0]) >= 5:
            between_lows = [l for l in lows if h1[0] < l[0] < h2[0]]
            if between_lows:
                neckline = min(l[1] for l in between_lows)
                curr = float(df["Close"].iloc[-1])
                if curr < h2[1]:
                    patterns.append("DOUBLE TOP ✓" if curr <= neckline else "DOUBLE TOP (Forming)")

    if len(lows) >= 3 and lows[-1][1] > lows[-2][1] > lows[-3][1]:
        patterns.append("HIGHER LOWS (Bullish)")
    if len(highs) >= 3 and highs[-1][1] < highs[-2][1] < highs[-3][1]:
        patterns.append("LOWER HIGHS (Bearish)")

    if patterns:
        pattern_text = f"Pattern: {patterns[0]}"
        color = "#2EBD85" if any(k in patterns[0] for k in ["BOTTOM", "Bullish"]) else "#F23645"
        ax.text(0.5, 0.94, pattern_text, transform=ax.transAxes,
                fontsize=9, color=color, alpha=0.9,
                ha="center", va="top", family="monospace", weight="bold",
                zorder=15,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#131722",
                          edgecolor=color, alpha=0.6, linewidth=0.8))


# ──────────────────────────────────────────────
# Master Entry Point
# ──────────────────────────────────────────────

def _draw_dow_labels(ax, dow_swings: list[dict], plot_df: pd.DataFrame, y_bottom: float, y_top: float):
    """
    Draw P, T, HP, HT, LP, LT labels on the chart and connect them with ZigZag lines.
    """
    if not dow_swings:
        return
        
    start_time = plot_df.index[0]
    
    prev_idx = None
    prev_price = None
    
    for s in dow_swings:
        # Convert absolute time to plot index
        if s["time"] < start_time:
            continue
            
        try:
            # Find integer index in the plot_df
            idx = plot_df.index.get_loc(s["time"])
        except KeyError:
            continue
            
        label = s["label"]
        price = s["price"]
        
        # Draw ZigZag line connecting to previous swing
        if prev_idx is not None and prev_price is not None:
            line_color = "#2EBD85" if price > prev_price else "#F23645" # Green if up swing, Red if down swing
            ax.plot([prev_idx, idx], [prev_price, price], color=line_color, linewidth=2, zorder=4)
        
        prev_idx = idx
        prev_price = price
        
        if not (y_bottom <= price <= y_top):
            continue
            
        if s["type"] == "peak":
            # Draw above the wick
            color = "#F23645" if "L" in label else "#2EBD85" if "H" in label else "#000000"
            ax.annotate(label, xy=(idx, price), xytext=(0, 6), textcoords="offset points",
                        fontsize=10, color=color, ha="center", va="bottom",
                        family="monospace", weight="bold", zorder=5)
            # Draw marker
            ax.plot(idx, price, marker="v", markersize=0, color=color, alpha=0.0, markeredgewidth=0) # Hide markers, rely on labels and lines
        else:
            # Draw below the wick
            color = "#2EBD85" if "H" in label else "#F23645" if "L" in label else "#000000"
            ax.annotate(label, xy=(idx, price), xytext=(0, -6), textcoords="offset points",
                        fontsize=10, color=color, ha="center", va="top",
                        family="monospace", weight="bold", zorder=5)
            # Draw marker
            ax.plot(idx, price, marker="^", markersize=0, color=color, alpha=0.0, markeredgewidth=0)

def draw_advanced_ta(ax, plot_df: pd.DataFrame, y_bottom: float, y_top: float, registry=None, dow_swings=None):
    """
    Draw all advanced auto-TA overlays on ax_price.
    If registry (LabelRegistry) is provided, Fib/Gap labels are registered
    instead of drawn directly, for anti-collision processing.
    """
    n_bars = len(plot_df)
    if n_bars < 15:
        return

    order = 3 if n_bars < 60 else 5 if n_bars < 150 else 7

    try:
        pivots = _detect_pivots(plot_df, order=order)
    except Exception as e:
        log.warning(f"Pivot detection error: {e}")
        pivots = {"highs": [], "lows": []}

    try:
        if dow_swings:
            _draw_dow_labels(ax, dow_swings, plot_df, y_bottom, y_top)
            # We still need pivots for patterns and trendlines, but we skip drawing the old markers
        else:
            for (idx, price) in pivots["highs"]:
                ax.plot(idx, price, marker="v", markersize=4, color="#F23645",
                        alpha=0.5, zorder=5, markeredgewidth=0)
            for (idx, price) in pivots["lows"]:
                ax.plot(idx, price, marker="^", markersize=4, color="#2EBD85",
                        alpha=0.5, zorder=5, markeredgewidth=0)
    except Exception as e:
        log.warning(f"Pivot/Dow marker error: {e}")

    try:
        _draw_trendlines(ax, plot_df, pivots, n_bars)
    except Exception as e:
        log.warning(f"Trendline error: {e}")

    try:
        _draw_fibonacci(ax, plot_df, y_bottom, y_top, n_bars, registry=registry)
    except Exception as e:
        log.warning(f"Fibonacci error: {e}")

    try:
        _draw_gaps(ax, plot_df, y_bottom, y_top, registry=registry)
    except Exception as e:
        log.warning(f"Gap detection error: {e}")

    try:
        _detect_patterns(ax, plot_df, pivots)
    except Exception as e:
        log.warning(f"Pattern detection error: {e}")

    # ── Draw PAST | FUTURE Splitter ──
    try:
        # Find the last valid close price index
        if "Close" in plot_df.columns:
            last_valid_idx = plot_df["Close"].last_valid_index()
            if last_valid_idx is not None:
                iloc_idx = plot_df.index.get_loc(last_valid_idx)
                
                # Draw vertical separator if there is future whitespace
                if iloc_idx < n_bars - 1:
                    ax.axvline(x=iloc_idx + 0.5, color="#555555", linewidth=1.0, linestyle="-.", alpha=0.6, zorder=1)
                    
                    # PAST Text
                    ax.text(iloc_idx, y_bottom + (y_top - y_bottom)*0.03, "PAST", 
                            color="#F23645", fontsize=10, weight="bold", 
                            ha="right", va="bottom", alpha=0.7, zorder=10)
                            
                    # FUTURE Text
                    ax.text(iloc_idx + 1, y_bottom + (y_top - y_bottom)*0.03, "FUTURE", 
                            color="#F8CE46", fontsize=10, weight="bold", 
                            ha="left", va="bottom", alpha=0.9, zorder=10)
    except Exception as e:
        log.warning(f"Future Splitter annotation error: {e}")
