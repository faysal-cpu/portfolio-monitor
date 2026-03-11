#!/usr/bin/env python3
"""
Portfolio Monitor - Daily Stock Analysis Email System
Runs weekdays at 7am, analyzes holdings, sends formatted email
"""

import os
import sys
import time
import logging
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import anthropic
import finnhub
import praw
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
from dotenv import load_dotenv
import schedule
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables - AUTO-DETECT PATH
# Get the directory where main.py is located (works on both Windows and Linux)
script_dir = os.path.dirname(os.path.abspath(__file__))
ENV_FILE_PATH = os.path.join(script_dir, '.env')

logger.info("="*60)
logger.info("ENVIRONMENT CONFIGURATION")
logger.info("="*60)
logger.info(f"Script directory: {script_dir}")
logger.info(f".env path: {ENV_FILE_PATH}")
logger.info(f".env file exists: {os.path.exists(ENV_FILE_PATH)}")

if not os.path.exists(ENV_FILE_PATH):
    logger.error(f"CRITICAL ERROR: .env file not found at {ENV_FILE_PATH}")
    logger.error("Please create a .env file in the same directory as main.py")
    sys.exit(1)

# Load the .env file
env_loaded = load_dotenv(ENV_FILE_PATH, override=True)
logger.info(f".env file loaded: {env_loaded}")

# API Clients
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
EMAIL_TO = os.getenv('EMAIL_TO')
EMAIL_FROM = os.getenv('EMAIL_FROM')

# Debug: Show what was loaded
logger.info("Loaded credentials:")
logger.info(f"  FINNHUB_API_KEY: {FINNHUB_API_KEY[:20] + '...' if FINNHUB_API_KEY else '✗ MISSING'}")
logger.info(f"  ALPHA_VANTAGE_API_KEY: {ALPHA_VANTAGE_API_KEY[:15] + '...' if ALPHA_VANTAGE_API_KEY else '✗ MISSING'}")
logger.info(f"  REDDIT_CLIENT_ID: {REDDIT_CLIENT_ID[:15] + '...' if REDDIT_CLIENT_ID else '✗ MISSING'}")
logger.info(f"  REDDIT_CLIENT_SECRET: {REDDIT_CLIENT_SECRET[:15] + '...' if REDDIT_CLIENT_SECRET else '✗ MISSING'}")
logger.info(f"  REDDIT_USER_AGENT: {REDDIT_USER_AGENT if REDDIT_USER_AGENT else '✗ MISSING'}")
logger.info(f"  ANTHROPIC_API_KEY: {ANTHROPIC_API_KEY[:20] + '...' if ANTHROPIC_API_KEY else '✗ MISSING'}")
logger.info(f"  SENDGRID_API_KEY: {SENDGRID_API_KEY[:20] + '...' if SENDGRID_API_KEY else '✗ MISSING'}")
logger.info(f"  EMAIL_FROM: {EMAIL_FROM}")
logger.info(f"  EMAIL_TO: {EMAIL_TO}")
logger.info("="*60)

# Validate critical credentials
if not EMAIL_FROM or not EMAIL_TO or not SENDGRID_API_KEY:
    logger.error("CRITICAL: Missing required email credentials!")
    logger.error("Please ensure your .env file has:")
    logger.error("  SENDGRID_API_KEY=SG.your_sendgrid_api_key")
    logger.error("  EMAIL_FROM=your_sender@example.com")
    logger.error("  EMAIL_TO=your_recipient@example.com")
    sys.exit(1)


