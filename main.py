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
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
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

# Load .env file if it exists (for local dev), otherwise use Railway/cloud environment variables
if os.path.exists(ENV_FILE_PATH):
    env_loaded = load_dotenv(ENV_FILE_PATH, override=True)
    logger.info(f".env file loaded: {env_loaded}")
else:
    logger.info("No .env file found - using environment variables from Railway/cloud platform")
    load_dotenv()  # Still call load_dotenv() in case variables are set elsewhere

# API Clients
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
BREVO_API_KEY = os.getenv('BREVO_API_KEY')
EMAIL_TO = os.getenv('EMAIL_TO')
EMAIL_FROM = os.getenv('EMAIL_FROM')

# Debug: Show what was loaded
logger.info("Loaded credentials:")
logger.info(f"  FINNHUB_API_KEY: {FINNHUB_API_KEY[:20] + '...' if FINNHUB_API_KEY else '✗ MISSING'}")
logger.info(f"  ALPHA_VANTAGE_API_KEY: {ALPHA_VANTAGE_API_KEY[:15] + '...' if ALPHA_VANTAGE_API_KEY else '✗ MISSING'}")
logger.info(f"  ANTHROPIC_API_KEY: {ANTHROPIC_API_KEY[:20] + '...' if ANTHROPIC_API_KEY else '✗ MISSING'}")
logger.info(f"  BREVO_API_KEY: {BREVO_API_KEY[:20] + '...' if BREVO_API_KEY else '✗ MISSING'}")
logger.info(f"  EMAIL_FROM: {EMAIL_FROM}")
logger.info(f"  EMAIL_TO: {EMAIL_TO}")
logger.info("="*60)

# Validate critical credentials
if not EMAIL_FROM or not EMAIL_TO or not BREVO_API_KEY:
    logger.error("CRITICAL: Missing required email credentials!")
    logger.error("Please ensure you have set these environment variables:")
    logger.error("  BREVO_API_KEY=xkeysib-your_brevo_api_key")
    logger.error("  EMAIL_FROM=your_sender@example.com")
    logger.error("  EMAIL_TO=your_recipient@example.com")
    logger.error("On Railway: Set these in the Variables tab")
    logger.error("Locally: Add them to your .env file")
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


def get_macro_context(date_str: str, holdings: List[str]) -> str:
    """Module 1: Get macro/geopolitical context - RESTRUCTURED per audit"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Categorize holdings by exposure
        energy_metal_tickers = [t for t in holdings if t in ['HBM', 'LUN', 'FCX', 'CCJ']]
        semi_tech_tickers = [t for t in holdings if t in ['LRCX', 'AMAT', 'MU', 'AXTI', 'TSEM', 'ORCL', 'FLEX']]
        defense_space_tickers = [t for t in holdings if t in ['MDA', 'NOC', 'ASTS']]
        other_tickers = [t for t in holdings if t not in energy_metal_tickers + semi_tech_tickers + defense_space_tickers]

        prompt = f"""Today is {date_str}. You are writing the macro context section for a Canadian TFSA investor's daily portfolio brief.

Portfolio holdings include:
- Energy/Metals: {', '.join(energy_metal_tickers) if energy_metal_tickers else 'None'}
- Semiconductors/Tech: {', '.join(semi_tech_tickers) if semi_tech_tickers else 'None'}
- Defense/Space: {', '.join(defense_space_tickers) if defense_space_tickers else 'None'}
- Other: {', '.join(other_tickers) if other_tickers else 'None'}

Write 2-3 narrative paragraphs (150-200 words EACH) covering today's most relevant macro developments.

PARAGRAPH STRUCTURE REQUIREMENTS:

1. START each paragraph with: Emoji + Descriptive Headline with Em Dash
   ✓ GOOD: "🛢️ Middle East War & Oil Shock: A Double-Edged Sword for Canada — "
   ✓ GOOD: "🏛️ New Fed Chair Kevin Warsh Takes the Helm — Rate Cuts Off the Table — "
   ✗ BAD: "🛢️ COMMODITIES & ENERGY:"
   ✗ BAD: "💰 RATES & TECH:"

2. Write flowing narrative that integrates:
   - The macro event and WHY it matters for this portfolio
   - Affected tickers mentioned naturally: "For HBM and FCX, higher diesel costs squeeze margins..."
   - Specific forward-looking catalyst with date: "Watch the OPEC+ meeting May 28 for..."

3. Direct analytical tone, no hype language

BANNED PHRASES: "kills", "demands action", "unambiguous", "firing on all cylinders", "gift", "market is underreacting", "transformational"

PARAGRAPH TOPICS (cover 2-3 as relevant today):
- Commodities/Energy (oil, copper, uranium): affects {', '.join(energy_metal_tickers) if energy_metal_tickers else 'holdings'}
- Interest Rates/Fed/BoC: affects tech positions and growth stocks
- Geopolitics/Defense/Trade: affects defense and international exposure

OUTPUT FORMAT (start immediately, no intro text):
🛢️ [Descriptive Headline with Em Dash] — [150-200 word narrative paragraph with natural ticker mentions and forward catalyst]

💰 [Descriptive Headline with Em Dash] — [150-200 word narrative paragraph]

(Third paragraph optional if highly relevant)

Your first character must be the emoji. No text before it."""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,  # Increased for narrative format (Email 1 style)
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
            # Strip any intro text before the first emoji section header
            import re
            # Find the first occurrence of emoji section headers
            emoji_pattern = r'(🛢️|💰|🌍)\s*(COMMODITIES|RATES|GEOPOLITICS)'
            match = re.search(emoji_pattern, response_text)
            if match:
                # Start from the emoji
                response_text = response_text[match.start():]

            logger.info("Successfully fetched structured macro context")
            return response_text
        else:
            logger.warning("No text found in macro context response")
            return "🛢️ COMMODITIES & ENERGY: No data available\n💰 RATES & TECH: No data available\n🌍 GEOPOLITICS & DEFENSE: No data available"

    except Exception as e:
        logger.error(f"Error fetching macro context: {e}")
        return "🛢️ COMMODITIES & ENERGY: Error fetching data\n💰 RATES & TECH: Error fetching data\n🌍 GEOPOLITICS & DEFENSE: Error fetching data"


def fetch_alpha_vantage_company_info(ticker: str) -> Optional[Dict]:
    """Fetch company info from Alpha Vantage (for Canadian TSX/CSE stocks)"""
    if not ALPHA_VANTAGE_API_KEY:
        return None

    try:
        # Try Canadian exchange suffixes: .TO (TSX), .V (Venture), .CN (CSE)
        symbols_to_try = [f"{ticker}.TO", f"{ticker}.V", f"{ticker}.CN"]

        for symbol in symbols_to_try:
            try:
                url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
                response = requests.get(url, timeout=10)
                data = response.json()

                # Check if we got valid company data
                if data and 'Symbol' in data and data.get('Name'):
                    name = data.get('Name', '').strip()
                    exchange = data.get('Exchange', '').strip()
                    description = data.get('Description', '')
                    industry = data.get('Industry', '')

                    if name and len(name) > 1:
                        logger.info(f"✓ Alpha Vantage company info for {ticker} (as {symbol}): {name} ({exchange})")

                        # Build business description
                        business_description = industry if industry else description[:100] if description else f"{exchange} company"

                        return {
                            'confirmed_name': name,
                            'exchange': exchange,
                            'business_description': business_description,
                            'canonical_ticker': symbol,
                            'source': 'Alpha Vantage'
                        }

                time.sleep(12)  # Alpha Vantage free tier: 5 calls/min
            except Exception as e:
                logger.warning(f"Alpha Vantage company info attempt failed for {symbol}: {e}")
                continue

        return None
    except Exception as e:
        logger.error(f"Alpha Vantage company info error for {ticker}: {e}")
        return None


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
                            'news_sentiment': 'N/A',
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


def fetch_ticker_data(ticker: str, finnhub_client, identity_cache: Optional[Dict] = None) -> Optional[Dict]:
    """Fetch price, change, and news for a single ticker

    Also verifies company identity if identity_cache is provided.
    """
    # Verify company identity first (if cache provided)
    identity_verified = False
    identity_data = {}

    if identity_cache is not None:
        identity_verified, identity_data = verify_company_identity(ticker, finnhub_client, identity_cache)
        if not identity_verified:
            logger.warning(f"IDENTITY NOT VERIFIED: {ticker} - will flag in analysis")

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
                'source': 'Finnhub',
                'identity_verified': identity_verified,
                'identity_data': identity_data
            }
        else:
            # No price data from Finnhub, try Alpha Vantage
            logger.warning(f"No price data from Finnhub for {ticker}, trying Alpha Vantage...")
            av_data = fetch_alpha_vantage_data(ticker)
            if av_data:
                # Keep Finnhub news if available
                av_data['headlines'] = headlines
                av_data['identity_verified'] = identity_verified
                av_data['identity_data'] = identity_data
                return av_data
            else:
                # Both APIs failed, return ticker with N/A data
                logger.warning(f"Both APIs failed for {ticker}, including with N/A data")
                return {
                    'ticker': ticker,
                    'price': None,
                    'change_percent': None,
                    'headlines': headlines,
                    'source': 'N/A',
                    'identity_verified': identity_verified,
                    'identity_data': identity_data
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
                        'source': 'Finnhub',
                        'identity_verified': identity_verified,
                        'identity_data': identity_data
                    }
            except:
                pass

        # Try Alpha Vantage as fallback
        logger.warning(f"Finnhub failed for {ticker}, trying Alpha Vantage...")
        av_data = fetch_alpha_vantage_data(ticker)
        if av_data:
            av_data['identity_verified'] = identity_verified
            av_data['identity_data'] = identity_data
            return av_data

        # Both failed, return N/A data
        return {
            'ticker': ticker,
            'price': None,
            'change_percent': None,
            'headlines': [],
            'source': 'N/A',
            'identity_verified': identity_verified,
            'identity_data': identity_data
        }



def analyze_holdings(holdings_data: List[Dict], macro_context: str, rec_history: Dict, position_status: Dict) -> str:
    """Module 2: Analyze holdings with ALL AUDIT IMPROVEMENTS"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Format holdings data WITH prior recommendations and identity verification
        holdings_text = ""
        for data in holdings_data:
            ticker = data['ticker']
            holdings_text += f"\n{ticker}:\n"

            # Identity verification
            if data.get('identity_verified'):
                identity = data.get('identity_data', {})
                holdings_text += f"  Company: {identity.get('confirmed_name', 'Unknown')} ({identity.get('exchange', 'Unknown')})\n"
                holdings_text += f"  Business: {identity.get('business_description', 'N/A')}\n"
            else:
                holdings_text += f"  ⚠️ IDENTITY NOT VERIFIED - OUTPUT 'NO DATA' FOR THIS TICKER\n"

            # Price data
            price = data.get('price')
            if price is not None:
                holdings_text += f"  Current Price: ${price:.2f}\n"
            else:
                holdings_text += f"  Current Price: N/A (DATA MISSING - OUTPUT 'NO DATA' FOR THIS TICKER)\n"

            # Change percent
            change = data.get('change_percent')
            if change is not None:
                holdings_text += f"  Day Change: {change:.2f}%\n"
            else:
                holdings_text += f"  Day Change: N/A\n"

            # Prior recommendation
            prior_rec, prior_date = get_prior_recommendation(ticker, rec_history)
            if prior_rec and prior_date:
                holdings_text += f"  PRIOR RECOMMENDATION: {prior_rec} on {prior_date}\n"
            else:
                holdings_text += f"  PRIOR RECOMMENDATION: None (first analysis)\n"

            # Position status
            status = position_status.get(ticker, 'OPEN')
            if status == 'PENDING EXIT':
                holdings_text += f"  POSITION STATUS: PENDING EXIT - DO NOT ANALYZE, OUTPUT SELL ONLY\n"
            else:
                holdings_text += f"  News: {'; '.join(data.get('headlines', [])[:2]) if data.get('headlines') else 'No recent news'}\n"

        prompt = f"""Canadian TFSA portfolio analyst. Daily holdings analysis.

MACRO: {macro_context}

HOLDINGS:
{holdings_text}

RULES:
1. Identity not verified (⚠️) → "TICKER|NO DATA|N/A|Company identity could not be verified. Verify ticker symbol is correct.|N/A"
2. Missing price → "TICKER|NO DATA|N/A|No price data|N/A"
3. PENDING EXIT status → "TICKER|SELL|HIGH|Exit position|Capital preservation"
4. Changed recommendation → Start REASON: "CHANGE FROM [prior] because [event]"
5. Catalyst required: earnings date, analyst action (firm+date), contract, regulatory event, specific macro event
6. BANNED: "thesis intact", "kills", "demands action", "unambiguous", "firing on all cylinders", "gift", "market is underreacting", "transformational"

7. CONFIDENCE CALIBRATION RUBRIC (for BUY MORE recommendations):
   Count how many of these 5 conditions are TRUE:
   a) Strong analyst consensus: 2+ analysts with Buy/Outperform rating AND recent PT raise (last 60 days)
   b) Recent earnings beat: Last quarterly report (within 60 days) beat on revenue or EPS
   c) Macro tailwind: Direct relevance to today's macro context (specific, not generic)
   d) Technical confirmation: Stock up today OR holding key support level (not down >3%)
   e) No material unresolved risk: No dilution risk, sharp unexplained drop, or governance flag

   Assign confidence:
   - 3+ conditions true = HIGH confidence allowed
   - 1-2 conditions true = Cap at MEDIUM (even if bullish)
   - 0-1 conditions true = Cap at LOW

   For HOLD: Always MEDIUM unless major risk → then LOW
   For SELL/WATCH: Use HIGH if clear catalyst, MEDIUM if deteriorating, LOW if uncertain

8. MANDATORY SELL EVALUATION TRIGGERS:
   If a holding meets 2+ of these criteria, you MUST explicitly evaluate for SELL:
   a) Down >8% single day with no positive news explaining it
   b) Down >15% over last 5 trading days (if data available)
   c) Large unexplained move (>10% either direction, <2 news articles)
   d) Dilutive financing: offering/shelf prospectus with terms undisclosed or unfavorable
   e) Governance red flag: AGM adjournment, material insider selling, restatement risk
   f) Identity unconfirmed for 2+ consecutive days

   When triggered: Evaluate whether to recommend SELL. If NOT selling, explicitly state why in REASON.
   Example: "HOLD despite -12% week — pullback on sector rotation, fundamentals intact, next catalyst is [date/event]"

9. Max words: REASON 80, RISK 50

Output ONLY pipe lines:
TICKER|RECOMMENDATION|CONFIDENCE|REASON|RISK

BUY MORE, HOLD, SELL, or NO DATA | HIGH, MEDIUM, LOW, or N/A

Start with first ticker:"""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=6000,
            temperature=0.2,  # Lower temperature for more consistent adherence to rules
            messages=[{"role": "user", "content": prompt}]
        )

        response = message.content[0].text
        logger.info("Successfully analyzed holdings with audit-compliant prompt")
        return response

    except Exception as e:
        logger.error(f"Error analyzing holdings with Claude: {e}")
        return "ANALYSIS_FAILED"


