import html
import logging
import os
import json
import time
from telegram import Update
from telegram.ext import ContextTypes
import asyncio
import concurrent.futures

from api.client import _get, _safe_int, AuthError
from api.market import get_orderbook, get_running_trade, get_historical_summary, get_trade_book, get_trade_book_chart, get_market_detector
from api.broker import get_broker_summary
from api.chartbit import get_daily_chart, get_intraday_chart
from engines.smart_money import calc_money_flow_chart, calc_volume_ratio, calc_price_strength, calc_broker_summary, calc_rsv, calc_spoofing_index
from engines.foreign_flow import calc_foreign_accum
from engines.swing import analyze_swing
from engines.day_trade import analyze_day_trade
from engines.scanner import scan_market
from engines.filter_parser import parse_filter
from engines.sentiment import aggregate_sentiment
from api.fundamental import get_info, get_keystats, get_profile
from api.news import get_stock_news
from engines.fundamental import calc_fundamental
from engines.bandarmology import analyze_bandar
from bot.config import ALLOWED_CHAT_ID, ALLOWED_THREAD_ID, ADMIN_CHAT_ID
from api.auth import refresh_stockbit_token, get_last_refresh_time, set_bearer_token
from engines.insider import analyze_insider
from engines.fundachart import analyze_fundachart
from engines.dropdown import is_buy_signal, analyze_dropdown
from api.buzzer import fetch_ihsg_summary
from engines.ihsg import format_ihsg_report
from api.indopremier import fetch_global_indices
from engines.report import generate_report

log = logging.getLogger("bot")

# Cache to store recently generated reports
# Structure: { chat_id: { symbol: {"time": timestamp, "msg_id": doc_message_id} } }
REPORT_CACHE = {}


def _log_cmd(update: Update):
    """Log command details: who, where, what."""
    msg = update.message
    if not msg:
        return
    user = msg.from_user
    user_name = user.full_name if user else "?"
    user_handle = f"@{user.username}" if user and user.username else ""
    chat_title = msg.chat.title or "Private"
    chat_id = msg.chat_id
    thread = f" thread={msg.message_thread_id}" if msg.message_thread_id else ""
    cmd = msg.text or ""
    log.info(f"CMD: {cmd} | From: {user_name} {user_handle} | Chat: {chat_title} (id={chat_id}{thread})")


# --- MIDDLEWARE ---
async def is_allowed(update: Update, override_thread_id=None) -> bool:
    if not update.message:
        return False
        
    chat_id = str(update.message.chat_id)
    thread_id = str(update.message.message_thread_id) if update.message.message_thread_id else None
    user_id = str(update.effective_user.id) if update.effective_user else None
    
    # 0. Admin Bypass
    if user_id == str(ADMIN_CHAT_ID) or chat_id == str(ADMIN_CHAT_ID):
        return True
        
    # 0.5 Maintenance Mode Check
    from bot.admin import read_env_toggles
    toggles = read_env_toggles()
    if toggles.get("CMD_MAINTENANCE_MODE", False):
        log.warning(f"MAINTENANCE MODE BLOCKED: {user_id} in {chat_id}")
        try:
            msg = await update.message.reply_text("🛠️ <b>Mode Maintenance Aktif</b>\n\nBot sedang dalam perbaikan sementara atau API ScopeBit sedang gangguan.\nMohon bersabar dan coba lagi nanti.", parse_mode="HTML")
            
            # Auto-delete
            async def delete_maint_later(chat, user_msg_id, bot_msg_id):
                await asyncio.sleep(60)  # 1 menit
                try: await chat.bot.delete_message(chat_id=chat.id, message_id=user_msg_id)
                except: pass
                try: await chat.bot.delete_message(chat_id=chat.id, message_id=bot_msg_id)
                except: pass
            
            asyncio.create_task(delete_maint_later(update.message.chat, update.message.message_id, msg.message_id))
        except Exception:
            pass
        return False
    
    # 1. Check Chat ID (Strict Mode)
    if ALLOWED_CHAT_ID and chat_id != str(ALLOWED_CHAT_ID):
        log.warning(f"UNAUTHORIZED CHAT: {chat_id} (allowed: {ALLOWED_CHAT_ID})")
        try:
            await update.message.reply_text("Halo! Bot ini eksklusif untuk grup Telegram ScopeBit. Silakan bergabung untuk menggunakan bot secara gratis: https://t.me/ScopeBit/564", disable_web_page_preview=True)
        except Exception as e:
            log.warning(f"Failed to send unauthorized message: {e}")
        return False
        
    # 2. Check Thread ID (if specified)
    from bot.config import BOT_MODE
    
    target_thread = str(override_thread_id) if override_thread_id is not None else str(ALLOWED_THREAD_ID)
    
    if target_thread and target_thread != "None" and BOT_MODE != "debug":
        # thread_id might be None if used in General or an unthreaded group
        if thread_id != target_thread:
            log.warning(f"UNAUTHORIZED THREAD: {thread_id} in {chat_id} (allowed: {target_thread})")
            try:
                # Add a formal warning to use the correct topic
                warning_msg = await update.message.reply_text(f"Silakan menuju ke topik **[Bot]** untuk menggunakan layanan bot, atau akses melalui tautan berikut:\n [Gunakan Bot Di Sini](https://t.me/ScopeBit/{target_thread})", disable_web_page_preview=True)
                
                # Auto-delete both the warning and the user's command after 15 seconds
                async def delete_warning_later(chat, user_msg_id, bot_msg_id):
                    await asyncio.sleep(15)  # 15 seconds
                    try:
                        await chat.bot.delete_message(chat_id=chat.id, message_id=user_msg_id)
                    except Exception as e:
                        log.debug(f"Could not delete unauthorized user message: {e}")
                    try:
                        await chat.bot.delete_message(chat_id=chat.id, message_id=bot_msg_id)
                    except Exception as e:
                        log.debug(f"Could not delete bot warning message: {e}")
                        
                asyncio.create_task(delete_warning_later(update.message.chat, update.message.message_id, warning_msg.message_id))
            except Exception as e:
                log.warning(f"Failed to send/schedule unauthorized thread message: {e}")
            return False
            
    return True

# --- HELPERS ---
def _loading(label: str) -> str:
    """Return a progress bar loading message."""
    return f"<code>[████░░░░░░]</code> {label}"

def _fmt_val(val: float) -> str:
    abs_val = abs(val)
    sign = "+" if val >= 0 else "-"
    if abs_val >= 1_000_000_000_000: return f"{sign}{abs_val / 1_000_000_000_000:.2f}T"
    elif abs_val >= 1_000_000_000: return f"{sign}{abs_val / 1_000_000_000:.2f}M"
    elif abs_val >= 1_000_000: return f"{sign}{abs_val / 1_000_000:.1f}Jt"
    elif abs_val >= 1_000: return f"{sign}{abs_val / 1_000:.1f}Rb"
    else: return f"{sign}{abs_val:.0f}"

def _fmt_price(val) -> str:
    return f"{int(val):,}".replace(",", ".")

def _fmt_val_short(val: float) -> str:
    abs_val = abs(val)
    if abs_val >= 1_000_000_000_000: return f"{abs_val / 1_000_000_000_000:.1f}T"
    elif abs_val >= 1_000_000_000: return f"{abs_val / 1_000_000_000:.1f}M"
    elif abs_val >= 1_000_000: return f"{abs_val / 1_000_000:.0f}Jt"
    elif abs_val >= 1_000: return f"{abs_val / 1_000:.0f}Rb"
    else: return f"{abs_val:.0f}"

async def send_auto_delete_error(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, timeout: int = 10):
    """Sends a formal error message and auto-deletes after timeout."""
    try:
        if not text.startswith("["):
            text = f"[ERROR] {text}"
        err_msg = await update.message.reply_text(text, parse_mode="HTML")
        
        async def delete_later(chat, user_msg_id, bot_msg_id):
            await asyncio.sleep(timeout)
            try:
                await chat.bot.delete_message(chat_id=chat.id, message_id=user_msg_id)
            except Exception:
                pass
            try:
                await chat.bot.delete_message(chat_id=chat.id, message_id=bot_msg_id)
            except Exception:
                pass
                
        asyncio.create_task(delete_later(update.message.chat, update.message.message_id, err_msg.message_id))
    except Exception as e:
        log.warning(f"Failed to send auto-delete error: {e}")

def sanitize_symbol(text: str) -> str:
    """Cleans up user input by removing spaces and common suffixes like .JK or .IJ"""
    text = text.upper().strip().replace(" ", "")
    if text.endswith(".JK") or text.endswith(".IJ"):
        text = text[:-3]
    return text

def schedule_auto_delete(chat_id: int, user_msg_id: int, bot_msg_id: int, delete_at: int):
    """Saves message IDs to a JSON file for background deletion (works across bot restarts)."""
    file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'auto_delete.json')
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        data = []
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        data.append({
            "chat_id": chat_id,
            "user_msg_id": user_msg_id,
            "bot_msg_id": bot_msg_id,
            "delete_at": delete_at
        })
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"Failed to schedule auto-delete: {e}")

