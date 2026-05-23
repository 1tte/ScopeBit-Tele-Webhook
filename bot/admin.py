import os
import sys
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.config import ADMIN_CHAT_ID

log = logging.getLogger("bot")

ENV_FILE = os.path.join(os.path.dirname(__file__), '..', '.env')

TOGGLE_MAPPINGS = {
    "CMD_SM_ENABLED": "/sm - Smart Money Analysis",
    "CMD_BR_ENABLED": "/br - Bandarmology (Stealth)",
    "CMD_FA_ENABLED": "/fa - Fundamental Analysis",
    "CMD_SW_ENABLED": "/sw - Swing Trade Setup",
    "CMD_DT_ENABLED": "/dt - Day Trade Setup",
    "CMD_RCM_ENABLED": "/rcm - Recap Clean Money",
    "CMD_IM_ENABLED": "/im - Insider & Major Tracker",
    "CMD_FC_ENABLED": "/fc - Fundachart Growth Trend",
    "CMD_REPORT_ENABLED": "/report - PDF Deep Report",
    "CMD_JARVIS_ENABLED": "/jarvis - JARVIS Auto-Pilot"
}

# ──────────────────────────────────────────────
# .env Read/Write
# ──────────────────────────────────────────────

def read_env_toggles() -> dict:
    toggles = {}
    if not os.path.exists(ENV_FILE):
        return toggles
    with open(ENV_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            if '=' in line:
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().lower()
                if key in TOGGLE_MAPPINGS:
                    toggles[key] = (val == 'true')
    for key in TOGGLE_MAPPINGS:
        if key not in toggles:
            toggles[key] = True
    return toggles

def write_env_toggle(target_key: str, new_val: bool):
    if not os.path.exists(ENV_FILE):
        return
    lines = []
    found = False
    with open(ENV_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{target_key}="):
            lines[i] = f"{target_key}={'true' if new_val else 'false'}\n"
            found = True
            break
    if not found:
        lines.append(f"{target_key}={'true' if new_val else 'false'}\n")
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)

# ──────────────────────────────────────────────
# Keyboard Builders
# ──────────────────────────────────────────────

def build_main_keyboard(toggles: dict) -> InlineKeyboardMarkup:
    keyboard = []
    for key, name in TOGGLE_MAPPINGS.items():
        is_on = toggles.get(key, True)
        status = "ON" if is_on else "OFF"
        keyboard.append([InlineKeyboardButton(f"[{status}] {name}", callback_data=f"toggle_{key}")])
    
    from bot.config import BOT_MODE
    bot_mode_str = "AKTIF / PRODUCTION" if BOT_MODE == "production" else "MAINTENANCE / DEBUG"
    keyboard.append([InlineKeyboardButton(f"Status Bot: {bot_mode_str}", callback_data="sys_toggle_mode")])

    keyboard.append([
        InlineKeyboardButton("Panel JARVIS", callback_data="page_jarvis"),
        InlineKeyboardButton("Kelola Radar", callback_data="page_radar")
    ])
    keyboard.append([
        InlineKeyboardButton("Lihat Token", callback_data="sys_get_token"),
        InlineKeyboardButton("Set Token", callback_data="sys_set_token")
    ])
    keyboard.append([
        InlineKeyboardButton("Broadcast Pesan", callback_data="sys_broadcast")
    ])
    keyboard.append([
        InlineKeyboardButton("Restart Bot", callback_data="sys_restart"),
        InlineKeyboardButton("Tutup", callback_data="sys_close"),
    ])
    return InlineKeyboardMarkup(keyboard)

def build_jarvis_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Test: Individual Screeners", callback_data="page_jarvis_screeners")],
        [InlineKeyboardButton("Test: Leaderboard", callback_data="jarvis_test_leaderboard")],
        [InlineKeyboardButton("Test: Daily Verdict", callback_data="jarvis_test_verdict")],
        [InlineKeyboardButton("Test: News Broadcast", callback_data="jarvis_test_news")],
        [InlineKeyboardButton("Test: Evaluation (H-1)", callback_data="jarvis_test_eval")],
        [InlineKeyboardButton("Reset Tracker", callback_data="sys_reset_tracker_prompt")],
        [InlineKeyboardButton("Kembali", callback_data="page_main")]
    ])