def load_recommendation_history() -> Dict:
    """Load history of all recommendations by date and ticker"""
    history_file = 'recommendations_history.json'
    try:
        if os.path.exists(history_file):
            with open(history_file, 'r') as f:
                import json
                return json.load(f)
        return {}
    except Exception as e:
        logger.warning(f"Error loading recommendation history: {e}")
        return {}


def save_recommendation_history(history: Dict):
    """Save complete recommendation history"""
    history_file = 'recommendations_history.json'
    try:
        import json
        with open(history_file, 'w') as f:
            json.dump(history, f, indent=2)
        logger.info(f"Saved recommendation history with {len(history)} tickers")
    except Exception as e:
        logger.error(f"Error saving recommendation history: {e}")


def get_prior_recommendation(ticker: str, history: Dict) -> Tuple[Optional[str], Optional[str]]:
    """Get the most recent recommendation for a ticker
    Returns: (recommendation, date) or (None, None)"""
    if ticker not in history or not history[ticker]:
        return None, None

    # Get the most recent entry
    dates = sorted(history[ticker].keys(), reverse=True)
    if dates:
        most_recent_date = dates[0]
        return history[ticker][most_recent_date], most_recent_date
    return None, None


def load_position_status() -> Dict:
    """Load position status tracking (OPEN/PENDING EXIT/CLOSED)"""
    status_file = 'position_status.json'
    try:
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                import json
                return json.load(f)
        return {}
    except Exception as e:
        logger.warning(f"Error loading position status: {e}")
        return {}


def save_position_status(status: Dict):
    """Save position status tracking"""
    status_file = 'position_status.json'
    try:
        import json
        with open(status_file, 'w') as f:
            json.dump(status, f, indent=2)
        logger.info(f"Saved position status for {len(status)} tickers")
    except Exception as e:
        logger.error(f"Error saving position status: {e}")


def update_position_status(ticker: str, recommendation: str, status_dict: Dict) -> str:
    """Update position status based on recommendation
    Returns: OPEN, PENDING EXIT, or CLOSED"""
    if recommendation == 'SELL':
        status_dict[ticker] = 'PENDING EXIT'
        return 'PENDING EXIT'
    elif ticker not in status_dict or status_dict[ticker] == 'PENDING EXIT':
        # If no status or was pending exit, set to OPEN
        status_dict[ticker] = 'OPEN'
    return status_dict.get(ticker, 'OPEN')


def load_company_identity_cache() -> Dict:
    """Load company identity verification cache"""
    cache_file = 'company_identity_cache.json'
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                import json
                return json.load(f)
        return {}
    except Exception as e:
        logger.warning(f"Error loading company identity cache: {e}")
        return {}


def save_company_identity_cache(cache: Dict):
    """Save company identity verification cache"""
    cache_file = 'company_identity_cache.json'
    try:
        import json
        with open(cache_file, 'w') as f:
            json.dump(cache, f, indent=2)
        logger.info(f"Saved company identity cache with {len(cache)} tickers")
    except Exception as e:
        logger.error(f"Error saving company identity cache: {e}")