async def analyze_sm(symbol: str) -> str | None:
    symbol = sanitize_symbol(symbol)

    tasks = [
        get_orderbook(symbol),
        get_historical_summary(symbol, days=20),
        get_trade_book(symbol),
        get_trade_book_chart(symbol),
        get_broker_summary(symbol, days=1),
        get_info(symbol),
        get_market_detector(symbol)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)

    ob = results[0] if not isinstance(results[0], Exception) else None
    if not ob:
        return f"Data untuk <b>{symbol}</b> tidak ditemukan."

    historical = results[1] if not isinstance(results[1], Exception) else None
    trade_book = results[2] if not isinstance(results[2], Exception) else None
    chart_data = results[3] if not isinstance(results[3], Exception) else None
    broker_data = results[4] if not isinstance(results[4], Exception) else None
    info = results[5] if not isinstance(results[5], Exception) else None
    detector = results[6] if not isinstance(results[6], Exception) else None

    # Advanced Money Flow calculation
    mf = calc_money_flow_chart(chart_data, fallback_price=ob["last_price"])

    vol_ratio = calc_volume_ratio(ob["volume"], historical) if historical else 0.0
    foreign = calc_foreign_accum(historical) if historical else None
    price_levels = calc_price_strength(trade_book)
    brokers = calc_broker_summary(broker_data)

    price = ob["last_price"]
    pct = ob["change_pct"]
    sign = "+" if pct >= 0 else ""

    vol_flag = ""
    if vol_ratio >= 5: vol_flag = " [!]"
    elif vol_ratio >= 3: vol_flag = " [*]"

    L = "━" * 38
    o = []
    
    comp_name = html.escape(info.get("name", "?")) if info else "?"
    o.append(f"<b>SMART MONEY: {comp_name} ({symbol})</b>")
    if info:
        sub_sector = html.escape(info.get("sub_sector") if info.get("sub_sector") != "?" else info.get("sector", "-"))
        o.append(f"<code>Sector : {sub_sector}</code>")
    o.append(f"<code>{L}</code>")

    rsv = calc_rsv(price, ob.get("high", 0), ob.get("low", 0))

    o.append(f"<b>MARKET SUMMARY</b>")
    o.append("<code>"
             f"Price        : {_fmt_price(price):>10} ({sign}{pct:.2f}%)\n"
             f"Volume       : {(_fmt_val_short(ob['volume']) + ' lot'):>10}\n"
             f"Value        : {_fmt_val_short(ob['value']):>10}\n"
             f"Freq         : {str(ob['frequency']).replace(',', '.') + 'x':>10}\n"
             f"Vol x        : {f'{vol_ratio:.1f}x' + vol_flag:>10}\n"
             f"RSV          : {f'{rsv:.0f}':>10}"
             "</code>")
    o.append(f"<code>{L}</code>")

    if mf:
        sm = mf["smart_money"]
        bm = mf["bad_money"]
        cm = mf["clean_money"]
        total = abs(sm) + abs(bm) if (abs(sm) + abs(bm)) > 0 else 1
        pwr = abs(cm) / total * 100

        if cm > 0: status = "BUYER DOM"
        elif cm < 0: status = "SELLER DOM"
        else: status = "NEUTRAL"

        o.append(f"<b>MONEY FLOW ({mf['tx_count']} tx)</b>")
        o.append("<code>"
                 f"Smart Money  : {_fmt_val(sm):>10}\n"
                 f"Bad Money    : {_fmt_val(bm):>10}\n"
                 f"Clean Money  : {_fmt_val(cm):>10}\n"
                 f"Status       : {status:>10}\n"
                 f"Power Ratio  : {f'{pwr:.2f}%':>10}"
                 "</code>")
    else:
        o.append(f"<b>MONEY FLOW</b>")
        o.append("<code>No trade data</code>")

    o.append(f"<code>{L}</code>")
    
    # Spoofing Detection
    spoof_info = calc_spoofing_index(ob)
    if spoof_info:
        o.append(f"<b>MICROSTRUCTURE (SPOOFING)</b>")
        ratio = spoof_info['ratio']
        warning = ""
        if spoof_info['is_spoofing']:
            warning = " ⚠️ [FAKE WALL DETECTED]"
        
        o.append("<code>"
                 f"OB vs Match  : {f'{ratio:.1f}x':>10}{warning}\n"
                 f"OB Volume    : {_fmt_val_short(spoof_info['ob_vol']) + ' lot':>10}\n"
                 f"Match Volume : {_fmt_val_short(spoof_info['match_vol']) + ' lot':>10}"
                 "</code>")
        o.append(f"<code>{L}</code>")
    
    o.append(f"<b>FOREIGN FLOW</b>")
    fnet_today = ob["fnet"]
    fnet_label = "Net Buy" if fnet_today >= 0 else "Net Sell"
    lines = f"Today        : {_fmt_val(fnet_today):>10} ({fnet_label})"
    if foreign:
        acc = foreign["accum_net"]
        acc_label = "Akum" if acc >= 0 else "Dist"
        lines += f"\nAcc {foreign['days']:>2}D      : {_fmt_val(acc):>10} ({acc_label})"
    o.append(f"<code>{lines}</code>")

    if price_levels:
        o.append(f"<code>{L}</code>")
        o.append("<b>PRICE STRENGTH (Top 3)</b>")
        pl_lines = []
        for p in price_levels:
            net_val = p["net"]
            b_str = f"{p['buy_lot']:,}".replace(",", ".")
            s_str = f"{p['sell_lot']:,}".replace(",", ".")
            n_str = f"{net_val:+,}".replace(",", ".")
            pl_lines.append(
                f"{_fmt_price(p['price']):>6} | B:{b_str:>10} S:{s_str:>10} | Net:{n_str}"
            )
        o.append("<code>" + "\n".join(pl_lines) + "</code>")

    if brokers["top_buyers"] or brokers["top_sellers"]:
        o.append(f"<code>{L}</code>")
        o.append("<b>TOP BROKERS</b>")
        bl = []
        if brokers["top_buyers"]:
            buy_str = " | ".join(f"{b['code']}:{_fmt_val_short(b['val'])}" for b in brokers["top_buyers"])
            bl.append(f"Buy          : {buy_str}")
        if brokers["top_sellers"]:
            sell_str = " | ".join(f"{s['code']}:{_fmt_val_short(s['val'])}" for s in brokers["top_sellers"])
            bl.append(f"Sell         : {sell_str}")
        o.append("<code>" + "\n".join(bl) + "</code>")

    o.append(f"<code>{L}</code>")
    return "\n".join(o)


