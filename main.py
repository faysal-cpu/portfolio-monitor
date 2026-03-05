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

        prompt = f"""Today is {date_str}. In 3 bullet points, give the most important macro and geopolitical factors a Canadian retail investor should know TODAY that could affect North American and global markets. Be specific — mention actual events, not generic risks."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        response = message.content[0].text
        logger.info("Successfully fetched macro context from Claude")
        return response

    except Exception as e:
        logger.error(f"Error fetching macro context: {e}")
        return "• Market context unavailable\n• Please check logs for errors\n• Analysis continues with available data"


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

        return {
            'ticker': ticker,
            'price': current_price,
            'change_percent': change_percent,
            'headlines': headlines
        }

    except Exception as e:
        logger.error(f"Error fetching data for {ticker}: {e}")
        # Retry once on rate limit
        if "rate limit" in str(e).lower():
            logger.info(f"Rate limit hit for {ticker}, waiting 2s and retrying...")
            time.sleep(2)
            try:
                quote = finnhub_client.quote(ticker)
                return {
                    'ticker': ticker,
                    'price': quote.get('c', 0),
                    'change_percent': quote.get('dp', 0),
                    'headlines': []
                }
            except:
                return None
        return None


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
            holdings_text += f"  Price: ${(data.get('price') or 0):.2f}\n"
            holdings_text += f"  Day Change: {(data.get('change_percent') or 0):.2f}%\n"
            holdings_text += f"  News: {'; '.join(data.get('headlines', [])[:3]) if data.get('headlines') else 'No recent news'}\n"
            holdings_text += f"  Reddit: {data.get('reddit_sentiment', 'N/A')}\n"

        prompt = f"""You are a sharp portfolio analyst for a Canadian retail investor using a self-directed TFSA.

MACRO CONTEXT:
{macro_context}

HOLDINGS DATA:
{holdings_text}

For each stock give:
- RECOMMENDATION: BUY MORE / HOLD / SELL / WATCH
- CONFIDENCE: HIGH / MEDIUM / LOW
- REASON: one sentence, max 15 words, be specific
- RISK: one key risk to watch right now

Consider: price action, news, Reddit sentiment, geopolitical context. Be direct and opinionated. If something should be sold, say so clearly.

Format each stock as:
TICKER|RECOMMENDATION|CONFIDENCE|REASON|RISK"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
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
            trending_text += f"\n{data['ticker']}: ${(data.get('price') or 0):.2f} ({(data.get('change_percent') or 0):+.2f}%)\n"
            if data.get('headlines'):
                trending_text += f"  News: {'; '.join(data['headlines'][:2])}\n"

        prompt = f"""Identify 5 tickers to consider buying today. Investor profile: Canadian TFSA, likes momentum plays, binary catalysts, defence, AI, commodities, small caps. Somewhat risk tolerant.

TRENDING TICKERS:
{trending_text}

For each of 5 tickers, provide:
TICKER|COMPANY|WHY TODAY|UPSIDE|RISK|EXCHANGE

WHY TODAY: be specific about why this is relevant TODAY
UPSIDE POTENTIAL: HIGH/MEDIUM
RISK: one warning
EXCHANGE: TSX or US"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        response = message.content[0].text
        logger.info("Successfully found opportunities with Claude")
        return response

    except Exception as e:
        logger.error(f"Error finding opportunities: {e}")
        return "OPPORTUNITIES_UNAVAILABLE"


def parse_holdings_analysis(analysis: str, holdings_data: List[Dict]) -> List[Dict]:
    """Parse Claude's analysis into structured data"""
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
    data_map = {d['ticker']: d for d in holdings_data}

    for line in lines:
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 5:
                ticker = parts[0].strip()
                if ticker in data_map:
                    parsed.append({
                        'ticker': ticker,
                        'price': data_map[ticker]['price'],
                        'change_percent': data_map[ticker]['change_percent'],
                        'recommendation': parts[1].strip(),
                        'confidence': parts[2].strip(),
                        'reason': parts[3].strip(),
                        'risk': parts[4].strip() if len(parts) > 4 else 'N/A',
                        'reddit': data_map[ticker].get('reddit_sentiment', 'N/A')
                    })

    return parsed


def parse_opportunities(opportunities: str) -> List[Dict]:
    """Parse Claude's opportunities into structured data"""
    parsed = []

    if opportunities == "OPPORTUNITIES_UNAVAILABLE":
        return []

    lines = opportunities.strip().split('\n')

    for line in lines:
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 6:
                parsed.append({
                    'ticker': parts[0].strip(),
                    'company': parts[1].strip(),
                    'why_today': parts[2].strip(),
                    'upside': parts[3].strip(),
                    'risk': parts[4].strip(),
                    'exchange': parts[5].strip()
                })

    return parsed[:5]  # Limit to 5