def git_pull_updates():
    """Auto-update from GitHub before running pipeline"""
    try:
        logger.info("Running git pull to check for updates...")
        result = subprocess.run(
            ['git', 'pull'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            logger.info(f"Git pull successful: {result.stdout.strip()}")
        else:
            logger.warning(f"Git pull failed: {result.stderr.strip()}")
    except Exception as e:
        logger.error(f"Git pull error: {e} - Continuing with existing files")


def read_holdings() -> List[str]:
    """Read ticker symbols from holdings.txt"""
    try:
        with open('holdings.txt', 'r') as f:
            tickers = [line.strip().upper() for line in f if line.strip()]
        logger.info(f"Loaded {len(tickers)} tickers from holdings.txt")
        return tickers
    except Exception as e:
        logger.error(f"Error reading holdings.txt: {e}")
        return []


def get_macro_context(date_str: str) -> str:
    """Module 1: Get macro/geopolitical context from Claude"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = f"""Today is {date_str}. Search for today's most important market news and macro developments. In 3 bullet points, give the most important macro and geopolitical factors a Canadian retail investor should know TODAY that could affect North American and global markets. Be specific — mention actual events, not generic risks."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "web_search_20250305", "name": "web_search"}]
        )

        # Extract text from response (handles tool use)
        response_text = ""
        for block in message.content:
            if hasattr(block, 'text'):
                response_text += block.text

        if response_text:
            logger.info("Successfully fetched macro context from Claude with web search")
            return response_text
        else:
            logger.warning("No text found in macro context response")
            return "• Market context unavailable\n• Please check logs for errors\n• Analysis continues with available data"

    except Exception as e:
        logger.error(f"Error fetching macro context: {e}")
        return "• Market context unavailable\n• Please check logs for errors\n• Analysis continues with available data"


def fetch_alpha_vantage_data(ticker: str) -> Optional[Dict]:
    """Fetch price data from Alpha Vantage as fallback (for Canadian TSX/CSE stocks)"""
    if not ALPHA_VANTAGE_API_KEY:
        return None

    try:
        # Try Canadian exchange suffixes: .TO (TSX), .V (Venture), .CN (CSE)
        symbols_to_try = [f"{ticker}.TO", f"{ticker}.V", f"{ticker}.CN", ticker]

        for symbol in symbols_to_try:
            try:
                url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
                response = requests.get(url, timeout=10)
                data = response.json()

                if 'Global Quote' in data and data['Global Quote']:
                    quote = data['Global Quote']
                    price = float(quote.get('05. price', 0))
                    change_percent = float(quote.get('10. change percent', '0').rstrip('%'))

                    if price > 0:  # Valid data found
                        logger.info(f"✓ Alpha Vantage success for {ticker} (as {symbol}): ${price:.2f}")
                        return {
                            'ticker': ticker,
                            'price': price,
                            'change_percent': change_percent,
                            'headlines': [],
                            'source': 'Alpha Vantage'
                        }

                time.sleep(12)  # Alpha Vantage free tier: 5 calls/min
            except Exception as e:
                logger.warning(f"Alpha Vantage attempt failed for {symbol}: {e}")
                continue

        return None
    except Exception as e:
        logger.error(f"Alpha Vantage error for {ticker}: {e}")
        return None


def fetch_ticker_data(ticker: str, finnhub_client) -> Optional[Dict]:
    """Fetch price, change, and news for a single ticker"""
    try:
        # Get current price
        quote = finnhub_client.quote(ticker)
        current_price = quote.get('c', 0)
        change_percent = quote.get('dp', 0)

        # Get recent news (last 7 days)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        news = finnhub_client.company_news(
            ticker,
            _from=start_date.strftime('%Y-%m-%d'),
            to=end_date.strftime('%Y-%m-%d')
        )

        # Get top 3 headlines
        headlines = [article.get('headline', '') for article in news[:3]]

        time.sleep(0.1)  # Rate limiting

        # Check if we got valid price data
        if current_price > 0:
            return {
                'ticker': ticker,
                'price': current_price,
                'change_percent': change_percent,
                'headlines': headlines,
                'source': 'Finnhub'
            }
        else:
            # No price data from Finnhub, try Alpha Vantage
            logger.warning(f"No price data from Finnhub for {ticker}, trying Alpha Vantage...")
            av_data = fetch_alpha_vantage_data(ticker)
            if av_data:
                # Keep Finnhub news if available
                av_data['headlines'] = headlines
                return av_data
            else:
                # Both APIs failed, return ticker with N/A data
                logger.warning(f"Both APIs failed for {ticker}, including with N/A data")
                return {
                    'ticker': ticker,
                    'price': None,
                    'change_percent': None,
                    'headlines': headlines,
                    'source': 'N/A'
                }

    except Exception as e:
        logger.error(f"Error fetching data for {ticker}: {e}")
        # Retry once on rate limit
        if "rate limit" in str(e).lower():
            logger.info(f"Rate limit hit for {ticker}, waiting 2s and retrying...")
            time.sleep(2)
            try:
                quote = finnhub_client.quote(ticker)
                if quote.get('c', 0) > 0:
                    return {
                        'ticker': ticker,
                        'price': quote.get('c', 0),
                        'change_percent': quote.get('dp', 0),
                        'headlines': [],
                        'source': 'Finnhub'
                    }
            except:
                pass

        # Try Alpha Vantage as fallback
        logger.warning(f"Finnhub failed for {ticker}, trying Alpha Vantage...")
        av_data = fetch_alpha_vantage_data(ticker)
        if av_data:
            return av_data

        # Both failed, return N/A data
        return {
            'ticker': ticker,
            'price': None,
            'change_percent': None,
            'headlines': [],
            'source': 'N/A'
        }