async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catch-all debugger to see every incoming update."""
    if not update.message:
        return
    
    msg = update.message
    chat = msg.chat
    user = msg.from_user
    
    text = msg.text or "[Non-text message]"
    user_info = f"{user.full_name} (@{user.username})" if user and user.username else (user.full_name if user else "Unknown")
    
    # LOG TO CLI
    log.info(f"DEBUG RECV | Chat: {chat.title} ({chat.type}, id={chat.id}) | From: {user_info} | Text: {text}")

# --- TELEGRAM HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    o = ["<b>SmartMoney & Bandarmology Bot</b>\n"]
    
    o.append("<b>Analysis Commands:</b>")
    from bot.admin import read_env_toggles
    _s = read_env_toggles()
    if _s.get("CMD_SM_ENABLED", True): o.append("<code>/sm [KODE]</code> - Smart Money Flow")
    if _s.get("CMD_BR_ENABLED", True): o.append("<code>/br [KODE]</code> - Broker Accumulation")
    if _s.get("CMD_FA_ENABLED", True): o.append("<code>/fa [KODE]</code> - Fundamental Analysis")
    if _s.get("CMD_IM_ENABLED", True): o.append("<code>/im [KODE]</code> - Insider & Major Tracker")
    if _s.get("CMD_FC_ENABLED", True): o.append("<code>/fc [KODE]</code> - Fundachart Growth Trend")
    if _s.get("CMD_SW_ENABLED", True): o.append("<code>/sw [KODE]</code> - Swing Trade Plan + Chart")
    if _s.get("CMD_DT_ENABLED", True): o.append("<code>/dt [KODE]</code> - Day Trade Plan + Chart")

    o.append("\n<b>Market Scanners:</b>")
    if _s.get("CMD_REPORT_ENABLED", True): o.append("<code>/report [KODE]</code> - PDF Deep-Dive Report")
    
    o.append("\n<i>Gunakan kapital untuk kode saham (misal: BBCA).</i>")
    o.append("<i>Ketik /help untuk panduan lengkap.</i>")
    
    await update.message.reply_text("\n".join(o), parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    L = "━" * 38
    o = []
    o.append("<b>PANDUAN LENGKAP SCOPEBIT</b>")
    o.append(f"<code>{L}</code>")

    o.append("<b>1. FITUR YANG TERSEDIA</b>")
    cmds = []
    from bot.admin import read_env_toggles
    _t = read_env_toggles()
    if _t.get("CMD_SM_ENABLED", True): cmds.append("/sm [KODE]  Smart Money Analysis")
    if _t.get("CMD_FA_ENABLED", True): cmds.append("/fa [KODE]  Fundamental Analysis")
    if _t.get("CMD_IM_ENABLED", True): cmds.append("/im [KODE]  Insider & Major Tracker")
    if _t.get("CMD_FC_ENABLED", True): cmds.append("/fc [KODE]  Fundachart Growth Trend")
    if _t.get("CMD_BR_ENABLED", True): cmds.append("/br [KODE]  Bandarmology (Stealth)")
    if _t.get("CMD_SW_ENABLED", True): cmds.append("/sw [KODE]  Swing Trade Setup")
    if _t.get("CMD_DT_ENABLED", True): cmds.append("/dt [KODE]  Day Trade Setup")
    if _t.get("CMD_REPORT_ENABLED", True): cmds.append("/report [KODE] PDF Deep Report")
    
    if cmds:
        o.append("<code>" + "\n".join(cmds) + "</code>")
    else:
        o.append("<code>Tidak ada fitur yang aktif.</code>")
    o.append(f"<code>{L}</code>")

    o.append("<b>2. APA YANG DIANALISIS</b>")
    desc = []
    if _t.get("CMD_SM_ENABLED", True):
        desc.append(
            "/sm - Money Flow\n"
            "  Menghitung aliran uang Smart Money\n"
            "  (institusi) vs Bad Money (retail).\n"
            "  Menggunakan threshold dinamis\n"
            "  berdasarkan volume transaksi.\n"
            "  Metrik: Clean Money, RSV, Spoofing.\n"
        )
    if _t.get("CMD_FA_ENABLED", True):
        desc.append(
            "/fa - Fundamental\n"
            "  Valuasi (PE, PBV, PEG, EV/EBITDA),\n"
            "  Fair Value (Graham + PBV + PE avg),\n"
            "  Margin of Safety, profitabilitas,\n"
            "  kesehatan keuangan (DER, F-Score,\n"
            "  Altman Z), dividen, pemegang saham,\n"
            "  dan jumlah investor (trend).\n"
        )
    if _t.get("CMD_BR_ENABLED", True):
        desc.append(
            "/br - Bandarmology\n"
            "  Tracking broker akumulasi/distribusi\n"
            "  di 4 timeframe (1D, 5D, 2W, 1M).\n"
            "  Mendeteksi Stealth Mode (broker\n"
            "  konsisten beli/jual lintas waktu).\n"
            "  Analisis Retail vs Asing Flow.\n"
        )
    if _t.get("CMD_IM_ENABLED", True):
        desc.append(
            "/im - Insider & Major\n"
            "  Track pergerakan pembelian dan\n"
            "  penjualan saham oleh Direksi,\n"
            "  Komisaris, atau institusi besar.\n"
        )
    if _t.get("CMD_SW_ENABLED", True):
        desc.append(
            "/sw - Swing Trade\n"
            "  Analisis teknikal berbasis Fractal\n"
            "  S/R, Hurst Exponent, regime market.\n"
            "  Menghasilkan Buy Area, TP, SL\n"
            "  dengan Risk:Reward ratio.\n"
        )
    if _t.get("CMD_DT_ENABLED", True):
        desc.append(
            "/dt - Day Trade\n"
            "  Sama seperti Swing tapi timeframe\n"
            "  intraday (candle 5 menit). Cocok\n"
            "  untuk transaksi harian."
        )
    if _t.get("CMD_FC_ENABLED", True):
        desc.append(
            "/fc - Fundachart\n"
            "  Grafik pertumbuhan historis PE,\n"
            "  PBV, Profit, ROE, dsb.\n"
            "  Format: /fc [KODE] [TEMPLATE]\n"
            "  Contoh: /fc BMRI ROE\n"
        )
    if _t.get("CMD_REPORT_ENABLED", True):
        desc.append(
            "/report - PDF Report\n"
            "  Generate PDF Deep-Dive Report yang\n"
            "  menggabungkan 7 engine analisis\n"
            "  dalam satu dokumen ringkas.\n"
        )
        
    if desc:
        o.append("<code>" + "\n".join(desc).strip() + "</code>")
    o.append(f"<code>{L}</code>")

    o.append("<b>3. CARA MEMBACA OUTPUT</b>")
    o.append("<code>"
             "SMART MONEY:\n"
             "  Clean Money (+) = Whale beli bersih\n"
             "  Clean Money (-) = Whale jual bersih\n"
             "  RSV tinggi = volume signifikan\n"
             "\n"
             "FUNDAMENTAL:\n"
             "  Score 0-100 = skor keseluruhan\n"
             "  MoS (+) = harga DIBAWAH fair value\n"
             "  MoS (-) = harga DIATAS fair value\n"
             "  Grade: Sangat Murah > Wajar > Mahal\n"
             "\n"
             "BANDARMOLOGY:\n"
             "  [A] = Broker Asing (Foreign)\n"
             "  [R] = Broker Retail (Lokal)\n"
             "  [G] = Broker Pemerintah\n"
             "  ACC = Akumulasi, DIST = Distribusi\n"
             "  STEALTH = broker konsisten beli/jual\n"
             "\n"
             "TRADING PLAN (SW/DT):\n"
             "  Buy Area = zona beli optimal\n"
             "  SL = batas kerugian maksimal\n"
             "  TP = target profit (RR 1:2, 1:3)\n"
             "  RR = Risk to Reward ratio"
             "</code>")
    o.append(f"<code>{L}</code>")

    o.append("<b>4. PERINGATAN DAN RISIKO</b>")
    o.append("<code>"
             "[!] Data bersifat INFORMATIF, bukan\n"
             "    ajakan untuk membeli atau menjual.\n"
             "\n"
             "[!] Fair Value adalah ESTIMASI dari\n"
             "    model matematis, bukan harga pasti.\n"
             "    Bisa meleset karena asumsi growth\n"
             "    dan retention rate.\n"
             "\n"
             "[!] Stealth Mode mendeteksi POLA, tapi\n"
             "    broker bisa berubah arah kapan saja.\n"
             "\n"
             "[!] Smart Money bukan jaminan profit.\n"
             "    Whale bisa salah atau manipulasi.\n"
             "\n"
             "[!] Selalu gunakan Stop Loss. Jangan\n"
             "    pernah all-in di satu saham.\n"
             "\n"
             "[!] Lakukan riset mandiri (DYOR) dan\n"
             "    pertimbangkan risk management."
             "</code>")
    o.append(f"<code>{L}</code>")

    o.append("<b>5. TIPS PENGGUNAAN</b>")
    o.append("<code>"
             "1. Cek /fa dulu untuk valuasi awal.\n"
             "2. Konfirmasi dengan /br atau /sm\n"
             "   apakah ada akumulasi.\n"
             "3. Gunakan /fc untuk lihat trend\n"
             "   pertumbuhan jangka panjang.\n"
             "4. Entry dengan /sw atau /dt.\n"
             "5. Cetak /report untuk analisa Lengkap."
             "</code>")
    o.append(f"<code>{L}</code>")
    o.append("<i>ScopeBit - Your Trading Intelligence</i>")

    await update.message.reply_text("\n".join(o), parse_mode="HTML")


async def sm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if not context.args:
        await send_auto_delete_error(update, context, "⚠️ Gunakan format: <code>/sm [KODE SAHAM]</code>\nContoh: <code>/sm BBCA</code>")
        return

    symbol = sanitize_symbol(context.args[0])

    progress_msg = await update.message.reply_text(_loading(f"Analisis Smart Money <b>{symbol}</b>"), parse_mode="HTML")

    try:
        # Run analysis 
        result = await analyze_sm(symbol)
        
        if result:
            result += "\n\n<i>💬 Pesan ini akan otomatis dihapus dalam 48 jam.</i>"
            await progress_msg.edit_text(result, parse_mode="HTML")
            delete_at = int(time.time()) + (48 * 3600)
            schedule_auto_delete(update.message.chat_id, update.message.message_id, progress_msg.message_id, delete_at)
        else:
            await progress_msg.edit_text(f"Gagal menganalisis <b>{symbol}</b>. Coba lagi nanti.", parse_mode="HTML")
    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat 💤", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(f"Error menganalisis <b>{symbol}</b>.\n<code>{error_msg}</code>", parse_mode="HTML")


async def analyze_fa(symbol: str) -> str | None:
    symbol = symbol.upper().strip()

    tasks = [
        get_info(symbol),
        get_keystats(symbol),
        get_profile(symbol),
        get_stock_news(symbol, 5)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)

    info = results[0] if not isinstance(results[0], Exception) else None
    if not info:
        return f"Data untuk <b>{symbol}</b> tidak ditemukan."

    ks = results[1] if not isinstance(results[1], Exception) else None
    profile = results[2] if not isinstance(results[2], Exception) else None
    news_items = results[3] if not isinstance(results[3], Exception) else None

    f = calc_fundamental(info, ks, profile)
    g = f.get("grades", {})
    L = "━" * 38
    o = []

    comp_name = html.escape(f['name'])
    sub_sector = html.escape(f['sub_sector'] if f['sub_sector'] != '?' else f['sector'])
    o.append(f"<b>FUNDAMENTAL: {comp_name} ({symbol})</b>")
    o.append(f"<code>Sector : {sub_sector}</code>")

    # Rapor Emiten (Scoring System)
    score = f.get("overall_score", 0)
    label = f.get("overall_label", "-")
    grade = f.get("overall_grade", "-")
    
    pillars = f.get("pillar_grades", {})
    val_g = pillars.get("valuation", {}).get("grade", "-")
    val_l = pillars.get("valuation", {}).get("label", "-")
    prof_g = pillars.get("profitability", {}).get("grade", "-")
    prof_l = pillars.get("profitability", {}).get("label", "-")
    solv_g = pillars.get("solvency", {}).get("grade", "-")
    solv_l = pillars.get("solvency", {}).get("label", "-")

    o.append(f"<b>RAPOR EMITEN</b>")
    o.append(f"<code>"
             f"Skor Total     : {score}/100 [{grade}] {label}\n"
             f"--------------------------------------\n"
             f"Valuasi        : Grade {val_g} ({val_l})\n"
             f"Profitabilitas : Grade {prof_g} ({prof_l})\n"
             f"Kesehatan      : Grade {solv_g} ({solv_l})"
             f"</code>")
    o.append(f"<code>{L}</code>")

    def _v(key):
        return html.escape(str(f.get(key, '-')))

    def _g(key):
        lbl, sc = g.get(key, ("-", 0))
        return lbl

    # VALUATION
    o.append(f"<b>VALUATION (Grade {val_g})</b>")
    o.append("<code>"
             f"Price        : {_fmt_price(f['price']):>10}\n"
             f"Market Cap   : {_v('market_cap'):>10}\n"
             f"Ent. Value   : {_v('enterprise_value'):>10}\n"
             f"Share Out.   : {_v('share_outstanding'):>10}\n"
             f"Free Float   : {_v('free_float'):>10}\n"
             f"P/E (TTM)    : {_v('pe_ttm'):>10}  {_g('pe')}\n"
             f"P/E Forward  : {_v('pe_forward'):>10}\n"
             f"PBV          : {_v('pbv'):>10}  {_g('pbv')}\n"
             f"PEG          : {_v('peg'):>10}  {_g('peg')}\n"
             f"EV/EBITDA    : {_v('ev_ebitda'):>10}\n"
             f"Earn Yield   : {_v('earnings_yield'):>10}"
             "</code>")
    o.append(f"<code>{L}</code>")

    # FAIR VALUE
    fair = f.get("fair_value")
    mos = f.get("margin_of_safety")
    methods = f.get("fair_methods", [])
    if fair and fair > 0:
        o.append("<b>FAIR VALUE ESTIMATION</b>")
        fv_lines = []
        for mname, val in methods:
            fv_lines.append(f"{mname:<12} : Rp {_fmt_price(val):>10}")
        fv_lines.append(f"{'─' * 30}")
        fv_lines.append(f"{'Rata-rata':<12} : Rp {_fmt_price(fair):>10}")
        price_num = int(str(f.get('price', '0')).replace(',', '').replace('.', '') or 0)
        if price_num > 0:
            fv_lines.append(f"{'Harga Now':<12} : Rp {_fmt_price(price_num):>10}")
        if mos is not None:
            if mos > 15:
                mos_label = "UNDERVALUED"
            elif mos > 0:
                mos_label = "SEDIKIT MURAH"
            elif mos > -15:
                mos_label = "SEDIKIT MAHAL"
            else:
                mos_label = "OVERVALUED"
            fv_lines.append(f"{'MoS':<12} : {mos:+.1f}% ({mos_label})")
        o.append("<code>" + "\n".join(fv_lines) + "</code>")
        o.append(f"<code>{L}</code>")

    # PROFITABILITY
    o.append(f"<b>PROFITABILITY (Grade {prof_g})</b>")
    o.append("<code>"
             f"GPM          : {_v('gpm'):>10}\n"
             f"OPM          : {_v('opm'):>10}\n"
             f"NPM          : {_v('npm'):>10}  {_g('npm')}\n"
             f"ROA          : {_v('roa'):>10}  {_g('roa')}\n"
             f"ROE          : {_v('roe'):>10}  {_g('roe')}\n"
             f"ROCE         : {_v('roce'):>10}\n"
             f"ROIC         : {_v('roic'):>10}\n"
             f"Asset Turn.  : {_v('asset_turnover'):>10}"
             "</code>")
    o.append(f"<code>{L}</code>")

    # SOLVENCY
    o.append(f"<b>SOLVENCY (Grade {solv_g})</b>")
    o.append("<code>"
             f"DER          : {_v('der'):>10}x  {_g('der')}\n"
             f"Liab/Equity  : {_v('liab_equity'):>10}x\n"
             f"Int. Covg.   : {_v('icr'):>10}x\n"
             f"Fin Leverage : {_v('fin_leverage'):>10}x\n"
             f"F-Score      : {_v('f_score'):>10}   {_g('f_score')}\n"
             f"Altman Z     : {_v('altman_z'):>10}"
             "</code>")
    o.append(f"<code>{L}</code>")

    # PER SHARE DATA
    o.append("<b>PER SHARE</b>")
    o.append("<code>"
             f"EPS (TTM)    : {_v('eps'):>10}\n"
             f"BVPS         : {_v('bvps'):>10}\n"
             f"FCF/Share    : {_v('fcfps'):>10}\n"
             f"Cash/Share   : {_v('cashps'):>10}"
             "</code>")
    o.append(f"<code>{L}</code>")

    # DIVIDEND
    o.append("<b>DIVIDEND</b>")
    o.append("<code>"
             f"Div Yield    : {_v('div_yield'):>10}  {_g('div_yield')}\n"
             f"Payout Ratio : {_v('div_payout'):>10}"
             "</code>")
    o.append(f"<code>{L}</code>")

    # OWNERSHIP Data intentionally suppressed to avoid duplication with Trends block


    # NUMBER OF SHAREHOLDERS (trend)
    prof = f.get("profile", {})
    sn_list = prof.get("shareholder_numbers", [])
    if sn_list:
        o.append("<b>JUMLAH PEMEGANG SAHAM</b>")
        sn_lines = []
        for sn in sn_list:
            date = sn.get("date", "-")
            total = sn.get("total", "-")
            chg = sn.get("change", 0)
            chg_fmt = sn.get("change_fmt", "")
            arrow = "+" if chg > 0 else ("-" if chg < 0 else " ")
            sn_lines.append(f"{date:<14} : {total:>6}  {chg_fmt}")
        o.append("<code>" + "\n".join(sn_lines) + "</code>")
        # Trend analysis
        if len(sn_list) >= 2:
            latest = sn_list[0].get("change", 0)
            if latest > 0:
                o.append("<code>Trend: Pemegang saham BERTAMBAH</code>")
            elif latest < 0:
                o.append("<code>Trend: Pemegang saham BERKURANG</code>")
            else:
                o.append("<code>Trend: Stabil</code>")
        o.append(f"<code>{L}</code>")

    # NEWS SENTIMENT
    if news_items:
        titles = [n["title"] for n in news_items]
        sentiment = aggregate_sentiment(titles)
        o.append("<b>SENTIMENT (NEWS)</b>")
        o.append("<code>"
                 f"Score        : {sentiment['total_score']} ({sentiment['label']})\n"
                 f"Bullish      : {sentiment['bullish_articles']} berita\n"
                 f"Bearish      : {sentiment['bearish_articles']} berita"
                 "</code>")

        o.append("<b>Headlines:</b>")
        for item in news_items[:3]:
            title = html.escape(item['title'])
            o.append(f"<a href='{item['link']}'>{title}</a>")

        o.append(f"<code>{L}</code>")

    o.append("<i>⚠️ Disclaimer: Bukan ajakan jual/beli.</i>")
    return "\n".join(o)
async def cmd_rcm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /rcm command (Recap Clean Money)."""
    if not await is_allowed(update):
        return

    chat_id = update.effective_chat.id
    args = context.args

    mover_type = "gainer"
    if args:
        mover_type = args[0].lower()

    valid_types = ["gainer", "loser", "val", "vol", "freq", "fbuy", "fsell"]
    if mover_type not in valid_types:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Tipe mover tidak valid.\nPilih: {', '.join(valid_types)}",
            reply_to_message_id=update.effective_message.message_id
        )
        return

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔄 Menyusun Recap Clean Money ({mover_type.upper()})...\nMohon tunggu...",
        reply_to_message_id=update.effective_message.message_id
    )

    try:
        data = await get_clean_money_recap(mover_type, limit=20)
        if not data:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg.message_id,
                text=f"⚠️ Gagal mendapatkan data untuk {mover_type.upper()}."
            )
            return

        L = "━" * 63
        o = []
        o.append(f"<b>RECAP CLEAN MONEY: {mover_type.upper()}</b>")
        o.append(f"<code>{L}</code>")
        o.append("<code> No |  Tx |Name|  Gain%|   Value|Smart M.| Bad M. |Clean M.|🚦|RSV </code>")
        o.append(f"<code>{L}</code>")

        for i, row in enumerate(data):
            # Format frequency -> 12K, 3M, etc.
            tx_raw = row["freq"]
            if tx_raw >= 1_000_000: tx_str = f"{tx_raw/1_000_000:.1f}x"
            elif tx_raw >= 1_000: tx_str = f"{tx_raw/1_000:.0f}K"
            else: tx_str = f"{tx_raw}x"
            
            # Format percent
            pct_val = row["gain_pct"]
            pct_str = f"{pct_val:+.2f}%" if pct_val != 0 else "0.00%"
            
            # Formats values strictly to short millions/billions
            val_str = _fmt_val_short(row["val"]).replace("Jt", "M").replace("Rb", "K").replace("M", "B") # Enforcing english short-types for narrow table
            sm_str = _fmt_val_short(row["smart"]).replace("Jt", "M").replace("Rb", "K").replace("M", "B")
            bm_str = _fmt_val_short(row["bad"]).replace("Jt", "M").replace("Rb", "K").replace("M", "B")
            cm_str = _fmt_val_short(row["clean"]).replace("Jt", "M").replace("Rb", "K").replace("M", "B")
            
            # Convert formatting to pure numbers
            # example logic: User table uses 108.68M or 1.25B
            def short_pure(v):
                abs_v = abs(v)
                if abs_v >= 1_000_000_000_000: return f"{v/1_000_000_000_000:+.2f}T"
                elif abs_v >= 1_000_000_000: return f"{v/1_000_000_000:+.1f}B"
                elif abs_v >= 1_000_000: return f"{v/1_000_000:+.1f}M"
                elif abs_v >= 1000: return f"{v/1000:+.0f}K"
                return f"{v:+.0f}"

            val_s = short_pure(row['val']).replace('+', '')
            sm_s = short_pure(row['smart']).replace('+', '')
            bm_s = short_pure(row['bad'])
            cm_s = short_pure(row['clean']).replace('+', '')
            
            # Indicator
            ind = "🟢" if row["clean"] > 0 else "🔴"
            
            line = f"{i+1:>3} {tx_str:>4} {row['code']:<4} {pct_str:>6} {val_s:>8} {sm_s:>8} {bm_s:>8} {cm_s:>8} {ind} {row['rsv']:>3}"
            o.append(f"<code>{line}</code>")
            
        o.append(f"<code>{L}</code>")
        final_text = "\n".join(o)
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=final_text,
            parse_mode="HTML"
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.message_id,
            text=f"⚠️ Terjadi kesalahan: {str(e)}"
        )




