"""
PDF Deep-Dive Report Engine
============================
Clean, light-mode, easy-to-read PDF report.
Designed for maximum readability across all ages.
"""

import os
import re
import html as html_mod
import tempfile
import logging
import asyncio
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black, white
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from api.market import (
    get_orderbook, get_historical_summary, get_trade_book,
    get_trade_book_chart, get_market_detector
)
from api.broker import get_broker_summary
from api.chartbit import get_daily_chart, get_intraday_chart
from api.fundamental import get_info, get_keystats, get_profile
from api.client import _safe_int, _safe_float

from engines.smart_money import (
    calc_money_flow_chart, calc_volume_ratio,
    calc_price_strength, calc_broker_summary, calc_rsv, calc_spoofing_index
)
from engines.foreign_flow import calc_foreign_accum
from engines.fundamental import calc_fundamental
from engines.bandarmology import analyze_bandar
from engines.fundachart import analyze_fundachart
from engines.swing import analyze_swing
from engines.day_trade import analyze_day_trade
from engines.insider import get_insider_raw_data

log = logging.getLogger("report")

# ── Colors ── (Stockbit-style Clean Palette)
BLACK       = HexColor("#111111")
DARK_GRAY   = HexColor("#383838")
GRAY        = HexColor("#6B7280")
LIGHT_GRAY  = HexColor("#9CA3AF")
BORDER      = HexColor("#E5E7EB")
BG_SECTION  = HexColor("#F9FAFB")
GREEN       = HexColor("#10B981") # Vibrant Stockbit-ish Green
RED         = HexColor("#EF4444") # Clean Red
BLUE        = HexColor("#3B82F6") # Clean Accent Blue

# ── Spacing Scale (Tailwind style) ──
SPACE_XS = 2 * mm
SPACE_SM = 4 * mm
SPACE_MD = 6 * mm
SPACE_LG = 10 * mm
SPACE_XL = 16 * mm

W, H = A4
MARGIN_L = 20 * mm
MARGIN_R = 20 * mm
CONTENT_W = W - MARGIN_L - MARGIN_R

# ── Watermark Setup ──
def _create_watermark_image():
    # Look for logo in data/ folder relative to project root
    logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "logo.jpeg")
    if not os.path.exists(logo_path):
        log.warning(f"Watermark logo not found at: {logo_path}")
        return None
    try:
        from PIL import Image
        import io
        img = Image.open(logo_path).convert("RGBA")
        alpha = img.split()[3]
        alpha = alpha.point(lambda p: p * 0.08) # 8% opacity
        img.putalpha(alpha)
        
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return ImageReader(buf)
    except Exception as e:
        log.error(f"Failed to create watermark: {e}")
        return None

_WATERMARK = _create_watermark_image()

# ── Helpers ──