def get_reddit_sentiment(ticker: str, reddit_client) -> Tuple[int, str]:
    """Search Reddit for ticker mentions and determine sentiment"""
    try:
        subreddits = ['wallstreetbets', 'stocks', 'investing', 'CanadianInvestor']
        mentions = 0
        posts = []

        for sub_name in subreddits:
            try:
                subreddit = reddit_client.subreddit(sub_name)
                # Search last 24 hours
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

        # Determine sentiment from top 3 posts
        top_posts = sorted(posts, key=lambda x: x['score'], reverse=True)[:3]
        avg_ratio = sum(p['upvote_ratio'] for p in top_posts) / len(top_posts)

        # Simple sentiment based on upvote ratio
        if avg_ratio >= 0.7:
            sentiment = "BULLISH"
        elif avg_ratio <= 0.5:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        return mentions, f"{mentions} mentions - {sentiment}"

    except Exception as e:
        logger.error(f"Reddit sentiment error for {ticker}: {e}")
        return 0, "Reddit unavailable"


def analyze_holdings(holdings_data: List[Dict], macro_context: str) -> str:
    """Module 2: Send all holdings to Claude for analysis"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Format holdings data
        holdings_text = ""
        for data in holdings_data:
            holdings_text += f"\n{data['ticker']}:\n"

            # Handle None values for price
            price = data.get('price')
            if price is not None:
                holdings_text += f"  Price: ${price:.2f}\n"
            else:
                holdings_text += f"  Price: N/A (data unavailable)\n"

            # Handle None values for change_percent
            change = data.get('change_percent')
            if change is not None:
                holdings_text += f"  Day Change: {change:.2f}%\n"
            else:
                holdings_text += f"  Day Change: N/A\n"

            holdings_text += f"  News: {'; '.join(data.get('headlines', [])[:3]) if data.get('headlines') else 'No recent news'}\n"
            holdings_text += f"  Reddit: {data.get('reddit_sentiment', 'N/A')}\n"

        prompt = f"""You are a decisive portfolio analyst for a Canadian retail investor using a self-directed TFSA. Your job is to SYNTHESIZE all available information and give ONE clear recommendation per stock.

MACRO CONTEXT:
{macro_context}

HOLDINGS DATA:
{holdings_text}

INSTRUCTIONS:
1. Consider ALL factors: price action, news, Reddit sentiment, macro context
2. Weigh the pros and cons of each position
3. Give ONE clear decisive recommendation - don't hedge
4. Your analysis should be consistent unless underlying data changes significantly
5. Be direct and opinionated - if you say HOLD, mean it. If you say SELL, mean it.

CRITICAL: Output ONLY pipe-delimited lines. NO explanatory text. NO preamble.

Format (one line per stock):
TICKER|RECOMMENDATION|CONFIDENCE|REASON|RISK

RECOMMENDATION: BUY MORE, HOLD, SELL, or WATCH
CONFIDENCE: HIGH, MEDIUM, or LOW
REASON: Specific catalyst or data point (max 30 words)
RISK: Key risk to watch (max 15 words)

Start immediately with the first ticker line."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}]
        )

        response = message.content[0].text
        logger.info("Successfully analyzed holdings with Claude")
        return response

    except Exception as e:
        logger.error(f"Error analyzing holdings with Claude: {e}")
        return "ANALYSIS_FAILED"


def get_trending_tickers(finnhub_client, reddit_client, current_holdings: List[str]) -> List[Dict]:
    """Module 3: Get trending tickers from Finnhub and Reddit"""
    trending = set()

    # Get Finnhub trending
    try:
        trending_data = finnhub_client.market_news('general', min_id=0)
        # Extract tickers mentioned in news
        for article in trending_data[:20]:
            # This is a simplified approach - in production you'd parse more carefully
            pass
    except Exception as e:
        logger.warning(f"Error fetching Finnhub trending: {e}")

    # Get Reddit trending
    try:
        subreddits = ['wallstreetbets', 'stocks', 'investing', 'CanadianInvestor']
        ticker_counts = {}

        for sub_name in subreddits:
            try:
                subreddit = reddit_client.subreddit(sub_name)
                for post in subreddit.hot(limit=30):
                    # Simple ticker extraction (words in all caps 2-5 chars)
                    words = post.title.upper().split()
                    for word in words:
                        clean_word = ''.join(c for c in word if c.isalpha())
                        if 2 <= len(clean_word) <= 5 and clean_word.isupper():
                            ticker_counts[clean_word] = ticker_counts.get(clean_word, 0) + 1
            except Exception as e:
                logger.warning(f"Error getting hot posts from r/{sub_name}: {e}")
                continue

        # Get top 30 mentioned
        top_mentioned = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:30]
        trending.update([t[0] for t in top_mentioned])

    except Exception as e:
        logger.error(f"Error getting Reddit trending: {e}")

    # Remove tickers already in holdings
    trending = trending - set(current_holdings)

    # Fetch data for trending tickers
    trending_data = []
    for ticker in list(trending)[:20]:  # Limit to 20 to avoid rate limits
        data = fetch_ticker_data(ticker, finnhub_client)
        if data:
            trending_data.append(data)

    return trending_data


