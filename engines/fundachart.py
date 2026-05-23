import os
import tempfile
import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from api.fundachart import get_fundachart

# Map user-friendly templates to Stockbit fitem_ids
TEMPLATES = {
    "PE": {
        "name": "PE Standard Deviation Band",
        "items": "12104,12101,12103,12102,12105,2891",
        "is_band": True,
    },
    "PBV": {
        "name": "PBV Standard Deviation Band",
        "items": "12140,12137,12139,12138,12141,2896",
        "is_band": True,
    },
    "PS": {
        "name": "PS Standard Deviation Band",
        "items": "12145,12142,12144,12143,12146,2893",
        "is_band": True,
    },
    "PROFIT": {
        "name": "Profitability Margins (%)",
        "items": "3107,3106,2290", # NPM, OPM, GPM
        "is_band": False,
    },
    "ROE": {
        "name": "Return On Management (%)",
        "items": "1461,1460,13447", # ROE, ROA, ROIC
        "is_band": False,
    },
    "SOLVENCY": {
        "name": "Debt & Liquidity Ratio",
        "items": "1508,1498,1512", # DER, Current Ratio, Debt/Assets
        "is_band": False,
    },
    "GROWTH": {
        "name": "YoY Quarterly Growth (%)",
        "items": "3064,2992,1470", # Net Income, Revenue, EPS 
        "is_band": False,
    },
    "CASH": {
        "name": "Cash Flow Trends",
        "items": "2545,2538,2534", # CFO, FCF, Capex
        "is_band": False,
    }
}

BAND_COLORS = ["#EF4444", "#F59E0B", "#3B82F6", "#10B981", "#059669"]
TREND_COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#A855F7"]