def _strip_html(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    return html_mod.unescape(text)

def _fv(val):
    """Format number with sign + B/M/K suffix."""
    if val is None: return "-"
    sign = "+" if val > 0 else ""
    av = abs(val)
    if av >= 1_000_000_000_000: return f"{sign}{val/1_000_000_000_000:.2f} T"
    if av >= 1_000_000_000: return f"{sign}{val/1_000_000_000:.2f} B"
    if av >= 1_000_000: return f"{sign}{val/1_000_000:.2f} M"
    if av >= 1_000: return f"{sign}{val/1_000:.1f} K"
    return f"{sign}{val:.0f}"

def _fp(val):
    """Format price with dot separator."""
    if val is None or val == 0: return "-"
    return f"{int(val):,}".replace(",", ".")

def _s(val, fb="-"):
    if val is None or str(val).strip() in ("", "None"): return fb
    return str(val)

class PDFReport:
    def __init__(self, symbol, company):
        self.symbol = symbol
        self.company = company
        self.tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix=f"report_{symbol}_")
        self.path = self.tmp.name
        self.tmp.close()
        self.c = canvas.Canvas(self.path, pagesize=A4)
        self.c.setTitle(f"ScopeBit Report — {symbol}")
        self.c.setAuthor("ScopeBit")
        self.page_num = 0
        self.y = H - 20 * mm

    # ── Layout primitives ──

    def _new_page(self):
        if self.page_num > 0:
            self.c.showPage()
        self.page_num += 1
        # White bg
        self.c.setFillColor(white)
        self.c.rect(0, 0, W, H, fill=1, stroke=0)
        
        # Scattered Text Watermark (Anti-Theft)
        self.c.saveState()
        # Very faint gray to not disturb readability
        self.c.setFillColorRGB(0.96, 0.96, 0.96)
        self.c.setFont("Helvetica-Bold", 35)
        
        wm_text = "ScopeBit"
        wm_spacing_x = 80 * mm
        wm_spacing_y = 100 * mm
        
        for y_idx in range(-1, int(H / wm_spacing_y) + 2):
            for x_idx in range(-1, int(W / wm_spacing_x) + 2):
                x = x_idx * wm_spacing_x
                y = y_idx * wm_spacing_y
                # Stagger alternate rows for brick pattern
                if y_idx % 2 != 0:
                    x += wm_spacing_x / 2
                    
                self.c.saveState()
                self.c.translate(x, y)
                self.c.rotate(30)
                self.c.drawCentredString(0, 0, wm_text)
                self.c.restoreState()
                
        self.c.restoreState()

        # Watermark
        if _WATERMARK:
            size_mm = 120 * mm
            # Center it
            x = (W - size_mm) / 2
            y = (H - size_mm) / 2
            self.c.drawImage(_WATERMARK, x, y, size_mm, size_mm, mask='auto', preserveAspectRatio=True)

        self.y = H - 18 * mm
        # Footer
        self.c.setFillColor(LIGHT_GRAY)
        self.c.setFont("Helvetica", 7)
        self.c.drawString(MARGIN_L, 8 * mm, f"ScopeBit Telegram  |  {self.symbol}  |  Halaman {self.page_num}")
        self.c.drawRightString(W - MARGIN_R, 8 * mm, datetime.now().strftime("%d %b %Y %H:%M WIB"))

    def _truncate_text(self, text, font, size, max_width):
        text = str(text)
        if self.c.stringWidth(text, font, size) <= max_width:
            return text
        for i in range(len(text), 0, -1):
            t = text[:i] + "..."
            if self.c.stringWidth(t, font, size) <= max_width:
                return t
        return "..."

    def _table_row(self, cols, widths, aligns, fonts, colors, sizes, rh=4.5*mm, border=True, padding=True):
        """Responsive flex-table row with compact spacing."""
        if not isinstance(fonts, list): fonts = [fonts]*len(cols)
        if not isinstance(colors, list): colors = [colors]*len(cols)
        if not isinstance(sizes, list): sizes = [sizes]*len(cols)
        
        start_x = MARGIN_L
        for i, text in enumerate(cols):
            w = widths[i] * CONTENT_W
            align = aligns[i]
            
            self.c.setFont(fonts[i], sizes[i])
            self.c.setFillColor(colors[i])
            
            text_str = self._truncate_text(str(text), fonts[i], sizes[i], w - 2*mm)
            
            if align == 'L':
                self.c.drawString(start_x + 1*mm, self.y - rh, text_str)
            elif align == 'R':
                self.c.drawRightString(start_x + w - 1*mm, self.y - rh, text_str)
            elif align == 'C':
                self.c.drawCentredString(start_x + w/2, self.y - rh, text_str)
                
            start_x += w
        
        if border:
            self.c.setStrokeColor(BORDER)
            self.c.setLineWidth(0.3)
            # Draw line at bottom with tight margin
            self.c.line(MARGIN_L, self.y - rh - 1.5*mm, MARGIN_L + CONTENT_W, self.y - rh - 1.5*mm)
            
        # Total drop per row
        row_drop = rh + (1.5*mm if border else 0) + (1.5*mm if padding else 0)
        self.y -= row_drop

    def _header(self, title):
        """Clean, professional Stockbit-style header."""
        self._need(SPACE_XL)
        self.y -= SPACE_LG # Pushes down away from previous content
        self.c.setFont("Helvetica-Bold", 10)
        self.c.setFillColor(BLACK)
        self.c.drawString(MARGIN_L, self.y, title.upper())
        self.y -= 2*mm     # Pulls closer to the accent line
        
        # Super thin border under header with blue accent
        self.c.setStrokeColor(BLUE)
        self.c.setLineWidth(1.5)
        self.c.line(MARGIN_L, self.y, MARGIN_L + 15*mm, self.y)
        self.c.setStrokeColor(BORDER)
        self.c.setLineWidth(0.5)
        self.c.line(MARGIN_L + 15*mm, self.y, W - MARGIN_R, self.y)
        
        self.y -= SPACE_MD # Tighter spacing pushing to row content

    def _row(self, label, value, grade=None, color=None):
        """Key-value row with very neat alignment, padding, and text truncation."""
        rh = 4.5 * mm # Compact generic row height
        v_font, v_size = "Helvetica-Bold", 8.5
        g_font, g_size = "Helvetica-Oblique", 8
        
        val_str = str(value)
        val_w = self.c.stringWidth(val_str, v_font, v_size)
        
        val_x = MARGIN_L + CONTENT_W
        if grade:
            val_x -= 30 * mm
            
        # Left side label max width (leave 10mm padding minimum from value)
        label_max_w = (val_x - val_w) - MARGIN_L - 10*mm
        
        # Label
        self.c.setFont("Helvetica", 8.5)
        self.c.setFillColor(GRAY)
        label_str = self._truncate_text(label, "Helvetica", 8.5, max(10*mm, label_max_w))
        self.c.drawString(MARGIN_L, self.y - rh, label_str)
        
        # Value
        self.c.setFillColor(color or BLACK)
        self.c.setFont(v_font, v_size)
        self.c.drawRightString(val_x, self.y - rh, val_str)
        
        # Grade
        if grade:
            self.c.setFillColor(LIGHT_GRAY)
            self.c.setFont(g_font, g_size)
            self.c.drawRightString(MARGIN_L + CONTENT_W, self.y - rh, str(grade))
            
        # Subtle bottom line
        self.c.setStrokeColor(BORDER)
        self.c.setLineWidth(0.3)
        self.c.line(MARGIN_L, self.y - rh - 1.5*mm, MARGIN_L + CONTENT_W, self.y - rh - 1.5*mm)
        self.y -= rh + 1.5*mm

    def _text(self, text, bold=False, size=8, color=None, indent=0):
        font = "Helvetica-Bold" if bold else "Helvetica"
        self.c.setFont(font, size)
        self.c.setFillColor(color or DARK_GRAY)
        self.c.drawString(MARGIN_L + indent, self.y - SPACE_SM, text)
        self.y -= SPACE_SM + 1*mm

    def _gap(self, h=None):
        h = h if h is not None else SPACE_SM
        self.y -= h

    def _need(self, h):
        if self.y - h < 18 * mm:
            self._new_page()

    # ── Page 1: Fundamental ──

    def page_fundamental(self, fa):
        self._new_page()
        g = fa.get("grades", {})
        def _gr(k):
            lbl, _ = g.get(k, ("-", 0))
            return lbl

        # Title block
        self.c.setFillColor(BLACK)
        self.c.setFont("Helvetica-Bold", 18)
        self.c.drawString(MARGIN_L, self.y, self.company)
        self.y -= 6 * mm
        self.c.setFont("Helvetica-Bold", 12)
        self.c.setFillColor(BLUE)
        self.c.drawString(MARGIN_L, self.y, self.symbol)
        sector = _s(fa.get("sub_sector", fa.get("sector")))
        self.c.setFillColor(GRAY)
        self.c.setFont("Helvetica", 9)
        self.c.drawString(MARGIN_L + 30 * mm, self.y, f"Sector: {sector}")
        self.c.setFillColor(LIGHT_GRAY)
        self.c.setFont("Helvetica", 8)
        self.c.drawRightString(W - MARGIN_R, self.y, "Deep-Dive Report  |  " + datetime.now().strftime("%d %B %Y"))
        self.y -= 4 * mm

        # Divider
        self.c.setStrokeColor(BLACK)
        self.c.setLineWidth(1)
        self.c.line(MARGIN_L, self.y, W - MARGIN_R, self.y)
        self.y -= 4 * mm

        # Score
        score = fa.get("overall_score", 0)
        label = fa.get("overall_label", "-")
        sc = GREEN if score >= 65 else HexColor("#E6A817") if score >= 40 else RED

        self.c.setFont("Helvetica-Bold", 10)
        self.c.setFillColor(BLACK)
        self.c.drawString(MARGIN_L, self.y, f"Skor Fundamental")
        self.c.setFillColor(sc)
        self.c.drawRightString(W - MARGIN_R, self.y, f"{score}/100  {label}")
        self.y -= 3 * mm

        # Score bar
        bar_w = CONTENT_W
        bar_h = 4 * mm
        self.c.setFillColor(HexColor("#E8E8E8"))
        self.c.roundRect(MARGIN_L, self.y - bar_h, bar_w, bar_h, 2, fill=1, stroke=0)
        fill_w = max(bar_w * (score / 100), 3)
        self.c.setFillColor(sc)
        self.c.roundRect(MARGIN_L, self.y - bar_h, fill_w, bar_h, 2, fill=1, stroke=0)
        self.y -= bar_h + 2 * mm

        # Sections
        self._header("VALUASI")
        self._row("Harga", _fp(fa.get("price", 0)))
        self._row("Market Cap", _s(fa.get("market_cap")))
        self._row("P/E (TTM)", _s(fa.get("pe_ttm")), _gr("pe"))
        self._row("P/E Forward", _s(fa.get("pe_forward")))
        self._row("PBV", _s(fa.get("pbv")), _gr("pbv"))
        self._row("PEG", _s(fa.get("peg")), _gr("peg"))
        self._row("EV/EBITDA", _s(fa.get("ev_ebitda")))

        # Fair Value
        fair = fa.get("fair_value")
        mos = fa.get("margin_of_safety")
        methods = fa.get("fair_methods", [])
        if fair and fair > 0:
            self._header("ESTIMASI NILAI WAJAR")
            for mname, val in methods:
                self._row(mname, f"Rp {_fp(val)}")
            self._row("Rata-rata", f"Rp {_fp(fair)}", color=BLUE)
            if mos is not None:
                ml = "UNDERVALUED" if mos > 15 else ("MURAH" if mos > 0 else ("MAHAL" if mos > -15 else "OVERVALUED"))
                mc = GREEN if mos > 0 else RED
                self._row("Margin of Safety", f"{mos:+.1f}%  ({ml})", color=mc)

        self._header("PROFITABILITAS")
        self._row("GPM", _s(fa.get("gpm")))
        self._row("OPM", _s(fa.get("opm")))
        self._row("NPM", _s(fa.get("npm")), _gr("npm"))

        self._header("EFEKTIVITAS")
        self._row("ROA", _s(fa.get("roa")), _gr("roa"))
        self._row("ROE", _s(fa.get("roe")), _gr("roe"))
        self._row("ROIC", _s(fa.get("roic")))

        self._header("KESEHATAN KEUANGAN")
        self._row("DER", _s(fa.get("der")), _gr("der"))
        self._row("Altman Z", _s(fa.get("altman_z")))
        self._row("F-Score", _s(fa.get("f_score")), _gr("f_score"))

        self._header("DIVIDEN")
        self._row("Yield", _s(fa.get("div_yield")), _gr("div_yield"))
        self._row("Payout Ratio", _s(fa.get("div_payout")))

    # ── Page 2: Smart Money ──

    def page_smart_money(self, ob, historical, trade_book, chart_data, broker_data):
        self._new_page()

        price = ob["last_price"]
        pct = ob["change_pct"]
        sign = "+" if pct >= 0 else ""
        vol_ratio = calc_volume_ratio(ob["volume"], historical) if historical else 0.0
        rsv = calc_rsv(price, ob.get("high", 0), ob.get("low", 0))

        self._header(f"RINGKASAN PASAR — {self.symbol}")
        self._row("Harga", f"{_fp(price)}  ({sign}{pct:.2f}%)")
        self._row("Volume", f"{_fv(ob['volume'])} lot")
        self._row("Value", _fv(ob["value"]))
        self._row("Vol Ratio", f"{vol_ratio:.1f}x")
        self._row("RSV", f"{rsv:.0f}")

        # Money Flow
        mf = calc_money_flow_chart(chart_data, fallback_price=price)
        self._header("ARUS UANG (MONEY FLOW)")
        if mf:
            sm, bm, cm = mf["smart_money"], mf["bad_money"], mf["clean_money"]
            total = abs(sm) + abs(bm) if (abs(sm) + abs(bm)) > 0 else 1
            pwr = abs(cm) / total * 100
            status = "BUYER" if cm > 0 else ("SELLER" if cm < 0 else "NETRAL")

            self._row("Smart Money", _fv(sm), color=GREEN if sm > 0 else RED)
            self._row("Bad Money", _fv(bm), color=RED)
            self._row("Clean Money", _fv(cm), color=GREEN if cm > 0 else RED)
            self._row("Dominasi", status)
            self._row("Power Ratio", f"{pwr:.1f}%")
        else:
            self._text("Tidak ada data transaksi", color=LIGHT_GRAY)

        # Spoofing
        spoof = calc_spoofing_index(ob)
        if spoof:
            self._header("DETEKSI SPOOFING")
            w = "TERDETEKSI" if spoof["is_spoofing"] else "Normal"
            wc = RED if spoof["is_spoofing"] else GREEN
            self._row("OB vs Match", f"{spoof['ratio']:.1f}x")
            self._row("Status", w, color=wc)

        # Foreign
        self._header("ASING (FOREIGN FLOW)")
        fnet = ob.get("fnet", 0)
        fc = GREEN if fnet >= 0 else RED
        fl = "Net Buy" if fnet >= 0 else "Net Sell"
        self._row("Hari Ini", f"{_fv(fnet)}  ({fl})", color=fc)
        if historical:
            foreign = calc_foreign_accum(historical)
            if foreign:
                acc = foreign["accum_net"]
                ac = GREEN if acc >= 0 else RED
                al = "Akumulasi" if acc >= 0 else "Distribusi"
                self._row(f"Akum {foreign['days']} Hari", f"{_fv(acc)}  ({al})", color=ac)

        # Brokers
        brokers = calc_broker_summary(broker_data)
        if brokers["top_buyers"] or brokers["top_sellers"]:
            self._header("BROKER TERBESAR")
            self._need(SPACE_MD)
            
            self._table_row(
                cols=["Top Buyers", "Top Sellers"],
                widths=[0.5, 0.5],
                aligns=["L", "L"],
                fonts="Helvetica-Bold",
                colors=[GREEN, RED],
                sizes=8,
                rh=4.5*mm,
                border=False,
                padding=False
            )
            self.y -= 2*mm
            
            for i in range(3):
                self._need(SPACE_SM)
                drawn = False
                
                b_code = b_val = s_code = s_val = ""
                # Buyer
                if i < len(brokers["top_buyers"]):
                    b = brokers["top_buyers"][i]
                    b_code, b_val = b['code'], _fv(b['val'])
                    drawn = True
                
                # Seller
                if i < len(brokers["top_sellers"]):
                    s = brokers["top_sellers"][i]
                    s_code, s_val = s['code'], _fv(s['val'])
                    drawn = True
                    
                if drawn:
                    self._table_row(
                        cols=[b_code, b_val, "", s_code, s_val],
                        widths=[0.1, 0.35, 0.05, 0.1, 0.4],
                        aligns=["L", "R", "C", "L", "R"],
                        fonts=["Helvetica-Bold", "Helvetica", "Helvetica", "Helvetica-Bold", "Helvetica"],
                        colors=[BLACK, GRAY, BLACK, BLACK, GRAY],
                        sizes=8,
                        rh=4.5*mm,
                        border=False,
                        padding=False
                    )

        # Price Strength
        levels = calc_price_strength(trade_book)
        if levels:
            self._need(SPACE_XL + SPACE_MD * len(levels))
            self._header("KEKUATAN HARGA (Top 3)")
            self._need(SPACE_MD)
            
            self._table_row(
                cols=["Harga", "Beli", "Jual", "Net"],
                widths=[0.2, 0.25, 0.25, 0.3],
                aligns=["L", "R", "R", "R"],
                fonts="Helvetica-Bold",
                colors=GRAY,
                sizes=7.5,
                rh=3.5*mm,
                border=True
            )
            
            for p in levels:
                self._need(SPACE_MD)
                net = p["net"]
                nc = GREEN if net > 0 else RED if net < 0 else GRAY
                b = f"{p['buy_lot']:,}".replace(",", ".")
                s = f"{p['sell_lot']:,}".replace(",", ".")
                n = f"{net:+,}".replace(",", ".")
                
                self._table_row(
                    cols=[_fp(p['price']), b, s, n],
                    widths=[0.2, 0.25, 0.25, 0.3],
                    aligns=["L", "R", "R", "R"],
                    fonts=["Helvetica-Bold", "Helvetica", "Helvetica", "Helvetica-Bold"],
                    colors=[BLACK, GRAY, GRAY, nc],
                    sizes=8,
                    rh=4.5*mm,
                    border=False,
                    padding=False
                )
                self.y -= 1*mm

    # ── Page 3: Bandarmology ──

    def page_bandarmology(self, text):
        if not text: return
        self._new_page()

        clean = _strip_html(text)
        lines = [l.strip() for l in clean.split("\n") if l.strip() and "━" not in l]

        first_header_done = False
        for line in lines:
            if line.startswith("BANDARMOLOGY:") or line.startswith("Tanggal") or line.startswith("Harga"):
                continue

            is_section = any(kw in line for kw in [
                "BROKER ACTIVITY", "FOREIGN FLOW", "BROKER CONCENTRATION",
                "STEALTH SCORE", "SUPPLY ZONE", "DEMAND ZONE",
                "VERDICT", "ACCUMULATION CONFIDENCE"
            ])

            if is_section:
                if not first_header_done:
                    self._header(f"BANDARMOLOGI — {self.symbol}")
                    first_header_done = True
                self._need(25 * mm)
                self._header(line)
                continue

            if line.startswith("["):
                self._need(SPACE_LG)
                # Determine color based on accumulation (ACC) vs distribution (DIST) or net positive/negative
                line_upper = line.upper()
                if "ACC" in line_upper or "Net: +" in line or "NET: +" in line_upper:
                    c = GREEN
                elif "DIST" in line_upper or "Net: -" in line or "NET: -" in line_upper:
                    c = RED
                else:
                    c = BLUE
                self._text(line, bold=True, size=8.5, color=c)
                continue

            self._need(SPACE_MD)
            
            # Check for Broker Activity line: "B MU [R] 44Rb Lot Avg 1.638"
            brok_match = re.match(r"^(B|S)\s+([A-Z0-9]{2,3})\s+(\[.*?\])\s+(.*?)\s+Avg\s+(.*)$", line)
            if brok_match:
                rh_bg = 6 * mm
                self._need(rh_bg)
                bs, code, type_flag, lot_val, avg = brok_match.groups()
                
                # Dynamic text color for 'B' or 'S'
                txt_color = GREEN if bs == "B" else RED
                
                # Highlight background spanning full width
                bg_color = HexColor("#F0FDF4") if bs == "B" else HexColor("#FEF2F2")
                self.c.setFillColor(bg_color)
                # Perfect touching rows (draw 6mm box and start text within it)
                self.c.rect(MARGIN_L, self.y - rh_bg + 1*mm, CONTENT_W, rh_bg, fill=1, stroke=0)
                
                self._table_row(
                    cols=[bs, code, type_flag, lot_val, f"Avg {avg}"],
                    widths=[0.05, 0.1, 0.15, 0.4, 0.3],
                    aligns=["C", "L", "L", "R", "R"],
                    fonts=["Helvetica-Bold", "Helvetica-Bold", "Helvetica", "Helvetica-Bold", "Helvetica-Bold"],
                    colors=[txt_color, BLACK, GRAY, BLACK, GRAY],
                    sizes=8.5,
                    rh=4.5*mm,
                    border=True,
                    padding=False
                )
                self.y -= 1.5 * mm # Finalizes the 6mm total drop to match rh_bg
                continue
                
            # --- REVISI: Parsing Support & Resistance yang Rapi ---
            sr_val_match = re.search(r'([0-9]+[\.\,]?[0-9]*)\s*\(\s*str[:\s]*([0-9\*]+)', line, re.IGNORECASE)
            # Header check: "Support  :" or "Resist   :" or "saat ini Support:"
            is_sr_header = bool(re.match(r'^(saat\s+ini\s+)?(support|resist(ance)?)[\s:]*$', line, re.IGNORECASE))

            if sr_val_match or is_sr_header:
                # 1. Update current mode if it's a header or contains keywords
                if re.search(r'support', line, re.IGNORECASE):
                    self.current_sr_mode = "Support"
                elif re.search(r'resist', line, re.IGNORECASE):
                    self.current_sr_mode = "Resist"
                
                # Default to Support if somehow skipped
                if not hasattr(self, 'current_sr_mode'):
                    self.current_sr_mode = "Support"
                
                # If just a header without numbers, skip rendering (we print mode on numbers line)
                if not sr_val_match:
                    continue
                    
                # 2. Extract price, strength, and optional shorthand [w/m/d]
                price = sr_val_match.group(1)
                strength = sr_val_match.group(2)
                
                # Try to find shorthand label [w], [m], or [d]
                sh_match = re.search(r'\[([wmd])\]', line, re.IGNORECASE)
                sh_lbl = f" [{sh_match.group(1)}]" if sh_match else ""
                
                label_to_print = self.current_sr_mode
                c_mode = GREEN if self.current_sr_mode == "Support" else RED
                
                # 3. Render row
                rh_bg = 4.5 * mm
                self._need(rh_bg + 1.5*mm)
                
                self._table_row(
                    cols=[label_to_print, f"Rp {price}{sh_lbl}", f"(str: {strength})"],
                    widths=[0.25, 0.4, 0.35],
                    aligns=["L", "L", "R"],
                    fonts=["Helvetica-Bold", "Helvetica-Bold", "Helvetica"],
                    colors=[c_mode, BLACK, GRAY],
                    sizes=8.5,
                    rh=rh_bg,
                    border=True,
                    padding=False
                )
                self.y -= 1.5 * mm
                continue
            # --------------------------------------------------------

            if ":" in line and len(line.split(":")) == 2:
                parts = line.split(":", 1)
                val = parts[1].strip()
                c = DARK_GRAY
                if "ACC" in val.upper() or "AKUM" in val.upper() or "Net Buy" in val:
                    c = GREEN
                elif "DIST" in val.upper() or "Net Sell" in val:
                    c = RED
                self._row(parts[0].strip(), val, color=c)
            else:
                self._text(line, size=7.5, color=GRAY)

    # ── Page 4: Insider & Major Holder ──

    def page_insider(self, data):
        if not data or not data.get("has_moves"): return
        self._new_page()

        # Header Title
        self.c.setFillColor(BLACK)
        self.c.setFont("Helvetica-Bold", 14)
        self.c.drawString(MARGIN_L, self.y, f"INSIDER & MAJOR HOLDER")
        self.y -= 6 * mm
        self.c.setFont("Helvetica-Bold", 11)
        self.c.setFillColor(BLUE)
        self.c.drawString(MARGIN_L, self.y, f"{self.company} ({self.symbol})")
        self.y -= 5 * mm
        self.c.setStrokeColor(BORDER)
        self.c.setLineWidth(0.5)
        self.c.line(MARGIN_L, self.y, W - MARGIN_R, self.y)
        self.y -= 5 * mm

        # Summary Metrics
        net_shares = data.get("net_shares", 0)
        net_val = data.get("net_val", 0)
        net_label = "AKUMULASI" if net_shares > 0 else ("DISTRIBUSI" if net_shares < 0 else "NEUTRAL")
        net_color = GREEN if net_shares > 0 else (RED if net_shares < 0 else GRAY)

        self._header("RINGKASAN (Top 50 Data Terakhir)")
        self._row("Status", net_label, color=net_color)
        self._row("Total Beli", f"{_fv(data.get('total_buy_shares', 0))} Lmbr  (Rp {_fv(data.get('total_buy_val', 0))})")
        self._row("Total Jual", f"{_fv(data.get('total_sell_shares', 0))} Lmbr  (Rp {_fv(data.get('total_sell_val', 0))})")
        self._row("Net Volume", f"{_fv(net_shares)} Lembar", color=net_color)
        self._row("Net Value", f"Rp {_fv(net_val)}", color=net_color)

        # Top Actors
        top_buyers = data.get("top_buyers", [])
        top_sellers = data.get("top_sellers", [])
        if top_buyers or top_sellers:
            self._header("TOP ACTORS (NET VOLUME)")
            
            # Buyers
            if top_buyers:
                self._need(SPACE_MD * len(top_buyers) + SPACE_LG)
                self._text("Pembeli Bersih Terbesar:", bold=True, size=8.5, color=GREEN)
                self.y -= SPACE_XS # Adjust spacing 
                for b in top_buyers:
                    self._text(f"[+] {_fv(b['net']):>8} Lmbr   |   {b['name']}", size=8, color=BLACK, indent=SPACE_MD)
            
            self._gap(SPACE_MD)
            # Sellers
            if top_sellers:
                self._need(SPACE_MD * len(top_sellers) + SPACE_LG)
                self._text("Penjual Bersih Terbesar:", bold=True, size=8.5, color=RED)
                self.y -= SPACE_XS # Adjust spacing
                for s in top_sellers:
                    self._text(f"[-] {_fv(s['net']):>8} Lmbr   |   {s['name']}", size=8, color=BLACK, indent=SPACE_MD)

        # Recent Moves Table-ish
        recent_moves = data.get("recent_moves", [])
        if recent_moves:
            self._gap(SPACE_LG)
            self._header("10 TRANSAKSI TERBARU")
            
            # Headers
            self._need(SPACE_MD)
            self._table_row(
                cols=["Tanggal", "Aksi", "Volume", "Harga", "Aktor"],
                widths=[0.15, 0.1, 0.25, 0.2, 0.3],
                aligns=["L", "L", "R", "R", "L"],
                fonts="Helvetica-Bold",
                colors=DARK_GRAY,
                sizes=7.5,
                rh=3.5*mm,
                border=True
            )

            for m in recent_moves:
                self._need(SPACE_MD + SPACE_XS)
                act = m['action'].upper()
                c = GREEN if act == "BUY" else RED
                
                self._table_row(
                    cols=[m['date'], act, _fv(m['shares']), f"Rp {_fp(m['price'])}", m['name']],
                    widths=[0.15, 0.1, 0.25, 0.2, 0.3],
                    aligns=["L", "L", "R", "R", "L"],
                    fonts=["Helvetica", "Helvetica-Bold", "Helvetica", "Helvetica", "Helvetica"],
                    colors=[GRAY, c, BLACK, BLACK, BLACK],
                    sizes=7.5,
                    rh=4.5*mm,
                    border=False,
                    padding=False
                )
                self.y -= 1*mm

    # ── Chart page (reusable) ──

    def page_chart(self, title, chart_path, caption=None):
        if not chart_path or not os.path.exists(chart_path): return
        self._new_page()
        self._header(title)

        try:
            img = ImageReader(chart_path)
            iw, ih = img.getSize()
            aspect = ih / iw
            tw = CONTENT_W
            th = tw * aspect
            if th > 110 * mm:
                th = 110 * mm
                tw = th / aspect

            ix = MARGIN_L + (CONTENT_W - tw) / 2
            iy = self.y - th - 2 * mm

            # Light border
            self.c.setStrokeColor(BORDER)
            self.c.setLineWidth(0.5)
            self.c.rect(ix - 1, iy - 1, tw + 2, th + 2, fill=0, stroke=1)
            self.c.drawImage(img, ix, iy, tw, th, preserveAspectRatio=True)
            self.y = iy - 5 * mm
        except Exception as e:
            log.warning(f"Chart embed fail: {e}")
            self._text("Gambar tidak tersedia.", color=LIGHT_GRAY)

        if caption:
            cc = _strip_html(caption)
            for line in cc.split("\n"):
                line = line.strip()
                if not line or "━" in line or "Disclaimer" in line: continue
                
                self._need(6 * mm)
                if "Setup" in line and (line.startswith("#") or "Day Trade" in line or "Swing" in line):
                    self.c.setFont("Helvetica-Bold", 10)
                    self.c.setFillColor(BLACK)
                    self.c.drawCentredString(MARGIN_L + CONTENT_W/2, self.y, line)
                    self.y -= SPACE_SM
                    active_mode = None
                # --- PERBAIKAN RENDER S&R UNTUK CHART ---
                elif line.startswith("Support") or line.startswith("Resist") or re.search(r'\[[wmd]\]', line):
                    # Update active mode
                    if "Support" in line: active_mode = "Support"
                    elif "Resist" in line: active_mode = "Resist"
                    
                    # Extract data row
                    sr_data_line = line
                    kv_match = re.match(r'^(Support|Resist)\s*:', sr_data_line, re.IGNORECASE)
                    if kv_match:
                        sr_data_line = sr_data_line[kv_match.end():].strip()
                    
                    if not sr_data_line: # Header only
                        continue

                    # Match for price and strength: [shorthand] price ... (str strength)
                    # Handle (str 215) or (str: 215)
                    sr_match = re.search(r'((?:\[[wmd]\]\s*)?)([0-9][0-9\.\,]*).*\(str[:\s]*([0-9\*]+)\)', sr_data_line, re.IGNORECASE)
                    
                    if sr_match:
                        tf_part, harga, strength = sr_match.groups()
                        tipe = active_mode or "Support"
                        c_mode = GREEN if tipe.lower() == "support" else RED
                        
                        rh_bg = 4.5 * mm
                        self._need(rh_bg + 1.5*mm)
                        self._table_row(
                            cols=[tipe, f"Rp {harga} {tf_part.strip()}", f"(str: {strength})"],
                            widths=[0.25, 0.4, 0.35],
                            aligns=["L", "L", "R"],
                            fonts=["Helvetica-Bold", "Helvetica-Bold", "Helvetica"],
                            colors=[c_mode, BLACK, GRAY],
                            sizes=8.5,
                            rh=rh_bg,
                            border=True,
                            padding=False
                        )
                        self.y -= 1.5 * mm
                    elif sr_data_line.lower() in ("support unknown", "resist ath/breakout"):
                        self._text(sr_data_line, size=8, color=GRAY)
                # ----------------------------------------
                elif ":" in line:
                    parts = line.split(":", 1)
                    self._row(parts[0].strip(), parts[1].strip())
                else:
                    self._text(line, size=8, color=GRAY)

    # ── Last Page: Disclaimer + Cara Membaca ──

    def page_disclaimer(self):
        self._new_page()

        # Title
        self.c.setFont("Helvetica-Bold", 14)
        self.c.setFillColor(BLACK)
        self.c.drawString(MARGIN_L, self.y, "Cara Membaca Report Ini")
        self.y -= 8 * mm

        guides = [
            ("Skor Fundamental", "Nilai 0-100 mengukur kesehatan keuangan secara keseluruhan. Di atas 65 = Baik, di bawah 40 = Kurang."),
            ("P/E (TTM)", "Rasio harga terhadap laba. Makin rendah biasanya makin murah. Bandingkan dengan rata-rata sektornya."),
            ("PBV", "Rasio harga terhadap nilai buku. Di bawah 1 berarti harga di bawah nilai aset bersih perusahaan."),
            ("ROE", "Kemampuan perusahaan menghasilkan laba dari modal sendiri. Di atas 15% dianggap baik."),
            ("DER", "Rasio utang terhadap modal. Di bawah 1 berarti utang lebih kecil dari modal sendiri."),
            ("Fair Value", "Estimasi harga wajar berdasarkan perhitungan Graham, PBV, dan PE. Margin of Safety positif berarti harga masih di bawah nilai wajar."),
            ("Smart Money", "Total nilai transaksi HAKA (beli agresif di harga offer). Menunjukkan minat beli kuat."),
            ("Bad Money", "Total nilai transaksi HAKI (jual agresif di harga bid). Menunjukkan tekanan jual."),
            ("Clean Money", "Selisih Smart Money dan Bad Money. Positif = buyer dominan, negatif = seller dominan."),
            ("Foreign Flow", "Arus dana asing. Net Buy = asing sedang beli. Net Sell = asing sedang jual."),
            ("Spoofing", "Perbandingan volume order book vs volume matched. Rasio tinggi (>10x) menandakan kemungkinan fake wall."),
            ("Bandarmologi", "Analisis aktivitas broker per timeframe. Akumulasi = broker besar sedang mengumpulkan saham secara diam-diam."),
            ("Insider & Major", "Pelacakan transaksi beli/jual saham oleh direksi, komisaris, atau institusi besar pengendali saham."),
            ("RSV", "Relative Strength Value (0-100). Menunjukkan posisi harga relatif terhadap range hari ini. >70 = di area atas."),
            ("Vol Ratio", "Perbandingan volume hari ini vs rata-rata 20 hari. Di atas 2x menandakan aktivitas tidak biasa."),
        ]

        for term, desc in guides:
            self._need(10 * mm)
            self.c.setFont("Helvetica-Bold", 8)
            self.c.setFillColor(BLACK)
            self.c.drawString(MARGIN_L + 3 * mm, self.y, term)
            self.y -= 3.5 * mm
            # Word-wrap description
            self.c.setFont("Helvetica", 7.5)
            self.c.setFillColor(GRAY)
            words = desc.split()
            line = ""
            for w in words:
                test = f"{line} {w}".strip()
                if self.c.stringWidth(test, "Helvetica", 7.5) > CONTENT_W - 10 * mm:
                    self.c.drawString(MARGIN_L + 6 * mm, self.y, line)
                    self.y -= 3 * mm
                    line = w
                else:
                    line = test
            if line:
                self.c.drawString(MARGIN_L + 6 * mm, self.y, line)
                self.y -= 3.5 * mm

        # Disclaimer section
        self._need(30 * mm)
        self.y -= 3 * mm
        self.c.setStrokeColor(BORDER)
        self.c.setLineWidth(0.5)
        self.c.line(MARGIN_L, self.y, W - MARGIN_R, self.y)
        self.y -= 5 * mm

        self.c.setFont("Helvetica-Bold", 10)
        self.c.setFillColor(BLACK)
        self.c.drawString(MARGIN_L, self.y, "⚠️ Disclaimer")
        self.y -= 5 * mm

        disclaimers = [
            "Laporan ini dibuat secara otomatis berdasarkan data publik dan bukan merupakan rekomendasi atau ajakan untuk membeli atau menjual saham.",
            "Segala keputusan investasi merupakan tanggung jawab penuh dari pengguna masing-masing.",
            "Data yang ditampilkan mungkin mengalami keterlambatan dan tidak menjamin akurasi 100%.",
            "Selalu lakukan riset mandiri (DYOR — Do Your Own Research) sebelum mengambil keputusan investasi.",
            "Kinerja masa lalu tidak menjamin kinerja di masa depan.",
        ]

        for d in disclaimers:
            self.c.setFont("Helvetica", 7.5)
            self.c.setFillColor(GRAY)
            words = d.split()
            line = ""
            for w in words:
                test = f"{line} {w}".strip()
                if self.c.stringWidth(test, "Helvetica", 7.5) > CONTENT_W - 6 * mm:
                    self.c.drawString(MARGIN_L + 3 * mm, self.y, line)
                    self.y -= 3 * mm
                    line = w
                else:
                    line = test
            if line:
                self.c.drawString(MARGIN_L + 3 * mm, self.y, line)
                self.y -= 4 * mm

    # ── Save ──

    def save(self):
        self.c.save()
        return self.path


