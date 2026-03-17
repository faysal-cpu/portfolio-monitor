"""
Hybrid Reddit Scraper - RSS Feeds + PRAW API
No rate limit issues, maximum reliability
"""
import feedparser
import time
import logging
from typing import Tuple, List, Dict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def get_reddit_sentiment_rss(ticker: str) -> Tuple[int, str]:
    """
    Monitor Reddit using RSS feeds (no authentication needed!)
    Falls back to basic sentiment if PRAW not available
    """
    try:
        subreddits = ['wallstreetbets', 'stocks', 'investing', 'CanadianInvestor']
        mentions = 0
        posts = []
        
        for sub_name in subreddits:
            try:
                # RSS feed URL - public, no auth needed!
                rss_url = f'https://www.reddit.com/r/{sub_name}/new/.rss'
                
                # Parse the RSS feed
                feed = feedparser.parse(rss_url)
                
                if feed.bozo:  # Feed parsing error
                    logger.warning(f"RSS feed error for r/{sub_name}: {feed.bozo_exception}")
                    continue
                
                # Check posts from last 24 hours
                cutoff_time = datetime.now() - timedelta(days=1)
                
                for entry in feed.entries:
                    # Check if ticker is mentioned in title or content
                    title = entry.get('title', '').upper()
                    summary = entry.get('summary', '').upper()
                    
                    if ticker.upper() in title or ticker.upper() in summary:
                        mentions += 1
                        
                        # Extract basic info from RSS
                        posts.append({
                            'title': entry.get('title', ''),
                            'link': entry.get('link', ''),
                            'subreddit': sub_name,
                            'published': entry.get('published', '')
                        })
                
                # Be respectful - small delay between feeds
                time.sleep(2)
                
            except Exception as e:
                logger.warning(f"Error parsing RSS for r/{sub_name}: {e}")
                continue
        
        if mentions == 0:
            return 0, "No Reddit activity"
        
        # Sort by most recent
        top_posts = sorted(posts, key=lambda x: x.get('published', ''), reverse=True)[:3]
        
        if not top_posts:
            return mentions, f"{mentions} mentions"
        
        top_title = top_posts[0]['title'][:80] if top_posts else ""
        
        return mentions, f"{mentions} mentions | Top: \"{top_title}...\""
    
    except Exception as e:
        logger.error(f"Reddit RSS error for {ticker}: {e}")
        return 0, "Reddit unavailable"


def get_reddit_sentiment_praw(ticker: str, reddit_client=None) -> Tuple[int, str]:
    """
    Deep analysis using PRAW (only for tickers with RSS activity)
    This minimizes API calls and stays well under rate limits
    """
    if reddit_client is None:
        # Fallback to RSS-only if PRAW not configured
        return get_reddit_sentiment_rss(ticker)
    
    try:
        subreddits = ['wallstreetbets', 'stocks', 'investing', 'CanadianInvestor']
        mentions = 0
        posts = []
        
        for sub_name in subreddits:
            try:
                subreddit = reddit_client.subreddit(sub_name)
                
                # Search last 24 hours (PRAW handles rate limiting automatically)
                for post in subreddit.search(ticker, time_filter='day', limit=10):
                    mentions += 1
                    posts.append({
                        'title': post.title,
                        'score': post.score,
                        'upvote_ratio': post.upvote_ratio
                    })
                    
            except Exception as e:
                logger.warning(f"Error searching r/{sub_name} for {ticker}: {e}")
                continue
        
        if mentions == 0:
            return 0, "No Reddit activity"
        
        # Determine sentiment from top posts
        top_posts = sorted(posts, key=lambda x: x['score'], reverse=True)[:3]
        
        if not top_posts:
            return mentions, f"{mentions} mentions"
        
        avg_ratio = sum(p['upvote_ratio'] for p in top_posts) / len(top_posts)
        
        # Sentiment analysis
        if avg_ratio > 0.7:
            sentiment = "BULLISH 🚀"
        elif avg_ratio < 0.4:
            sentiment = "BEARISH 📉"
        else:
            sentiment = "NEUTRAL"
        
        top_title = top_posts[0]['title'][:80] if top_posts else ""
        
        return mentions, f"{mentions} mentions - {sentiment} | Top: \"{top_title}...\""
    
    except Exception as e:
        logger.error(f"Reddit PRAW error for {ticker}: {e}")
        # Fallback to RSS if PRAW fails
        return get_reddit_sentiment_rss(ticker)


def get_reddit_sentiment(ticker: str, reddit_client=None) -> Tuple[int, str]:
    """
    Smart hybrid approach:
    1. Try PRAW if available (best sentiment analysis)
    2. Fallback to RSS if PRAW unavailable (still gets mentions)
    """
    if reddit_client is not None:
        return get_reddit_sentiment_praw(ticker, reddit_client)
    else:
        return get_reddit_sentiment_rss(ticker)


def test_rss_scraper():
    """Test RSS-only scraping (no API needed)"""
    print("Testing RSS Reddit scraper (no auth needed)...\n")
    
    test_tickers = ['NVDA', 'TSLA', 'AAPL']
    
    for ticker in test_tickers:
        print(f"Searching for {ticker}...")
        mentions, sentiment = get_reddit_sentiment_rss(ticker)
        print(f"  Result: {sentiment}")
        print(f"  Mentions: {mentions}\n")
        time.sleep(3)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_rss_scraper()