def create_html_email(macro_context: str, holdings: List[Dict], opportunities: List[Dict], date_str: str) -> Tuple[str, str]:
    """Create HTML and plain text email content"""

    # HTML Email
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5; margin: 0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; background-color: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background-color: #1A1A2E; color: white; padding: 30px; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 28px; }}
        .section {{ padding: 30px; border-bottom: 1px solid #e0e0e0; }}
        .section h2 {{ color: #1A1A2E; margin-top: 0; border-left: 4px solid #00B386; padding-left: 15px; }}
        .macro-context {{ background-color: #f9f9f9; padding: 20px; border-radius: 5px; line-height: 1.8; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th {{ background-color: #1A1A2E; color: white; padding: 12px; text-align: left; font-weight: 600; }}
        td {{ padding: 12px; border-bottom: 1px solid #e0e0e0; }}
        tr:hover {{ background-color: #f5f5f5; }}
        .buy-more {{ background-color: #d4edda; color: #155724; font-weight: bold; padding: 4px 8px; border-radius: 3px; }}
        .hold {{ background-color: #e2e3e5; color: #383d41; font-weight: bold; padding: 4px 8px; border-radius: 3px; }}
        .sell {{ background-color: #f8d7da; color: #721c24; font-weight: bold; padding: 4px 8px; border-radius: 3px; }}
        .watch {{ background-color: #fff3cd; color: #856404; font-weight: bold; padding: 4px 8px; border-radius: 3px; }}
        .positive {{ color: #00B386; font-weight: bold; }}
        .negative {{ color: #dc3545; font-weight: bold; }}
        .opportunity-card {{ background-color: #f9f9f9; padding: 20px; margin: 15px 0; border-left: 4px solid #00B386; border-radius: 5px; }}
        .opportunity-card h3 {{ margin: 0 0 10px 0; color: #1A1A2E; }}
        .opportunity-card .ticker {{ font-size: 20px; font-weight: bold; color: #00B386; }}
        .footer {{ background-color: #1A1A2E; color: #999; padding: 20px; text-align: center; font-size: 12px; }}
        .footer .timestamp {{ color: #00B386; }}
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
                {macro_context.replace(chr(10), '<br>')}
            </div>
        </div>

        <div class="section">
            <h2>📊 Your Holdings</h2>
            <table>
                <thead>
                    <tr>
                        <th>Ticker</th>
                        <th>Price</th>
                        <th>Day Change</th>
                        <th>Recommendation</th>
                        <th>Confidence</th>
                        <th>Reason</th>
                        <th>Risk</th>
                        <th>Reddit</th>
                    </tr>
                </thead>
                <tbody>
"""

    for h in holdings:
        rec_class = ''
        if 'BUY MORE' in h['recommendation'].upper():
            rec_class = 'buy-more'
        elif 'SELL' in h['recommendation'].upper():
            rec_class = 'sell'
        elif 'WATCH' in h['recommendation'].upper():
            rec_class = 'watch'
        else:
            rec_class = 'hold'

        change_class = 'positive' if (h.get('change_percent') or 0) >= 0 else 'negative'

        html += f"""
                    <tr>
                        <td><strong>{h['ticker']}</strong></td>
                        <td>${(h.get('price') or 0):.2f}</td>
                        <td class="{change_class}">{(h.get('change_percent') or 0):+.2f}%</td>
                        <td><span class="{rec_class}">{h['recommendation']}</span></td>
                        <td>{h['confidence']}</td>
                        <td>{h['reason']}</td>
                        <td>{h['risk']}</td>
                        <td>{h['reddit']}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>
"""

    if opportunities:
        html += """
        <div class="section">
            <h2>🔥 Opportunities</h2>
"""
        for opp in opportunities:
            html += f"""
            <div class="opportunity-card">
                <div class="ticker">{opp['ticker']}</div>
                <h3>{opp['company']}</h3>
                <p><strong>Why Today:</strong> {opp['why_today']}</p>
                <p><strong>Upside:</strong> {opp['upside']} | <strong>Risk:</strong> {opp['risk']}</p>
                <p><strong>Exchange:</strong> {opp['exchange']}</p>
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
        plain += f"\n{h['ticker']}: ${h['price']:.2f} ({h['change_percent']:+.2f}%)\n"
        plain += f"  Recommendation: {h['recommendation']} ({h['confidence']} confidence)\n"
        plain += f"  Reason: {h['reason']}\n"
        plain += f"  Risk: {h['risk']}\n"
        plain += f"  Reddit: {h['reddit']}\n"

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
    parsed_holdings = parse_holdings_analysis(analysis, holdings_data)

    # Step 5: Find new opportunities
    logger.info("Finding new opportunities...")
    trending_data = get_trending_tickers(finnhub_client, reddit_client, holdings)
    opportunities_text = find_opportunities(trending_data)
    parsed_opportunities = parse_opportunities(opportunities_text)

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
    """Schedule the job to run weekdays at 7am"""
    logger.info("Scheduler initialized - Running Mon-Fri at 7:00am")

    schedule.every().monday.at("07:00").do(run_portfolio_analysis)
    schedule.every().tuesday.at("07:00").do(run_portfolio_analysis)
    schedule.every().wednesday.at("07:00").do(run_portfolio_analysis)
    schedule.every().thursday.at("07:00").do(run_portfolio_analysis)
    schedule.every().friday.at("07:00").do(run_portfolio_analysis)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        logger.info("Running immediate analysis (--now flag)")
        run_portfolio_analysis()
    else:
        schedule_job()