def find_opportunities(trending_data: List[Dict]) -> str:
    """Get Claude's recommendations for new opportunities"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Format trending data
        trending_text = ""
        for data in trending_data:
            price = data.get('price')
            change = data.get('change_percent')

            price_str = f"${price:.2f}" if price is not None else "N/A"
            change_str = f"({change:+.2f}%)" if change is not None else "(N/A)"

            trending_text += f"\n{data['ticker']}: {price_str} {change_str}\n"
            if data.get('headlines'):
                trending_text += f"  News: {'; '.join(data['headlines'][:2])}\n"

        prompt = f"""CRITICAL: Respond ONLY with pipe-delimited lines. NO explanatory text. NO preamble. NO markdown. NO introductions.

Investor profile: Canadian TFSA, momentum plays, binary catalysts, defence, AI, commodities, small caps. Somewhat risk tolerant.

TRENDING TICKERS:
{trending_text}

Output EXACTLY 5 lines in this format:
TICKER|COMPANY|WHY TODAY|UPSIDE|RISK|EXCHANGE

WHY TODAY: be specific about why this is relevant TODAY (max 15 words)
UPSIDE: HIGH or MEDIUM
RISK: one key warning (max 10 words)
EXCHANGE: TSX or US

Start immediately with the first ticker line. Nothing else."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}]
        )

        response = message.content[0].text
        logger.info("Successfully found opportunities with Claude")
        return response

    except Exception as e:
        logger.error(f"Error finding opportunities: {e}")
        return "OPPORTUNITIES_UNAVAILABLE"


def parse_holdings_analysis(analysis: str, holdings_data: List[Dict]) -> List[Dict]:
    """Parse Claude's analysis into structured data - ROBUST VERSION"""
    parsed = []

    if analysis == "ANALYSIS_FAILED":
        # Return raw data
        for data in holdings_data:
            parsed.append({
                'ticker': data['ticker'],
                'price': data['price'],
                'change_percent': data['change_percent'],
                'recommendation': 'N/A',
                'confidence': 'N/A',
                'reason': 'Analysis failed',
                'risk': 'See logs',
                'reddit': data.get('reddit_sentiment', 'N/A')
            })
        return parsed

    # Parse pipe-delimited format
    lines = analysis.strip().split('\n')

    # Create case-insensitive ticker lookup
    data_map = {d['ticker'].upper(): d for d in holdings_data}
    ticker_lookup = {d['ticker'].upper(): d['ticker'] for d in holdings_data}

    # Track which tickers we've parsed
    parsed_tickers = set()

    for line in lines:
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 5:
                ticker_raw = parts[0].strip()
                ticker_upper = ticker_raw.upper()

                # Case-insensitive lookup
                if ticker_upper in data_map:
                    original_ticker = ticker_lookup[ticker_upper]
                    parsed.append({
                        'ticker': original_ticker,
                        'price': data_map[ticker_upper]['price'],
                        'change_percent': data_map[ticker_upper]['change_percent'],
                        'recommendation': parts[1].strip(),
                        'confidence': parts[2].strip(),
                        'reason': parts[3].strip(),
                        'risk': parts[4].strip() if len(parts) > 4 else 'N/A',
                        'reddit': data_map[ticker_upper].get('reddit_sentiment', 'N/A')
                    })
                    parsed_tickers.add(ticker_upper)
                else:
                    logger.warning(f"Holdings parser: Ticker '{ticker_raw}' in Claude response not found in holdings_data")

    # Log missing tickers
    missing_tickers = set(ticker_lookup.keys()) - parsed_tickers
    if missing_tickers:
        logger.warning(f"Holdings parser: {len(missing_tickers)} tickers not found in Claude response: {missing_tickers}")

    # Validation
    if len(parsed) == 0:
        logger.error("⚠️ CRITICAL: Holdings parser returned 0 results! Check Claude's response format.")
        logger.error(f"Claude response preview: {analysis[:500]}...")
    else:
        logger.info(f"✓ Holdings parser: Successfully parsed {len(parsed)} out of {len(holdings_data)} tickers")

    return parsed