async def fa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if not context.args:
        await send_auto_delete_error(update, context, "⚠️ Gunakan format: <code>/fa [KODE SAHAM]</code>\nContoh: <code>/fa BBCA</code>")
        return

    symbol = sanitize_symbol(context.args[0])

    progress_msg = await update.message.reply_text(_loading(f"Analisis Fundamental <b>{symbol}</b>"), parse_mode="HTML")

    try:
        # Run analysis
        result = await analyze_fa(symbol) # Changed to call analyze_fa
        
        if result:
            result += "\n\n<i>💬 Pesan ini akan otomatis dihapus dalam 48 jam.</i>"
            await progress_msg.edit_text(result, parse_mode="HTML")
            delete_at = int(time.time()) + (48 * 3600)
            schedule_auto_delete(update.message.chat_id, update.message.message_id, progress_msg.message_id, delete_at)
        else:
            await progress_msg.edit_text(f"Gagal memproses data fundamental <b>{symbol}</b>.", parse_mode="HTML")
    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat 💤", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(f"Error analisis Fundamental <b>{symbol}</b>.\n<code>{error_msg}</code>", parse_mode="HTML")


async def im_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if not context.args:
        await send_auto_delete_error(update, context, "⚠️ Gunakan format: <code>/im [KODE SAHAM]</code>\nContoh: <code>/im BUMI</code>")
        return

    symbol = sanitize_symbol(context.args[0])

    progress_msg = await update.message.reply_text(_loading(f"Analisis Insider <b>{symbol}</b>"), parse_mode="HTML")

    try:
        # Run analysis
        result = await analyze_insider(symbol)
        
        if result:
            result += "\n\n<i>💬 Pesan ini akan otomatis dihapus dalam 48 jam.</i>"
            await progress_msg.edit_text(result, parse_mode="HTML")
            delete_at = int(time.time()) + (48 * 3600)
            schedule_auto_delete(update.message.chat_id, update.message.message_id, progress_msg.message_id, delete_at)
        else:
            await progress_msg.edit_text(f"Gagal mengambil data insider untuk <b>{symbol}</b>.", parse_mode="HTML")
    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat 💤", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(f"Error analisis Insider <b>{symbol}</b>.\n<code>{error_msg}</code>", parse_mode="HTML")


