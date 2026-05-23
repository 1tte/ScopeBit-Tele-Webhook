"""
Multi-source news fetcher for Indonesian stock market.
Sources: Google News RSS + CNBC Indonesia API
Includes sentiment classification and emiten (stock ticker) extraction.
"""
import re
import logging
import asyncio
import urllib.parse
import xml.etree.ElementTree as ET
from api import cache as trade_cache

log = logging.getLogger("bot")

# ── Sentiment Keywords (from NESE backend) ──
POSITIVE_KEYWORDS = [
    "naik", "bullish", "upgrade", "target", "positif", "tumbuh", "meningkat",
    "laba", "dividen", "buyback", "akuisisi", "ekspansi", "rebound", "recovery",
    "outperform", "buy", "overweight", "beat", "record", "optimis", "surplus",
    "akumulasi", "cuan", "rally", "breakout", "all-time high", "ath",
]
NEGATIVE_KEYWORDS = [
    "turun", "bearish", "downgrade", "jual", "negatif", "rugi", "melemah",
    "defisit", "gagal", "default", "sell", "underweight", "underperform",
    "resesi", "inflasi", "koreksi", "crash", "cut", "disposal", "fraud",
    "distribusi", "anjlok", "rugi bersih", "suspend", "delisting", "pailit",
]
NEGATION_WORDS = ["tidak", "belum", "bukan", "gagal", "jangan", "kurang"]

# Common 4-letter false positives in Indonesian finance news to filter out
FALSE_POSITIVES = {
    "YANG", "DARI", "PADA", "SAAT", "BISA", "KITA", "KAMI", "AKAN", "ATAU", 
    "BARU", "BAIK", "HARI", "LALU", "LAGI", "NAIK", "JUAL", "BELI", "UANG", 
    "ASET", "DANA", "INFO", "DATA", "CARI", "KURS", "IHSG", "RUPS", "BANK", 
    "ASING", "KPK", "PPAT", "BUMI", "BUMN", "BEI", "OJK", "FED", "SRBI",
    "DPK", "NPL", "NIM", "LPS", "PPN", "PPH", "PDB", "YTD", "QTD", "MTD",
    "NEWS", "LIVE", "UPDATE"
}

def classify_sentiment(text: str) -> str:
    """Classify text sentiment using keyword matching with negation handling."""
    words = re.findall(r'\w+', text.lower())
    pos_score = 0
    neg_score = 0

    for i, word in enumerate(words):
        # Check previous 2 words for negation
        start_idx = max(0, i - 2)
        is_negated = any(nw in words[start_idx:i] for nw in NEGATION_WORDS)

        if word in POSITIVE_KEYWORDS:
            if is_negated:
                neg_score += 1
            else:
                pos_score += 1
        elif word in NEGATIVE_KEYWORDS:
            if is_negated:
                pos_score += 1
            else:
                neg_score += 1

    # Multi-word phrases
    lower_text = text.lower()
    if "rugi bersih" in lower_text:
        neg_score += 2
    if "all-time high" in lower_text or "all time high" in lower_text:
        pos_score += 2

    if pos_score > neg_score:
        return "Bullish"
    elif neg_score > pos_score:
        return "Bearish"
    return "Netral"


def extract_emiten(text: str) -> list[str]:
    """Extract stock ticker mentions dynamically (4-letter uppercase sequences)."""
    candidates = re.findall(r'\b([A-Z]{4})\b', text)
    found = []
    seen = set()
    for c in candidates:
        if c not in FALSE_POSITIVES and c not in seen:
            # Re-verify it doesn't match standard false positive words that might sneak in
            found.append(c)
            seen.add(c)
    return found


async def _fetch_google_news(query: str = "saham Indonesia", limit: int = 15) -> list[dict]:
    """Fetch latest news from Google News RSS."""
    import httpx
    try:
        encoded = urllib.parse.quote(f"{query} when:3h")
        url = f"https://news.google.com/rss/search?q={encoded}&hl=id&gl=ID&ceid=ID:id"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            log.warning(f"Google News HTTP {resp.status_code}")
            return []

        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []

        items = []
        for item in channel.findall("item")[:limit]:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")
            source_el = item.find("source")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link = link_el.text.strip() if link_el is not None and link_el.text else ""

            # Google News appends " - Publisher" to title
            source = "Google News"
            if source_el is not None and source_el.text:
                source = source_el.text.strip()
            elif " - " in title:
                source = title.split(" - ")[-1].strip()
                title = " - ".join(title.split(" - ")[:-1]).strip()

            description = ""
            if desc_el is not None and desc_el.text:
                # Strip HTML tags from description
                description = re.sub(r'<[^>]+>', '', desc_el.text).strip()

            pub_date = pub_el.text.strip() if pub_el is not None and pub_el.text else ""

            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "description": description,
                    "source": source,
                    "pub_date": pub_date,
                })

        return items

    except Exception as e:
        log.warning(f"Google News fetch error: {e}")
        return []