def build_jarvis_screener_test_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("[P] Pre-Market", callback_data="jarvis_run_pre_market"),
            InlineKeyboardButton("[M] Money", callback_data="jarvis_run_money")
        ],
        [
            InlineKeyboardButton("[Mo] Momentum", callback_data="jarvis_run_momentum"),
            InlineKeyboardButton("[V] Value", callback_data="jarvis_run_value")
        ],
        [
            InlineKeyboardButton("[Q] Quality", callback_data="jarvis_run_quality"),
            InlineKeyboardButton("[I] Insider", callback_data="jarvis_run_insider")
        ],
        [
            InlineKeyboardButton("[C] Closing", callback_data="jarvis_run_closing"),
            InlineKeyboardButton("[L] Liquid", callback_data="jarvis_run_liquid")
        ],
        [
            InlineKeyboardButton("[SM] Smart Money", callback_data="jarvis_run_smart_money"),
            InlineKeyboardButton("[D] Danger", callback_data="jarvis_run_danger")
        ],
        [
            InlineKeyboardButton("[Dv] Dividend", callback_data="jarvis_run_dividend"),
            InlineKeyboardButton("[B] Bagger", callback_data="jarvis_run_bagger")
        ],
        [
            InlineKeyboardButton("[T] Turnaround", callback_data="jarvis_run_turnaround"),
            InlineKeyboardButton("[Te] Technical", callback_data="jarvis_run_technical")
        ],
        [InlineKeyboardButton("Kembali", callback_data="page_jarvis")]
    ])

def build_radar_keyboard() -> InlineKeyboardMarkup:
    from bot.jobs import load_screeners
    screeners = load_screeners()
    keyboard = []
    
    for uid, cfg in screeners.items():
        name = cfg.get("name", "?")
        time_str = cfg.get("time", "?")
        
        keyboard.append([InlineKeyboardButton(
            f"{name} | {time_str} WIB",
            callback_data=f"radar_noop"
        )])
        keyboard.append([
            InlineKeyboardButton("Check", callback_data=f"radar_check_{uid}"),
            InlineKeyboardButton("Edit Jam", callback_data=f"radar_edittime_{uid}"),
            InlineKeyboardButton("Hapus", callback_data=f"radar_del_{uid}"),
        ])
    
    if not screeners:
        keyboard.append([InlineKeyboardButton("-- Belum ada radar --", callback_data="radar_noop")])
    
    keyboard.append([InlineKeyboardButton("Kembali", callback_data="page_main")])
    return InlineKeyboardMarkup(keyboard)

# ──────────────────────────────────────────────
# Text Builders
# ──────────────────────────────────────────────

def build_main_text() -> str:
    return (
        "<b>Admin Control Center</b>\n"
        "\n"
        "Klik tombol untuk ON/OFF fitur (berlaku langsung)."
    )

def build_jarvis_text() -> str:
    from bot.config import JARVIS_THREAD_ID
    return (
        "<b>Panel JARVIS P.I.S</b>\n\n"
        "Gunakan panel ini untuk menguji dan melakukan *debug* "
        "terhadap fungsi-fungsi JARVIS Intelligence secara manual.\n\n"
        f"<i>Output report akan dikirim langsung ke chat ini. (Target Produksi JARVIS: Thread {JARVIS_THREAD_ID})</i>"
    )

def build_jarvis_screener_test_text() -> str:
    return (
        "<b>Test Individual Screeners</b>\n\n"
        "Pilih salah satu Stone di bawah untuk dijalankan secara instan. "
        "Hasil eksekusi akan dikirimkan ke chat ini sebagai file <code>.txt</code>."
    )

def build_radar_text() -> str:
    from bot.jobs import load_screeners
    screeners = load_screeners()
    count = len(screeners)
    lines = [
        "<b>Kelola Radar</b>",
        f"Total: {count} radar aktif\n",
    ]
    if screeners:
        lines.append("Pilih aksi untuk setiap radar di bawah:")
    else:
        lines.append("Belum ada radar. Tambahkan dengan:")
    lines.append("\n<code>/add_radar HH:MM {JSON payload}</code>")
    return "\n".join(lines)

