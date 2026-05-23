"""
News Broadcast Engine — Scheduled news delivery to Telegram.
Fetches latest market news, deduplicates against sent history,
formats with sentiment + emiten tags, and sends to the news thread.
"""
import json
import os
import logging
import html
from datetime import datetime, timedelta, timezone

log = logging.getLogger("bot")

# ── Persistent Sent Tracker ──
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SENT_FILE = os.path.join(DATA_DIR, "news_sent.json")
# Rolling window: don't re-send articles sent within this period
DEDUP_HOURS = 48
# Max articles per broadcast cycle
MAX_PER_CYCLE = 5


def _load_sent() -> dict:
    """Load sent article URLs with timestamps."""
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_sent(data: dict):
    """Save sent tracker to disk."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Failed to save news sent tracker: {e}")


def _prune_sent(data: dict) -> dict:
    """Remove entries older than DEDUP_HOURS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)).isoformat()
    return {url: ts for url, ts in data.items() if ts > cutoff}





def format_news_message(articles: list[dict]) -> str:
    """
    Format a batch of articles into a single Telegram message.
    
    Output format:
    📰 BERITA PASAR TERBARU
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    🟢 [Title]
    🔗 link
    📌 Emiten: BBCA, BMRI
    📡 CNBC Indonesia
    
    🔴 [Title 2]
    ...
    """
    if not articles:
        return ""

    _WIB = timezone(timedelta(hours=7))
    now = datetime.now(_WIB)
    time_str = now.strftime("%H:%M WIB")

    L = "━" * 30
    lines = [
        f"<b>BERITA PASAR TERBARU</b>",
        f"<code>{L}</code>",
    ]

    for i, article in enumerate(articles):
        sentiment = article.get("sentiment", "Netral")
        title = html.escape(article.get("title", ""))
        link = article.get("link", "")
        source = html.escape(article.get("source", ""))

        # Article block with HTML href
        lines.append(f"<b><a href='{link}'>{title}</a></b>")

        # Separator between articles (not after last)
        if i < len(articles) - 1:
            lines.append("")

    lines.append(f"<code>{L}</code>")
    lines.append(f"<i>⚠️ Disclaimer: Bukan ajakan jual/beli.</i>")
    lines.append(f"<i>⏰ Update: {time_str}</i>")

    return "\n".join(lines)


async def get_new_articles() -> list[dict]:
    """
    Fetch latest news and filter out already-sent articles.
    Returns only NEW articles (max MAX_PER_CYCLE).
    """
    from api.news import get_latest_news

    all_articles = await get_latest_news(limit=20)
    if not all_articles:
        return []

    # Load and prune sent tracker
    sent = _prune_sent(_load_sent())

    new_articles = []
    for article in all_articles:
        url_key = article["link"].split("?")[0].rstrip("/").lower()
        if url_key not in sent:
            new_articles.append(article)
            if len(new_articles) >= MAX_PER_CYCLE:
                break

    return new_articles


def mark_as_sent(articles: list[dict]):
    """Mark articles as sent in the persistent tracker."""
    sent = _prune_sent(_load_sent())
    now_iso = datetime.now(timezone.utc).isoformat()

    for article in articles:
        url_key = article["link"].split("?")[0].rstrip("/").lower()
        sent[url_key] = now_iso

    _save_sent(sent)
