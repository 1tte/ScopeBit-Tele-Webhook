from datetime import datetime
import pytz

def format_ticker_news_report(data: dict) -> str:
    """Formats the specific stock news data into a Telegram HTML message."""
    symbol = data.get("symbol", "UNKNOWN")
    articles = data.get("articles", [])
    sentiment = data.get("sentiment", {})
    emotions = data.get("top_emotions", [])
    
    # Calculate percentages
    total = sum(sentiment.values())
    if total > 0:
        pos_pct = (sentiment.get('positive', 0) / total) * 100
        neg_pct = (sentiment.get('negative', 0) / total) * 100
        neu_pct = (sentiment.get('neutral', 0) / total) * 100
        
        if pos_pct > neg_pct and pos_pct > 35:
            mood_str = "BULLISH"
        elif neg_pct > pos_pct and neg_pct > 35:
            mood_str = "BEARISH"
        else:
            mood_str = "NEUTRAL"
    else:
        pos_pct = neg_pct = neu_pct = 0
        mood_str = "NO DATA"

    from datetime import timedelta
    tz = pytz.timezone("Asia/Jakarta")
    now = datetime.now(tz)
    days_back = data.get("days_back", 7)
    past = now - timedelta(days=days_back)
    
    bulan = ["Januari","Februari","Maret","April","Mei","Juni","Juli","Agustus","September","Oktober","November","Desember"]
    start_str = f"{past.day} {bulan[past.month - 1]} {past.year}"
    end_str = f"{now.day} {bulan[now.month - 1]} {now.year}"

    L = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    lines = [
        f"<b>{symbol} SENTIMENT RADAR</b>",
        f"<code>{L}</code>",
        f"<b>TICKER NEWS BRIEFING</b>",
        f"Periode : {start_str} - {end_str}",
        "",
        f"Market Pulse : <b>{mood_str}</b>",
        f"<code>  Positive   : {pos_pct:.1f}% ({sentiment.get('positive', 0)} post)</code>",
        f"<code>  Negative   : {neg_pct:.1f}% ({sentiment.get('negative', 0)} post)</code>",
        f"<code>  Neutral    : {neu_pct:.1f}% ({sentiment.get('neutral', 0)} post)</code>",
    ]

    if emotions:
        emo_str = " | ".join([e.title() for e in emotions])
        lines.extend([
            "",
            f"Dominant Emotion: <b>{emo_str}</b>",
        ])

    lines.extend([
        f"<code>{L}</code>",
        "<b>REKAP BERITA TERKAIT:</b>"
    ])

    if not articles:
        lines.append("<i>Tidak ada berita signifikan dalam 7 hari terakhir.</i>")
    else:
        for idx, news in enumerate(articles, 1):
            title = news['title'].replace('<', '&lt;').replace('>', '&gt;')
            link = news['link']
            
            if link:
                lines.append(f"• <a href='{link}'>{title}</a>")
            else:
                lines.append(f"• {title}")

    lines.extend([
        f"<code>{L}</code>",
        "<i>Filter: Relevansi tinggi | Window: 7 Hari</i>"
    ])

    return "\n".join(lines)
