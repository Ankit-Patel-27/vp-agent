"""
News Engine — RSS headlines + Fear & Greed Index
Sentiment = confidence modifier only. Never changes entry/stop/target.
"""
import requests
from datetime import datetime, timezone

try:
    import feedparser
    _HAS_FEEDPARSER = True
except ImportError:
    _HAS_FEEDPARSER = False

FEEDS = [
    ("CoinDesk",       "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph",  "https://cointelegraph.com/rss"),
    ("CryptoSlate",    "https://cryptoslate.com/feed/"),
    ("Decrypt",        "https://decrypt.co/feed"),
    ("BeInCrypto",     "https://beincrypto.com/feed/"),
]

BULL_WORDS = ["surge","rally","bullish","breakout","gains","buy","adoption","upgrade",
              "record","high","positive","recover","green","moon","support","strong"]
BEAR_WORDS = ["crash","drop","bearish","sell","fear","hack","ban","regulation",
              "lawsuit","warning","risk","red","dump","weak","low","concern","loss"]

def fetch_headlines(max_per_feed=3) -> list:
    if not _HAS_FEEDPARSER:
        return []
    headlines = []
    now = datetime.now(timezone.utc)
    for source, url in FEEDS:
        try:
            feed = feedparser.parse(url)
            count = 0
            for e in feed.entries:
                if count >= max_per_feed:
                    break
                title = e.get("title", "").strip()
                if not title:
                    continue
                # Age in hours
                published = e.get("published_parsed")
                age_h = 999
                if published:
                    from time import mktime
                    pub_dt = datetime.fromtimestamp(mktime(published), tz=timezone.utc)
                    age_h = max(0, (now - pub_dt).total_seconds() / 3600)
                if age_h > 48:
                    continue
                score = _score_headline(title)
                headlines.append({
                    "title":     title,
                    "source":    source,
                    "age_hours": round(age_h, 1),
                    "score":     score,
                    "url":       e.get("link", ""),
                })
                count += 1
        except Exception as e:
            print(f"[News] {source} error: {e}")
    headlines.sort(key=lambda x: x["age_hours"])
    return headlines


def _score_headline(title: str) -> float:
    t = title.lower()
    score = 0.0
    for w in BULL_WORDS:
        if w in t:
            score += 8
    for w in BEAR_WORDS:
        if w in t:
            score -= 8
    return round(max(-100, min(100, score)), 1)


def fetch_fear_greed() -> dict:
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        data = r.json()["data"][0]
        value = int(data["value"])
        label = data["value_classification"]
        if value <= 25:
            regime = "extreme_fear"
        elif value <= 45:
            regime = "fear"
        elif value <= 55:
            regime = "neutral"
        elif value <= 75:
            regime = "greed"
        else:
            regime = "extreme_greed"
        note = _fg_note(regime)
        return {"value": value, "label": label, "regime": regime, "note": note}
    except Exception as e:
        print(f"[FearGreed] error: {e}")
        return {"value": 50, "label": "Neutral", "regime": "neutral",
                "note": "Could not fetch Fear & Greed index."}


def _fg_note(regime: str) -> str:
    return {
        "extreme_fear":  "Extreme fear — potential buying opportunity (contrarian).",
        "fear":          "Market fearful — caution on longs; shorts may have edge.",
        "neutral":       "Neutral sentiment — setup quality drives the trade.",
        "greed":         "Market greedy — be cautious on breakout longs.",
        "extreme_greed": "Extreme greed — high reversal risk; tighten stops.",
    }.get(regime, "")


def compute_sentiment(headlines: list, fg: dict) -> dict:
    if not headlines:
        return {"score": 0, "direction": "neutral", "label": "No data",
                "bull_count": 0, "bear_count": 0}
    scores = [h["score"] for h in headlines]
    avg = sum(scores) / len(scores)
    # Weight FG into score
    fg_v   = fg.get("value", 50)
    fg_adj = (fg_v - 50) * 0.3
    total  = round(avg + fg_adj, 1)
    direction = "bullish" if total > 15 else "bearish" if total < -15 else "neutral"
    label = ("Bullish" if total > 30 else "Mildly Bullish" if total > 10
             else "Bearish" if total < -30 else "Mildly Bearish" if total < -10
             else "Neutral")
    return {
        "score":      round(total, 1),
        "direction":  direction,
        "label":      label,
        "bull_count": sum(1 for s in scores if s > 0),
        "bear_count": sum(1 for s in scores if s < 0),
    }


def confidence_modifier(sentiment: dict, fg: dict, trade_bias: str) -> dict:
    boosts, warnings = [], []
    mod = 0
    direction  = sentiment.get("direction", "neutral")
    score      = sentiment.get("score", 0)
    fg_regime  = fg.get("regime", "neutral")

    # News alignment
    if direction == trade_bias == "bullish":
        mod += 15; boosts.append("News sentiment aligns with bullish bias (+15)")
    elif direction == trade_bias == "bearish":
        mod += 15; boosts.append("News sentiment aligns with bearish bias (+15)")
    elif direction != "neutral" and direction != trade_bias:
        mod -= 15; warnings.append("News sentiment conflicts with trade bias (-15)")

    # Fear & Greed
    if trade_bias == "bullish" and fg_regime in ("extreme_fear", "fear"):
        mod += 10; boosts.append("Extreme fear = contrarian bullish edge (+10)")
    elif trade_bias == "bearish" and fg_regime in ("extreme_greed",):
        mod += 10; boosts.append("Extreme greed = contrarian bearish edge (+10)")
    elif trade_bias == "bullish" and fg_regime == "extreme_greed":
        mod -= 10; warnings.append("Extreme greed — late breakout risk (-10)")

    mod = max(-25, min(25, mod))
    return {"modifier": mod, "boosts": boosts, "warnings": warnings}