# ──────────────────────────────────────────────
# /fc Command (Fundachart)
# ──────────────────────────────────────────────────────

async def fc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if len(context.args) < 2:
        await send_auto_delete_error(update, context, 
            "⚠️ Gunakan format: <code>/fc [KODE] [RASIO] [OPT: TIMEFRAME]</code>\n"
            "   List Rasio   : PE, PBV, ROE, ROA, DER, NPM\n"
            "List Timeframe: 1y, 3y, 5y, 10y\n"
            "Contoh: <code>/fc PTBA PE 3y</code>"
        )
        return

    symbol = sanitize_symbol(context.args[0])
    template_key = context.args[1].upper() if len(context.args) > 1 else "PE"

    progress_msg = await update.message.reply_text(_loading(f"Analisis Fundachart <b>{symbol}</b>"), parse_mode="HTML")

    try:
        chart_path, caption = await analyze_fundachart(symbol, template_key)
        
        if chart_path and os.path.exists(chart_path):
            caption += "\n\n<i>💬 Pesan ini akan otomatis dihapus dalam 48 jam.</i>"
            with open(chart_path, "rb") as photo:
                sent_photo = await update.message.reply_photo(photo=photo, caption=caption, parse_mode="HTML")
            await progress_msg.delete()
            
            delete_at = int(time.time()) + (48 * 3600)
            schedule_auto_delete(update.message.chat_id, update.message.message_id, sent_photo.message_id, delete_at)

            try:
                os.remove(chart_path)
            except OSError:
                pass
        else:
            await progress_msg.edit_text(caption or f"Gagal mengambil data Fundachart <b>{symbol}</b>.", parse_mode="HTML")
            
    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat 💤", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(f"Error Fundachart <b>{symbol}</b>.\n<code>{error_msg}</code>", parse_mode="HTML")


# ─── IHSG / MACRO ─────────────────────────────────────────────

async def ihsg_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /ihsg command (IHSG Sentiment & Macro Radar)."""
    if not await is_allowed(update):
        return
    
    _log_cmd(update)
    msg = await update.message.reply_text(_loading("Memproses Sentiment Engine & Macro..."), parse_mode="HTML")
    
    try:
        import pytz
        from datetime import datetime
        import asyncio
        smode = "full" if datetime.now(pytz.timezone("Asia/Jakarta")).hour >= 12 else "morning"
        
        # Concurrently fetch sentiment and live index numbers
        data_task = asyncio.create_task(fetch_ihsg_summary(days_back=1, source_mode=smode))
        idx_task = asyncio.create_task(fetch_global_indices())
        
        data, indices = await asyncio.gather(data_task, idx_task)
        
        report_str, img_path = format_ihsg_report(data, indices)
        
        await msg.delete()
        if img_path:
            with open(img_path, 'rb') as f:
                await update.message.reply_photo(photo=f)
        await update.message.reply_text(report_str, parse_mode="HTML", disable_web_page_preview=True)
            
    except Exception as e:
        log.error(f"/ihsg error: {e}")
        try:
            await msg.edit_text(f"SYSTEM FAILURE:\n<code>{e}</code>", parse_mode="HTML")
        except Exception:
            await update.message.reply_text(f"SYSTEM FAILURE:\n<code>{e}</code>", parse_mode="HTML")

# ─── TICKER NEWS ──────────────────────────────────────────────

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /news [TICKER] command (Stock-specific sentiment & news)."""
    from bot.config import NEWS_THREAD_ID
    
    if not await is_allowed(update, override_thread_id=NEWS_THREAD_ID):
        return
        
    if not context.args:
        await send_auto_delete_error(update, context, "Format: <code>/news [KODE SAHAM]</code>\nContoh: <code>/news BBCA</code>")
        return

    symbol = sanitize_symbol(context.args[0])
    _log_cmd(update)
    msg = await update.message.reply_text(_loading(f"Menganalisis sentimen media untuk {symbol}..."), parse_mode="HTML")

    try:
        from api.buzzer import fetch_stock_news
        from engines.ticker_news import format_ticker_news_report
        import time
        
        data = await fetch_stock_news(symbol, days_back=7)
        report_str = format_ticker_news_report(data)
        
        result_msg = await msg.edit_text(report_str, parse_mode="HTML", disable_web_page_preview=True)
        
        # Schedule auto-delete in 12 hours (43200 seconds)
        delete_at = int(time.time()) + (12 * 60 * 60)
        schedule_auto_delete(
            chat_id=update.message.chat_id,
            user_msg_id=update.message.message_id,
            bot_msg_id=result_msg.message_id,
            delete_at=delete_at
        )
        
    except Exception as e:
        log.error(f"/news {symbol} error: {e}")
        try:
            await msg.edit_text(f"❌ <b>Sistem Gagal:</b>\n<code>{e}</code>", parse_mode="HTML")
        except Exception:
            pass

# ──────────────────────────────────────────────
# /report Command (PDF Deep-Dive Report)
# ──────────────────────────────────────────────


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if not context.args:
        await send_auto_delete_error(update, context, "⚠️ Gunakan format: <code>/report [KODE SAHAM]</code>\nContoh: <code>/report BBCA</code>")
        return

    symbol = sanitize_symbol(context.args[0])

    chat_id = update.message.chat_id
    now = time.time()
    
    if chat_id not in REPORT_CACHE:
        REPORT_CACHE[chat_id] = {}
        
    cached_data = REPORT_CACHE[chat_id].get(symbol)
    if cached_data and (now - cached_data["time"]) < 2 * 3600:
        old_msg_id = cached_data["msg_id"]
        user_mention = update.message.from_user.mention_html()
        reply_text = f"Halo {user_mention}, report untuk <b>{symbol}</b> sudah ditarik sebelumnya nih 👆\n\n<i>Silakan cek dokumen di atas yaa. Request ulang untuk emiten yang sama bisa dilakukan setelah 2 jam.</i>"
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=reply_text,
                reply_to_message_id=old_msg_id,
                parse_mode="HTML"
            )
            return
        except Exception as e:
            log.warning(f"Failed to quote cached report: {e}")
            # Continue to generate new report if old message is deleted

    progress_msg = await update.message.reply_text(
        _loading(f"Mempersiapkan PDF Report <b>{symbol}</b>..."),
        parse_mode="HTML"
    )

    async def _update_progress(text):
        try:
            await progress_msg.edit_text(text, parse_mode="HTML")
        except Exception:
            pass  # Ignore "message is not modified" errors

    try:
        pdf_path, error = await generate_report(symbol, progress_callback=_update_progress)

        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as doc:
                caption_text = (
                    f"<b>{symbol} — Deep-Dive Report</b>\n\n"
                    f"<i>⚠️ Disclaimer:\n"
                    f"Laporan ini bersifat informatif dan disediakan sebagai referensi analitik singkat. Keputusan investasi sepenuhnya berada di tangan Anda. "
                    f"Selalu lakukan riset independen (DYOR) sebelum bertransaksi.</i>"
                )
                caption_text += "\n\n<i>💬 File ini akan otomatis dihapus dalam 48 jam.</i>"
                sent_doc = await update.message.reply_document(
                    document=doc,
                    filename=f"ScopeBit_{symbol}_Report.pdf",
                    caption=caption_text,
                    parse_mode="HTML"
                )
                
            REPORT_CACHE[chat_id][symbol] = {
                "time": time.time(),
                "msg_id": sent_doc.message_id
            }
            
            await progress_msg.delete()

            delete_at = int(time.time()) + (48 * 3600)
            schedule_auto_delete(update.message.chat_id, update.message.message_id, sent_doc.message_id, delete_at)

            try:
                os.remove(pdf_path)
            except OSError:
                pass
        else:
            await progress_msg.edit_text(
                error or f"Gagal membuat report untuk <b>{symbol}</b>.",
                parse_mode="HTML"
            )

    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat 💤", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(
            f"Error Report <b>{symbol}</b>.\n<code>{error_msg}</code>",
            parse_mode="HTML"
        )


# ──────────────────────────────────────────────
# /swing Command
# ──────────────────────────────────────────────

async def swing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if not context.args:
        await send_auto_delete_error(update, context, "⚠️ Gunakan format: <code>/sw [KODE SAHAM]</code>\nContoh: <code>/sw PTBA</code>")
        return

    symbol = sanitize_symbol(context.args[0])

    progress_msg = await update.message.reply_text(
        _loading(f"Analisis Swing <b>{symbol}</b>"),
        parse_mode="HTML"
    )

    try:
        # Fetch OHLCV data
        ohlcv = await get_daily_chart(symbol, 1000)

        if not ohlcv:
            await progress_msg.edit_text(
                f"Ticker <b>{symbol}</b> tidak ditemukan atau data chart tidak tersedia.",
                parse_mode="HTML"
            )
            return

        # Generate chart + plan
        chart_path, caption = await asyncio.to_thread(analyze_swing, symbol, ohlcv, False)

        if chart_path is None:
            # caption contains the error message
            await progress_msg.edit_text(caption, parse_mode="HTML")
            return

        # Send the chart photo with caption
        with open(chart_path, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode="HTML"
            )

        # Delete the progress message
        await progress_msg.delete()

        # Clean up temp file
        try:
            os.remove(chart_path)
        except OSError:
            pass

    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat 💤", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(
            f"Error analisis Swing <b>{symbol}</b>.\n<code>{error_msg}</code>",
            parse_mode="HTML"
        )