async def analyze_fundachart(symbol: str, template_key: str = "PE", timeframe: str = "3y") -> tuple[str | None, str | None]:
    """
    Fetch Fundachart data, render it using matplotlib, and return (chart_path, caption).
    """
    symbol = symbol.upper().strip()
    template_key = template_key.upper().strip()
    
    if template_key not in TEMPLATES:
        template_key = "PE"
        
    config = TEMPLATES[template_key]
    is_band = config.get("is_band", False)
    
    # Fetch Data
    raw_data = await get_fundachart(symbol, config["items"], timeframe)
    if not raw_data or len(raw_data) == 0 or "ratios" not in raw_data[0]:
        return None, f"Data Fundachart untuk <b>{symbol}</b> tidak ditemukan atau API sedang offline."
        
    ratios = raw_data[0]["ratios"]
    if not ratios:
        return None, f"Tidak ada data rasio {template_key} untuk saham <b>{symbol}</b>."

    # Parse data into separate DataFrames/Series
    lines_data = {}
    main_line_name = None
    
    for r in ratios:
        name = r.get("item_name", "Unknown")
        chart_points = r.get("chart_data", [])
        
        if not chart_points:
            continue
            
        if is_band:
            if "Current" in name or len(chart_points) > 10:
                main_line_name = name
            
        # Parse Dates & Values
        dates = []
        values = []
        
        for pt in chart_points:
            dt = datetime.fromtimestamp(pt["date"])
            val = pt.get("value")
            real_val = pt.get("ratio_value", val)
            if real_val is not None:
                dates.append(dt)
                values.append(float(real_val))
                
        if dates and values:
            s = pd.Series(values, index=dates)
            s.sort_index(inplace=True)
            lines_data[name] = s

    if is_band and (not main_line_name or main_line_name not in lines_data):
        return None, f"Gagal memproses data utama untuk <b>{symbol}</b>."

    if not lines_data:
        return None, f"Data poin kosong untuk <b>{symbol}</b>."

    # --- Render Chart ---
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(12, 6), facecolor='#121212')
    ax.set_facecolor('#1A1D24')
    
    # Configure grid and borders
    ax.grid(color='#2A2E39', linestyle='--', linewidth=0.5, alpha=0.7)
    for spine in ax.spines.values():
        spine.set_color('#2A2E39')
        
    ax.tick_params(colors='#8B92A5', which='both')
    
    latest_val_texts = []
    
    if is_band:
        main_series = lines_data[main_line_name]
        
        # Sort bands by their value descending
        band_series = [(name, s) for name, s in lines_data.items() if name != main_line_name]
        try:
            band_series.sort(key=lambda x: x[1].iloc[-1], reverse=True)
        except Exception:
            pass
            
        for i, (name, series) in enumerate(band_series):
            color = BAND_COLORS[i % len(BAND_COLORS)]
            if len(series) == 2:
                ax.plot([series.index[0], series.index[-1]], [series.iloc[0], series.iloc[-1]], color=color, linewidth=1.5, linestyle='--', label=name, zorder=2)
            else:
                ax.plot(series.index, series.values, color=color, linewidth=1.5, linestyle='--', label=name, zorder=2)
                
        # Main line
        ax.plot(main_series.index, main_series.values, color="#FFFFFF", linewidth=2, label=main_line_name, zorder=3)
        try:
            latest_val = main_series.iloc[-1]
            latest_val_texts.append(f"Current: <b>{latest_val:.2f}</b>")
        except Exception:
            latest_val_texts.append("Current: -")
            
    else:
        for i, (name, series) in enumerate(lines_data.items()):
            color = TREND_COLORS[i % len(TREND_COLORS)]
            ax.plot(series.index, series.values, color=color, linewidth=2, label=name, zorder=3)
            try:
                latest_val = series.iloc[-1]
                latest_val_texts.append(f"{name}: <b>{latest_val:.2f}</b>")
            except Exception:
                pass
    
    # Title
    comp_name = raw_data[0].get("company_name", symbol)
    ax.set_title(f"{comp_name} ({symbol}) - {config['name']} ({timeframe})", color="#E0E0E0", fontsize=14, fontweight="bold", pad=15)
    
    # X-Axis formatting
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    fig.autofmt_xdate()
    
    # Legend
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, loc='upper left', fontsize=9, facecolor="#1A1D24", edgecolor="#2A2E39", labelcolor="#E0E0E0", bbox_to_anchor=(1.02, 1))

    # Watermark (Image)
    try:
        import random
        import matplotlib.image as mpimg
        from matplotlib.offsetbox import OffsetImage, AnnotationBbox
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logo_path = os.path.join(base_dir, "data", "logo.jpeg")
        if os.path.exists(logo_path):
            logo = mpimg.imread(logo_path)
            imagebox = OffsetImage(logo, zoom=0.6, alpha=0.12)
            ab = AnnotationBbox(imagebox, (0.5, 0.5), frameon=False, xycoords='axes fraction')
            ax.add_artist(ab)
            
            # Additional random text watermark
            fig.text(random.uniform(0.1, 0.8), random.uniform(0.1, 0.8), 
                     "ScopeBit", fontsize=35, color="#ffffff", 
                     alpha=0.04, rotation=random.randint(0, 45))
        else:
            fig.text(0.5, 0.5, "ScopeBit", fontsize=65, color="#ffffff", 
                     ha="center", va="center", alpha=0.06, rotation=30)
    except Exception:
        fig.text(0.5, 0.5, "ScopeBit", fontsize=65, color="#ffffff", 
                 ha="center", va="center", alpha=0.06, rotation=30)
             
    # Save Image
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix=f"fundachart_{symbol}_")
    tmp_path = tmp.name
    tmp.close()
    
    fig.savefig(tmp_path, dpi=150, bbox_inches="tight", facecolor="#121212")
    plt.close(fig)
    
    # --- Generate Caption ---
    L = "━" * 32
    
    # Calculate padding for alignment
    if latest_val_texts:
        # Each entry is (formatted_name, value)
        # We need to re-format them to be aligned
        max_label_len = 0
        pairs = []
        for name, series in lines_data.items():
            if is_band and name != main_line_name: continue
            
            # Clean up long names like "(TTM)(%)" or "(MRQ)" for cleaner alignment if needed?
            # User wants it like "the others", which usually has fixed spacing.
            label = name.replace("Current ", "").replace(" Ratio", "").strip()
            max_label_len = max(max_label_len, len(label))
            pairs.append((label, series.iloc[-1]))
            
        formatted_rows = []
        for label, val in pairs:
            # Value formatting: if it's a huge number (like Cash Flow), use B/M
            if abs(val) >= 1_000_000_000:
                fmt_val = f"{val/1_000_000_000:.2f} B"
            elif abs(val) >= 1_000_000:
                fmt_val = f"{val/1_000_000:.2f} M"
            else:
                fmt_val = f"{val:.2f}"
                
            padding = " " * (max_label_len - len(label))
            formatted_rows.append(f"<code>{label}{padding} : </code><b>{fmt_val}</b>")
            
        joined_vals = "\n".join(formatted_rows)
    else:
        joined_vals = "No Data"
    
    if is_band:
        desc = "<i>💡 Band Deviation mengindikasikan seberapa murah/mahal valuasi saham secara historis.</i>"
    else:
        desc = "<i>💡 Trend Line mengindikasikan trajectory pertumbuhan atau kesehatan finansial emiten.</i>"
        
    caption = (
        f"<b>FUNDACHART: {symbol}</b>\n"
        f"<code>{L}</code>\n"
        f"Model  : {config['name']}\n"
        f"<code>{L}</code>\n"
        f"{joined_vals}\n"
        f"<code>{L}</code>\n"
        f"{desc}\n\n"
        f"<i>⚠️ Disclaimer: Bukan ajakan jual/beli.</i>"
    )
    
    return tmp_path, caption
