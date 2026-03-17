# Reddit Scraper Update Instructions

## What Changed
Replaced Reddit API (praw) with public JSON endpoints - **NO API KEY NEEDED!**

## Files Added
1. **reddit_scraper.py** - New scraper using Reddit's public JSON endpoints

## Changes Needed in main.py

### Change 1: Line 16 - Replace import
**OLD:**
```python
import praw
```

**NEW:**
```python
from reddit_scraper import get_reddit_sentiment as reddit_get_sentiment
```

### Change 2: Lines 279-321 - Replace get_reddit_sentiment function
**DELETE these 42 lines** and **REPLACE with:**
```python
def get_reddit_sentiment(ticker: str) -> Tuple[int, str]:
    """Get Reddit sentiment using JSON endpoints (no API needed)"""
    return reddit_get_sentiment(ticker)
```

### Change 3: Lines 1123-1127 - Remove Reddit client initialization
**DELETE:**
```python
reddit_client = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT
)
```

**REPLACE with:**
```python
# Reddit client no longer needed - using public JSON endpoints
```

### Change 4: Line ~1140 - Update function call
**OLD:**
```python
mentions, sentiment = get_reddit_sentiment(ticker, reddit_client)
```

**NEW:**
```python
mentions, sentiment = get_reddit_sentiment(ticker)
```

### Change 5: Line ~393 - Update get_trending_tickers signature  
**OLD:**
```python
def get_trending_tickers(finnhub_client, reddit_client, current_holdings: List[str]) -> List[Dict]:
```

**NEW:**
```python
def get_trending_tickers(finnhub_client, current_holdings: List[str]) -> List[Dict]:
```

### Change 6: Update get_trending_tickers call
**OLD:**
```python
opportunities = get_trending_tickers(finnhub_client, reddit_client, holdings)
```

**NEW:**
```python
opportunities = get_trending_tickers(finnhub_client, holdings)
```

### Change 7: Lines 409-428 - Update Reddit trending in get_trending_tickers
The old code uses `reddit_client.subreddit(sub_name).hot()`. You can either:
- **Option A:** Remove Reddit trending from this function entirely
- **Option B:** Add similar JSON endpoint code from reddit_scraper.py

## Testing
Run the scraper test:
```bash
cd /tmp/portfolio-monitor
python reddit_scraper.py
```

Should see Reddit mentions for NVDA, TSLA, AAPL without any API errors!

## Benefits
✅ No Reddit API authentication needed
✅ No rate limits (more lenient)
✅ No API application approval wait
✅ Same data quality
✅ More reliable long-term