async def _fetch_cnbc_news(query: str = "saham", limit: int = 15) -> list[dict]:
    """Fetch latest news from CNBC Indonesia API."""
    import httpx
    try:
        url = "https://www.cnbcindonesia.com/api/v2/search-result"
        params = {
            "query": query,
            "idtype": "1 4",
            "start": 0,
            "limit": limit,
            "isrelevance": 1,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params, headers=headers)

        if resp.status_code != 200:
            log.warning(f"CNBC API HTTP {resp.status_code}")
            return []

        data = resp.json()
        items_raw = data.get("data", [])
        items = []

        for item in items_raw[:limit]:
            title = (item.get("strjudul") or "").strip()
            if not title or len(title) < 10:
                continue

            link = item.get("url") or item.get("articleUrl") or ""
            source = (item.get("strnmpartner") or "CNBC Indonesia").strip()
            description = (item.get("strringkasan") or item.get("strdeskripsi") or "").strip()
            # Strip HTML from description
            description = re.sub(r'<[^>]+>', '', description).strip()

            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "description": description[:200] if description else "",
                    "source": source or "CNBC Indonesia",
                    "pub_date": item.get("strtanggal", ""),
                })

        return items

    except Exception as e:
        log.warning(f"CNBC fetch error: {e}")
        return []


async def get_latest_news(limit: int = 20) -> list[dict]:
    """
    Fetch latest stock market news from multiple sources in parallel.
    Returns deduplicated list with sentiment and emiten extraction.
    """
    cache_key = "news:latest_broadcast"
    cached = trade_cache.get(cache_key)
    if cached is not None:
        return cached

    # Parallel fetch from 2 sources
    google_res, cnbc_res = await asyncio.gather(
        _fetch_google_news("saham Indonesia", limit=15),
        _fetch_cnbc_news("saham", limit=15),
        return_exceptions=True,
    )

    all_items = []
    if isinstance(google_res, list):
        all_items.extend(google_res)
    if isinstance(cnbc_res, list):
        all_items.extend(cnbc_res)

    # Deduplicate by normalized URL
    seen_urls = set()
    deduped = []
    for item in all_items:
        url_key = item["link"].split("?")[0].rstrip("/").lower()
        if url_key not in seen_urls:
            seen_urls.add(url_key)

            # Enrich with sentiment and emiten
            full_text = f"{item['title']} {item.get('description', '')}"
            item["sentiment"] = classify_sentiment(full_text)
            item["emiten"] = extract_emiten(full_text)

            deduped.append(item)
            if len(deduped) >= limit:
                break

    # Cache for 30 minutes
    if deduped:
        trade_cache.put(cache_key, deduped, ttl=1800)

    return deduped


async def get_stock_news(symbol: str, limit: int = 5) -> list[dict]:
    """Fetch recent news articles for a specific stock symbol.
    
    Args:
        symbol: Stock symbol (e.g. 'BBCA')
        limit: Max articles to return
        
    Returns:
        List of dicts containing 'title', 'link', 'pubDate'
    """
    try:
        cache_key = f"news:{symbol}:{limit}"
        cached = trade_cache.get(cache_key)
        if cached is not None:
            return cached

        query = urllib.parse.quote(f"{symbol} saham")
        url = f"https://news.google.com/rss/search?q={query}&hl=id&gl=ID&ceid=ID:id"
        
        import httpx
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)
        
        if resp.status_code != 200:
            return []
            
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []
        
        items = []
        for item in channel.findall("item")[:limit]:
            title = item.find("title").text if item.find("title") is not None else ""
            if " - " in title:
                title = " - ".join(title.split(" - ")[:-1])
                
            link = item.find("link").text if item.find("link") is not None else ""
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            
            items.append({
                "title": title.strip(),
                "link": link,
                "pub_date": pub_date
            })
            
        if items:
            trade_cache.put(cache_key, items, ttl=900)
            
        return items
        
    except Exception as e:
        log.warning(f"News fetch error for {symbol}: {e}")
        return []