def parse_opportunities(opportunities: str) -> List[Dict]:
    """Parse Claude's opportunities into structured data - ROBUST VERSION"""
    parsed = []

    if opportunities == "OPPORTUNITIES_UNAVAILABLE":
        logger.warning("Opportunities marked as unavailable")
        return []

    lines = opportunities.strip().split('\n')

    # Only filter out the exact header line
    header_pattern = "TICKER|COMPANY|WHY TODAY|UPSIDE|RISK|EXCHANGE"

    for line in lines:
        if '|' in line:
            # Skip the exact header line (case-insensitive)
            if line.strip().upper() == header_pattern.upper():
                continue

            parts = line.split('|')
            if len(parts) >= 6:
                ticker = parts[0].strip()
                company = parts[1].strip()

                # Skip if ticker is empty or just whitespace
                if not ticker or not company:
                    continue

                # Skip only if it's EXACTLY one of the column names (less aggressive)
                if ticker.upper() == "TICKER" or company.upper() == "COMPANY":
                    continue

                parsed.append({
                    'ticker': ticker,
                    'company': company,
                    'why_today': parts[2].strip(),
                    'upside': parts[3].strip(),
                    'risk': parts[4].strip(),
                    'exchange': parts[5].strip()
                })

    # Validation
    if len(parsed) == 0:
        logger.error("⚠️ CRITICAL: Opportunities parser returned 0 results! Check Claude's response format.")
        logger.error(f"Claude response preview: {opportunities[:500]}...")
    else:
        logger.info(f"✓ Opportunities parser: Successfully parsed {len(parsed)} opportunities")

    return parsed[:5]  # Limit to 5