# ── Main ──

async def generate_report(symbol, progress_callback=None):
    symbol = symbol.upper().strip()

    tasks = [
        get_info(symbol),
        get_keystats(symbol),
        get_profile(symbol),
        get_orderbook(symbol),
        get_historical_summary(symbol, 20),
        get_trade_book(symbol),
        get_trade_book_chart(symbol),
        get_broker_summary(symbol, days=1),
        analyze_bandar(symbol),
        analyze_fundachart(symbol, "PE", "3y"),
        get_daily_chart(symbol, 365),
        get_intraday_chart(symbol),
        get_insider_raw_data(symbol)
    ]
    
    if progress_callback:
        await progress_callback(f"<code>[██░░░░░░░░] 25%</code>\nMenganalisis Data Fundamental & Market...")
        
    # We gather everything at once for speed
    results = await asyncio.gather(*tasks, return_exceptions=True)

    if progress_callback:
        await progress_callback(f"<code>[█████░░░░░] 50%</code>\nMemproses Grafik & Algoritma Bandarmologi...")
        await asyncio.sleep(0.5)

    for i, res in enumerate(results):
        if isinstance(res, Exception):
            log.error(f"Task {i} in generate_report failed: {res}")

    info = results[0] if not isinstance(results[0], Exception) else None
    if not info:
        return None, f"Data untuk {symbol} tidak ditemukan."

    ks = results[1] if not isinstance(results[1], Exception) else None
    profile = results[2] if not isinstance(results[2], Exception) else None
    ob = results[3] if not isinstance(results[3], Exception) else None
    historical = results[4] if not isinstance(results[4], Exception) else None
    trade_book = results[5] if not isinstance(results[5], Exception) else None
    chart_data = results[6] if not isinstance(results[6], Exception) else None
    broker_data = results[7] if not isinstance(results[7], Exception) else None
    bandar_text = results[8] if not isinstance(results[8], Exception) else None
    fc_result = results[9] if not isinstance(results[9], Exception) else None
    swing_ohlcv = results[10] if not isinstance(results[10], Exception) else None
    dt_ohlcv = results[11] if not isinstance(results[11], Exception) else None
    insider_data = results[12] if not isinstance(results[12], Exception) else None

    fc_path, fc_caption = fc_result if fc_result else (None, None)

    swing_path, swing_caption = None, None
    if swing_ohlcv:
        try: 
            swing_path, swing_caption = analyze_swing(symbol, swing_ohlcv)
        except Exception as e:
            log.error(f"Gagal menganalisis swing untuk {symbol}: {e}")

    dt_path, dt_caption = None, None
    if dt_ohlcv:
        try: 
            dt_path, dt_caption = analyze_day_trade(symbol, dt_ohlcv)
        except Exception as e:
            log.error(f"Gagal menganalisis day trade untuk {symbol}: {e}")

    if progress_callback:
        await progress_callback(f"<code>[████████░░] 80%</code>\nMenyusun Dokumen PDF Report...")
        await asyncio.sleep(0.5)

    fa = calc_fundamental(info, ks, profile)
    pdf = PDFReport(symbol, fa.get("name", symbol))

    log.info(f"Generating PDF for {symbol}...")
    log.info(f"Data status: ob={bool(ob)}, bandar={bool(bandar_text)}, insider={bool(insider_data)}, fc={bool(fc_path)}, swing={bool(swing_path)}, dt={bool(dt_path)}")

    pdf.page_fundamental(fa)
    
    if ob: 
        log.info(f"Adding Smart Money page for {symbol}")
        pdf.page_smart_money(ob, historical, trade_book, chart_data, broker_data)
    else:
        log.warning(f"Skipping Smart Money page for {symbol} (ob is None/Empty)")

    if bandar_text: 
        log.info(f"Adding Bandarmology page for {symbol}")
        pdf.page_bandarmology(bandar_text)
    else:
        log.warning(f"Skipping Bandarmology page for {symbol} (bandar_text is None/Empty)")

    if insider_data: 
        log.info(f"Adding Insider page for {symbol}")
        pdf.page_insider(insider_data)
    else:
        log.warning(f"Skipping Insider page for {symbol} (insider_data is None/Empty)")

    if fc_path: 
        log.info(f"Adding Fundachart page for {symbol}")
        pdf.page_chart(f"PE VALUATION BAND — {symbol}", fc_path, fc_caption)
    
    if swing_path: 
        log.info(f"Adding Swing Trading page for {symbol}")
        pdf.page_chart(f"SWING TRADING — {symbol}", swing_path, swing_caption)
    
    if dt_path: 
        log.info(f"Adding Day Trade page for {symbol}")
        pdf.page_chart(f"DAY TRADE — {symbol}", dt_path, dt_caption)

    pdf.page_disclaimer()
    try:
        path = pdf.save()
        return path, None
    finally:
        for p in [fc_path, swing_path, dt_path]:
            if p and os.path.exists(p):
                try: 
                    os.remove(p)
                except Exception as e:
                    log.warning(f"Gagal menghapus temp file {p}: {e}")