# ──────────────────────────────────────────────
# Pending edits storage (in-memory per session)
# ──────────────────────────────────────────────
_pending_time_edit = {}  # chat_id -> {"uid": "xxxx", "msg_id": 123}
_pending_token_edit = {} # chat_id -> msg_id
_pending_broadcast_edit = {} # chat_id -> msg_id

# ──────────────────────────────────────────────
# Command Entry Point
# ──────────────────────────────────────────────

async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text("Akses Ditolak.", parse_mode="HTML")
        return
    toggles = read_env_toggles()
    kb = build_main_keyboard(toggles)
    await update.message.reply_text(build_main_text(), parse_mode="HTML", reply_markup=kb)

# ──────────────────────────────────────────────
# Callback Handler (all button presses)
# ──────────────────────────────────────────────

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if str(user_id) != str(ADMIN_CHAT_ID):
        await query.answer("Akses ditolak.", show_alert=True)
        return
    
    data = query.data
    
    # ── Navigation ──
    if data == "page_main":
        await query.answer()
        toggles = read_env_toggles()
        await query.edit_message_text(build_main_text(), parse_mode="HTML", reply_markup=build_main_keyboard(toggles))
        return
    
    if data == "page_radar":
        await query.answer()
        await query.edit_message_text(build_radar_text(), parse_mode="HTML", reply_markup=build_radar_keyboard())
        return

    if data == "page_jarvis":
        await query.answer()
        await query.edit_message_text(build_jarvis_text(), parse_mode="HTML", reply_markup=build_jarvis_keyboard())
        return
    
    # ── System ──
    if data == "sys_close":
        await query.message.delete()
        await query.answer("Panel ditutup.")
        return
    
    if data == "sys_restart":
        await query.answer()
        await query.edit_message_text("<b>Merestart Bot...</b>\nTunggu sekitar 5 detik.", parse_mode="HTML")
        log.warning(f"Admin {user_id} triggered remote system restart!")
        import subprocess
        script_path = os.path.abspath(sys.argv[0])
        cwd = os.path.dirname(script_path)
        subprocess.Popen([sys.executable, script_path], cwd=cwd)
        await asyncio.sleep(2)
        os._exit(0)
        return
    
    if data == "radar_noop":
        await query.answer()
        return

    # ── JARVIS TESTS ──
    if data == "page_jarvis_screeners":
        await query.answer()
        await query.edit_message_text(build_jarvis_screener_test_text(), parse_mode="HTML", reply_markup=build_jarvis_screener_test_keyboard())
        return

    if data.startswith("jarvis_run_"):
        stone_name = data.replace("jarvis_run_", "")
        await query.answer(f"Menjalankan {stone_name} scanner...")
        
        from engines.jarvis import run_stone, generate_stone_report, JARVIS_STONES
        
        stone = JARVIS_STONES.get(stone_name)
        if not stone:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Stone {stone_name} tidak ditemukan.")
            return
            
        try:
            # Use run_stone directly — identical to production flow
            stocks_data = await run_stone(stone_name)
            
            # Generate the report document
            caption, img_doc, txt_doc = generate_stone_report(stone_name, stocks_data)
            
            # Send the photo if generated
            if img_doc:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=img_doc,
                    caption=caption,
                    parse_mode="HTML"
                )
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=txt_doc,
                    filename=f"JARVIS_{stone_name}_{len(stocks_data)}.txt"
                )
            else:
                # Fallback to document only
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=txt_doc,
                    filename=f"JARVIS_{stone_name}_{len(stocks_data)}.txt",
                    caption=caption,
                    parse_mode="HTML"
                )
        except Exception as e:
            log.error(f"Screener test failed: {e}")
            import traceback
            log.error(f"Traceback: {traceback.format_exc()}")
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Error running {stone_name}: {e}")
        return
    if data == "jarvis_test_leaderboard":
        await query.answer("Mengambil data Leaderboard JARVIS...")
        from engines.jarvis import get_leaderboard
        try:
            res = get_leaderboard()
            await context.bot.send_message(chat_id=query.message.chat_id, text=res, parse_mode="HTML")
        except Exception as e:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Error Leaderboard: {e}")
        return

    if data == "jarvis_test_verdict":
        await query.answer("Menghitung Conviction & Verdict harian...")
        from engines.jarvis import generate_daily_verdict
        try:
            res = generate_daily_verdict()
            await context.bot.send_message(chat_id=query.message.chat_id, text=res, parse_mode="HTML")
        except Exception as e:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Error Verdict: {e}")
        return
    
    if data == "jarvis_test_news":
        await query.answer("Menjalankan News Broadcast Test...")
        from bot.jobs import run_scheduled_news_broadcast
        try:
            # We wrap it in a mock context-like object if necessary, but run_scheduled_news_broadcast 
            # only needs context to access context.bot.
            await run_scheduled_news_broadcast(context)
            await context.bot.send_message(chat_id=query.message.chat_id, text="✅ News broadcast test selesai dijalankan.")
        except Exception as e:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Error News Broadcast Test: {e}")
        return

    if data == "jarvis_test_eval":
        await query.answer("Mengevaluasi performa JARVIS kemarin...")
        from engines.jarvis import generate_evaluation_report
        try:
            res = await generate_evaluation_report()
            await context.bot.send_message(chat_id=query.message.chat_id, text=res, parse_mode="HTML")
        except Exception as e:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Error Eval: {e}")
        return

    # ── BOT MODE TOGGLE ──
    if data == "sys_toggle_mode":
        from bot.config import BOT_MODE
        
        new_mode = "production" if BOT_MODE == "debug" else "debug"
        if os.path.exists(ENV_FILE):
            lines = []
            found = False
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if line.strip().startswith("BOT_MODE="):
                    lines[i] = f"BOT_MODE={new_mode}\n"
                    found = True
                    break
            if not found:
                lines.append(f"BOT_MODE={new_mode}\n")
            with open(ENV_FILE, 'w', encoding='utf-8') as f:
                f.writelines(lines)
                
        await query.answer()
        await query.message.reply_text(f"<b>Mode diubah ke {new_mode.upper()}! Merestart Bot...</b>", parse_mode="HTML")
        log.warning(f"Admin {user_id} toggled BOT_MODE to {new_mode}. Restarting...")
        import subprocess
        script_path = os.path.abspath(sys.argv[0])
        cwd = os.path.dirname(script_path)
        subprocess.Popen([sys.executable, script_path], cwd=cwd)
        await asyncio.sleep(2)
        os._exit(0)
        return

    # ── RESET TRACKER ──
    if data == "sys_reset_tracker_prompt":
        await query.answer()
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("YA, HAPUS", callback_data="sys_reset_tracker_confirm"),
                InlineKeyboardButton("BATAL", callback_data="sys_reset_tracker_cancel")
            ]
        ])
        await query.edit_message_text("<b>PERINGATAN!</b>\n\nApakah Anda yakin ingin MENGHAPUS SEMUA DATA TRACKER JARVIS? Data historis streak dan conviction akan hilang permanen.", parse_mode="HTML", reply_markup=kb)
        return

    if data == "sys_reset_tracker_cancel":
        await query.answer("Dibatalkan.")
        toggles = read_env_toggles()
        await query.edit_message_text(build_main_text(), parse_mode="HTML", reply_markup=build_main_keyboard(toggles))
        return

    if data == "sys_reset_tracker_confirm":
        tracker_path = os.path.join(os.path.dirname(__file__), "..", "data", "jarvis_tracker.json")
        if os.path.exists(tracker_path):
            try:
                os.remove(tracker_path)
            except Exception as e:
                log.error(f"Failed to delete tracker: {e}")
        await query.answer("Tracker berhasil dihapus!", show_alert=True)
        toggles = read_env_toggles()
        await query.edit_message_text(build_main_text(), parse_mode="HTML", reply_markup=build_main_keyboard(toggles))
        return

    # ── Token Edit (start conversation) ──
    if data == "sys_get_token":
        await query.answer("Memeriksa status token saat ini...")
        
        bearer = "Tidak Diatur"
        refresh = "Tidak Diatur"
        
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("STOCKBIT_BEARER_TOKEN="):
                        bearer = stripped.split("=", 1)[1].strip()
                    elif stripped.startswith("STOCKBIT_REFRESH_TOKEN="):
                        refresh = stripped.split("=", 1)[1].strip()

        from bot.config import STOCKBIT_HEADERS
        current_header_bearer = STOCKBIT_HEADERS.get("Authorization", "").replace("Bearer ", "").strip()
        
        # Read From Backup (Decoded)
        from api.auth import get_backup_tokens
        back_bearer, back_refresh = get_backup_tokens()
        if back_refresh:
            refresh = back_refresh
        
        # Test API
        status_text = "Memeriksa..."
        try:
            import httpx
            test_url = "https://exodus.stockbit.com/company-price-feed/v2/orderbook/companies/BBCA"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(test_url, headers=STOCKBIT_HEADERS)
                if resp.status_code == 200:
                    status_text = "✅ <b>VALID (200 OK)</b>"
                elif resp.status_code == 401:
                    status_text = "❌ <b>EXPIRED (401 Unauthorized)</b>"
                else:
                    status_text = f"⚠️ <b>ERROR ({resp.status_code})</b>"
        except Exception as e:
            status_text = f"⚠️ <b>REQUEST FAILED</b>"

        msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "🔑 <b>ScopeBit Tokens:</b>\n"
                f"Api Status: {status_text}\n\n"
                f"<b>Current Active Bearer:</b>\n<code>{current_header_bearer}</code>\n\n"
                f"<b>Reserve Refresh Token (Decoded):</b>\n<code>{refresh}</code>\n\n"
                "<i>⚠️ Pesan ini akan otomatis terhapus dalam 5 detik.</i>\n"
                "<i>🌐 Token berhasil didorong ke Webhook.</i>"
            ),
            parse_mode="HTML"
        )
        
        # Trigger webhook to send the current token to website
        from api.auth import _send_webhook
        context.application.create_task(_send_webhook(current_header_bearer, refresh, "Manually Pushed via Admin"))

        
        async def _del_token():
            await asyncio.sleep(5)
            try: await msg.delete()
            except: pass
            
        context.application.create_task(_del_token())
        return

    if data == "sys_set_token":
        await query.answer()
        msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "<b>Ganti ScopeBit Token</b>\n"
                "Balas pesan ini dengan Bearer Token JWT yang baru."
            ),
            parse_mode="HTML"
        )
        _pending_token_edit[query.message.chat_id] = msg.message_id
        return
        
    # ── Broadcast Message (start conversation) ──
    if data == "sys_broadcast":
        await query.answer()
        msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "<b>Broadcast Pesan</b>\n\n"
                "Balas pesan ini dengan pengumuman yang ingin dikirimkan ke grup utama.\n"
                "<i>(Mendukung teks, gambar, atau dokumen)</i>"
            ),
            parse_mode="HTML"
        )
        _pending_broadcast_edit[query.message.chat_id] = msg.message_id
        return
    
    
    # ── Feature Toggles ──
    if data.startswith("toggle_"):
        await query.answer()
        key = data.replace("toggle_", "")
        if key in TOGGLE_MAPPINGS:
            toggles = read_env_toggles()
            new_state = not toggles.get(key, True)
            write_env_toggle(key, new_state)
            updated_toggles = read_env_toggles()
            from telegram.error import BadRequest
            try:
                await query.edit_message_reply_markup(reply_markup=build_main_keyboard(updated_toggles))
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    log.error(f"Failed to update keyboard: {e}")
            except Exception as e:
                log.error(f"Failed to update keyboard: {e}")
            
            status_text = "ON" if new_state else "OFF"
            msg = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"{TOGGLE_MAPPINGS[key]} => <b>{status_text}</b>",
                parse_mode="HTML"
            )
            async def _del():
                await asyncio.sleep(8)
                try: await msg.delete()
                except: pass
            context.application.create_task(_del())
        return
    
    # ── Radar: Delete ──
    if data.startswith("radar_del_"):
        uid = data.replace("radar_del_", "")
        from bot.jobs import load_screeners, save_screeners, load_screener_jobs
        screeners = load_screeners()
        if uid in screeners:
            name = screeners[uid]["name"]
            del screeners[uid]
            save_screeners(screeners)
            load_screener_jobs(context.application)
            await query.answer(f"Radar '{name}' dihapus.", show_alert=True)
        else:
            await query.answer("Radar tidak ditemukan.", show_alert=True)
        await query.edit_message_text(build_radar_text(), parse_mode="HTML", reply_markup=build_radar_keyboard())
        return
    
    # ── Radar: Check (manual run) ──
    if data.startswith("radar_check_"):
        uid = data.replace("radar_check_", "")
        from bot.jobs import load_screeners
        screeners = load_screeners()
        if uid not in screeners:
            await query.answer("Radar tidak ditemukan.", show_alert=True)
            return
        
        await query.answer("Menjalankan radar... tunggu.")
        cfg = screeners[uid]
        name = cfg.get("name", "?")
        filters = cfg.get("filters", [])
        sequence = cfg.get("sequence", [])
        
        from api.screener import run_screener, format_screener_rules
        from api.market import get_trade_book_chart
        from engines.smart_money import calc_money_flow_chart
        import html as html_mod
        from datetime import datetime
        import pytz
        
        try:
            res = await run_screener(filters, sequence, ordercol=2661, ordertype="desc", page=1)
            calcs = res.get("calcs", [])
            
            now_str = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%H:%M WIB")
            rules_text = format_screener_rules(filters)
            
            o = [
                f"<b>CHECK RADAR: {now_str}</b>",
                f"{html_mod.escape(name)}",
                f"Ditemukan {len(calcs)} saham.\n",
                f"<code>{rules_text}</code>",
                ""
            ]
            
            processed = []
            for c in calcs:
                sym = c["company"]["symbol"]
                
                # Extract price from results array (same as check_radar_command)
                price_str = "-"
                for r in c["results"]:
                    if r["id"] == 2661:
                        price_str = str(r["display"])
                
                f_price = 0.0
                try:
                    f_price = float(price_str.replace(",", ""))
                except:
                    pass
                
                # Fetch Clean Money (same as check_radar_command)
                cm_val = 0.0
                cm_text = "-"
                try:
                    tb = await get_trade_book_chart(sym)
                    mf = calc_money_flow_chart(tb, fallback_price=f_price)
                    if mf:
                        cm_val = float(mf["clean_money"])
                        if cm_val > 1_000_000_000 or cm_val < -1_000_000_000:
                            cm_text = f"Rp {cm_val/1_000_000_000:.1f} M"
                        else:
                            cm_text = f"Rp {cm_val/1_000_000:.1f} JT"
                    await asyncio.sleep(0.8)
                except:
                    pass
                
                processed.append({"sym": sym, "price": price_str, "cm_val": cm_val, "cm_text": cm_text})
            
            processed.sort(key=lambda x: x["cm_val"], reverse=True)
            
            for i, p in enumerate(processed[:10]):  # type: ignore
                o.append(f"<b>{i+1}. {p['sym']}</b>")
                o.append(f"<code>Price      : {p['price']:>10}</code>")
                o.append(f"<code>Clean Money: {p['cm_text']:>10}</code>")
                if i < 9 and i < len(processed)-1:
                    o.append("")
            
            if len(processed) > 10:
                watchlist = [f"{p['sym']} [{p['cm_text']}]" for p in processed[10:]]  # type: ignore
                o.append("")
                o.append(f"<b>Watchlist + :</b> [{', '.join(watchlist)}]")
            
            o.append("")
            o.append("<i>Mendeteksi akumulasi bandar berdasarkan Trade Book flow saat ini.</i>")
            
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                message_thread_id=query.message.message_thread_id,
                text="\n".join(o),
                parse_mode="HTML"
            )
        except Exception as e:
            log.error(f"Radar check via admin failed: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Gagal check radar: <code>{html_mod.escape(str(e))}</code>",
                parse_mode="HTML"
            )
        return
    
    # ── Radar: Edit Time (start conversation) ──
    if data.startswith("radar_edittime_"):
        uid = data.replace("radar_edittime_", "")
        from bot.jobs import load_screeners
        screeners = load_screeners()
        if uid not in screeners:
            await query.answer("Radar tidak ditemukan.", show_alert=True)
            return
        
        name = screeners[uid]["name"]
        current_time = screeners[uid]["time"]
        
        await query.answer()
        msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                f"<b>Edit Jadwal: {name}</b>\n"
                f"Waktu saat ini: <code>{current_time}</code>\n\n"
                f"Balas pesan ini dengan waktu baru (format <code>HH:MM</code>)\n"
                f"Contoh: <code>09:30</code> atau <code>14:00</code>"
            ),
            parse_mode="HTML"
        )
        
        _pending_time_edit[query.message.chat_id] = {
            "uid": uid,
            "name": name,
            "msg_id": msg.message_id
        }
        return

