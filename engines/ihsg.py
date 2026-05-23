import os
from datetime import datetime
import pytz
import html

def format_ihsg_report(data: dict, indices: dict | None = None) -> tuple[str, str]:
    """
    Format the IHSG sentiment summary into an elegant Telegram message.
    Returns: (formatted_string, absolute_image_path)
    """
    tz = pytz.timezone("Asia/Jakarta")
    now_str = datetime.now(tz).strftime("%H:%M WIB")
    
    total = data.get('total_analyzed', 0)
    sentiment = data.get('sentiment', {'positive': 0, 'negative': 0, 'neutral': 0})
    source_mode = data.get('source_mode', 'full')
    
    pos = sentiment.get('positive', 0)
    neg = sentiment.get('negative', 0)
    neu = sentiment.get('neutral', 0)
    
    total_sent = pos + neg + neu
    global_mood = data.get('global_mood', 'NO DATA')
    global_analyzed = data.get('global_analyzed', 0)
    
    if total_sent == 0:
        return ("Belum ada data sentimen IHSG yang signifikan.", None)
        
    pos_pct = (pos / total_sent) * 100
    neg_pct = (neg / total_sent) * 100
    neu_pct = (neu / total_sent) * 100

    img_path = None
    # Determine core mood
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if pos_pct > neg_pct and pos_pct > 35:
        mood_str = "BULLISH"
        signal = "Optimisme sentimen publik menguat. Proyeksi IHSG berpotensi naik."
        img_path = os.path.join(root_dir, 'data', 'Bullish.png')
    elif neg_pct > pos_pct and neg_pct > 30:
        mood_str = "BEARISH"
        signal = "Kewaspadaan pasar tinggi. Tekanan isu negatif mendominasi indeks."
        img_path = os.path.join(root_dir, 'data', 'Bearish.png')
    else:
        mood_str = "NETRAL / CONSOLIDATING"
        signal = "Sentimen tidak memiliki arah pasti. Pasar dalam fase *Wait and See*."

    # Sub-header based on session
    session_title = "MORNING NEWS BRIEFING" if source_mode == "morning" else "CLOSING SENTIMENT RECAP"
    
    # Indonesian month names
    bulan = ["Januari","Februari","Maret","April","Mei","Juni","Juli","Agustus","September","Oktober","November","Desember"]
    now = datetime.now(tz)
    date_str = f"{now.day} {bulan[now.month - 1]} {now.year}"

    L = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    lines = [
        "<b>IHSG SENTIMENT RADAR</b>",
        f"<code>{L}</code>",
        f"<b>{session_title}</b>",
        f"Data tanggal {date_str}",
        "",
        f"Market Pulse : <b>{mood_str}</b>",
        f"<code>  Positive   : {pos_pct:.1f}% ({pos} post)</code>",
        f"<code>  Negative   : {neg_pct:.1f}% ({neg} post)</code>",
        f"<code>  Neutral    : {neu_pct:.1f}% ({neu} post)</code>",
        "",
        f"Asia/Global  : <b>{global_mood}</b>",
        f"<code>  (Data dari bursa Nikkei, HSI, Wall Street - {global_analyzed} Berita)</code>"
    ]
    
    if indices:
        lines.append("")
        lines.append("<b>GLOBAL INDICES (REAL-TIME):</b>")
        lines.append("<code>")
        for name, pchg in indices.items():
            lines.append(f" • {name:<16}: {pchg:>7}")
        lines.append("</code>")
    
    emotions = data.get('top_emotions', [])
    if emotions:
        emotions_title = [e.title() for e in emotions]
        lines.append(f"\nTop Emotions : <b>{', '.join(emotions_title)}</b>")
        
    lines.append(f"Database     : {total} publications analyzed.")
    
    lines.append(f"\n<code>{L}</code>")
    lines.append("<b>REKAP TOPIK BERITA UTAMA:</b>")
    
    if not data.get('recent_news'):
        lines.append("Tidak ada isu signifikan.")
    else:
        for n in data.get('recent_news', []):
            title = html.escape(n.get('title', ''))
            link = n.get('link', '')
            if link:
                lines.append(f"• <a href='{link}'>{title}</a>")
            else:
                lines.append(f"• {title}")
                
    lines.append(f"\n<b>Kesimpulan:</b>\n{signal}")
    lines.append(f"<code>{L}</code>")
    lines.append(f"<i>Update: {now_str}</i>")
    
    return ("\n".join(lines), img_path)
