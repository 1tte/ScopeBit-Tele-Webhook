import json
import os
from typing import Dict

SCREENERS_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'screeners.json')

def load_screeners() -> Dict:
    if os.path.exists(SCREENERS_FILE):
        try:
            with open(SCREENERS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_screeners(data: Dict):
    os.makedirs(os.path.dirname(SCREENERS_FILE), exist_ok=True)
    with open(SCREENERS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

import logging
from telegram.ext import ContextTypes
from telegram import Bot
import html
from bot.config import ALLOWED_CHAT_ID, ALLOWED_THREAD_ID

log = logging.getLogger("bot")

async def run_scheduled_radar(context: ContextTypes.DEFAULT_TYPE):
    """Execution triggered by JobQueue at specific times."""
    from datetime import datetime
    import pytz
    if datetime.now(pytz.timezone("Asia/Jakarta")).weekday() >= 5:
        log.info("Radar skipped: Weekend detected.")
        return
    job = context.job
    if not job or not job.data:
        return
    
    cfg = job.data
    name = cfg.get("name", "Unknown Radar")
    filters = cfg.get("filters", [])
    sequence = cfg.get("sequence", [])

    from api.screener import run_screener
    from api.market import get_trade_book_chart
    from engines.smart_money import calc_money_flow_chart

    log.info(f"Running automated screener '{name}'...")
    try:
        res = await run_screener(filters, sequence, ordercol=2661, ordertype="desc", page=1)
        calcs = res.get("calcs", [])
        total = res.get("totalrows", len(calcs))

        if not calcs:
             log.info(f"Radar {name} empty.")
             return

        o = []
        from datetime import datetime
        import pytz
        now_str = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%H:%M WIB")
        o.append(f"<b>⏱️ RADAR OTOMATIS: {now_str}</b>\n<code>{html.escape(name)}</code>")
        
        from api.screener import format_screener_rules
        rules_text = format_screener_rules(filters)
        o.append(f"<code>{rules_text}</code>")
        o.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        o.append(f"<code>Ditemukan {total} saham yang masuk kriteria:</code>\n")

        processed = []
        import asyncio
        for c in calcs:
            sym = c['company']['symbol']
            
            price_str = "-"
            for r in c["results"]:
                if r["id"] == 2661: price_str = str(r["display"])
                
            f_price = 0.0
            try:
                f_price = float(price_str.replace(",", ""))  # type: ignore
            except Exception:
                pass
                
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

        processed.sort(key=lambda x: x["cm_val"], reverse=True)  # type: ignore

        for i, p in enumerate(processed[:10]):  # type: ignore
            o.append(f"<b>{i+1}. {p['sym']}</b>")
            o.append(f"<code>Price      : {p['price']:>10}</code>")
            o.append(f"<code>Clean Money: {p['cm_text']:>10}</code>")
            if i < 9 and i < len(processed)-1:
                o.append("")

        if len(processed) > 10:
            watchlist = []
            for p in processed[10:]:  # type: ignore
                watchlist.append(f"{p['sym']} [{p['cm_text']}]")
            
            o.append("━━━━━━━━━━━━━━━━━━━━━━━━")
            o.append(f"<b>Watchlist + :</b> [{', '.join(watchlist)}]")

        o.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        o.append("<i>⚠️ Disclaimer: Bukan ajakan jual/beli. Pesan otomatis dihapus dalam 1 hari.</i>")

        if ALLOWED_CHAT_ID:
            sent_msg = await context.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=ALLOWED_THREAD_ID if ALLOWED_THREAD_ID else None,
                text="\n".join(o),
                parse_mode="HTML"
            )
            
            from bot.handlers import schedule_auto_delete
            import time
            delete_at = int(time.time()) + 86400
            schedule_auto_delete(ALLOWED_CHAT_ID, sent_msg.message_id, sent_msg.message_id, delete_at)
        
    except Exception as e:
        log.error(f"Failed to run automated radar {name}: {e}")

async def run_scheduled_token_refresh(context: ContextTypes.DEFAULT_TYPE):
    """Proactively refresh ScopeBit token before it expires."""
    from api.auth import refresh_stockbit_token
    from bot.config import ADMIN_CHAT_ID
    log.info("AUTO-REFRESH | Running scheduled token refresh...")
    try:
        result = await refresh_stockbit_token()
        if result:
            if result.get("debounced"):
                log.info("AUTO-REFRESH | Skipped (debounced)")
            else:
                expires = result.get('access_expired_at', '?')
                log.info(f"AUTO-REFRESH | Success — new token expires at {expires}")
                if ADMIN_CHAT_ID:
                    msg = (
                        "🔄 <b>Token Refresh Sukses (Backup)</b>\n\n"
                        f"<b>Access Token:</b>\n<code>{result.get('access_token')}</code>\n\n"
                        f"<b>Refresh Token:</b>\n<code>{result.get('refresh_token')}</code>\n\n"
                        f"<i>Expires: {expires}</i>"
                    )
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode="HTML")
        else:
            log.warning("AUTO-REFRESH | Refresh returned None — refresh token may be invalid")
    except Exception as e:
        log.error(f"AUTO-REFRESH | Failed: {e}")