async def handle_time_edit_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called from main.py's message handler to catch time edit replies"""
    if not update.message:
        return False
        
    chat_id = update.message.chat_id
    user_id = update.effective_user.id
    
    if str(user_id) != str(ADMIN_CHAT_ID):
        return False
    
    if chat_id not in _pending_time_edit:
        return False
    
    pending = _pending_time_edit.pop(chat_id)
    uid = pending["uid"]
    name = pending["name"]
    prompt_msg_id = pending["msg_id"]
    
    raw_time = update.message.text.strip().replace(".", ":")
    
    # Validate format
    import re
    if not re.match(r"^\d{1,2}:\d{2}$", raw_time):
        await update.message.reply_text(
            "Format waktu salah. Gunakan <code>HH:MM</code>",
            parse_mode="HTML"
        )
        _pending_time_edit[chat_id] = pending  # Put it back
        return True
    
    # Pad hour
    if len(raw_time) == 4:
        raw_time = "0" + raw_time
    
    from bot.jobs import load_screeners, save_screeners, load_screener_jobs
    screeners = load_screeners()
    if uid in screeners:
        screeners[uid]["time"] = raw_time
        save_screeners(screeners)
        load_screener_jobs(context.application)
        
        await update.message.reply_text(
            f"Jadwal <b>{name}</b> diubah ke <code>{raw_time}</code> WIB.",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("Radar tidak ditemukan lagi.", parse_mode="HTML")
    
    # Clean up prompt message
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=prompt_msg_id)
    except:
        pass
    
    return True

