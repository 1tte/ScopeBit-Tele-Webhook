"""
Simple NLP engine for Indonesian financial sentiment analysis.
Scores news headlines based on positive and negative keyword lexicons.
"""
import re

# Lexicon of positive financial words
POSITIVE_WORDS = {
    "laba", "naik", "untung", "cuan", "ekspansi", "akuisisi", "dividen", 
    "rekor", "melonjak", "tumbuh", "meroket", "positif", "optimis",
    "profit", "meningkat", "surplus", "rebound", "moncer", "tertinggi",
    "target", "investasi", "buyback"
}

# Lexicon of negative financial words
NEGATIVE_WORDS = {
    "rugi", "turun", "anjlok", "suspend", "pkpu", "gugat", "pailit", 
    "anjlog", "merosot", "negatif", "pesimis", "jeblok", "lesu", 
    "menurun", "defisit", "denda", "phk", "bangkrut", "kasus",
    "skandal", "gagal", "batal", "merosot"
}


def analyze_sentiment(text: str) -> dict:
    """Analyze Indonesian financial text and return a sentiment score.
    
    Returns:
        A dict with 'score', 'label', 'pos_matches', 'neg_matches'.
        Score range depends on matched keywords.
    """
    # Clean text: lowercase and remove non-alphanumeric chars
    clean_text = re.sub(r'[^\w\s]', ' ', text.lower())
    words = clean_text.split()
    
    pos_matches = []
    neg_matches = []
    
    for word in words:
        if word in POSITIVE_WORDS:
            pos_matches.append(word)
        elif word in NEGATIVE_WORDS:
            neg_matches.append(word)
            
    # Simple scoring logic
    score = len(pos_matches) - len(neg_matches)
    
    # Cap score for normalization if needed
    if score > 0:
        label = "Bullish"
    elif score < 0:
        label = "Bearish"
    else:
        label = "Netral"
        
    return {
        "text": text,
        "score": score,
        "label": label,
        "pos_matches": pos_matches,
        "neg_matches": neg_matches
    }


def aggregate_sentiment(titles: list[str]) -> dict:
    """Aggregate sentiment scores from multiple news titles."""
    if not titles:
        return {"total_score": 0, "label": "No News", "analyzed": 0}
        
    total_score = 0
    bullish_cnt = 0
    bearish_cnt = 0
    
    for title in titles:
        result = analyze_sentiment(title)
        total_score += result["score"]
        if result["score"] > 0:
            bullish_cnt += 1
        elif result["score"] < 0:
            bearish_cnt += 1
            
    if total_score > 0:
        label = "Bullish"
    elif total_score < 0:
        label = "Bearish"
    else:
        label = "Netral"
        
    return {
        "total_score": total_score,
        "bullish_articles": bullish_cnt,
        "bearish_articles": bearish_cnt,
        "neutral_articles": len(titles) - bullish_cnt - bearish_cnt,
        "label": label,
        "analyzed": len(titles)
    }