# ──────────────────────────────────────────────
# /dt Command (Day Trading)
# ──────────────────────────────────────────────

async def dt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if not context.args:
        await send_auto_delete_error(update, context, "⚠️ Gunakan format: <code>/dt [KODE SAHAM]</code>\nContoh: <code>/dt BBRI</code>")
        return

    symbol = sanitize_symbol(context.args[0])

    progress_msg = await update.message.reply_text(
        _loading(f"Analisis Day Trade <b>{symbol}</b>"),
        parse_mode="HTML"
    )

    try:
        ohlcv = await get_intraday_chart(symbol)

        if not ohlcv:
            await progress_msg.edit_text(
                f"Ticker <b>{symbol}</b> tidak ditemukan atau data chart tidak tersedia.",
                parse_mode="HTML"
            )
            return

        chart_path, caption = await asyncio.to_thread(analyze_day_trade, symbol, ohlcv, False)

        if chart_path is None:
            await progress_msg.edit_text(caption, parse_mode="HTML")
            return

        with open(chart_path, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode="HTML"
            )

        await progress_msg.delete()

        try:
            os.remove(chart_path)
        except OSError:
            pass

    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat 💤", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(
            f"Error analisis Day Trade <b>{symbol}</b>.\n<code>{error_msg}</code>",
            parse_mode="HTML"
        )


# ──────────────────────────────────────────────
# /tps Command (Trading Plan Swing)
# ──────────────────────────────────────────────

async def tps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if not context.args:
        await send_auto_delete_error(update, context, "Gunakan format: <code>/tps [KODE SAHAM]</code>\nContoh: <code>/tps PTBA</code>")
        return

    symbol = sanitize_symbol(context.args[0])

    progress_msg = await update.message.reply_text(
        _loading(f"Trading Plan Swing <b>{symbol}</b>"),
        parse_mode="HTML"
    )

    try:
        # Fetch ohlcv and historical data dynamically over asyncio
        tasks = [
            get_daily_chart(symbol, 1000),
            get_historical_summary(symbol, days=20)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        ohlcv = results[0] if not isinstance(results[0], Exception) else None
        hist = results[1] if not isinstance(results[1], Exception) else None

        if not ohlcv:
            await progress_msg.edit_text(
                f"Ticker <b>{symbol}</b> tidak ditemukan atau data chart tidak tersedia.",
                parse_mode="HTML"
            )
            return

        extra_data = {
            "historical": hist
        }

        chart_path, caption = await asyncio.to_thread(analyze_swing, symbol, ohlcv, True, extra_data)

        if chart_path is None:
            await progress_msg.edit_text(caption, parse_mode="HTML")
            return

        with open(chart_path, "rb") as photo:
            sent_photo = await update.message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode="HTML"
            )

        await progress_msg.delete()

        # ── Dropdown Enable Engine: Auto SM + Bandar on BUY signal ──
        if caption and is_buy_signal(caption):
            try:
                dropdown_text = await analyze_dropdown(symbol)
                if dropdown_text:
                    await sent_photo.reply_text(
                        dropdown_text,
                        parse_mode="HTML",
                        quote=True
                    )
            except Exception as dd_err:
                log.warning(f"Dropdown analysis skipped for {symbol}: {dd_err}")

        try:
            os.remove(chart_path)
        except OSError:
            pass

    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(
            f"Error Trading Plan Swing <b>{symbol}</b>.\n<code>{error_msg}</code>",
            parse_mode="HTML"
        )


# ──────────────────────────────────────────────
# /tpd Command (Trading Plan Day Trade)
# ──────────────────────────────────────────────

async def tpd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if not context.args:
        await send_auto_delete_error(update, context, "Gunakan format: <code>/tpd [KODE SAHAM]</code>\nContoh: <code>/tpd BBRI</code>")
        return

    symbol = sanitize_symbol(context.args[0])

    progress_msg = await update.message.reply_text(
        _loading(f"Trading Plan Day Trade <b>{symbol}</b>"),
        parse_mode="HTML"
    )

    try:
        # Fetch intraday chart and historical data
        tasks = [
            get_intraday_chart(symbol),
            get_historical_summary(symbol, days=5)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        ohlcv = results[0] if not isinstance(results[0], Exception) else None
        hist = results[1] if not isinstance(results[1], Exception) else None

        if not ohlcv:
            await progress_msg.edit_text(
                f"Ticker <b>{symbol}</b> tidak ditemukan atau data chart tidak tersedia.",
                parse_mode="HTML"
            )
            return

        extra_data = {
            "historical": hist
        }

        chart_path, caption = await asyncio.to_thread(analyze_day_trade, symbol, ohlcv, True, extra_data)

        if chart_path is None:
            await progress_msg.edit_text(caption, parse_mode="HTML")
            return

        with open(chart_path, "rb") as photo:
            sent_photo = await update.message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode="HTML"
            )

        await progress_msg.delete()

        # ── Dropdown Enable Engine: Auto SM + Bandar on BUY signal ──
        if caption and is_buy_signal(caption):
            try:
                dropdown_text = await analyze_dropdown(symbol)
                if dropdown_text:
                    await sent_photo.reply_text(
                        dropdown_text,
                        parse_mode="HTML",
                        quote=True
                    )
            except Exception as dd_err:
                log.warning(f"Dropdown analysis skipped for {symbol}: {dd_err}")

        try:
            os.remove(chart_path)
        except OSError:
            pass

    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(
            f"Error Trading Plan Day Trade <b>{symbol}</b>.\n<code>{error_msg}</code>",
            parse_mode="HTML"
        )


# --- SCANNER COMMANDS ---

_SCANNER_CONFIGS = {
    "rcm": {"sort_key": "cm", "title": "REKAP CLEAN MONEY", "desc": "Filter: Akumulasi Whale Ter-Clean (Whale Buying & Retail Selling)"},
}


def _format_scanner_result(results: list, config: dict, date_str: str, filter_str: str = "") -> str:
    """Format scanner results into Telegram HTML message."""
    L = "━" * 38
    o = [f"<b>{config['title']}</b>"]
    o.append(f"<i>{config['desc']}</i>")
    o.append(f"<code>Data Date: {date_str}</code>")
    if filter_str:
        o.append(f"<code>Filter: {html.escape(filter_str)}</code>")
    o.append(f"<code>{L}</code>")

    if not results:
        o.append("<code>Tidak ada data yang cocok.</code>")
        o.append(f"<code>{L}</code>")
        return "\n".join(o)

    # Highlight column headers
    h_sm = " [SM]" if config["sort_key"] == "sm" else "  SM"
    h_bm = " [BM]" if config["sort_key"] == "bm" else "  BM"
    h_cm = " [CM]" if config["sort_key"] == "cm" else "  CM"

    # Header
    o.append(f"<code>{'No':>2} {'Kode':<6}{h_sm:>8}{h_bm:>8}{h_cm:>8} {'Tx':>5}</code>")
    o.append(f"<code>{L}</code>")

    for i, r in enumerate(results, 1):
        sm_s = _fmt_val_short(r['sm'])
        bm_s = _fmt_val_short(r['bm'])
        cm_s = _fmt_val_short(r['cm'])
        
        # Add sort indicator to values
        v_sm = f"*{sm_s}" if config["sort_key"] == "sm" else sm_s
        v_bm = f"*{bm_s}" if config["sort_key"] == "bm" else bm_s
        v_cm = f"*{cm_s}" if config["sort_key"] == "cm" else cm_s
        
        sign_sm = "+" if r['sm'] >= 0 else "-"
        sign_bm = "+" if r['bm'] >= 0 else "-"
        sign_cm = "+" if r['cm'] >= 0 else "-"
        
        pwr = 0
        total = abs(r['sm']) + abs(r['bm'])
        if total > 0:
            pwr = abs(r['cm']) / total * 100
            
        o.append(f"<code>{i:>2} {r['symbol']:<6} {sign_sm}{sm_s:>7} {sign_bm}{bm_s:>7} {sign_cm}{cm_s:>7} {int(pwr):>3}%</code>")

    o.append(f"<code>{L}</code>")
    o.append("<i>*Sorted by highlighted column. Power Ratio in right col.</i>")
    return "\n".join(o)


# ──────────────────────────────────────────────
# COMMANDS
# ──────────────────────────────────────────────

async def send_auto_delete_error(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str, delay: int = 5):
    """Sends an error message that automatically deletes itself after a delay."""
    sent_message = await update.message.reply_text(message_text, parse_mode="HTML")
    await asyncio.sleep(delay)
    try:
        await sent_message.delete()
        await update.message.delete() # Also delete the user's command message
    except Exception:
        pass # Ignore if messages can't be deleted


# ──────────────────────────────────────────────
# /bandar Command
# ──────────────────────────────────────────────