async def handle_token_edit_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called from main.py's message handler to catch token edit replies"""
    if not update.message:
        return False
        
    chat_id = update.message.chat_id
    user_id = update.effective_user.id
    
    if str(user_id) != str(ADMIN_CHAT_ID):
        return False
    
    if chat_id not in _pending_token_edit:
        return False
    
    prompt_msg_id = _pending_token_edit.pop(chat_id)
    
    raw_token = update.message.text.strip()
    
    # Try to delete user message (contains token)
    try:
        await update.message.delete()
    except:
        pass
        
    if len(raw_token) < 50:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Token terlalu pendek. Pastikan Anda mengirim JWT yang benar.",
            parse_mode="HTML"
        )
        _pending_token_edit[chat_id] = prompt_msg_id  # Put it back
        return True
        
    from api.auth import set_bearer_token
    success = set_bearer_token(raw_token)
    
    if success:
        await context.bot.send_message(chat_id=chat_id, text="✅ <b>ScopeBit Token Update SUKSES!</b>", parse_mode="HTML")
    else:
        await context.bot.send_message(chat_id=chat_id, text="❌ <b>Gagal update token.</b> Cek server logs.", parse_mode="HTML")
        
    # Clean up prompt message
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=prompt_msg_id)
    except:
        pass
        
    return True