def verify_company_identity(ticker: str, finnhub_client, cache: Dict) -> Tuple[bool, Dict]:
    """Verify company identity before analysis - auto-detects exchange suffix

    Returns: (is_verified, identity_data)

    identity_data contains:
    - confirmed_name: str
    - exchange: str
    - business_description: str
    - canonical_ticker: str (may include exchange suffix like .TO)
    - last_verified: str (date)
    - verification_confidence: str (HIGH/MEDIUM/LOW)
    - failed_verifications: int
    """
    from datetime import datetime, timedelta

    # Clear stale failed verifications (LOW confidence older than 1 day)
    # This ensures failed attempts are retried daily with exchange auto-detection
    if ticker in cache:
        cached = cache[ticker]
        if cached.get('verification_confidence') == 'LOW':
            try:
                last_verified = datetime.strptime(cached.get('last_verified', ''), '%Y-%m-%d')
                days_since = (datetime.now() - last_verified).days
                if days_since >= 1:
                    logger.info(f"CLEARING STALE FAILED CACHE: {ticker} (failed {days_since} days ago, will retry)")
                    del cache[ticker]
            except:
                pass

    # Check cache - if verified <7 days ago with HIGH confidence, return cached
    if ticker in cache:
        cached = cache[ticker]
        last_verified_str = cached.get('last_verified', '')
        try:
            last_verified = datetime.strptime(last_verified_str, '%Y-%m-%d')
            days_since = (datetime.now() - last_verified).days

            if days_since < 7 and cached.get('verification_confidence') == 'HIGH':
                logger.info(f"IDENTITY CACHE HIT: {ticker} verified {days_since} days ago")
                return True, cached
        except:
            pass  # Cache entry invalid, re-verify

    # Try multiple ticker formats (auto-detect exchange)
    ticker_variants = [ticker]

    # If ticker has no suffix, try common Canadian exchanges
    if '.' not in ticker:
        ticker_variants.append(f"{ticker}.TO")  # TSX
        ticker_variants.append(f"{ticker}.V")   # TSX Venture
        ticker_variants.append(f"{ticker}.CN")  # Canadian Securities Exchange

    logger.info(f"IDENTITY VERIFICATION: Will try {len(ticker_variants)} variants for {ticker}: {ticker_variants}")
    last_error = None

    for ticker_variant in ticker_variants:
        try:
            time.sleep(0.1)  # Rate limiting
            profile = finnhub_client.company_profile2(symbol=ticker_variant)

            if not profile:
                logger.debug(f"No profile data for {ticker_variant}, trying next variant...")
                continue

            name = profile.get('name', '').strip()
            exchange = profile.get('exchange', '').strip()
            country = profile.get('country', '').strip()
            industry = profile.get('finnhubIndustry', '').strip()

            # Validation checks
            if not name or len(name) < 2:
                logger.debug(f"Invalid name for {ticker_variant}: '{name}', trying next variant...")
                continue

            if not exchange:
                logger.debug(f"No exchange data for {ticker_variant}, trying next variant...")
                continue

            # SUCCESS - Found valid company data
            # Build business description
            business_description = industry if industry else f"{country} company"
            if len(business_description) > 100:
                business_description = business_description[:97] + "..."

            # Cache the result with canonical ticker
            identity_data = {
                'confirmed_name': name,
                'exchange': exchange,
                'business_description': business_description,
                'canonical_ticker': ticker_variant,  # Store which format worked
                'last_verified': datetime.now().strftime('%Y-%m-%d'),
                'verification_confidence': 'HIGH',
                'failed_verifications': 0
            }

            cache[ticker] = identity_data

            if ticker_variant != ticker:
                logger.info(f"IDENTITY VERIFIED: {ticker} → {ticker_variant} = {name} ({exchange})")
            else:
                logger.info(f"IDENTITY VERIFIED: {ticker} = {name} ({exchange})")

            return True, identity_data

        except Exception as e:
            logger.debug(f"Error checking {ticker_variant}: {e}")
            last_error = e
            continue  # Try next variant

    # All Finnhub variants failed - try Alpha Vantage fallback for Canadian stocks
    logger.warning(f"IDENTITY VERIFICATION FAILED on Finnhub: {ticker} (tried {len(ticker_variants)} variants)")
    if last_error:
        logger.error(f"Last Finnhub error: {last_error}")

    # Try Alpha Vantage as fallback (supports Canadian TSX stocks on free tier)
    logger.info(f"Trying Alpha Vantage fallback for {ticker}...")
    av_company_info = fetch_alpha_vantage_company_info(ticker)

    if av_company_info:
        # Success with Alpha Vantage
        identity_data = {
            'confirmed_name': av_company_info['confirmed_name'],
            'exchange': av_company_info['exchange'],
            'business_description': av_company_info['business_description'],
            'canonical_ticker': av_company_info['canonical_ticker'],
            'last_verified': datetime.now().strftime('%Y-%m-%d'),
            'verification_confidence': 'HIGH',
            'failed_verifications': 0
        }

        cache[ticker] = identity_data
        logger.info(f"IDENTITY VERIFIED via Alpha Vantage: {ticker} → {av_company_info['canonical_ticker']} = {av_company_info['confirmed_name']} ({av_company_info['exchange']})")
        return True, identity_data

    # Both Finnhub and Alpha Vantage failed
    logger.error(f"IDENTITY VERIFICATION FAILED: {ticker} (Finnhub and Alpha Vantage both failed)")
    return False, _record_failed_verification(ticker, cache)


def _record_failed_verification(ticker: str, cache: Dict) -> Dict:
    """Record a failed verification attempt"""
    if ticker in cache:
        cache[ticker]['failed_verifications'] = cache[ticker].get('failed_verifications', 0) + 1
        logger.warning(f"IDENTITY: {ticker} has {cache[ticker]['failed_verifications']} failed verifications")
    else:
        cache[ticker] = {
            'confirmed_name': 'UNVERIFIED',
            'exchange': 'UNKNOWN',
            'business_description': 'Identity could not be verified',
            'last_verified': datetime.now().strftime('%Y-%m-%d'),
            'verification_confidence': 'LOW',
            'failed_verifications': 1
        }
    return cache[ticker]


def load_recommendation_cache() -> Dict:
    """Load cache of recently recommended stocks to avoid repetition (for Opportunities)"""
    cache_file = 'recommendations_cache.json'
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                import json
                cache = json.load(f)
                # Clean old entries (older than 14 days)
                cutoff = (datetime.now() - timedelta(days=14)).isoformat()
                cache = {k: v for k, v in cache.items() if v > cutoff}
                return cache
        return {}
    except Exception as e:
        logger.warning(f"Error loading recommendation cache: {e}")
        return {}


def save_recommendation_cache(cache: Dict):
    """Save cache of recently recommended stocks"""
    cache_file = 'recommendations_cache.json'
    try:
        import json
        with open(cache_file, 'w') as f:
            json.dump(cache, f, indent=2)
        logger.info(f"Saved {len(cache)} tickers to recommendation cache")
    except Exception as e:
        logger.error(f"Error saving recommendation cache: {e}")


def load_opportunity_scorecard() -> Dict:
    """Load opportunity scorecard tracking last 7 days of recommendations"""
    scorecard_file = 'opportunity_scorecard.json'
    try:
        if os.path.exists(scorecard_file):
            with open(scorecard_file, 'r') as f:
                import json
                scorecard = json.load(f)
                # Filter to last 7 days only
                cutoff_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                filtered = {date: opps for date, opps in scorecard.items() if date >= cutoff_date}
                return filtered
        return {}
    except Exception as e:
        logger.warning(f"Error loading opportunity scorecard: {e}")
        return {}


def save_opportunity_scorecard(scorecard: Dict):
    """Save opportunity scorecard"""
    scorecard_file = 'opportunity_scorecard.json'
    try:
        import json
        with open(scorecard_file, 'w') as f:
            json.dump(scorecard, f, indent=2)
        total_opps = sum(len(opps) for opps in scorecard.values())
        logger.info(f"Saved opportunity scorecard with {total_opps} opportunities across {len(scorecard)} days")
    except Exception as e:
        logger.error(f"Error saving opportunity scorecard: {e}")


def add_opportunity_to_scorecard(ticker: str, price: float, catalyst: str, scorecard: Dict):
    """Add a new opportunity to today's scorecard entry"""
    today = datetime.now().strftime('%Y-%m-%d')

    if today not in scorecard:
        scorecard[today] = []

    # Check if ticker already in today's list
    existing_tickers = [opp['ticker'] for opp in scorecard[today]]
    if ticker not in existing_tickers:
        scorecard[today].append({
            'ticker': ticker,
            'date_suggested': today,
            'price_at_suggestion': price,
            'catalyst': catalyst[:100],  # Truncate catalyst
            'current_price': price,
            'last_updated': today,
            'gain_pct': 0.0,
            'verdict': 'PENDING'
        })
        logger.info(f"SCORECARD: Added {ticker} at ${price:.2f}")


def update_scorecard_prices(scorecard: Dict, finnhub_client) -> Dict:
    """Update current prices for all opportunities in the scorecard"""
    if not scorecard:
        return scorecard

    logger.info("Updating scorecard prices...")
    today = datetime.now().strftime('%Y-%m-%d')
    updated_count = 0

    for date, opportunities in scorecard.items():
        for opp in opportunities:
            ticker = opp['ticker']
            try:
                time.sleep(0.2)  # Rate limiting
                quote = finnhub_client.quote(ticker)
                current_price = quote.get('c', 0)

                if current_price > 0:
                    opp['current_price'] = current_price
                    opp['last_updated'] = today

                    # Calculate gain percentage
                    entry_price = opp['price_at_suggestion']
                    gain_pct = ((current_price - entry_price) / entry_price) * 100
                    opp['gain_pct'] = round(gain_pct, 2)

                    # Assign verdict
                    if gain_pct > 10:
                        opp['verdict'] = 'HIT - strong gain'
                    elif gain_pct > 0:
                        opp['verdict'] = 'HIT - modest gain'
                    elif gain_pct > -5:
                        opp['verdict'] = 'FLAT - watch'
                    elif gain_pct > -10:
                        opp['verdict'] = 'MISS - small loss'
                    else:
                        opp['verdict'] = 'MISS - significant loss'

                    updated_count += 1
                    logger.debug(f"SCORECARD: {ticker} ${entry_price:.2f} → ${current_price:.2f} ({gain_pct:+.1f}%)")

            except Exception as e:
                logger.warning(f"SCORECARD: Could not update price for {ticker}: {e}")
                continue

    logger.info(f"SCORECARD: Updated {updated_count} opportunity prices")
    return scorecard


def generate_scorecard_summary(scorecard: Dict) -> str:
    """Generate HTML table showing last 7 days of opportunity performance"""
    if not scorecard:
        return ""

    # Flatten all opportunities and sort by date (newest first)
    all_opps = []
    for date, opportunities in scorecard.items():
        all_opps.extend(opportunities)

    if not all_opps:
        return ""

    # Sort by date suggested (newest first)
    all_opps.sort(key=lambda x: x['date_suggested'], reverse=True)

    # Limit to 15 most recent
    all_opps = all_opps[:15]

    html = """
        <div style="background: #f8fafc; border: 2px solid #e2e8f0; border-radius: 10px; padding: 20px; margin-bottom: 30px;">
            <h3 style="margin: 0 0 15px 0; color: #1e293b; font-size: 16px;">📊 Opportunity Scorecard (Last 7 Days)</h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="background: #667eea; color: white;">
                        <th style="padding: 10px; text-align: left;">Ticker</th>
                        <th style="padding: 10px; text-align: left;">Date</th>
                        <th style="padding: 10px; text-align: right;">Entry $</th>
                        <th style="padding: 10px; text-align: right;">Now $</th>
                        <th style="padding: 10px; text-align: right;">Gain %</th>
                        <th style="padding: 10px; text-align: left;">Verdict</th>
                    </tr>
                </thead>
                <tbody>
"""

    for opp in all_opps:
        ticker = opp['ticker']
        date_short = datetime.strptime(opp['date_suggested'], '%Y-%m-%d').strftime('%b %d')
        entry_price = f"${opp['price_at_suggestion']:.2f}"
        current_price = f"${opp['current_price']:.2f}"
        gain_pct = opp['gain_pct']
        verdict = opp['verdict']

        # Color coding
        if gain_pct > 0:
            gain_class = 'color: #10b981; font-weight: 700;'
        elif gain_pct < 0:
            gain_class = 'color: #ef4444; font-weight: 700;'
        else:
            gain_class = 'color: #64748b;'

        gain_str = f"{gain_pct:+.1f}%"

        html += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 8px; font-weight: 600;">{ticker}</td>
                        <td style="padding: 8px;">{date_short}</td>
                        <td style="padding: 8px; text-align: right;">{entry_price}</td>
                        <td style="padding: 8px; text-align: right;">{current_price}</td>
                        <td style="padding: 8px; text-align: right; {gain_class}">{gain_str}</td>
                        <td style="padding: 8px; font-size: 12px;">{verdict}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>