async def run_scheduled_ihsg_radar(context: ContextTypes.DEFAULT_TYPE):
    """Fires at 08:00 and 16:30 WIB to provide IHSG sentiment summary."""
    import pytz
    from datetime import datetime
    import asyncio
    
    if datetime.now(pytz.timezone("Asia/Jakarta")).weekday() >= 5:
        log.info("IHSG Radar skipped: Weekend detected.")
        return
        
    log.info("Running automated IHSG Sentiment Radar...")
    from api.buzzer import fetch_ihsg_summary
    from engines.ihsg import format_ihsg_report
    from api.indopremier import fetch_global_indices
    
    try:
        source_mode = context.job.data.get("source_mode", "morning")
        
        # Concurrently fetch sentiment + live indices
        data, indices = await asyncio.gather(
            fetch_ihsg_summary(days_back=1, source_mode=source_mode),
            fetch_global_indices()
        )
        
        report_str, img_path = format_ihsg_report(data, indices)
        
        chat_id = ALLOWED_CHAT_ID or context.job.chat_id
        thread_id = ALLOWED_THREAD_ID if ALLOWED_THREAD_ID else None
        
        if chat_id:
            if img_path:
                with open(img_path, 'rb') as f:
                    await context.bot.send_photo(
                        chat_id=chat_id, photo=f,
                        message_thread_id=thread_id
                    )
            await context.bot.send_message(
                chat_id=chat_id, text=report_str, parse_mode="HTML",
                disable_web_page_preview=True, message_thread_id=thread_id
            )
    except Exception as e:
        log.error(f"IHSG Radar auto-pilot failed: {e}")

