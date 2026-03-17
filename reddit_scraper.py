"""
Reddit scraper using public JSON endpoints (no API key required)
"""
import requests
import time
import logging
from typing import Tuple, List, Dict

logger = logging.getLogger(__name__)

def get_reddit_sentiment(ticker: str) -> Tuple[int, str]:
    """
    Search Reddit for ticker mentions using public JSON endpoints
    No API authentication required!
    """
    try:
        subreddits = ['wallstreetbets', 'stocks', 'investing', 'CanadianInvestor']
        mentions = 0
        posts = []
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        for sub_name in subreddits:
            try:
                # Reddit's public JSON endpoint - just add .json to the URL!
                url = f'https://www.reddit.com/r/{sub_name}/search.json'
                params = {
                    'q': ticker,
                    'restrict_sr': '1',  # Restrict to this subreddit
                    'sort': 'relevance',
                    't': 'day',  # Time filter: day
                    'limit': 10
                }
                
                response = requests.get(url, headers=headers, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Extract posts from JSON
                    if 'data' in data and 'children' in data['data']:
                        for child in data['data']['children']:
                            post_data = child.get('data', {})
                            
                            # Check if ticker is actually mentioned in title or selftext
                            title = post_data.get('title', '').upper()
                            selftext = post_data.get('selftext', '').upper()
                            
                            if ticker.upper() in title or ticker.upper() in selftext:
                                mentions += 1
                                posts.append({
                                    'title': post_data.get('title', ''),
                                    'score': post_data.get('score', 0),
                                    'upvote_ratio': post_data.get('upvote_ratio', 0.5),
                                    'subreddit': sub_name
                                })
                
                # Be nice to Reddit - small delay between requests
                time.sleep(1)
                
            except Exception as e:
                logger.warning(f"Error searching r/{sub_name} for {ticker}: {e}")
                continue
        
        if mentions == 0:
            return 0, "No Reddit activity"
        
        # Determine sentiment from top 3 posts by score
        top_posts = sorted(posts, key=lambda x: x['score'], reverse=True)[:3]
        
        if not top_posts:
            return mentions, f"{mentions} mentions - NEUTRAL"
        
        avg_ratio = sum(p['upvote_ratio'] for p in top_posts) / len(top_posts)
        
        # Sentiment based on upvote ratio
        if avg_ratio > 0.7:
            sentiment = "BULLISH 🚀"
        elif avg_ratio < 0.4:
            sentiment = "BEARISH 📉"
        else:
            sentiment = "NEUTRAL"
        
        # Get most upvoted post title for context
        top_title = top_posts[0]['title'][:80] if top_posts else ""
        
        return mentions, f"{mentions} mentions - {sentiment} | Top: \"{top_title}...\""
    
    except Exception as e:
        logger.error(f"Reddit sentiment error for {ticker}: {e}")
        return 0, "Reddit unavailable"


def test_reddit_scraper():
    """Test the scraper with a popular ticker"""
    print("Testing Reddit scraper (no API key needed)...\n")
    
    test_tickers = ['NVDA', 'TSLA', 'AAPL']
    
    for ticker in test_tickers:
        print(f"Searching for {ticker}...")
        mentions, sentiment = get_reddit_sentiment(ticker)
        print(f"  Result: {sentiment}")
        print(f"  Mentions: {mentions}\n")
        time.sleep(2)  # Be nice to Reddit


if __name__ == "__main__":
    # Test it
    logging.basicConfig(level=logging.INFO)
    test_reddit_scraper()