async def handle_broadcast_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Called from main.py's message handler to catch broadcast replies"""
    if not update.message:
        return False
        
    chat_id = update.message.chat_id
    user_id = update.effective_user.id
    
    if str(user_id) != str(ADMIN_CHAT_ID):
        return False
    
    if chat_id not in _pending_broadcast_edit:
        return False
    
    prompt_msg_id = _pending_broadcast_edit.pop(chat_id)
    
    from bot.config import ALLOWED_CHAT_ID, ALLOWED_THREAD_ID
    if not ALLOWED_CHAT_ID:
        await context.bot.send_message(chat_id=chat_id, text="❌ <b>Gagal:</b> ALLOWED_CHAT_ID belum di set di .env", parse_mode="HTML")
        return True
        
    # Forward or copy message to the main group
    try:
        kwargs = {"chat_id": ALLOWED_CHAT_ID}
        if ALLOWED_THREAD_ID:
            kwargs["message_thread_id"] = ALLOWED_THREAD_ID
            
        await update.message.copy(
            **kwargs,
            reply_markup=update.message.reply_markup  # Preserve inline buttons if any
        )
        await context.bot.send_message(chat_id=chat_id, text="✅ <b>Broadcast berhasil dikirim!</b>", parse_mode="HTML")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ <b>Gagal kirim broadcast:</b> <code>{e}</code>", parse_mode="HTML")
        
    # Clean up prompt message
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=prompt_msg_id)
    except:
        pass
        
    return True


