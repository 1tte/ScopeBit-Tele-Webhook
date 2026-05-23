import logging
import asyncio
import os
import sys
import psutil
import time
import json
from functools import wraps
from telegram import Update
import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

from api.client import api_request_counter
from bot.config import TELEGRAM_BOT_TOKEN, BOT_MODE, ALLOWED_CHAT_ID, ALLOWED_THREAD_ID
from bot.handlers import (
    start_command, help_command, sm_command, bandar_command, fa_command, swing_command,
    dt_command, scanner_command, debug_handler, im_command, fc_command, report_command,
    refresh_command, token_command, token_refresh_command, new_member_handler, add_radar_command, del_radar_command,
    list_radar_command, check_radar_command, help_radar_command,
    tps_command, tpd_command, ihsg_command, news_command,
    is_allowed, send_auto_delete_error
)

# Suppress noisy library logs, enable our bot logger
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logging.basicConfig(
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)

_global_lock = asyncio.Lock()
_global_last_cmd_time = 0.0

def with_request_logging(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        # We handle button callbacks (CallbackQuery) and normal commands (Message)
        if hasattr(update, 'callback_query') and update.callback_query:
            user = update.callback_query.from_user
            msg = update.callback_query.message
        else:
            user = update.message.from_user if update.message else None
            msg = update.message
            
        if not user or not msg:
            return await func(update, context, *args, **kwargs)
            
        global _global_last_cmd_time
        
        # Determine if we should wait
        if _global_lock.locked() or (time.time() - _global_last_cmd_time < 15.0):
            wait_msg = None
            # Only send wait message for actual chat messages, not inline buttons
            if not (hasattr(update, 'callback_query') and update.callback_query):
                try:
                    wait_msg = await msg.reply_text("⏳ <i>Menunggu antrian ...</i>", parse_mode="HTML")
                except Exception:
                    pass
            
            async with _global_lock:
                now = time.time()
                elapsed_since_last = now - _global_last_cmd_time
                if elapsed_since_last < 15.0:
                    await asyncio.sleep(15.0 - elapsed_since_last)
                    _global_last_cmd_time = time.time()
                else:
                    _global_last_cmd_time = now
                    
                if wait_msg:
                    try:
                        await wait_msg.delete()
                    except Exception:
                        pass
                
                # Now we have the lock and cooldown has elapsed.
                api_request_counter.set({"count": 0})
                start_t = time.time()
                try:
                    res = await func(update, context, *args, **kwargs)
                    _global_last_cmd_time = time.time()  # Update time AFTER command finishes
                    return res
                finally:
                    tracker = api_request_counter.get()
                    count = tracker["count"] if tracker else 0
                    elapsed = time.time() - start_t
                    cmd_name = func.__name__ if hasattr(func, '__name__') else "Command"
                    user_str = f"@{user.username}" if user.username else user.first_name
                    log = logging.getLogger("bot")
                    log.info(f"MONITOR PYL | {cmd_name} | User: {user_str} | API Requests = {count} | Time: {elapsed:.2f}s")
        else:
            async with _global_lock:
                _global_last_cmd_time = time.time()
                api_request_counter.set({"count": 0})
                start_t = time.time()
                try:
                    res = await func(update, context, *args, **kwargs)
                    _global_last_cmd_time = time.time()
                    return res
                finally:
                    tracker = api_request_counter.get()
                    count = tracker["count"] if tracker else 0
                    elapsed = time.time() - start_t
                    cmd_name = func.__name__ if hasattr(func, '__name__') else "Command"
                    user_str = f"@{user.username}" if user.username else user.first_name
                    log = logging.getLogger("bot")
                    log.info(f"MONITOR PYL | {cmd_name} | User: {user_str} | API Requests = {count} | Time: {elapsed:.2f}s")
    return wrapper

def kill_old_instances():
    """Membunuh proses bot.py lama yang masih berjalan di background."""
    current_pid = os.getpid()
    script_name = os.path.basename(sys.argv[0])

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Lewati proses saat ini
            if proc.info['pid'] == current_pid:
                continue
                
            # Jika prosesnya adalah python dan menjalankan script yang sama
            if proc.info['cmdline'] and script_name in proc.info['cmdline']:
                proc.terminate() 
                proc.wait(timeout=3)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

async def post_shutdown(application: Application):
    pass

async def auto_delete_worker(app: Application):
    """Background task that runs every 6 hours to delete expired messages from auto_delete.json"""
    file_path = os.path.join(os.path.dirname(__file__), 'data', 'auto_delete.json')
    while True:
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        data = []
                
                now = time.time()
                remaining = []
                modified = False
                
                for item in data:
                    if now >= item.get("delete_at", 0):
                        modified = True
                        chat_id = item["chat_id"]
                        
                        # Delete user message
                        try:
                            await app.bot.delete_message(chat_id=chat_id, message_id=item["user_msg_id"])
                        except Exception:
                            pass # Probably already deleted or bot lacks admin rights
                            
                        # Delete bot message
                        try:
                            await app.bot.delete_message(chat_id=chat_id, message_id=item["bot_msg_id"])
                        except Exception:
                            pass
                    else:
                        remaining.append(item)
                
                if modified:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(remaining, f, indent=2)
                        
        except Exception as e:
            logging.getLogger("bot").error(f"Auto-delete worker error: {e}")
            
        await asyncio.sleep(21600)  # 6 hours = 6 * 60 * 60 seconds

def main():
    if not TELEGRAM_BOT_TOKEN:
        return

    # Ensure an event loop exists in the main thread for Python 3.10+
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    log = logging.getLogger("bot")

    import pytz
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .job_queue(
            telegram.ext.JobQueue() if hasattr(telegram.ext, 'JobQueue') else None,
            # We must pass JobQueue instances but python-telegram-bot handles defaults via builder kwargs in v20+
        )
        .post_shutdown(post_shutdown)
        .build()
    )
    # The timezone on JobQueue determines the reference timezone for time-based jobs.
    if application.job_queue:
        application.job_queue.scheduler.timezone = pytz.timezone("Asia/Jakarta")

    application.add_handler(CommandHandler("start", with_request_logging(start_command)))
    application.add_handler(CommandHandler("help", with_request_logging(help_command)))
    # Feature commands — check .env at RUNTIME so /admin toggles work without restart
    from bot.admin import read_env_toggles
    
    def _make_toggled_handler(cmd_key, enabled_func, cmd_name):
        """Creates a handler that checks .env at runtime"""
        async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            toggles = read_env_toggles()
            if toggles.get(cmd_key, True):
                return await enabled_func(update, context)
            else:
                if not await is_allowed(update): return
                await send_auto_delete_error(update, context, f"Fitur <code>{cmd_name}</code> sedang dinonaktifkan oleh admin.")
        return _handler
    
    application.add_handler(CommandHandler("sm", with_request_logging(_make_toggled_handler("CMD_SM_ENABLED", sm_command, "/sm"))))
    application.add_handler(CommandHandler("br", with_request_logging(_make_toggled_handler("CMD_BR_ENABLED", bandar_command, "/br"))))
    application.add_handler(CommandHandler("fa", with_request_logging(_make_toggled_handler("CMD_FA_ENABLED", fa_command, "/fa"))))
    application.add_handler(CommandHandler("sw", with_request_logging(_make_toggled_handler("CMD_SW_ENABLED", swing_command, "/sw"))))
    application.add_handler(CommandHandler("dt", with_request_logging(_make_toggled_handler("CMD_DT_ENABLED", dt_command, "/dt"))))
    application.add_handler(CommandHandler("tps", with_request_logging(_make_toggled_handler("CMD_SW_ENABLED", tps_command, "/tps"))))
    application.add_handler(CommandHandler("tpd", with_request_logging(_make_toggled_handler("CMD_DT_ENABLED", tpd_command, "/tpd"))))
    application.add_handler(CommandHandler("rcm", with_request_logging(_make_toggled_handler("CMD_RCM_ENABLED", scanner_command, "/rcm"))))
    application.add_handler(CommandHandler("im", with_request_logging(_make_toggled_handler("CMD_IM_ENABLED", im_command, "/im"))))
    application.add_handler(CommandHandler("fc", with_request_logging(_make_toggled_handler("CMD_FC_ENABLED", fc_command, "/fc"))))
    application.add_handler(CommandHandler("ihsg", with_request_logging(ihsg_command)))
    application.add_handler(CommandHandler("news", with_request_logging(news_command)))
    application.add_handler(CommandHandler("report", with_request_logging(report_command)))
    application.add_handler(CommandHandler("refresh", with_request_logging(refresh_command)))
    application.add_handler(CommandHandler("token", with_request_logging(token_command)))
    application.add_handler(CommandHandler(
        # We handle "token_refresh" since hyphens break clickable commands in Telegram
        "token_refresh", 
        with_request_logging(token_refresh_command)
    ))
    application.add_handler(CommandHandler("add_radar", with_request_logging(add_radar_command)))
    application.add_handler(CommandHandler("del_radar", with_request_logging(del_radar_command)))
    application.add_handler(CommandHandler("list_radar", with_request_logging(list_radar_command)))
    application.add_handler(CommandHandler("check_radar", with_request_logging(check_radar_command)))
    application.add_handler(CommandHandler("help_radar", with_request_logging(help_radar_command)))
    
    # Admin Control Panel
    from bot.admin import admin_panel_command, admin_callback_handler, handle_time_edit_reply, handle_token_edit_reply, handle_broadcast_reply
    application.add_handler(CommandHandler("admin", with_request_logging(admin_panel_command)))
    application.add_handler(CallbackQueryHandler(admin_callback_handler))
    
    # Admin time/token/broadcast-edit reply interceptor (before debug handler)
    async def _admin_text_interceptor(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await handle_time_edit_reply(update, context): return
        if await handle_token_edit_reply(update, context): return
        if await handle_broadcast_reply(update, context): return
        # If handled, stop propagation; otherwise let debug_handler take over
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), _admin_text_interceptor), group=0)
    
    # Also catch photos/documents for broadcast
    application.add_handler(MessageHandler(
        (filters.PHOTO | filters.Document.ALL | filters.VIDEO) & (~filters.COMMAND), 
        _admin_text_interceptor
    ), group=0)
    
    # New Member Greetings
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler))
    
    # Debug handler: logs EVERYTHING in group 1 (runs in parallel with commands)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), debug_handler), group=1)

    mode_emoji = "🔧" if BOT_MODE == "debug" else "🚀"
    log.info(f"{mode_emoji} Bot started in [{BOT_MODE.upper()}] mode")
    log.info(f"   Allowed Chat: {ALLOWED_CHAT_ID or 'ANY'} | Thread: {ALLOWED_THREAD_ID or 'ANY'}")
    
    # Start the background auto-delete worker
    # We need an event loop to create a task. run_polling creates its own later.
    # The recommended python-telegram-bot way is to use post_init.
    
    async def post_init(app: Application):
        asyncio.create_task(auto_delete_worker(app))
        
        # Load Scheduled Screeners
        from bot.jobs import load_screener_jobs
        load_screener_jobs(app)
        
        # Send startup confirmation to admin chat
        if ALLOWED_CHAT_ID:
            from datetime import datetime
            import pytz
            now_str = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%H:%M:%S WIB")
            try:
                msg = await app.bot.send_message(
                    chat_id=ALLOWED_CHAT_ID,
                    message_thread_id=ALLOWED_THREAD_ID if ALLOWED_THREAD_ID else None,
                    text=f"<b>Bot Online</b> - {now_str}\nMode: <code>{BOT_MODE.upper()}</code>",
                    parse_mode="HTML"
                )
                # Auto-delete after 1 minute
                async def _del():
                    await asyncio.sleep(60)
                    try: await msg.delete()
                    except: pass
                asyncio.create_task(_del())
            except Exception as e:
                log.error(f"Failed to send startup notification: {e}")
        
    application.post_init = post_init

    log.info("Starting bot in polling mode...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    # Panggil fungsi kill sebelum bot benar-benar berjalan
    kill_old_instances()
    main()