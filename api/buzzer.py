import logging
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta

log = logging.getLogger("bot")

API_BASE = 'https://ias.blackeye.id'
WORKSPACE_ID = '5f100a96c2c1a948bf071aea'
DEFAULT_FIELDS = 'post_url,ann_clean_text,url,id,title,created_at,admiralty_code,ann_emotions,ann_info_class,ann_sentiment,domains,links,text,source,media,data_source,user_image,user_id,username,user_full_name,post_code,type,credibility_score,engagement'

def get_headers(referer=''):
    return {
        'authority': 'ias.blackeye.id',
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'origin': 'https://ias.blackeye.id',
        'referer': f'https://ias.blackeye.id/{referer.lstrip("/")}' if referer else 'https://ias.blackeye.id',
        'sec-ch-ua': '"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
    }

async def fetch_ihsg_summary(days_back=1, source_mode="full"):
    """
    Fetch overnight/intraday sentiment summary for IHSG & Global Indices.
    source_mode: 'morning' (news only, overnight), 'full' (all sources, intraday)
    """
    import pytz
    tz_wib = pytz.timezone("Asia/Jakarta")
    now = datetime.now(tz_wib)
    
    if source_mode == "morning":
        # Morning Briefing focuses on overnight data (Yesterday 16:00 to Today 08:00)
        past = (now - timedelta(days=1)).replace(hour=16, minute=0, second=0)
        data_sources = ['online-news']
    else:
        # Closing Recap focuses on intraday data (Today 08:00 to Today 16:30)
        past = now.replace(hour=7, minute=0, second=0)
        data_sources = ['twitter', 'online-news', 'youtube-post', 'facebook-post', 'instagram-post']
        
    fmt_sdate = past.strftime('%Y%m%d%H%M')
    fmt_edate = now.strftime('%Y%m%d%H%M')
        
    all_posts = []
    global_posts = []
    global_keywords = ["Nikkei", "Hang Seng", "Wall Street", "Dow Jones"]
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        # Tasks for IHSG
        for src in data_sources:
            body = {
                'fields': DEFAULT_FIELDS, 'geo_type': 'distance', 'sort': 'desc', 'rows': 15,
                'info_class': 'all', 'data_source': src, 'sort_by': 'created_at',
                'credibility_score_max': 100, 'sdate': fmt_sdate, 'edate': fmt_edate,
                'keyword': 'IHSG'
            }
            url = f"{API_BASE}/v2/api/ias/issue/dashboard/getPost"
            tasks.append(('ihsg', session.post(url, json=body, headers=get_headers('issue/select-issue'))))
            
        # Tasks for Global Sentiment (using online-news only for speed/relevance)
        for kw in global_keywords:
            body_g = {
                'fields': DEFAULT_FIELDS, 'geo_type': 'distance', 'sort': 'desc', 'rows': 25,
                'info_class': 'all', 'data_source': 'online-news', 'sort_by': 'created_at',
                'credibility_score_max': 100, 'sdate': fmt_sdate, 'edate': fmt_edate,
                'keyword': kw
            }
            tasks.append(('global', session.post(url, json=body_g, headers=get_headers('issue/select-issue'))))
            
        responses = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        
        for idx, res in enumerate(responses):
            tag = tasks[idx][0]
            if isinstance(res, Exception):
                continue
            if res.status == 200:
                try:
                    data = await res.json()
                    if data and 'data' in data and 'data' in data['data']:
                        if tag == 'ihsg':
                            all_posts.extend(data['data']['data'])
                        else:
                            global_posts.extend(data['data']['data'])
                except Exception as e:
                    log.warning(f"Buzzer API Decode Error: {e}")
                    
    # Process stats locally
    sentiment = {'positive': 0, 'negative': 0, 'neutral': 0}
    emotions = {}
    online_news = []
    
    for p in all_posts:
        # Sentiment
        s = str(p.get('ann_sentiment', 'neutral')).lower()
        sentiment[s] = sentiment.get(s, 0) + 1
        
        # Emotions
        e = str(p.get('ann_emotions', 'unknown')).lower()
        if e and e != 'unknown' and e != 'null':
            emotions[e] = emotions.get(e, 0) + 1
            
        # Collect recent news for highlighting
        src = p.get('data_source', '')
        if src in ['online-news', 'twitter'] and len(online_news) < 15:
            title = p.get('title', p.get('text', ''))
            
            # Skip null/empty/garbage titles
            if not title or title.lower() in ('null', 'none', ''):
                continue
            
            # Decode HTML entities (e.g. &ndash; &#58;)
            import html as html_mod
            title = html_mod.unescape(title)
            
            # STRICT RELEVANCE FILTER: title must contain IHSG-related keywords
            relevance_keywords = ['ihsg', 'idx', 'bei', 'bursa', 'saham', 'emiten', 'indeks', 'composite', 'pasar modal', 'asing', 'investor']
            title_lower = title.lower()
            if not any(kw in title_lower for kw in relevance_keywords):
                continue
            
            raw_links = p.get('links', [])
            extracted_link = raw_links[0] if raw_links and isinstance(raw_links, list) else p.get('post_url', p.get('url', ''))
            
            if title and title not in [n['title'] for n in online_news]:
                online_news.append({
                    'title': title[:120].replace('\n', ' '),
                    'source': src,
                    'link': extracted_link,
                    'date': p.get('created_at', '')
                })
                
    # Sort emotions
    sorted_emotions = sorted(emotions.items(), key=lambda x: x[1], reverse=True)
    top_emotions = [k for k, v in sorted_emotions[:3]]
    
    # Sort news by date descending
    online_news.sort(key=lambda x: x['date'], reverse=True)
    
    # Process Global Sentiment
    global_sentiment = {'positive': 0, 'negative': 0, 'neutral': 0}
    for gp in global_posts:
        s = str(gp.get('ann_sentiment', 'neutral')).lower()
        global_sentiment[s] = global_sentiment.get(s, 0) + 1
        
    global_total = sum(global_sentiment.values())
    if global_total > 0:
        pos_g = global_sentiment['positive'] / global_total
        neg_g = global_sentiment['negative'] / global_total
        global_mood = "BULLISH" if pos_g > neg_g and pos_g > 0.35 else ("BEARISH" if neg_g > pos_g and neg_g > 0.35 else "CONSOLIDATING")
    else:
        global_mood = "NO DATA"
    
    return {
        'total_analyzed': len(all_posts),
        'sentiment': sentiment,
        'top_emotions': top_emotions,
        'recent_news': online_news[:5],
        'source_mode': source_mode,
        'global_mood': global_mood,
        'global_analyzed': global_total
    }