def create_html_email(macro_context: str, holdings: List[Dict], opportunities: List[Dict], date_str: str) -> Tuple[str, str]:
    """Create HTML and plain text email content"""

    # Count recommendations by type
    rec_counts = {'BUY MORE': 0, 'HOLD': 0, 'SELL': 0, 'WATCH': 0}
    for h in holdings:
        rec = h['recommendation'].upper()
        if 'BUY MORE' in rec or 'BUY' in rec:
            rec_counts['BUY MORE'] += 1
        elif 'SELL' in rec:
            rec_counts['SELL'] += 1
        elif 'WATCH' in rec:
            rec_counts['WATCH'] += 1
        else:
            rec_counts['HOLD'] += 1

    rec_summary = f"{rec_counts['BUY MORE']} BUY · {rec_counts['HOLD']} HOLD · {rec_counts['SELL']} SELL · {rec_counts['WATCH']} WATCH"

    # HTML Email
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            font-size: 16px;
            line-height: 1.6;
            color: #2d3748;
            -webkit-font-smoothing: antialiased;
        }}
        .container {{
            max-width: 680px;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        .header {{
            background-color: #5a4d8a;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #ffffff !important;
            padding: 40px 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.5px;
            line-height: 1.3;
            color: #ffffff !important;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }}
        .section {{
            padding: 32px 24px;
            border-bottom: 1px solid #e2e8f0;
        }}
        .section:last-child {{ border-bottom: none; }}
        .section h2 {{
            color: #1a202c;
            margin: 0 0 20px 0;
            font-size: 20px;
            font-weight: 700;
            letter-spacing: -0.3px;
        }}
        .macro-context {{
            background: linear-gradient(135deg, #f6f8fb 0%, #eef2f7 100%);
            padding: 24px;
            border-radius: 12px;
            line-height: 1.8;
            font-size: 15px;
            border-left: 4px solid #667eea;
            color: #2d3748;
        }}
        .macro-context strong {{ color: #1a202c; }}
        .rec-summary {{
            background: linear-gradient(135deg, #f7fafc 0%, #edf2f7 100%);
            padding: 16px 20px;
            border-radius: 10px;
            text-align: center;
            font-size: 15px;
            font-weight: 600;
            margin-bottom: 24px;
            color: #2d3748;
            border: 1px solid #e2e8f0;
            letter-spacing: 0.3px;
        }}

        /* Stock Cards - Mobile First */
        .stock-card {{
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
            transition: all 0.2s ease;
        }}
        .stock-card:hover {{
            box-shadow: 0 8px 24px rgba(0,0,0,0.12);
            transform: translateY(-2px);
        }}
        .stock-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .stock-ticker {{
            font-size: 18px;
            font-weight: 700;
            color: #1a202c;
            letter-spacing: 0.5px;
        }}
        .stock-price {{
            font-size: 17px;
            font-weight: 600;
            color: #2d3748;
        }}
        .stock-change {{
            font-size: 17px;
            font-weight: 700;
            letter-spacing: -0.2px;
        }}
        .stock-change.positive {{ color: #10b981; }}
        .stock-change.negative {{ color: #ef4444; }}
        .stock-rec-line {{
            margin-bottom: 14px;
            padding-bottom: 14px;
            border-bottom: 1px solid #f1f5f9;
        }}
        .stock-detail {{
            margin: 10px 0;
            font-size: 14px;
            line-height: 1.7;
            color: #4a5568;
        }}
        .stock-detail strong {{
            color: #1a202c;
            font-weight: 600;
        }}

        .buy-more {{
            background: #d1fae5;
            color: #065f46;
            font-weight: 700;
            padding: 8px 16px;
            border-radius: 8px;
            display: inline-block;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            box-shadow: 0 2px 8px rgba(16, 185, 129, 0.2);
            border: 2px solid #10b981;
        }}
        .hold {{
            background: #fef3c7;
            color: #78350f;
            font-weight: 700;
            padding: 8px 16px;
            border-radius: 8px;
            display: inline-block;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            box-shadow: 0 2px 8px rgba(245, 158, 11, 0.2);
            border: 2px solid #f59e0b;
        }}
        .sell {{
            background: #fee2e2;
            color: #991b1b;
            font-weight: 700;
            padding: 8px 16px;
            border-radius: 8px;
            display: inline-block;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            box-shadow: 0 2px 8px rgba(239, 68, 68, 0.2);
            border: 2px solid #ef4444;
        }}
        .watch {{
            background: #e0e7ff;
            color: #3730a3;
            font-weight: 700;
            padding: 8px 16px;
            border-radius: 8px;
            display: inline-block;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            box-shadow: 0 2px 8px rgba(99, 102, 241, 0.2);
            border: 2px solid #6366f1;
        }}
        .positive {{ color: #00B386; font-weight: bold; }}
        .negative {{ color: #dc3545; font-weight: bold; }}
        .opportunity-card {{
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            padding: 24px;
            margin: 16px 0;
            border-left: 5px solid #f59e0b;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(245, 158, 11, 0.15);
        }}
        .opportunity-card h3 {{
            margin: 0 0 12px 0;
            color: #1a202c;
            font-size: 17px;
            font-weight: 700;
        }}
        .opportunity-card .ticker {{
            font-size: 20px;
            font-weight: 800;
            color: #d97706;
            letter-spacing: 0.5px;
        }}
        .opportunity-card p {{
            margin: 8px 0;
            line-height: 1.6;
            color: #4a5568;
        }}
        .footer {{
            background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%);
            color: #a0aec0;
            padding: 28px;
            text-align: center;
            font-size: 13px;
            line-height: 1.8;
        }}
        .footer .timestamp {{
            color: #667eea;
            font-weight: 600;
        }}
        .footer strong {{ color: #e2e8f0; }}

        /* Mobile responsive */
        @media only screen and (max-width: 600px) {{
            body {{ padding: 12px; }}
            .container {{ border-radius: 12px; }}
            .header {{ padding: 32px 20px; }}
            .header h1 {{ font-size: 20px; }}
            .section {{ padding: 24px 16px; }}
            .section h2 {{ font-size: 18px; }}
            .stock-card {{ padding: 16px; }}
            .stock-ticker {{ font-size: 17px; }}
            .stock-price, .stock-change {{ font-size: 15px; }}
            .macro-context {{ padding: 18px; font-size: 14px; }}
            .opportunity-card {{ padding: 18px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📈 Portfolio Brief — {date_str} | {len(holdings)} positions</h1>
        </div>

        <div class="section">
            <h2>🌍 Macro Context</h2>
            <div class="macro-context">
"""

    # Process macro context: strip intro, convert markdown, add line breaks
    import re
    processed_macro = macro_context
    # Strip everything before the first bullet point
    if '•' in processed_macro:
        processed_macro = '•' + processed_macro.split('•', 1)[1]
    # Convert **text** to <strong>text</strong>
    processed_macro = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', processed_macro)
    # Convert newlines to <br>
    processed_macro = processed_macro.replace(chr(10), '<br>')

    html += f"""
                {processed_macro}
            </div>
        </div>

        <div class="section">
            <h2>📊 Your Holdings</h2>
            <div class="rec-summary">{rec_summary}</div>
"""

    for h in holdings:
        rec_class = ''
        if 'BUY MORE' in h['recommendation'].upper() or 'BUY' in h['recommendation'].upper():
            rec_class = 'buy-more'
        elif 'SELL' in h['recommendation'].upper():
            rec_class = 'sell'
        elif 'WATCH' in h['recommendation'].upper():
            rec_class = 'watch'
        else:
            rec_class = 'hold'

        # Handle None values for price and change_percent
        price_str = f"${h.get('price'):.2f}" if h.get('price') is not None else "N/A"
        change_val = h.get('change_percent')
        if change_val is not None:
            change_class = 'positive' if change_val >= 0 else 'negative'
            change_str = f"{change_val:+.2f}%"
        else:
            change_class = ''
            change_str = "N/A"

        html += f"""
            <div class="stock-card">
                <div class="stock-header">
                    <span class="stock-ticker">{h['ticker']}</span>
                    <span class="stock-price">{price_str}</span>
                    <span class="stock-change {change_class}">{change_str}</span>
                </div>
                <div class="stock-rec-line">
                    <span class="{rec_class}">{h['recommendation']}</span>
                    <span style="color: #666; font-size: 13px; margin-left: 8px;">{h['confidence']} confidence</span>
                </div>
                <div class="stock-detail"><strong>Reason:</strong> {h['reason']}</div>
                <div class="stock-detail"><strong>Risk:</strong> {h['risk']}</div>
                <div class="stock-detail" style="color: #666; font-size: 13px;"><strong>Reddit:</strong> {h['reddit']}</div>
            </div>
"""

    html += """
        </div>
"""

    if opportunities:
        html += """
        <div class="section">
            <h2>🔥 Opportunities</h2>
"""
        for opp in opportunities:
            # Convert markdown **text** to HTML <strong>text</strong>
            import re
            why_today = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp['why_today'])
            company = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp['company'])
            upside = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp['upside'])
            risk = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp['risk'])
            exchange = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp['exchange'])

            html += f"""
            <div class="opportunity-card">
                <div class="ticker">{opp['ticker']}</div>
                <h3>{company}</h3>
                <p><strong>Why Today:</strong> {why_today}</p>
                <p><strong>Upside:</strong> {upside} | <strong>Risk:</strong> {risk}</p>
                <p><strong>Exchange:</strong> {exchange}</p>
            </div>
"""
        html += """
        </div>
"""

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    html += f"""
        <div class="footer">
            <p><strong>AI analysis for informational purposes only.</strong></p>
            <p class="timestamp">Generated: {timestamp}</p>
            <p>To update holdings: edit holdings.txt on GitHub</p>
        </div>
    </div>
</body>
</html>
"""

    # Plain text version
    plain = f"""PORTFOLIO BRIEF — {date_str} | {len(holdings)} positions

=== MACRO CONTEXT ===
{macro_context}

=== YOUR HOLDINGS ===
"""
    for h in holdings:
        price_str = f"${h.get('price'):.2f}" if h.get('price') is not None else "N/A"
        change_val = h.get('change_percent')
        change_str = f"({change_val:+.2f}%)" if change_val is not None else "(N/A)"

        plain += f"\n{h['ticker']}: {price_str} {change_str}\n"
        plain += f"  Recommendation: {h.get('recommendation', 'N/A')} ({h.get('confidence', 'N/A')} confidence)\n"
        plain += f"  Reason: {h.get('reason', 'N/A')}\n"
        plain += f"  Risk: {h.get('risk', 'N/A')}\n"
        plain += f"  Reddit: {h.get('reddit', 'N/A')}\n"

    if opportunities:
        plain += "\n=== OPPORTUNITIES ===\n"
        for opp in opportunities:
            plain += f"\n{opp['ticker']} - {opp['company']} ({opp['exchange']})\n"
            plain += f"  Why Today: {opp['why_today']}\n"
            plain += f"  Upside: {opp['upside']} | Risk: {opp['risk']}\n"

    plain += f"\n---\nAI analysis for informational purposes only.\nGenerated: {timestamp}\nTo update holdings: edit holdings.txt on GitHub\n"

    return html, plain


def send_email(subject: str, html_content: str, plain_content: str):
    """Send email via SendGrid Python library"""

    # ALWAYS save email locally first
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"portfolio_email_{timestamp}.html"
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"✓ Email saved locally: {filename}")
    except Exception as save_error:
        logger.error(f"✗ Error saving email to file: {save_error}")

    try:
        # Log email details
        logger.info("="*60)
        logger.info("EMAIL SEND ATTEMPT (SendGrid Python SDK)")
        logger.info("="*60)
        logger.info(f"From: {EMAIL_FROM}")
        logger.info(f"To: {EMAIL_TO}")
        logger.info(f"Subject: {subject}")
        logger.info(f"SendGrid API Key: {SENDGRID_API_KEY[:20]}... (length: {len(SENDGRID_API_KEY)})")
        logger.info(f"API Key valid format: {'✓ Yes' if SENDGRID_API_KEY.startswith('SG.') else '✗ No - should start with SG.'}")

        # Create the email message using SendGrid SDK
        message = Mail(
            from_email=Email(EMAIL_FROM),
            to_emails=To(EMAIL_TO),
            subject=subject,
            plain_text_content=Content("text/plain", plain_content),
            html_content=Content("text/html", html_content)
        )

        # Initialize SendGrid client and send
        logger.info("Initializing SendGrid client...")
        sg = SendGridAPIClient(api_key=SENDGRID_API_KEY)

        logger.info("Sending email via SendGrid...")
        response = sg.send(message)

        logger.info(f"✓ Response Status: {response.status_code}")
        logger.info(f"  Response Headers: {dict(response.headers)}")
        logger.info(f"  Response Body: {response.body if hasattr(response, 'body') else '(none)'}")

        if response.status_code in [200, 202]:
            logger.info("✓ SUCCESS: Email sent to SendGrid!")
            logger.info("  → Check SendGrid Activity Feed: https://app.sendgrid.com/email_activity")
            logger.info(f"  → Email saved locally: {filename}")
            logger.info("="*60)
            return True
        else:
            logger.error(f"✗ Unexpected status code: {response.status_code}")
            logger.info("="*60)
            return False

    except Exception as e:
        logger.error("="*60)
        logger.error("✗ SENDGRID ERROR")
        logger.error("="*60)
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")

        # Try to extract more details from SendGrid errors
        if hasattr(e, 'body'):
            logger.error(f"Error body: {e.body}")
        if hasattr(e, 'status_code'):
            logger.error(f"Status code: {e.status_code}")
        if hasattr(e, 'headers'):
            logger.error(f"Headers: {e.headers}")

        logger.error(f"Email saved locally: {filename}")
        logger.error("="*60)

        # Import traceback for full error details
        import traceback
        logger.error("Full traceback:")
        logger.error(traceback.format_exc())

        return False


def run_portfolio_analysis():
    """Main pipeline - runs the complete analysis"""
    logger.info("="*60)
    logger.info("Starting portfolio analysis pipeline")
    logger.info("="*60)

    # Step 0: Git pull
    git_pull_updates()

    # Step 1: Read holdings
    holdings = read_holdings()
    if not holdings:
        logger.error("No holdings found. Aborting.")
        return

    # Step 2: Get macro context
    date_str = datetime.now().strftime('%A, %B %d, %Y')
    macro_context = get_macro_context(date_str)

    # Initialize API clients
    try:
        finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
        reddit_client = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT
        )
    except Exception as e:
        logger.error(f"Error initializing API clients: {e}")
        return

    # Step 3: Fetch data for all holdings
    logger.info("Fetching data for holdings...")
    holdings_data = []
    for ticker in holdings:
        data = fetch_ticker_data(ticker, finnhub_client)
        if data:
            # Add Reddit sentiment
            mentions, sentiment = get_reddit_sentiment(ticker, reddit_client)
            data['reddit_sentiment'] = sentiment
            holdings_data.append(data)
        else:
            logger.warning(f"Skipping {ticker} due to data fetch error")

    if not holdings_data:
        logger.error("No holdings data fetched. Aborting.")
        return

    # Step 4: Analyze holdings with Claude
    logger.info("Analyzing holdings with Claude...")
    analysis = analyze_holdings(holdings_data, macro_context)

    # DEBUG: Log Claude's raw response for holdings
    logger.info("="*60)
    logger.info("DEBUG - Holdings Analysis from Claude")
    logger.info("="*60)
    logger.info(f"Response length: {len(analysis)} characters")
    logger.info(f"Response preview (first 800 chars):\n{analysis[:800]}")
    logger.info("="*60)

    parsed_holdings = parse_holdings_analysis(analysis, holdings_data)

    # Step 5: Find new opportunities
    logger.info("Finding new opportunities...")
    trending_data = get_trending_tickers(finnhub_client, reddit_client, holdings)
    opportunities_text = find_opportunities(trending_data)

    # DEBUG: Log Claude's raw response for opportunities
    logger.info("="*60)
    logger.info("DEBUG - Opportunities from Claude")
    logger.info("="*60)
    logger.info(f"Response length: {len(opportunities_text)} characters")
    logger.info(f"Response preview (first 800 chars):\n{opportunities_text[:800]}")
    logger.info("="*60)

    parsed_opportunities = parse_opportunities(opportunities_text)

    # Validation: Check if parsing succeeded
    if len(parsed_holdings) == 0:
        logger.error("⚠️⚠️⚠️ CRITICAL WARNING: No holdings were parsed! Email will have empty holdings section!")
    if len(parsed_opportunities) == 0:
        logger.warning("⚠️ WARNING: No opportunities were parsed! Email will have no opportunities section.")

    # Step 6: Create email
    logger.info("Creating email...")
    subject = f"📈 Portfolio Brief — {date_str} | {len(parsed_holdings)} positions"
    html_content, plain_content = create_html_email(
        macro_context,
        parsed_holdings,
        parsed_opportunities,
        date_str
    )

    # Step 7: Send email
    logger.info("Sending email...")
    send_email(subject, html_content, plain_content)

    logger.info("="*60)
    logger.info("Portfolio analysis pipeline complete")
    logger.info("="*60)


def schedule_job():
    """Schedule the job to run weekdays at 11am"""
    logger.info("Scheduler initialized - Running Mon-Fri at 11:00am")

    schedule.every().monday.at("11:00").do(run_portfolio_analysis)
    schedule.every().tuesday.at("11:00").do(run_portfolio_analysis)
    schedule.every().wednesday.at("11:00").do(run_portfolio_analysis)
    schedule.every().thursday.at("11:00").do(run_portfolio_analysis)
    schedule.every().friday.at("11:00").do(run_portfolio_analysis)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        logger.info("Running immediate analysis (--now flag)")
        run_portfolio_analysis()
    else:
        schedule_job()