"""

    return html


def detect_recommendation_changes(parsed_holdings: List[Dict]) -> List[Dict]:
    """Detect which holdings had recommendation changes from prior day"""
    changes = []

    for h in parsed_holdings:
        if h.get('changed'):
            ticker = h['ticker']
            prior_rec = h.get('prior_recommendation', 'N/A')
            current_rec = h['recommendation']
            prior_date = h.get('prior_date', 'Unknown')

            # Extract trigger from reason (first 80 chars)
            reason = h.get('reason', '')
            trigger = reason[:80] + "..." if len(reason) > 80 else reason

            changes.append({
                'ticker': ticker,
                'prior_rec': prior_rec,
                'current_rec': current_rec,
                'prior_date': prior_date,
                'trigger': trigger
            })

    return changes


def generate_change_log_table(changes: List[Dict]) -> str:
    """Generate HTML table showing recommendation changes"""
    if not changes:
        return ""

    html = """
        <div style="background: #fff3cd; border-left: 4px solid #f59e0b; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
            <h3 style="margin: 0 0 12px 0; color: #1a202c; font-size: 16px;">⚠️ Recommendation Changes</h3>
            <table style="width: 100%; font-size: 13px; border-collapse: collapse;">
                <thead>
                    <tr style="border-bottom: 2px solid #fde68a;">
                        <th style="padding: 8px; text-align: left; font-weight: 600;">Ticker</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600;">Was</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600;">Now</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600;">Trigger</th>
                    </tr>
                </thead>
                <tbody>
"""

    for change in changes:
        html += f"""
                    <tr style="border-bottom: 1px solid #fde68a;">
                        <td style="padding: 6px 8px; font-weight: 600;">{change['ticker']}</td>
                        <td style="padding: 6px 8px;">{change['prior_rec']}</td>
                        <td style="padding: 6px 8px; font-weight: 600;">{change['current_rec']}</td>
                        <td style="padding: 6px 8px; font-size: 12px;">{change['trigger']}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>
"""

    return html


def load_price_anomaly_log() -> Dict:
    """Load price anomaly tracking log"""
    log_file = 'price_anomaly_log.json'
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                import json
                return json.load(f)
        return {}
    except Exception as e:
        logger.warning(f"Error loading price anomaly log: {e}")
        return {}


def save_price_anomaly_log(log: Dict):
    """Save price anomaly tracking log"""
    log_file = 'price_anomaly_log.json'
    try:
        import json
        with open(log_file, 'w') as f:
            json.dump(log, f, indent=2)
        logger.info(f"Saved price anomaly log for {len(log)} tickers")
    except Exception as e:
        logger.error(f"Error saving price anomaly log: {e}")


def detect_price_anomalies(holdings_data: List[Dict], anomaly_log: Dict) -> List[Dict]:
    """Detect >20% overnight price moves with no news

    Returns list of anomalies with ticker, jump_pct, news_count
    """
    anomalies = []
    today = datetime.now().strftime('%Y-%m-%d')

    for data in holdings_data:
        ticker = data['ticker']
        current_price = data.get('price')
        news_count = len(data.get('headlines', []))

        if current_price is None or current_price <= 0:
            continue

        # Get yesterday's price from log
        if ticker in anomaly_log:
            prior_price = anomaly_log[ticker].get('last_price')
            prior_date = anomaly_log[ticker].get('last_date')

            if prior_price and prior_price > 0:
                # Calculate change percentage
                change_pct = abs((current_price - prior_price) / prior_price) * 100

                # Flag if >20% change with <2 news articles
                if change_pct > 20 and news_count < 2:
                    anomalies.append({
                        'ticker': ticker,
                        'from_price': prior_price,
                        'to_price': current_price,
                        'jump_pct': round(change_pct, 1),
                        'news_count': news_count,
                        'prior_date': prior_date
                    })
                    logger.warning(f"PRICE ANOMALY: {ticker} jumped {change_pct:.1f}% (${prior_price:.2f} → ${current_price:.2f}) with only {news_count} news")

                    # Add to anomaly log
                    if 'anomalies_logged' not in anomaly_log[ticker]:
                        anomaly_log[ticker]['anomalies_logged'] = []
                    anomaly_log[ticker]['anomalies_logged'].append({
                        'date': today,
                        'jump_pct': round(change_pct, 1),
                        'from': prior_price,
                        'to': current_price,
                        'news_count': news_count,
                        'flagged': True
                    })

        # Update today's price in log
        if ticker not in anomaly_log:
            anomaly_log[ticker] = {}

        anomaly_log[ticker].update({
            'last_price': current_price,
            'last_date': today,
            'prior_price': anomaly_log[ticker].get('last_price', current_price),
            'prior_date': anomaly_log[ticker].get('last_date', today)
        })

    return anomalies


def format_anomaly_warnings(anomalies: List[Dict]) -> str:
    """Generate HTML warning box for price anomalies"""
    if not anomalies:
        return ""

    html = """
        <div style="background: #fef2f2; border: 2px solid #ef4444; border-radius: 10px; padding: 20px; margin-bottom: 20px;">
            <h3 style="margin: 0 0 12px 0; color: #991b1b; font-size: 16px;">🚨 Price Anomaly Alert</h3>
            <p style="margin: 0 0 12px 0; color: #7f1d1d; font-size: 14px;">The following positions had unusual price moves (>20%) with minimal news coverage. Verify data accuracy.</p>
            <table style="width: 100%; font-size: 13px; border-collapse: collapse;">
                <thead>
                    <tr style="border-bottom: 2px solid #fecaca;">
                        <th style="padding: 8px; text-align: left; font-weight: 600;">Ticker</th>
                        <th style="padding: 8px; text-align: right; font-weight: 600;">From</th>
                        <th style="padding: 8px; text-align: right; font-weight: 600;">To</th>
                        <th style="padding: 8px; text-align: right; font-weight: 600;">Jump %</th>
                        <th style="padding: 8px; text-align: center; font-weight: 600;">News</th>
                    </tr>
                </thead>
                <tbody>
"""

    for anomaly in anomalies:
        ticker = anomaly['ticker']
        from_price = f"${anomaly['from_price']:.2f}"
        to_price = f"${anomaly['to_price']:.2f}"
        jump_pct = f"{anomaly['jump_pct']:.1f}%"
        news_count = anomaly['news_count']

        html += f"""
                    <tr style="border-bottom: 1px solid #fecaca;">
                        <td style="padding: 6px 8px; font-weight: 600;">{ticker}</td>
                        <td style="padding: 6px 8px; text-align: right;">{from_price}</td>
                        <td style="padding: 6px 8px; text-align: right;">{to_price}</td>
                        <td style="padding: 6px 8px; text-align: right; font-weight: 700; color: #dc2626;">{jump_pct}</td>
                        <td style="padding: 6px 8px; text-align: center;">{news_count}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
        </div>
"""

    return html


def get_trending_tickers(finnhub_client, current_holdings: List[str]) -> List[Dict]:
    """Module 3: Get diverse trending tickers using multiple Finnhub sources"""
    trending = set()

    # Load cache of recently recommended stocks
    recent_recommendations = load_recommendation_cache()
    recently_recommended_tickers = set(recent_recommendations.keys())

    logger.info(f"Recently recommended (excluding): {recently_recommended_tickers}")

    # Fallback: Popular tickers to ensure we always have some candidates
    fallback_tickers = [
        'NVDA', 'TSLA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'AMD', 'PLTR', 'COIN',
        'SHOP', 'SQ', 'SNOW', 'NET', 'CRWD', 'ZS', 'DDOG', 'MDB', 'U', 'RBLX',
        'LMT', 'RTX', 'BA', 'GD', 'NOC', 'FCX', 'NEM', 'GOLD', 'WPM', 'AEM'
    ]

    # Source 1: Market Movers - Top Gainers
    try:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        market_movers = finnhub_client.stock_symbols('US')

        # Get price data for random sample of US stocks to find movers
        import random
        sample_tickers = random.sample([s['symbol'] for s in market_movers if s.get('type') == 'Common Stock'], min(50, len(market_movers)))

        movers = []
        for ticker in sample_tickers:
            try:
                quote = finnhub_client.quote(ticker)
                change_pct = quote.get('dp', 0)
                if abs(change_pct) > 5:  # Moved more than 5%
                    movers.append(ticker)
                    if len(movers) >= 10:
                        break
                time.sleep(0.1)
            except:
                continue

        trending.update(movers)
        logger.info(f"Found {len(movers)} market movers")
    except Exception as e:
        logger.warning(f"Error fetching market movers: {e}")

    # Source 2: Finnhub Market News - Extract mentioned tickers
    try:
        news = finnhub_client.general_news('general', min_id=0)
        ticker_mentions = {}

        for article in news[:50]:
            # Look for ticker patterns in headlines and summaries
            text = f"{article.get('headline', '')} {article.get('summary', '')}".upper()
            # Extract potential tickers (2-5 letter uppercase words with $ prefix or standalone)
            import re
            potential_tickers = re.findall(r'\$([A-Z]{2,5})\b|\b([A-Z]{2,5})\b', text)
            for match in potential_tickers:
                ticker = match[0] or match[1]
                if ticker and len(ticker) >= 2:
                    ticker_mentions[ticker] = ticker_mentions.get(ticker, 0) + 1

        # Get top 15 most mentioned
        top_news_tickers = sorted(ticker_mentions.items(), key=lambda x: x[1], reverse=True)[:15]
        trending.update([t[0] for t in top_news_tickers])
        logger.info(f"Found {len(top_news_tickers)} tickers from news")
    except Exception as e:
        logger.warning(f"Error extracting tickers from news: {e}")

    # Source 3: Ask Claude for trending stocks based on today's market context
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        today_str = datetime.now().strftime('%B %d, %Y')

        prompt = f"""Today is {today_str}. Search for and identify 10 stocks that are trending or have interesting catalysts TODAY. Focus on:
- Stocks with significant news or events today
- High-growth tech, defense, AI, commodities, or small-cap momentum plays
- Canadian (TSX) or US stocks
- Exclude: {', '.join(current_holdings)}
- Exclude recently recommended: {', '.join(recently_recommended_tickers)}

Return ONLY a comma-separated list of ticker symbols. No explanations."""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "web_search_20250305", "name": "web_search"}]
        )

        response_text = ""
        for block in message.content:
            if hasattr(block, 'text'):
                response_text += block.text

        # Parse tickers from response
        import re
        claude_tickers = re.findall(r'\b[A-Z]{2,5}\b', response_text)
        trending.update(claude_tickers[:10])
        logger.info(f"Claude suggested {len(claude_tickers)} trending tickers")
    except Exception as e:
        logger.warning(f"Error getting Claude trending suggestions: {e}")

    # Remove tickers already in holdings (but KEEP recently recommended - we'll check for major catalysts)
    trending = trending - set(current_holdings)

    logger.info(f"Trending candidates (may include cached): {len(trending)} tickers")

    # If we don't have enough trending tickers, add from fallback list
    if len(trending) < 15:
        logger.warning(f"Only found {len(trending)} trending tickers, adding from fallback list")
        fallback_available = [t for t in fallback_tickers if t not in current_holdings]
        import random
        random.shuffle(fallback_available)
        trending.update(fallback_available[:20])
        logger.info(f"After fallback: {len(trending)} tickers to check")

    # Fetch data for trending tickers
    trending_data = []
    for ticker in list(trending)[:30]:  # Check more tickers to get 5 good ones
        data = fetch_ticker_data(ticker, finnhub_client)
        if data and data.get('price'):  # Only include if we got valid price data
            trending_data.append(data)
            if len(trending_data) >= 20:  # Get 20 candidates for Claude to pick from
                break

    logger.info(f"Collected {len(trending_data)} trending candidates for opportunities")

    # Final fallback: if still no data, use popular stocks
    if len(trending_data) == 0:
        logger.error("No trending data collected! Using emergency fallback")
        fallback_available = [t for t in fallback_tickers[:10] if t not in current_holdings]
        for ticker in fallback_available:
            data = fetch_ticker_data(ticker, finnhub_client)
            if data:
                trending_data.append(data)
                if len(trending_data) >= 10:
                    break

    return trending_data


def filter_conflicting_opportunities(trending_data: List[Dict], parsed_holdings: List[Dict]) -> List[Dict]:
    """HARD EXCLUSION: Remove any ticker that has SELL or WATCH LOW in holdings today

    Prevents contradictory recommendations (e.g., QUBT as both SELL and Opportunity same day)
    """
    # Build set of tickers to exclude
    exclude_tickers = set()
    for h in parsed_holdings:
        rec = h['recommendation'].upper()
        confidence = h.get('confidence', '').upper()

        # Exclude if SELL or if WATCH with LOW confidence
        if 'SELL' in rec:
            exclude_tickers.add(h['ticker'])
        elif 'WATCH' in rec and 'LOW' in confidence:
            exclude_tickers.add(h['ticker'])

    # Filter trending_data
    filtered = []
    for d in trending_data:
        ticker = d.get('ticker', '')
        if ticker not in exclude_tickers:
            filtered.append(d)

    if exclude_tickers:
        logger.info(f"OPPORTUNITIES HARD EXCLUSION: Removed {len(exclude_tickers)} tickers with SELL/WATCH LOW: {exclude_tickers}")

    return filtered


def filter_opportunities_by_audit_rules(trending_data: List[Dict], current_holdings: List[str], holdings_themes: Dict[str, List[str]]) -> List[Dict]:
    """TAG opportunities with filter warnings instead of excluding

    Tagging rules:
    1. Stock up >8% today - tag with SURGE warning
    2. Stock up >15% today - tag with EXTREME SURGE warning
    3. Duplicates existing portfolio theme - tag with OVERLAP warning
    4. Recently recommended - tag with RECENT warning
    """
    tagged = []

    for data in trending_data:
        ticker = data.get('ticker', '')
        change_pct = data.get('change_percent', 0)
        headlines = data.get('headlines', [])

        # Initialize warning tags list
        data['filter_warnings'] = []

        # Rule 1: SURGE FILTER
        if change_pct and change_pct > 15:
            data['filter_warnings'].append(f"⚠️ EXTREME SURGE +{change_pct:.1f}% - High mean-reversion risk")
            logger.info(f"OPPORTUNITIES FILTER: Tagging {ticker} - EXTREME SURGE >15% ({change_pct:.1f}%)")
        elif change_pct and change_pct > 8:
            data['filter_warnings'].append(f"⚠️ SURGE +{change_pct:.1f}% - Wait for pullback")
            logger.info(f"OPPORTUNITIES FILTER: Tagging {ticker} - SURGE >8% ({change_pct:.1f}%)")

        # Rule 2: Theme overlap check
        for theme_name, theme_tickers in holdings_themes.items():
            if ticker in theme_tickers or any(ticker.startswith(t) for t in theme_tickers):
                data['filter_warnings'].append(f"⚠️ OVERLAP - Already hold {theme_name}")
                logger.info(f"OPPORTUNITIES FILTER: Tagging {ticker} - Theme overlap with {theme_name}")
                break

        tagged.append(data)

    return tagged[:20]  # Limit to 20 candidates (increased from 15 to show more)


def find_opportunities(trending_data: List[Dict], current_holdings: List[str]) -> Tuple[str, List[str], List[Dict]]:
    """Find new opportunities with filter warnings
    Returns: (response_text, list_of_recommended_tickers, tagged_trending_data)"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Load recent recommendations to tell Claude
        recent_cache = load_recommendation_cache()
        recent_list = list(recent_cache.keys())

        # Define portfolio themes for overlap detection
        holdings_themes = {
            'semiconductors': ['AMAT', 'LRCX', 'MU', 'AXTI', 'TSEM'],
            'defense_space': ['MDA', 'NOC', 'ASTS'],
            'metals_mining': ['FCX', 'HBM', 'LUN', 'CCJ'],
            'tech_software': ['ORCL', 'TRI'],
            'healthcare_biotech': ['LNTH', 'AXSM', 'MBX']
        }

        # APPLY TAGGING (not exclusion) - tag opportunities with warnings
        tagged_trending = filter_opportunities_by_audit_rules(trending_data, current_holdings, holdings_themes)

        if len(tagged_trending) == 0:
            logger.warning("No trending data available for opportunities")
            return "No trending data available today - market analysis unavailable", [], []

        # Format tagged trending data WITH all filter warnings
        trending_text = ""
        major_catalyst_bypasses = []

        for data in tagged_trending:
            ticker = data.get('ticker', '')
            price = data.get('price')
            change = data.get('change_percent', 0)
            headlines = data.get('headlines', [])
            filter_warnings = data.get('filter_warnings', [])

            price_str = f"${price:.2f}" if price is not None else "N/A"
            change_str = f"({change:+.2f}%)" if change is not None else "(N/A)"

            # Check for MAJOR CATALYST BYPASS:
            # - Previously recommended (in cache) AND
            # - Big move (>10%) AND
            # - Has fundamental news
            is_cached = ticker in recent_list
            has_major_move = abs(change) > 10 if change else False
            has_news = len(headlines) > 0

            if is_cached and has_major_move and has_news:
                major_catalyst_bypasses.append(ticker)
                trending_text += f"\n{ticker}: {price_str} {change_str} ⚠️ CACHED BUT MAJOR CATALYST - BYPASS ALLOWED\n"
            else:
                trending_text += f"\n{ticker}: {price_str} {change_str}\n"

            # Add ALL filter warnings
            if filter_warnings:
                for warning in filter_warnings:
                    trending_text += f"  {warning}\n"

            if headlines:
                trending_text += f"  News: {'; '.join(headlines[:2])}\n"

        # Build recent recommendations string with bypass explanation
        if recent_list:
            recent_str = f"\nRECENTLY RECOMMENDED (normally excluded, but BYPASS ALLOWED if marked above):\n{', '.join(recent_list)}\n"
            if major_catalyst_bypasses:
                recent_str += f"\nMAJOR CATALYST BYPASSES (re-recommend these if catalyst is strong):\n{', '.join(major_catalyst_bypasses)}\n"
        else:
            recent_str = ""

        # Get current holdings by theme for Claude context
        theme_summary = "\n".join([f"{theme}: {', '.join(tickers)}" for theme, tickers in holdings_themes.items()])

        today = datetime.now().strftime('%B %d, %Y')

        prompt = f"""You are finding new investment opportunities for a Canadian TFSA portfolio. EVALUATE CANDIDATES WITH WARNINGS.

Today is {today}.

CURRENT HOLDINGS BY THEME:
{theme_summary}
{recent_str}

TRENDING CANDIDATES (may have filter warnings - evaluate carefully):
{trending_text}

MANDATORY RULES:
1. Maximum 5 opportunities. Quality over quantity.

2. FILTER WARNINGS - Candidates may have these tags:
   - "⚠️ SURGE" (up 8-15%) or "⚠️ EXTREME SURGE" (up >15%) - High mean-reversion risk
   - "⚠️ OVERLAP" - Already hold similar theme
   - "⚠️ RECENT" - Recently recommended

   You MAY recommend flagged candidates IF:
   - There's a NEW, MAJOR fundamental catalyst (earnings beat, M&A, regulatory approval, major contract)
   - The catalyst justifies the move or creates new entry opportunity
   - For SURGE warnings: Either wait for pullback OR catalyst is strong enough to justify chase
   - For OVERLAP warnings: Must explain why this is better than adding to existing position

3. Each opportunity MUST have a NAMED CATALYST with a DATE:
   - "Earnings released today" with specific numbers
   - "Analyst upgrade by [firm] on [date]"
   - "Contract announced [date]"
   - "Regulatory approval on [date]"
   - "M&A announcement on [date]"

   BANNED: "trending," "momentum," "sector rotation," "up X% today" - these are NOT catalysts

4. EDGE STATEMENT REQUIRED:
   Compare to existing holdings. If it duplicates a theme (e.g., another semiconductor stock when we have AMAT, LRCX, MU),
   you MUST explain why this is better than adding to existing positions.

5. ENTRY GUIDANCE FOR WARNED CANDIDATES:
   - SURGE (8-15%): ENTRY must be "Wait for pullback to $[price]" unless catalyst is exceptional
   - EXTREME SURGE (>15%): ENTRY should almost always be "PASS - too extended" or "Wait for 10-15% pullback"
   - No warnings: "Current price $X-Y acceptable" if entry is reasonable

6. BANNED PHRASES:
   "firing on all cylinders," "gift," "the market is underreacting," "transformational," "exploding," "surging"

7. If fewer than 5 candidates meet criteria, return as many as qualify (1-5).
   You should find opportunities even with warnings IF catalysts justify them.

OUTPUT FORMAT (1-5 opportunities, or "No qualifying opportunities"):
TICKER|COMPANY|CATALYST|EDGE|ENTRY|TARGET|STOP|RISK|EXCHANGE

CATALYST: Named event with date (30-50 words)
EDGE: Why this vs. adding to existing position (20-30 words)
ENTRY: Specific price range or condition (be precise)
  - Good: "Current price $45-47 acceptable" or "Wait for pullback to $38-40"
  - Bad: "Review before buying" or "Current levels"
TARGET: Analyst PT or thesis-based price objective
  - Good: "Analyst PT $65 (Jefferies, Apr 28)" or "Fair value $58 based on 2.5x P/S"
  - Bad: "Upside potential" or "Monitor"
STOP: Price level where thesis is broken (below which you'd exit)
  - Good: "Stop below $32 (breaks 200-day MA and support)"
  - Bad: "Manage risk"
RISK: One specific risk with trigger (20-30 words)
EXCHANGE: TSX or US

Start immediately with first ticker or "No qualifying opportunities today"."""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}]
        )

        response = message.content[0].text
        logger.info("Successfully found opportunities with audit filters")

        # Extract recommended tickers from response
        import re
        lines = response.strip().split('\n')
        recommended_tickers = []

        # Check if response says no opportunities
        if "no qualifying opportunities" in response.lower():
            logger.info("Claude found no qualifying opportunities after filtering")
            return response, [], tagged_trending

        for line in lines:
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 1:
                    ticker = parts[0].strip().upper()
                    if ticker and ticker != "TICKER":
                        recommended_tickers.append(ticker)

        return response, recommended_tickers, tagged_trending

    except Exception as e:
        logger.error(f"Error finding opportunities: {e}")
        return "OPPORTUNITIES_UNAVAILABLE", [], []