async def fetch_stock_news(symbol: str, days_back: int = 7):
    """
    Fetch sentiment-analyzed news for a specific stock ticker.
    Returns dict with sentiment breakdown + top relevant news articles.
    """
    import pytz
    import html as html_mod
    tz_wib = pytz.timezone("Asia/Jakarta")
    now = datetime.now(tz_wib)
    past = now - timedelta(days=days_back)
    
    fmt_sdate = past.strftime('%Y%m%d%H%M')
    fmt_edate = now.strftime('%Y%m%d%H%M')
    
    ambiguous_tickers = {
        'AYAM', 'FIRE', 'BOLA', 'SAPI', 'FILM', 'GOLF', 'WIFI', 'GOOD', 
        'BOSS', 'KREN', 'BANK', 'CAMP', 'CHIP', 'CITY', 'COAL', 'DEWA', 
        'FAST', 'FISH', 'HOPE', 'IDEA', 'JAWA', 'NICE', 'SOUL', 'BUDI', 
        'GOLD', 'HOME', 'JAYA', 'LIFE', 'MARI', 'MEGA', 'NUSA', 'PURA', 
        'REAL', 'ROCK', 'ROSE', 'SINI', 'TELE', 'TOYS', 'TRUE', 'WIND', 
        'ZONE', 'CASH', 'CLUB', 'DEAL', 'DIVA', 'EDGE', 'ICON', 'KEEP', 
        'KINO', 'MATE', 'OMRE', 'PUTR', 'HOKI', 'CASS', 'BELL', 'PANI', 'OASA', 'NANO'
    }
    
    # Search with plain symbol as requested to maximize results, UNLESS it's an ambiguous word
    if symbol.upper() in ambiguous_tickers:
        keyword = f"saham {symbol.upper()}"
    else:
        keyword = symbol.upper()
    data_sources = ['online-news', 'twitter']
    
    all_posts = []
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for src in data_sources:
            body = {
                'fields': DEFAULT_FIELDS, 'geo_type': 'distance', 'sort': 'desc', 'rows': 30,
                'info_class': 'all', 'data_source': src, 'sort_by': 'created_at',
                'credibility_score_max': 100, 'sdate': fmt_sdate, 'edate': fmt_edate,
                'keyword': keyword
            }
            url = f"{API_BASE}/v2/api/ias/issue/dashboard/getPost"
            tasks.append(session.post(url, json=body, headers=get_headers('issue/select-issue')))
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in responses:
            if isinstance(res, Exception):
                continue
            if res.status == 200:
                try:
                    data = await res.json()
                    if data and 'data' in data and 'data' in data['data']:
                        all_posts.extend(data['data']['data'])
                except Exception as e:
                    log.warning(f"Buzzer Stock News Decode Error: {e}")
    
    # Process
    sentiment = {'positive': 0, 'negative': 0, 'neutral': 0}
    emotions = {}
    articles = []
    
    for p in all_posts:
        title = p.get('title', p.get('text', ''))
        if not title or title.lower() in ('null', 'none', ''):
            continue
            
        title = html_mod.unescape(title)
        
        title_lower = title.lower()
        sym_lower = symbol.lower()
        text_lower = p.get('text', '').lower()
        
        if sym_lower not in title_lower and sym_lower not in text_lower:
            continue
            
        ambiguous_tickers = {
            'AYAM', 'FIRE', 'BOLA', 'SAPI', 'FILM', 'GOLF', 'WIFI', 'GOOD', 
            'BOSS', 'KREN', 'BANK', 'CAMP', 'CHIP', 'CITY', 'COAL', 'DEWA', 
            'FAST', 'FISH', 'HOPE', 'IDEA', 'JAWA', 'NICE', 'SOUL', 'BUDI', 
            'GOLD', 'HOME', 'JAYA', 'LIFE', 'MARI', 'MEGA', 'NUSA', 'PURA', 
            'REAL', 'ROCK', 'ROSE', 'SINI', 'TELE', 'TOYS', 'TRUE', 'WIND', 
            'ZONE', 'CASH', 'CLUB', 'DEAL', 'DIVA', 'EDGE', 'ICON', 'KEEP', 
            'KINO', 'MATE', 'OMRE', 'PUTR', 'HOKI', 'CASS', 'BELL', 'PANI', 'OASA', 'NANO'
        }
        
        # Prevent literal dictionary words (e.g. AYAM) from matching non-stock news
        # We require financial context in either the title or text snippet
        if symbol.upper() in ambiguous_tickers:
            text_lower = p.get('text', '').lower()
            combined_text = title_lower + " " + text_lower
            stock_terms = ['saham', 'emiten', 'bursa', 'idx', 'ihsg', 'investor', 'tbk', 'pt ', 'rp ', 'laba', 'rugi', 'dividen', 'direktur']
            if not any(t in combined_text for t in stock_terms):
                continue
            
        # Post passed relevance filter! Count sentiment and emotions.
        s = str(p.get('ann_sentiment', 'neutral')).lower()
        sentiment[s] = sentiment.get(s, 0) + 1
        
        e = str(p.get('ann_emotions', 'unknown')).lower()
        if e and e != 'unknown' and e != 'null':
            emotions[e] = emotions.get(e, 0) + 1
            
        src = p.get('data_source', '')
        if src in ['online-news', 'twitter'] and len(articles) < 20:
            raw_links = p.get('links', [])
            extracted_link = raw_links[0] if raw_links and isinstance(raw_links, list) else ''
            
            sent_label = str(p.get('ann_sentiment', 'neutral')).lower()
            date_raw = p.get('created_at', '')
            
            if title not in [a['title'] for a in articles]:
                articles.append({
                    'title': title[:140].replace('\n', ' '),
                    'link': extracted_link,
                    'sentiment': sent_label,
                    'source': src,
                    'date': date_raw[:10] if date_raw else ''
                })
    
    sorted_emotions = sorted(emotions.items(), key=lambda x: x[1], reverse=True)
    top_emotions = [k for k, v in sorted_emotions[:3]]
    
    articles.sort(key=lambda x: x['date'], reverse=True)
    
    return {
        'symbol': keyword,
        'total_analyzed': len(all_posts),
        'sentiment': sentiment,
        'top_emotions': top_emotions,
        'articles': articles[:10],
        'days_back': days_back
    }