async def bandar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update):
        return
    _log_cmd(update)

    if not context.args:
        await update.message.reply_text("Silakan masukkan kode saham. Contoh: <code>/br ASII</code>", parse_mode="HTML")
        return

    symbol = context.args[0].upper()
    progress_msg = await update.message.reply_text(_loading(f"Analisis Bandarmology <b>{symbol}</b>"), parse_mode="HTML")

    try:
        result = await analyze_bandar(symbol)
        if result:
            result += "\n\n<i>💬 Pesan ini akan otomatis dihapus dalam 48 jam.</i>"
            await progress_msg.edit_text(result, parse_mode="HTML")
            delete_at = int(time.time()) + (48 * 3600)
            schedule_auto_delete(update.message.chat_id, update.message.message_id, progress_msg.message_id, delete_at)
        else:
            await progress_msg.edit_text(f"Gagal mengambil data Bandarmology <b>{symbol}</b>.", parse_mode="HTML")
    except AuthError:
        await progress_msg.edit_text(f"<b>{symbol}</b>: Bot sedang istirahat 💤", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(f"Error analisis Bandarmology <b>{symbol}</b>.\n<code>{error_msg}</code>", parse_mode="HTML")


async def scanner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /rcm, /rsm, /rbm commands."""
    if not await is_allowed(update):
        return
    _log_cmd(update)

    # Determine which scanner was invoked
    cmd = update.message.text.split()[0].lstrip("/").lower()
    config = _SCANNER_CONFIGS.get(cmd)
    if not config:
        return

    # Parse optional filter from args
    filter_str = " ".join(context.args) if context.args else ""
    filter_fn = parse_filter(filter_str) if filter_str else None

    progress_msg = await update.message.reply_text(
        _loading(f"Scanning <b>{config['title']}</b> (30-60 detik)"),
        parse_mode="HTML"
    )

    try:
        results, date_str = await scan_market(
            sort_key=config["sort_key"],
            filter_fn=filter_fn,
            top_n=15,
        )

        msg = _format_scanner_result(results, config, date_str, filter_str)
        await progress_msg.edit_text(msg, parse_mode="HTML")

    except AuthError:
        await progress_msg.edit_text("⚠️ <b>Scanner</b>: Bot sedang istirahat 💤", parse_mode="HTML")
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(
            f"Error scanner.\n<code>{error_msg}</code>",
            parse_mode="HTML"
        )


# ──────────────────────────────────────────────
# /refresh Command (Admin Only)
# ──────────────────────────────────────────────

async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual token refresh — admin only (ADMIN_CHAT_ID)."""
    if not await is_allowed(update): return
    from bot.config import ADMIN_CHAT_ID
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await send_auto_delete_error(update, context, "⛔ <b>Akses Ditolak:</b> Anda bukan admin yang diizinkan merestart token.")
        return

    _log_cmd(update)

    progress_msg = await update.message.reply_text("🔄 Refreshing API token...", parse_mode="HTML")

    try:
        result = await refresh_stockbit_token()

        if result:
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone(timedelta(hours=7)))
            ts = now.strftime("%Y-%m-%d %H:%M:%S")

            expires = result.get('access_expired_at', '-')
            lines = [
                "🔑 <b>Token Refreshed Successfully</b>",
                "",
                f"<code>created_at {ts} by admin</code>",
                f"<code>expires_at {expires}</code>",
            ]
            await progress_msg.edit_text("\n".join(lines), parse_mode="HTML")
        else:
            await progress_msg.edit_text(
                "❌ <b>Token refresh gagal.</b>\n"
                "<code>Pastikan STOCKBIT_REFRESH_TOKEN di .env masih valid.</code>",
                parse_mode="HTML"
            )
    except Exception as e:
        error_msg = html.escape(str(e))
        await progress_msg.edit_text(f"❌ Error refresh token.\n<code>{error_msg}</code>", parse_mode="HTML")


# ──────────────────────────────────────────────
# /token Command (Admin Only)
# ──────────────────────────────────────────────

async def token_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set Stockbit bearer token manually — admin only.
    Usage: /token <bearer_jwt>
    """
    if not await is_allowed(update): return
    from bot.config import ADMIN_CHAT_ID
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await send_auto_delete_error(update, context, "<b>Akses Ditolak:</b> Anda bukan admin yang diizinkan memperbarui token.")
        return

    _log_cmd(update)

    # Delete the original message immediately (contains sensitive token)
    try:
        await update.message.delete()
    except Exception:
        pass  # May fail if bot lacks delete permission

    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Gunakan: <code>/token &lt;bearer_jwt&gt;</code>",
            parse_mode="HTML"
        )
        return

    new_token = context.args[0].strip()

    if len(new_token) < 50:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Token terlalu pendek. Pastikan Anda mengirim JWT yang benar.",
            parse_mode="HTML"
        )
        return

    success = set_bearer_token(new_token)

    if success:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone(timedelta(hours=7)))
        ts = now.strftime("%Y-%m-%d %H:%M:%S")

        user_id = update.effective_user.id
        masked = new_token[:20] + "..." + new_token[-10:]
        lines = [
            "🔑 <b>Bearer Token Updated</b>",
            "",
            f"<code>token   : {masked}</code>",
            f"<code>updated : {ts}</code>",
            f"<code>by      : admin ({user_id})</code>",
        ]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\n".join(lines),
            parse_mode="HTML"
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ <b>Gagal update token.</b>\n<code>Cek log untuk detail error.</code>",
            parse_mode="HTML"
        )

async def token_refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set Stockbit refresh token manually — admin only.
    Usage: /token-refresh <refresh_token>
    """
    if not await is_allowed(update): return
    from bot.config import ADMIN_CHAT_ID
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await send_auto_delete_error(update, context, "⛔ <b>Akses Ditolak:</b> Anda bukan admin yang diizinkan memperbarui token.")
        return

    _log_cmd(update)

    # Delete the original message immediately (contains sensitive token)
    try:
        await update.message.delete()
    except Exception:
        pass  # May fail if bot lacks delete permission

    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Gunakan: <code>/token-refresh &lt;refresh_token&gt;</code>",
            parse_mode="HTML"
        )
        return

    new_token = context.args[0].strip()

    if len(new_token) < 20:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Refresh Token terlalu pendek. Pastikan Anda mengirim token yang benar.",
            parse_mode="HTML"
        )
        return

    # Write to .env
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('STOCKBIT_REFRESH_TOKEN='):
                lines[i] = f'STOCKBIT_REFRESH_TOKEN={new_token}\n'
                updated = True
                break
                
        if not updated:
            lines.insert(1, f'STOCKBIT_REFRESH_TOKEN={new_token}\n')
            
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
            
        # Update OS env so it applies immediately without restart
        os.environ['STOCKBIT_REFRESH_TOKEN'] = new_token
        
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone(timedelta(hours=7)))
        ts = now.strftime("%Y-%m-%d %H:%M:%S")

        user_id = update.effective_user.id
        masked = new_token[:10] + "..." + new_token[-5:] if len(new_token) > 15 else "***"
        reply_lines = [
            "🔑 <b>Refresh Token Updated</b>",
            "",
            f"<code>token   : {masked}</code>",
            f"<code>updated : {ts}</code>",
            f"<code>by      : admin ({user_id})</code>",
        ]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\n".join(reply_lines),
            parse_mode="HTML"
        )
    except Exception as e:
        error_msg = html.escape(str(e))
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ <b>Gagal update token.</b>\n<code>{error_msg}</code>",
            parse_mode="HTML"
        )

async def help_radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    from bot.config import ADMIN_CHAT_ID
    
    o = [
        "<b>🛠️ Panduan Penggunaan Radar Otomatis</b>",
        f"Sistem akses admin ({ADMIN_CHAT_ID})\n",
        "<b>1. Tambah Radar Baru</b>",
        "Command: <code>/add_radar [Waktu] [JSON]</code>",
        "Contoh: <code>/add_radar 09:30 {\"name\":\"Bullish Reversal\"...}</code>",
        "<i>Otomatis memindai Stockbit setiap hari pada jam tersebut.</i>\n",
        "<b>2. Hapus Radar</b>",
        "Command: <code>/del_radar [ID Radar]</code>",
        "<i>Gunakan /list_radar untuk menyalin ID.</i>\n",
        "<b>3. Daftar Radar Aktif</b>",
        "Command: <code>/list_radar</code>",
        "<i>Menampilkan semua jadwal saat ini.</i>\n",
        "<b>4. Check Radar (Manual)</b>",
        "Command: <code>/check_radar [ID Radar]</code>",
        "<i>Eksekusi radar instant tanpa menunggu jadwal untuk memastikan formula & clean money (hapus otomatis dlm 1 hari).</i>"
    ]
    await update.message.reply_text("\n".join(o), parse_mode="HTML")