async def run_scheduled_news_broadcast(context: ContextTypes.DEFAULT_TYPE):
    """Fetch and broadcast latest market news to the news thread."""
    from bot.config import ALLOWED_CHAT_ID, NEWS_THREAD_ID
    from engines.news_broadcast import get_new_articles, format_news_message, mark_as_sent

    if not ALLOWED_CHAT_ID or not NEWS_THREAD_ID:
        log.warning("NEWS | Skipping: ALLOWED_CHAT_ID or NEWS_THREAD_ID not set")
        return

    try:
        articles = await get_new_articles()
        if not articles:
            log.info("NEWS | No new articles to broadcast")
            return

        message = format_news_message(articles)
        if not message:
            return

        await context.bot.send_message(
            chat_id=ALLOWED_CHAT_ID,
            message_thread_id=NEWS_THREAD_ID,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        # Mark as sent AFTER successful send
        mark_as_sent(articles)
        log.info(f"NEWS | Broadcast {len(articles)} articles to thread {NEWS_THREAD_ID}")

    except Exception as e:
        log.error(f"NEWS | Broadcast failed: {e}")

async def run_scheduled_jarvis_single_stone(context: ContextTypes.DEFAULT_TYPE):
    """Run a single JARVIS stone and send TXT report to JARVIS thread."""
    from datetime import datetime
    import pytz
    if datetime.now(pytz.timezone("Asia/Jakarta")).weekday() >= 5:
        log.info("JARVIS Single Stone skipped: Weekend detected.")
        return
    from bot.config import ALLOWED_CHAT_ID, JARVIS_THREAD_ID
    if not ALLOWED_CHAT_ID:
        return

    from bot.admin import read_env_toggles
    toggles = read_env_toggles()
    if not toggles.get("CMD_JARVIS_ENABLED", True):
        log.info("JARVIS Auto-Pilot is disabled in admin settings. Skipping scheduled run.")
        return

    job = context.job
    if not job or not job.data:
        return
    
    stone_name = job.data.get("stone_name")
    if not stone_name:
        return

    from engines.jarvis import run_stone, generate_stone_report
    import asyncio

    log.info(f"JARVIS Single Stone: Starting {stone_name} scan...")

    try:
        stocks = await run_stone(stone_name)
        caption, img_doc, txt_doc = generate_stone_report(stone_name, stocks)

        if img_doc:
            await context.bot.send_photo(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=JARVIS_THREAD_ID if JARVIS_THREAD_ID else None,
                photo=img_doc,
                caption=caption,
                parse_mode="HTML"
            )
            await context.bot.send_document(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=JARVIS_THREAD_ID if JARVIS_THREAD_ID else None,
                document=txt_doc,
                filename=f"JARVIS_{stone_name}_{len(stocks)}.txt"
            )
        else:
            await context.bot.send_document(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=JARVIS_THREAD_ID if JARVIS_THREAD_ID else None,
                document=txt_doc,
                filename=f"JARVIS_{stone_name}_{len(stocks)}.txt",
                caption=caption,
                parse_mode="HTML"
            )
        log.info(f"JARVIS Single Stone: Sent {stone_name} ({len(stocks)} stocks)")
    except Exception as e:
        log.error(f"JARVIS Single Stone: Failed to run {stone_name}: {e}")
        import traceback
        log.error(f"Traceback: {traceback.format_exc()}")

async def run_scheduled_jarvis_reports(context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime
    import pytz
    if datetime.now(pytz.timezone("Asia/Jakarta")).weekday() >= 5:
        log.info("JARVIS Full Report skipped: Weekend detected.")
        return
    from bot.config import ALLOWED_CHAT_ID, JARVIS_THREAD_ID
    if not ALLOWED_CHAT_ID: return
    
    from bot.admin import read_env_toggles
    toggles = read_env_toggles()
    if not toggles.get("CMD_JARVIS_ENABLED", True):
        log.info("JARVIS Auto-Pilot is disabled in admin settings. Skipping scheduled reports.")
        return
    
    # 1. Leaderboard
    try:
        from engines.jarvis import get_leaderboard
        board = get_leaderboard()
        if board:
            await context.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=JARVIS_THREAD_ID if JARVIS_THREAD_ID else None,
                text=board,
                parse_mode="HTML"
            )
    except Exception as e:
        log.error(f"Auto Leaderboard error: {e}")
        
    # 2. Daily Verdict (Eval)
    try:
        import asyncio
        await asyncio.sleep(2)
        from engines.jarvis import generate_daily_verdict
        verdict = generate_daily_verdict()
        if verdict:
            await context.bot.send_message(
                chat_id=ALLOWED_CHAT_ID,
                message_thread_id=JARVIS_THREAD_ID if JARVIS_THREAD_ID else None,
                text=verdict,
                parse_mode="HTML"
            )
    except Exception as e:
        log.error(f"Auto Verdict error: {e}")

def load_screener_jobs(application):
    """Loads screeners from JSON and registers them into Python Telegram Bot's JobQueue."""
    from datetime import datetime
    import pytz
    
    screeners = load_screeners()
    tz = pytz.timezone("Asia/Jakarta")
    queue = application.job_queue
    
    for job in queue.jobs():
        if job.name and job.name.startswith("radar_"):
            job.schedule_removal()
            
    for uuid, cfg in screeners.items():
        time_str = cfg.get("time") # expected "09:30"
        if not time_str: continue
        
        try:
            h, m = map(int, time_str.split(":"))
            t = datetime.strptime(f"{h}:{m}", "%H:%M").time().replace(tzinfo=tz)
            
            queue.run_daily(
                run_scheduled_radar,
                time=t,
                days=(0, 1, 2, 3, 4, 5, 6),
                data=cfg,
                name=f"radar_{uuid}",
                job_kwargs={"misfire_grace_time": 60}
            )
            log.info(f"Loaded scheduled screener '{cfg['name']}' at {time_str} WIB.")
        except Exception as e:
            log.error(f"Error scheduling radar {uuid}: {e}")

    # --- JARVIS Auto-Pilot Schedule (Each stone at its own time) ---
    import datetime as dt
    from engines.jarvis import JARVIS_STONES, STONE_ORDER

    # Remove any existing jarvis jobs first
    for job in list(queue.jobs()):
        if job.name and (job.name.startswith("jarvis_stone_") or job.name.startswith("jarvis_verdict_")):
            job.schedule_removal()

    # Schedule each stone at its specified time from JARVIS_STONES
    for stone_name in STONE_ORDER:
        if stone_name not in JARVIS_STONES:
            continue
        
        stone_config = JARVIS_STONES[stone_name]
        time_str = stone_config.get("time", "09:00")  # Default to 09:00 if not set
        
        try:
            h, m = map(int, time_str.split(":"))
            t = dt.time(h, m, tzinfo=tz)
            
            queue.run_daily(
                run_scheduled_jarvis_single_stone,
                time=t,
                days=(0, 1, 2, 3, 4),  # Mon-Fri
                data={"stone_name": stone_name},
                name=f"jarvis_stone_{stone_name}",
                job_kwargs={"misfire_grace_time": 120}
            )
            log.info(f"JARVIS Scheduled: {stone_name} at {time_str} WIB")
        except Exception as e:
            log.error(f"Error scheduling jarvis stone {stone_name}: {e}")

    # --- JARVIS Reports (Leaderboard + Verdict) ---
    # Run at 09:30 (morning after morning stones) and 16:00 (afternoon after afternoon stones)
    t_verdict_morning = dt.time(9, 30, tzinfo=tz)
    queue.run_daily(
        run_scheduled_jarvis_reports,
        time=t_verdict_morning,
        days=(0, 1, 2, 3, 4),
        name="jarvis_verdict_morning",
        job_kwargs={"misfire_grace_time": 60}
    )

    t_verdict_afternoon = dt.time(16, 0, tzinfo=tz)
    queue.run_daily(
        run_scheduled_jarvis_reports,
        time=t_verdict_afternoon,
        days=(0, 1, 2, 3, 4),
        name="jarvis_verdict_afternoon",
        job_kwargs={"misfire_grace_time": 60}
    )

    log.info("JARVIS Auto-Pilot: Each stone scheduled at its own time | Verdict at 09:30 & 16:00 WIB")

    # --- IHSG Morning Briefing ---
    t_ihsg_morning = dt.time(8, 0, tzinfo=tz)
    queue.run_daily(
        run_scheduled_ihsg_radar,
        time=t_ihsg_morning,
        days=(0, 1, 2, 3, 4),
        name="ihsg_morning_briefing",
        data={"source_mode": "morning"},
        job_kwargs={"misfire_grace_time": 120}
    )
    
    # --- IHSG Closing Recap ---
    t_ihsg_afternoon = dt.time(16, 30, tzinfo=tz)
    queue.run_daily(
        run_scheduled_ihsg_radar,
        time=t_ihsg_afternoon,
        days=(0, 1, 2, 3, 4),
        name="ihsg_closing_recap",
        data={"source_mode": "full"},
        job_kwargs={"misfire_grace_time": 120}
    )
    log.info("IHSG Sentiment Radar: Morning Briefing 08:00 WIB | Closing Recap 16:30 WIB")

    # --- Proactive Token Auto-Refresh (every 20 hours) ---
    queue.run_repeating(
        run_scheduled_token_refresh,
        interval=20 * 3600,  # 20 hours in seconds
        first=300,           # First run 5 minutes after startup
        name="token_auto_refresh",
        job_kwargs={"misfire_grace_time": 120}
    )
    log.info("TOKEN Auto-Refresh: Scheduled every 20 hours")
    
    # --- News Broadcast Schedule (every 45 minutes) ---
    queue.run_repeating(
        run_scheduled_news_broadcast,
        interval=45 * 60,   # 45 minutes in seconds
        first=60,           # First run 1 minute after startup
        name="news_broadcast",
        job_kwargs={"misfire_grace_time": 60}
    )
    log.info("NEWS Broadcast: Scheduled every 45 minutes")