def parse_holdings_analysis(analysis: str, holdings_data: List[Dict], rec_history: Dict, position_status: Dict) -> List[Dict]:
    """Parse Claude's analysis with PRIOR REC TRACKING and CHANGE DETECTION"""
    parsed = []
    today = datetime.now().strftime('%Y-%m-%d')

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
                'prior_recommendation': None,
                'prior_date': None,
                'status': position_status.get(data['ticker'], 'OPEN'),
                'identity_verified': data.get('identity_verified', False),
                'identity_data': data.get('identity_data', {})
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
                    recommendation = parts[1].strip()
                    confidence = parts[2].strip()
                    reason = parts[3].strip()
                    risk = parts[4].strip() if len(parts) > 4 else 'N/A'

                    # Get prior recommendation
                    prior_rec, prior_date = get_prior_recommendation(original_ticker, rec_history)

                    # Update recommendation history
                    if original_ticker not in rec_history:
                        rec_history[original_ticker] = {}
                    rec_history[original_ticker][today] = recommendation

                    # Update position status
                    status = update_position_status(original_ticker, recommendation, position_status)

                    # Check if recommendation changed
                    recommendation_changed = (prior_rec is not None and prior_rec != recommendation)

                    parsed.append({
                        'ticker': original_ticker,
                        'price': data_map[ticker_upper]['price'],
                        'change_percent': data_map[ticker_upper]['change_percent'],
                        'recommendation': recommendation,
                        'confidence': confidence,
                        'reason': reason,
                        'risk': risk,
                        'prior_recommendation': prior_rec,
                        'prior_date': prior_date,
                        'status': status,
                        'changed': recommendation_changed,
                        'identity_verified': data_map[ticker_upper].get('identity_verified', False),
                        'identity_data': data_map[ticker_upper].get('identity_data', {})
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

        # Log recommendation changes
        changes = [p for p in parsed if p.get('changed')]
        if changes:
            logger.info(f"RECOMMENDATION CHANGES detected for {len(changes)} positions:")
            for p in changes:
                logger.info(f"  {p['ticker']}: {p['prior_recommendation']} → {p['recommendation']}")

    return parsed


def parse_opportunities(opportunities: str, tagged_trending: List[Dict] = None) -> List[Dict]:
    """Parse Claude's opportunities with ENHANCED FORMAT and match filter warnings
    Format: TICKER|COMPANY|CATALYST|EDGE|ENTRY|TARGET|STOP|RISK|EXCHANGE"""
    parsed = []

    if opportunities == "OPPORTUNITIES_UNAVAILABLE":
        logger.warning("Opportunities marked as unavailable")
        return []

    # Check if Claude said no qualifying opportunities
    if "no qualifying opportunities" in opportunities.lower():
        logger.info("No qualifying opportunities found (filter enforced)")
        return []

    # Build ticker -> warnings lookup from tagged_trending
    warnings_lookup = {}
    if tagged_trending:
        for data in tagged_trending:
            ticker = data.get('ticker', '').upper()
            warnings = data.get('filter_warnings', [])
            if warnings:
                warnings_lookup[ticker] = warnings

    lines = opportunities.strip().split('\n')

    for line in lines:
        if '|' in line:
            parts = line.split('|')

            # Skip header lines
            if len(parts) > 0 and parts[0].strip().upper() == "TICKER":
                continue

            if len(parts) >= 9:  # Enhanced format with TARGET and STOP
                ticker = parts[0].strip()
                company = parts[1].strip()

                if not ticker or ticker.upper() == "TICKER":
                    continue

                # Check if ENTRY says PASS
                entry = parts[4].strip()
                is_pass = "PASS" in entry.upper()

                # Match filter warnings from tagged_trending
                filter_warnings = warnings_lookup.get(ticker.upper(), [])

                parsed.append({
                    'ticker': ticker,
                    'company': company,
                    'catalyst': parts[2].strip(),
                    'edge': parts[3].strip(),
                    'entry': entry,
                    'target': parts[5].strip(),
                    'stop': parts[6].strip(),
                    'risk': parts[7].strip(),
                    'exchange': parts[8].strip(),
                    'is_pass': is_pass,
                    'filter_warnings': filter_warnings
                })
            elif len(parts) >= 7:  # Backward compatibility: 7-field format
                ticker = parts[0].strip()
                company = parts[1].strip()

                if not ticker or ticker.upper() == "TICKER":
                    continue

                entry = parts[4].strip()
                is_pass = "PASS" in entry.upper()

                # Match filter warnings
                filter_warnings = warnings_lookup.get(ticker.upper(), [])

                parsed.append({
                    'ticker': ticker,
                    'company': company,
                    'catalyst': parts[2].strip(),
                    'edge': parts[3].strip(),
                    'entry': entry,
                    'target': 'Monitor',  # Default for old format
                    'stop': 'Manage risk',  # Default for old format
                    'risk': parts[5].strip(),
                    'exchange': parts[6].strip(),
                    'is_pass': is_pass,
                    'filter_warnings': filter_warnings
                })
            elif len(parts) >= 6:  # Fallback to oldest format if needed
                ticker = parts[0].strip()
                company = parts[1].strip()

                if not ticker or ticker.upper() == "TICKER":
                    continue

                # Match filter warnings
                filter_warnings = warnings_lookup.get(ticker.upper(), [])

                parsed.append({
                    'ticker': ticker,
                    'company': company,
                    'catalyst': parts[2].strip(),
                    'edge': 'See catalyst',
                    'entry': 'Review before buying',
                    'target': 'Monitor',
                    'stop': 'Manage risk',
                    'risk': parts[4].strip() if len(parts) > 4 else 'N/A',
                    'exchange': parts[5].strip() if len(parts) > 5 else 'Unknown',
                    'is_pass': False,
                    'filter_warnings': filter_warnings
                })

    # Validation
    if len(parsed) == 0:
        logger.info("Opportunities parser: No opportunities parsed (may be intentional if all filtered)")
    else:
        logger.info(f"✓ Opportunities parser: Successfully parsed {len(parsed)} opportunities")
        pass_count = sum(1 for p in parsed if p.get('is_pass'))
        if pass_count > 0:
            logger.info(f"  {pass_count} marked as PASS (wait for better entry)")

    return parsed[:5]  # Limit to 5 (user preference with strict filters)


def create_html_email(macro_context: str, holdings: List[Dict], opportunities: List[Dict], date_str: str, scorecard: Optional[Dict] = None, recommendation_changes: Optional[List[Dict]] = None, price_anomalies: Optional[List[Dict]] = None) -> Tuple[str, str]:
    """Create HTML and plain text email content - AUDIT-COMPLIANT VERSION"""

    # Count recommendations by type (including new categories)
    rec_counts = {'BUY MORE': 0, 'HOLD': 0, 'SELL': 0, 'WATCH': 0, 'PENDING EXIT': 0, 'NO DATA': 0}
    for h in holdings:
        rec = h['recommendation'].upper()
        status = h.get('status', 'OPEN')
        if status == 'PENDING EXIT':
            rec_counts['PENDING EXIT'] += 1
        elif 'NO DATA' in rec:
            rec_counts['NO DATA'] += 1
        elif 'BUY' in rec:
            rec_counts['BUY MORE'] += 1
        elif 'SELL' in rec:
            rec_counts['SELL'] += 1
        elif 'WATCH' in rec:
            rec_counts['WATCH'] += 1
        else:
            rec_counts['HOLD'] += 1

    # Build summary line (exclude zero counts)
    summary_parts = []
    if rec_counts['BUY MORE'] > 0:
        summary_parts.append(f"{rec_counts['BUY MORE']} BUY")
    if rec_counts['HOLD'] > 0:
        summary_parts.append(f"{rec_counts['HOLD']} HOLD")
    if rec_counts['SELL'] > 0:
        summary_parts.append(f"{rec_counts['SELL']} SELL")
    if rec_counts['WATCH'] > 0:
        summary_parts.append(f"{rec_counts['WATCH']} WATCH")
    if rec_counts['PENDING EXIT'] > 0:
        summary_parts.append(f"{rec_counts['PENDING EXIT']} PENDING EXIT")
    if rec_counts['NO DATA'] > 0:
        summary_parts.append(f"{rec_counts['NO DATA']} NO DATA")

    rec_summary = " · ".join(summary_parts) if summary_parts else "No positions"

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
"""

    # Insert price anomaly warning if anomalies detected
    if price_anomalies:
        anomaly_warning_html = format_anomaly_warnings(price_anomalies)
        html += f"""
        <div class="section">
            {anomaly_warning_html}
        </div>
"""

    html += """
        <div class="section">
            <h2>🌍 Macro Context</h2>
            <div class="macro-context">
"""

    # Process macro context: strip intro, convert markdown, add line breaks
    import re
    processed_macro = macro_context

    # Strip intro text (everything before first ### or numbered section)
    lines = processed_macro.split('\n')
    # Find first line that starts with ### or a number
    start_idx = 0
    for i, line in enumerate(lines):
        if line.strip().startswith('###') or (len(line) > 0 and line[0].isdigit()):
            start_idx = i
            break
    processed_macro = '\n'.join(lines[start_idx:])

    # Remove horizontal rules (---)
    processed_macro = re.sub(r'-{3,}', '', processed_macro)

    # Convert ### headers to <strong>
    processed_macro = re.sub(r'###\s*(.+)', r'<strong>\1</strong>', processed_macro)

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

    # Insert change log if there are changes
    if recommendation_changes:
        change_log_html = generate_change_log_table(recommendation_changes)
        html += change_log_html

    for h in holdings:
        rec_class = ''
        status = h.get('status', 'OPEN')

        # Determine recommendation class
        if status == 'PENDING EXIT':
            rec_class = 'sell'
        elif 'NO DATA' in h['recommendation'].upper():
            rec_class = 'watch'
        elif 'BUY' in h['recommendation'].upper():
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

        # Build prior recommendation line
        prior_line = ""
        if h.get('prior_recommendation') and h.get('prior_date'):
            prior_rec = h['prior_recommendation']
            prior_date = h['prior_date']
            if h.get('changed'):
                prior_line = f'<div style="background: #fff3cd; padding: 8px; border-radius: 6px; margin: 8px 0; font-size: 13px;"><strong>⚠️ CHANGE:</strong> {prior_rec} on {prior_date} → {h["recommendation"]}</div>'
            else:
                prior_line = f'<div style="color: #666; font-size: 12px; margin-top: 4px;">Prior: {prior_rec} ({prior_date})</div>'

        # Add status badge if PENDING EXIT
        status_badge = ''
        if status == 'PENDING EXIT':
            status_badge = '<span style="background: #fee2e2; color: #991b1b; padding: 4px 8px; border-radius: 4px; font-size: 11px; margin-left: 8px;">PENDING EXIT</span>'

        # Build identity line
        identity_line = ''
        if h.get('identity_verified'):
            identity = h.get('identity_data', {})
            company_name = identity.get('confirmed_name', '')
            exchange = identity.get('exchange', '')
            business_desc = identity.get('business_description', '')
            # Truncate business description if too long
            if len(business_desc) > 80:
                business_desc = business_desc[:77] + "..."
            identity_line = f'<div style="color: #059669; font-size: 11px; margin-bottom: 6px; border-left: 2px solid #10b981; padding-left: 8px;">✓ {company_name} ({exchange}) — {business_desc}</div>'
        elif h.get('identity_verified') == False:
            # Explicitly not verified
            identity_line = f'<div style="color: #dc2626; font-size: 11px; margin-bottom: 6px; border-left: 2px solid #ef4444; padding-left: 8px;">⚠️ Identity could not be verified - check ticker symbol</div>'

        html += f"""
            <div class="stock-card">
                {identity_line}
                <div class="stock-header">
                    <span class="stock-ticker">{h['ticker']}</span>
                    <span class="stock-price">{price_str}</span>
                    <span class="stock-change {change_class}">{change_str}</span>
                </div>
                <div class="stock-rec-line">
                    <span class="{rec_class}">{h['recommendation']}</span>
                    <span style="color: #666; font-size: 13px; margin-left: 8px;">{h['confidence']} confidence</span>
                    {status_badge}
                </div>
                {prior_line}
                <div class="stock-detail"><strong>Reason:</strong> {h['reason']}</div>
                <div class="stock-detail"><strong>Risk:</strong> {h['risk']}</div>
            </div>
"""

    html += """
        </div>
"""

    if opportunities and len(opportunities) > 0:
        html += """
        <div class="section">
            <h2>🔥 Opportunities (Max 5, filtered for quality)</h2>
"""
        # Insert scorecard if available
        if scorecard:
            scorecard_html = generate_scorecard_summary(scorecard)
            html += scorecard_html

        for opp in opportunities:
            # Convert markdown **text** to HTML <strong>text</strong>
            import re
            catalyst = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp.get('catalyst', opp.get('why_today', '')))
            company = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp.get('company', ''))
            edge = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp.get('edge', 'See catalyst'))
            entry = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp.get('entry', 'Review before buying'))
            target = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp.get('target', 'Monitor'))
            stop = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp.get('stop', 'Manage risk'))
            risk = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp.get('risk', 'N/A'))
            exchange = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', opp.get('exchange', 'Unknown'))

            # Build badges for PASS and filter warnings
            badges = ''
            is_pass = opp.get('is_pass', False)
            if is_pass:
                badges += '<span style="background: #fee2e2; color: #991b1b; padding: 4px 12px; border-radius: 6px; font-size: 12px; font-weight: 700; margin-left: 8px;">PASS - WAIT</span>'

            # Add filter warning badges
            filter_warnings = opp.get('filter_warnings', [])
            if filter_warnings:
                for warning in filter_warnings:
                    # Different colors for different warning types
                    if 'EXTREME SURGE' in warning:
                        badge_color = 'background: #fee2e2; color: #991b1b;'  # Red
                    elif 'SURGE' in warning:
                        badge_color = 'background: #fef3c7; color: #78350f;'  # Yellow
                    elif 'OVERLAP' in warning:
                        badge_color = 'background: #e0e7ff; color: #3730a3;'  # Blue
                    else:
                        badge_color = 'background: #f1f5f9; color: #475569;'  # Gray
                    badges += f'<span style="{badge_color} padding: 4px 12px; border-radius: 6px; font-size: 11px; font-weight: 700; margin-left: 8px;">{warning}</span>'

            html += f"""
            <div class="opportunity-card">
                <div class="ticker">{opp['ticker']}{badges}</div>
                <h3>{company}</h3>
                <p><strong>Catalyst:</strong> {catalyst}</p>
                <p><strong>Edge vs. Holdings:</strong> {edge}</p>
                <p><strong>Entry:</strong> {entry}</p>
                <p><strong>Target:</strong> {target}</p>
                <p><strong>Stop:</strong> {stop}</p>
                <p><strong>Risk:</strong> {risk}</p>
                <p><strong>Exchange:</strong> {exchange}</p>
            </div>
"""
        html += """
        </div>
"""
    else:
        # Show message if no opportunities found
        html += """
        <div class="section">
            <h2>🔥 Opportunities</h2>
            <div style="background: #f1f5f9; padding: 20px; border-radius: 10px; text-align: center; color: #64748b;">
                <p><strong>No qualifying opportunities today</strong></p>
                <p style="font-size: 14px;">All candidates excluded by quality filters (price chasing, theme overlap, or no catalysts)</p>
            </div>
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

    # Plain text version (AUDIT-COMPLIANT)
    plain = f"""PORTFOLIO BRIEF — {date_str} | {len(holdings)} positions
{rec_summary}

=== MACRO CONTEXT ===
{macro_context}

=== YOUR HOLDINGS ===
"""
    for h in holdings:
        price_str = f"${h.get('price'):.2f}" if h.get('price') is not None else "N/A"
        change_val = h.get('change_percent')
        change_str = f"({change_val:+.2f}%)" if change_val is not None else "(N/A)"

        # Status and prior recommendation
        status = h.get('status', 'OPEN')
        status_str = f" [{status}]" if status == 'PENDING EXIT' else ""
        prior = f" (Prior: {h['prior_recommendation']} on {h['prior_date']})" if h.get('prior_recommendation') else ""
        change_flag = " ⚠️ CHANGED" if h.get('changed') else ""

        plain += f"\n{h['ticker']}: {price_str} {change_str}{status_str}{change_flag}\n"
        plain += f"  Recommendation: {h.get('recommendation', 'N/A')} ({h.get('confidence', 'N/A')} confidence){prior}\n"
        plain += f"  Reason: {h.get('reason', 'N/A')}\n"
        plain += f"  Risk: {h.get('risk', 'N/A')}\n"

    if opportunities and len(opportunities) > 0:
        plain += "\n=== OPPORTUNITIES (max 5, quality filtered) ===\n"
        for opp in opportunities:
            pass_flag = " [PASS - WAIT]" if opp.get('is_pass') else ""
            plain += f"\n{opp['ticker']} - {opp.get('company', 'N/A')} ({opp.get('exchange', 'Unknown')}){pass_flag}\n"
            plain += f"  Catalyst: {opp.get('catalyst', opp.get('why_today', 'N/A'))}\n"
            plain += f"  Edge: {opp.get('edge', 'See catalyst')}\n"
            plain += f"  Entry: {opp.get('entry', 'Review before buying')}\n"
            plain += f"  Risk: {opp.get('risk', 'N/A')}\n"
    else:
        plain += "\n=== OPPORTUNITIES ===\nNo qualifying opportunities today (all filtered for quality)\n"

    plain += f"\n---\nAI analysis for informational purposes only.\nAUDIT-COMPLIANT VERSION - tracks changes and filters price chasing\nGenerated: {timestamp}\nTo update holdings: edit holdings.txt on GitHub\n"

    return html, plain


def send_email(subject: str, html_content: str, plain_content: str):
    """Send email via Brevo (Sendinblue) API"""

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
        logger.info("EMAIL SEND ATTEMPT (Brevo API)")
        logger.info("="*60)
        logger.info(f"From: {EMAIL_FROM}")
        logger.info(f"To: {EMAIL_TO}")
        logger.info(f"Subject: {subject}")
        logger.info(f"Brevo API Key: {BREVO_API_KEY[:20]}... (length: {len(BREVO_API_KEY)})")
        logger.info(f"API Key valid format: {'✓ Yes' if BREVO_API_KEY.startswith('xkeysib-') else '✗ No - should start with xkeysib-'}")

        # Configure Brevo API
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = BREVO_API_KEY

        # Create API instance
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

        # Create email message
        sender = {"name": "Daily Portfolio Monitor", "email": EMAIL_FROM}
        to = [{"email": EMAIL_TO}]

        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=to,
            sender=sender,
            subject=subject,
            html_content=html_content,
            text_content=plain_content
        )

        logger.info("Initializing Brevo client...")
        logger.info("Sending email via Brevo...")

        # Send the email
        api_response = api_instance.send_transac_email(send_smtp_email)

        logger.info(f"✓ SUCCESS: Email sent via Brevo!")
        logger.info(f"  → Message ID: {api_response.message_id}")
        logger.info(f"  → Email saved locally: {filename}")
        logger.info("="*60)
        return True

    except ApiException as e:
        logger.error("="*60)
        logger.error("✗ BREVO API ERROR")
        logger.error("="*60)
        logger.error(f"Error type: ApiException")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Status code: {e.status}")
        logger.error(f"Reason: {e.reason}")
        logger.error(f"Email saved locally: {filename}")
        logger.error("="*60)

        import traceback
        logger.error("Full traceback:")
        logger.error(traceback.format_exc())

        return False

    except Exception as e:
        logger.error("="*60)
        logger.error("✗ BREVO ERROR")
        logger.error("="*60)
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(f"Email saved locally: {filename}")
        logger.error("="*60)

        import traceback
        logger.error("Full traceback:")
        logger.error(traceback.format_exc())

        return False


def run_portfolio_analysis():
    """Main pipeline - AUDIT-COMPLIANT VERSION with full tracking"""
    import socket
    hostname = socket.gethostname()

    logger.info("="*60)
    logger.info("Starting AUDIT-COMPLIANT portfolio analysis pipeline")
    logger.info(f"Instance: {hostname}")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info("="*60)

    # Step 0: Git pull
    git_pull_updates()

    # Step 0.5: Load tracking systems
    logger.info("Loading recommendation history, position status, identity cache, scorecard, and anomaly log...")
    rec_history = load_recommendation_history()
    position_status = load_position_status()
    identity_cache = load_company_identity_cache()
    scorecard = load_opportunity_scorecard()
    anomaly_log = load_price_anomaly_log()
    logger.info(f"Loaded history for {len(rec_history)} tickers, status for {len(position_status)} positions, identity cache for {len(identity_cache)} tickers, scorecard with {sum(len(opps) for opps in scorecard.values())} opportunities, anomaly log for {len(anomaly_log)} tickers")

    # Step 1: Read holdings
    holdings = read_holdings()
    if not holdings:
        logger.error("No holdings found. Aborting.")
        return

    # Step 2: Get macro context (now includes holdings for categorization)
    date_str = datetime.now().strftime('%A, %B %d, %Y')
    macro_context = get_macro_context(date_str, holdings)

    # Initialize API clients
    try:
        finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
    except Exception as e:
        logger.error(f"Error initializing API clients: {e}")
        return

    # Step 3: Fetch data for all holdings (with identity verification)
    logger.info("Fetching data for holdings and verifying identities...")
    holdings_data = []
    for ticker in holdings:
        data = fetch_ticker_data(ticker, finnhub_client, identity_cache)
        if data:
            holdings_data.append(data)
            time.sleep(0.5)  # Rate limiting
        else:
            logger.warning(f"Could not fetch data for {ticker}")
            # Still add to holdings_data with None price so it gets "NO DATA" recommendation
            holdings_data.append({
                'ticker': ticker,
                'price': None,
                'change_percent': None,
                'headlines': [],
                'source': 'N/A',
                'identity_verified': False,
                'identity_data': {}
            })

    if not holdings_data:
        logger.error("No holdings data available. Aborting.")
        return

    # Step 3.5: Detect price anomalies (>20% overnight moves with no news)
    price_anomalies = detect_price_anomalies(holdings_data, anomaly_log)
    if price_anomalies:
        logger.warning(f"Detected {len(price_anomalies)} price anomalies")

    # Step 3.6: Update scorecard prices for accountability tracking
    scorecard = update_scorecard_prices(scorecard, finnhub_client)

    # Step 4: Analyze holdings with Claude (now includes rec_history and position_status)
    logger.info("Analyzing holdings with audit-compliant prompt...")
    analysis = analyze_holdings(holdings_data, macro_context, rec_history, position_status)

    # DEBUG: Log Claude's raw response for holdings
    logger.info("="*60)
    logger.info("DEBUG - Holdings Analysis from Claude")
    logger.info("="*60)
    logger.info(f"Response length: {len(analysis)} characters")
    logger.info(f"Response preview (first 1000 chars):\n{analysis[:1000]}")
    logger.info("="*60)

    parsed_holdings = parse_holdings_analysis(analysis, holdings_data, rec_history, position_status)

    # Detect recommendation changes for change log
    recommendation_changes = detect_recommendation_changes(parsed_holdings)
    if recommendation_changes:
        logger.info(f"Detected {len(recommendation_changes)} recommendation changes")

    # Save updated recommendation history, position status, identity cache, and anomaly log
    save_recommendation_history(rec_history)
    save_position_status(position_status)
    save_company_identity_cache(identity_cache)
    save_price_anomaly_log(anomaly_log)

    # Step 5: Find new opportunities (with hard filters)
    logger.info("Finding new opportunities with audit filters...")
    trending_data = get_trending_tickers(finnhub_client, holdings)

    # Apply hard exclusion rule: no ticker with SELL or WATCH LOW in holdings
    trending_data = filter_conflicting_opportunities(trending_data, parsed_holdings)

    opportunities_text, recommended_tickers, tagged_trending = find_opportunities(trending_data, holdings)

    # DEBUG: Log Claude's raw response for opportunities
    logger.info("="*60)
    logger.info("DEBUG - Opportunities from Claude")
    logger.info("="*60)
    logger.info(f"Response length: {len(opportunities_text)} characters")
    logger.info(f"Response preview (first 800 chars):\n{opportunities_text[:800]}")
    logger.info("="*60)

    parsed_opportunities = parse_opportunities(opportunities_text, tagged_trending)

    # Add new opportunities to scorecard for performance tracking
    for opp in parsed_opportunities:
        if not opp.get('is_pass'):  # Only track actual recommendations, not PASS
            ticker = opp['ticker']
            # Get price from trending_data
            ticker_data = next((d for d in trending_data if d.get('ticker') == ticker), None)
            if ticker_data and ticker_data.get('price'):
                price = ticker_data['price']
                catalyst = opp.get('catalyst', opp.get('why_today', 'N/A'))
                add_opportunity_to_scorecard(ticker, price, catalyst, scorecard)

    # Update recommendation cache with new recommendations (for Opportunities tracking)
    if recommended_tickers:
        cache = load_recommendation_cache()
        today = datetime.now().isoformat()
        for ticker in recommended_tickers:
            cache[ticker] = today
        save_recommendation_cache(cache)
        logger.info(f"Added {len(recommended_tickers)} tickers to Opportunities cache")

    # Validation: Check if parsing succeeded
    if len(parsed_holdings) == 0:
        logger.error("⚠️⚠️⚠️ CRITICAL WARNING: No holdings were parsed! Email will have empty holdings section!")

    # Count recommendation types
    rec_counts = {'BUY MORE': 0, 'HOLD': 0, 'SELL': 0, 'WATCH': 0, 'NO DATA': 0, 'PENDING EXIT': 0}
    for h in parsed_holdings:
        rec = h['recommendation'].upper()
        status = h.get('status', 'OPEN')
        if status == 'PENDING EXIT':
            rec_counts['PENDING EXIT'] += 1
        elif 'NO DATA' in rec:
            rec_counts['NO DATA'] += 1
        elif 'BUY' in rec:
            rec_counts['BUY MORE'] += 1
        elif 'SELL' in rec:
            rec_counts['SELL'] += 1
        elif 'WATCH' in rec:
            rec_counts['WATCH'] += 1
        else:
            rec_counts['HOLD'] += 1

    logger.info(f"Recommendation breakdown: {rec_counts}")

    if len(parsed_opportunities) == 0:
        logger.info("No opportunities found (may be intentional due to audit filters)")

    # Save scorecard before creating email
    save_opportunity_scorecard(scorecard)

    # Step 6: Create email
    logger.info("Creating email...")
    subject = f"📈 Portfolio Brief — {date_str} | {len(parsed_holdings)} positions"
    html_content, plain_content = create_html_email(
        macro_context,
        parsed_holdings,
        parsed_opportunities,
        date_str,
        scorecard,
        recommendation_changes,
        price_anomalies
    )

    # Step 7: Send email
    logger.info("Sending email...")
    send_email(subject, html_content, plain_content)

    logger.info("="*60)
    logger.info("AUDIT-COMPLIANT portfolio analysis complete")
    logger.info("="*60)


def schedule_job():
    """Schedule the job to run weekdays at 7am LOCAL TIME

    IMPORTANT: If running on Railway/cloud, the schedule runs in UTC timezone!
    - 07:00 UTC = ~3:00 AM Eastern Time (EDT/EST)
    - If you're getting duplicate emails (3 AM and 7 AM), you likely have TWO instances:
      1. Cloud instance (Railway) running in UTC at 07:00 (= 3 AM local)
      2. Local instance running at 07:00 local time (= 7 AM local)

    To fix: Either stop one instance OR adjust the cloud schedule to run at 11:00 UTC (= 7 AM EDT)
    """
    import socket
    hostname = socket.gethostname()

    logger.info("="*60)
    logger.info("SCHEDULER STARTING")
    logger.info(f"Instance identifier: {hostname}")
    logger.info(f"Scheduled time: Mon-Fri at 07:00 (LOCAL timezone)")
    logger.info("WARNING: Cloud instances run in UTC - see function docstring for timezone info")
    logger.info("="*60)

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