async def list_radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    from bot.config import ADMIN_CHAT_ID
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await send_auto_delete_error(update, context, "⛔ <b>Akses Ditolak:</b> Anda bukan admin yang diizinkan.")
        return
    from bot.jobs import load_screeners
    screeners = load_screeners()
    if not screeners:
        await update.message.reply_text("📭 <b>Radar Kosong</b>\nBelum ada jadwal preset radar otomatis.", parse_mode="HTML")
        return
    
    o = ["<b>🗓️ JADWAL RADAR OTOMATIS</b>", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    for uid, cfg in screeners.items():
        o.append(f"<b>ID:</b> <code>{uid}</code>")
        o.append(f"<b>Name:</b> {cfg['name']}")
        o.append(f"<b>Time:</b> {cfg['time']} WIB")
        o.append("")
    o.append("<i>Gunakan /del_radar &lt;ID&gt; untuk menghapus jadwal.</i>")
    await update.message.reply_text("\n".join(o), parse_mode="HTML")

async def del_radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    from bot.config import ADMIN_CHAT_ID
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await send_auto_delete_error(update, context, "⛔ <b>Akses Ditolak:</b> Anda bukan admin yang diizinkan.")
        return
    if not context.args:
        await send_auto_delete_error(update, context, "⚠️ Gunakan format: <code>/del_radar [ID]</code>\nContoh: <code>/del_radar b4x9</code>")
        return
    
    uid = context.args[0]
    from bot.jobs import load_screeners, save_screeners, load_screener_jobs
    screeners = load_screeners()
    if uid in screeners:
        name = screeners[uid]["name"]
        del screeners[uid]
        save_screeners(screeners)
        load_screener_jobs(context.application)
        await update.message.reply_text(f"✅ Jadwal Radar <b>{name}</b> ({uid}) berhasil dihapus.", parse_mode="HTML")
    else:
        await send_auto_delete_error(update, context, f"⚠️ Jadwal Radar dengan ID <code>{uid}</code> tidak ditemukan.")

async def check_radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    from bot.config import ADMIN_CHAT_ID
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await send_auto_delete_error(update, context, "⛔ <b>Akses Ditolak:</b> Anda bukan admin yang diizinkan.")
        return
    if not context.args:
        await send_auto_delete_error(update, context, "⚠️ Gunakan format: <code>/check_radar [ID]</code>\nContoh: <code>/check_radar b4x9</code>")
        return
    
    uid = context.args[0]
    from bot.jobs import load_screeners
    screeners = load_screeners()
    if uid not in screeners:
        await send_auto_delete_error(update, context, f"⚠️ Jadwal Radar dengan ID <code>{uid}</code> tidak ditemukan.")
        return
        
    cfg = screeners[uid]
    name = cfg.get("name", "Unknown Radar")
    filters = cfg.get("filters", [])
    sequence = cfg.get("sequence", [])

    from api.screener import run_screener
    from api.market import get_trade_book_chart
    from engines.smart_money import calc_money_flow_chart
    import html
    import time
    from datetime import datetime
    import pytz

    wait_msg = await update.message.reply_text(f"📡 <i>Mengeksekusi Radar '{name}'...</i>", parse_mode="HTML")

    log.info(f"Running manual check for screener '{name}'...")
    try:
        res = await run_screener(filters, sequence, ordercol=2661, ordertype="desc", page=1)
        calcs = res.get("calcs", [])
        total = res.get("totalrows", len(calcs))

        if not calcs:
             await wait_msg.edit_text(f"📭 <b>Radar Kosong</b>\nTidak menemukan emiten yang masuk kriteria '{name}'.", parse_mode="HTML")
             return

        o = []
        now_str = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%H:%M WIB")
        o.append(f"<b>{html.escape(name)} - {now_str}</b>")
        
        from api.screener import format_screener_rules
        rules_text = format_screener_rules(filters)
        o.append(f"<code>{rules_text}</code>")
        o.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        o.append(f"<code>Ditemukan {total} saham yang masuk kriteria:</code>\n")

        processed = []
        import asyncio
        for c in calcs:
            sym = c['company']['symbol']
            
            # Extract basic price for info
            price_str = "-"
            for r in c["results"]:
                if r["id"] == 2661: price_str = str(r["display"])
                
            # Attempt parsing float price for Clean Money calc fallback
            f_price = 0.0
            try:
                f_price = float(price_str.replace(",", ""))
            except Exception:
                pass
                
            # Fetch intraday tradebook chart and calc Clean money
            chart_data = await get_trade_book_chart(sym)
            mf = calc_money_flow_chart(chart_data, fallback_price=f_price)
            
            cm_val = 0.0
            cm_text = "-"
            if mf:
                cm_val = float(mf["clean_money"])
                if cm_val > 1_000_000_000:
                    cm_text = f"Rp {cm_val/1_000_000_000:.1f} M"
                elif cm_val < -1_000_000_000:
                    cm_text = f"Rp {cm_val/1_000_000_000:.1f} M"
                else:
                    cm_text = f"Rp {cm_val/1_000_000:.1f} JT"
                    
            processed.append({
                "sym": sym,
                "price": price_str,
                "cm_val": cm_val,
                "cm_text": cm_text
            })
            
            await asyncio.sleep(0.8) # Avoid API rate limit

        # Sort by Clean Money descending
        processed.sort(key=lambda x: x["cm_val"], reverse=True)

        for i, p in enumerate(processed[:10]):
            o.append(f"<b>{i+1}. {p['sym']}</b>")
            o.append(f"<code>Price      : {p['price']:>10}</code>")
            o.append(f"<code>Clean Money: {p['cm_text']:>10}</code>")
            if i < 9 and i < len(processed)-1:
                o.append("")

        if len(processed) > 10:
            watchlist = []
            for p in processed[10:]:
                watchlist.append(f"{p['sym']} [{p['cm_text']}]")
            
            o.append("━━━━━━━━━━━━━━━━━━━━━━━━")
            o.append(f"<b>Watchlist + :</b> [{', '.join(watchlist)}]")

        o.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        o.append("<i>Mendeteksi akumulasi bandar berdasarkan Trade Book flow saat ini.</i>\n\n💬 Pesan otomatis dihapus dalam 1 hari.")

        await wait_msg.edit_text("\n".join(o), parse_mode="HTML")
        delete_at = int(time.time()) + 86400
        schedule_auto_delete(update.message.chat_id, update.message.message_id, wait_msg.message_id, delete_at)
        
    except Exception as e:
        log.error(f"Failed to check radar {name}: {e}")
        await wait_msg.edit_text(f"❌ <b>Terjadi Kesalahan:</b>\n<code>{e}</code>", parse_mode="HTML")

async def add_radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Format: /add_radar 09:30 {"name":"Bullish Reversal"...}
    """
    if not await is_allowed(update): return
    from bot.config import ADMIN_CHAT_ID
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await send_auto_delete_error(update, context, "⛔ <b>Akses Ditolak:</b> Anda bukan admin yang diizinkan menyetel radar.")
        return
    msg = update.message.text
    
    cmd_parts = msg.split(None, 2)
    if len(cmd_parts) < 3:
        await send_auto_delete_error(update, context, "⚠️ Gunakan format:\n<code>/add_radar 09:30 [JSON PAYLOAD]</code>", delay=10)
        return
    
    time_str = cmd_parts[1].replace(".", ":")
    if len(time_str) == 4:
        time_str = "0" + time_str # 9:30 -> 09:30
        
    json_str = cmd_parts[2].strip()
    
    import json
    import uuid
    from api.screener import run_screener
    try:
        raw_payload = json.loads(json_str)
        name_str = str(raw_payload.get("name", "Custom Radar"))
        
        wait_msg = await update.message.reply_text(f"📡 <i>Validasi Payload '{name_str}' ke Stockbit API...</i>", parse_mode="HTML")
        
        # Stockbit encodes filters inside a stringified json sometimes, or array
        f_val = raw_payload.get("filters", "[]")
        if isinstance(f_val, str):
            filters = json.loads(f_val)
        else:
            filters = f_val
            
        seq_val = raw_payload.get("sequence", "")
        if isinstance(seq_val, str):
            sequence = [int(x.strip()) for x in seq_val.split(",") if x.strip()]
        else:
            sequence = seq_val
            
        # Dry Run
        res = await run_screener(filters, sequence, ordercol=2661, ordertype="desc", page=1)
        calcs = res.get("calcs", [])
        total = res.get("totalrows", len(calcs))
        
        o = [f"✅ <b>Payload Valid! Preview Hasil ({total} stocks):</b>\n"]
        for i, c in enumerate(calcs[:3]):
            o.append(f"{i+1}. {c['company']['symbol']}")
        o.append("\n💾 Menyimpan jadwal untuk dijalankan...")
        
        # Save setup
        from bot.jobs import load_screeners, save_screeners, load_screener_jobs
        screeners = load_screeners()
        uid = str(uuid.uuid4())[:4]
        
        screeners[uid] = {
            "name": name_str,
            "time": time_str,
            "filters": filters,
            "sequence": sequence
        }
        save_screeners(screeners)
        load_screener_jobs(context.application)
        
        o.append(f"<b>Sukses!</b> Radar otomatis akan jalan tiap jam <code>{time_str}</code> WIB.")
        await wait_msg.edit_text("\n".join(o), parse_mode="HTML")
        
    except Exception as e:
        log.error(f"/add_radar Exception: {e}")
        await wait_msg.edit_text(f"❌ <b>Gagal Validasi Payload:</b>\n<code>{e}</code>\n\nPastikan JSON yang dicopas dari tab Network benar.", parse_mode="HTML")

# We store active welcome tasks and message IDs per chat to prevent spam
ACTIVE_WELCOMES_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'active_welcomes.json')

def _load_active_welcomes():
    if os.path.exists(ACTIVE_WELCOMES_FILE):
        try:
            with open(ACTIVE_WELCOMES_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_active_welcomes(data):
    os.makedirs(os.path.dirname(ACTIVE_WELCOMES_FILE), exist_ok=True)
    try:
        with open(ACTIVE_WELCOMES_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass

async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets new members and explains group rules and bot usage."""
    message = update.message
    if not message or not message.new_chat_members:
        return
        
    chat_id = message.chat.id
    
    for member in message.new_chat_members:
        # Don't welcome ourselves or other bots
        if member.is_bot:
            continue
            
        name = html.escape(member.first_name)
        
        # Abbreviated welcome text with specific chat link
        welcome_text = (
            f"Halo <b>{name}</b>, selamat datang di komunitas ScopeBit! Senang sekali kamu bisa bergabung dengan kami.\n\n"
            f"Untuk mulai menggunakan bot analisa dan melihat panduan lengkapnya, kamu bisa langsung mengunjungi tautan berikut ya:\n\n"
            f"https://t.me/ScopeBit/564\n\n"
        )
        
        try:
            _active_welcomes = _load_active_welcomes()
            
            # If there's already an active welcome message in this chat, delete it early (as well as its sys message) to prevent spam
            str_chat_id = str(chat_id)
            if str_chat_id in _active_welcomes:
                old_sys_id, old_bot_id = _active_welcomes[str_chat_id]
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=old_sys_id)
                except Exception:
                    pass
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=old_bot_id)
                except Exception:
                    pass
            
            # Send new welcome message
            welcome_msg = await message.reply_text(text=welcome_text, parse_mode="HTML", disable_web_page_preview=True)
            
            # Update the active welcomes with the current system message and bot message
            _active_welcomes[str_chat_id] = [message.message_id, welcome_msg.message_id]
            _save_active_welcomes(_active_welcomes)
            
            # Auto delete the welcome message and the system "user joined" message after 30 seconds
            async def delete_welcome_later(chat, sys_msg_id, bot_msg_id):
                await asyncio.sleep(30)  # 30 seconds
                
                # Check if this specific welcome message is still the active one
                # If it is, clear it from the active welcomes dictionary
                current_welcomes = _load_active_welcomes()
                str_c_id = str(chat.id)
                if current_welcomes.get(str_c_id) == [sys_msg_id, bot_msg_id]:
                    current_welcomes.pop(str_c_id, None)
                    _save_active_welcomes(current_welcomes)
                        
                # 30 seconds passed, delete the messages
                try:
                    await chat.bot.delete_message(chat_id=chat.id, message_id=sys_msg_id)
                except Exception:
                    pass
                try:
                    await chat.bot.delete_message(chat_id=chat.id, message_id=bot_msg_id)
                except Exception:
                    pass
                    
            asyncio.create_task(delete_welcome_later(message.chat, message.message_id, welcome_msg.message_id))
            
        except Exception as e:
            log.warning(f"Failed to send welcome message: {e}")
