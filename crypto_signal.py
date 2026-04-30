#!/usr/bin/env python3
"""
Crypto Signal Monitor - Daily Top 10 Volatile Cryptos
Runs daily at 3pm ET, sends watchlist email to Dylan & team
"""

import os
import sys
import time
import logging
from datetime import datetime
from typing import List, Dict, Tuple
import requests
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
from dotenv import load_dotenv
import schedule

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crypto_signal.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables - AUTO-DETECT PATH (matches main.py pattern)
script_dir = os.path.dirname(os.path.abspath(__file__))
ENV_FILE_PATH = os.path.join(script_dir, '.env')

logger.info("="*60)
logger.info("CRYPTO SIGNAL MONITOR - ENVIRONMENT CONFIGURATION")
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
    load_dotenv()

# Email Configuration (reuse from existing setup)
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_TO = os.getenv('EMAIL_TO')  # Your email
CRYPTO_RECIPIENT_EMAIL = os.getenv('CRYPTO_RECIPIENT_EMAIL', '')  # Dylan's email (can be comma-separated list)

# Build recipient list: Always include EMAIL_TO (you) + CRYPTO_RECIPIENT_EMAIL (Dylan)
crypto_recipients = []
if EMAIL_TO:
    crypto_recipients.append(EMAIL_TO.strip())
if CRYPTO_RECIPIENT_EMAIL:
    # Support comma-separated emails
    for email in CRYPTO_RECIPIENT_EMAIL.split(','):
        email = email.strip()
        if email and email not in crypto_recipients:
            crypto_recipients.append(email)

# If no crypto recipients set, fall back to just EMAIL_TO
if not crypto_recipients:
    crypto_recipients = [EMAIL_TO] if EMAIL_TO else []

# Debug: Show what was loaded
logger.info("Loaded credentials:")
logger.info(f"  SENDGRID_API_KEY: {SENDGRID_API_KEY[:20] + '...' if SENDGRID_API_KEY else '✗ MISSING'}")
logger.info(f"  EMAIL_FROM: {EMAIL_FROM}")
logger.info(f"  EMAIL_TO (you): {EMAIL_TO}")
logger.info(f"  CRYPTO_RECIPIENT_EMAIL (Dylan): {CRYPTO_RECIPIENT_EMAIL}")
logger.info(f"  Final recipients: {', '.join(crypto_recipients)}")
logger.info("="*60)

# Validate critical credentials
if not EMAIL_FROM or not SENDGRID_API_KEY:
    logger.error("CRITICAL: Missing required email credentials!")
    logger.error("Please ensure you have set these environment variables:")
    logger.error("  SENDGRID_API_KEY=SG.your_sendgrid_api_key")
    logger.error("  EMAIL_FROM=your_sender@example.com")
    logger.error("  CRYPTO_RECIPIENT_EMAIL=dylan@example.com")
    logger.error("On Railway: Set these in the Variables tab")
    logger.error("Locally: Add them to your .env file")
    sys.exit(1)


def fetch_coingecko_data() -> List[Dict]:
    """
    Fetch top 100 cryptos by market cap from CoinGecko (free API, no key required)
    Returns list with price, volume, 24h change, high/low for volatility calculation
    """
    try:
        logger.info("Fetching crypto data from CoinGecko...")

        # CoinGecko /coins/markets endpoint (free tier, no API key)
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            'vs_currency': 'usd',
            'order': 'market_cap_desc',
            'per_page': 100,
            'page': 1,
            'sparkline': False,
            'price_change_percentage': '1h,24h'  # Get both 1h and 24h price changes
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()

        data = response.json()
        logger.info(f"✓ Fetched {len(data)} cryptocurrencies from CoinGecko")

        return data

    except Exception as e:
        logger.error(f"Error fetching CoinGecko data: {e}")
        return []


def calculate_volatility_score(coin: Dict) -> float:
    """
    Calculate combined volatility score based on:
    1. 24h price range (high-low spread as % of current price)
    2. 24h volume (normalized)

    Higher score = more volatile and liquid (better for trading)
    """
    try:
        current_price = coin.get('current_price', 0)
        high_24h = coin.get('high_24h', current_price)
        low_24h = coin.get('low_24h', current_price)
        volume_24h = coin.get('total_volume', 0)

        if current_price == 0:
            return 0

        # Price volatility: % range from low to high
        price_range_pct = ((high_24h - low_24h) / current_price) * 100 if current_price > 0 else 0

        # Volume score: normalized to billions for scoring
        volume_score = volume_24h / 1_000_000_000  # Convert to billions

        # Combined score: weight volatility 60%, volume 40%
        combined_score = (price_range_pct * 0.6) + (volume_score * 0.4)

        return combined_score

    except Exception as e:
        logger.warning(f"Error calculating volatility for {coin.get('symbol', 'unknown')}: {e}")
        return 0


def rank_cryptos(coins: List[Dict]) -> List[Dict]:
    """Rank cryptos by combined volatility + volume score, return top 10

    Filters applied BEFORE scoring:
    1. Exclude stablecoins (no volatility by design)
    2. Minimum $1M 24h volume (liquidity requirement for trading)
    """
    try:
        # Stablecoin exclusion list (uppercase)
        STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'PYUSD', 'USDD', 'GUSD', 'USDP'}

        # Stablecoin name patterns (case-insensitive)
        STABLE_PATTERNS = ['stable', 'usd', 'usdc', 'usdt']

        # Minimum volume threshold
        MIN_VOLUME_USD = 1_000_000  # $1M minimum

        # Filter and score
        scored_coins = []
        excluded_count = {'stablecoin': 0, 'low_volume': 0}

        for coin in coins:
            symbol = coin.get('symbol', '').upper()
            name = coin.get('name', '').lower()
            volume_24h = coin.get('total_volume', 0)

            # Filter 1: Exclude stablecoins (by ticker)
            if symbol in STABLECOINS:
                excluded_count['stablecoin'] += 1
                continue

            # Filter 1b: Exclude stablecoins (by name pattern)
            if any(pattern in name for pattern in STABLE_PATTERNS):
                excluded_count['stablecoin'] += 1
                logger.info(f"Excluded {symbol} ({name}) - stablecoin name pattern match")
                continue

            # Filter 2: Minimum volume check
            if volume_24h < MIN_VOLUME_USD:
                excluded_count['low_volume'] += 1
                continue

            # Calculate score for qualifying coins
            score = calculate_volatility_score(coin)
            if score > 0:
                coin['volatility_score'] = score
                scored_coins.append(coin)

        # Sort by score descending
        ranked = sorted(scored_coins, key=lambda x: x['volatility_score'], reverse=True)

        logger.info(f"Filtered out: {excluded_count['stablecoin']} stablecoins, {excluded_count['low_volume']} low-volume coins")
        logger.info(f"Ranked {len(ranked)} coins by volatility score")
        return ranked[:10]  # Top 10

    except Exception as e:
        logger.error(f"Error ranking cryptos: {e}")
        return []


def create_crypto_email(top_coins: List[Dict], date_str: str) -> Tuple[str, str]:
    """Create HTML and plain text email content (matches portfolio monitor style)"""

    # HTML Email (matching portfolio monitor styling)
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
            background: #1e3a8a;
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
        .intro {{
            background: linear-gradient(135deg, #f6f8fb 0%, #eef2f7 100%);
            padding: 20px 24px;
            border-radius: 12px;
            line-height: 1.8;
            font-size: 15px;
            border-left: 4px solid #667eea;
            color: #2d3748;
            margin-bottom: 24px;
        }}

        /* Crypto Cards */
        .crypto-card {{
            background: #ffffff;
            border: 2px solid #cbd5e0;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }}
        .crypto-card:hover {{
            box-shadow: 0 8px 24px rgba(0,0,0,0.12);
            transform: translateY(-2px);
        }}
        .crypto-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .rank {{
            background: #1e3a8a;
            color: white;
            font-weight: 800;
            font-size: 14px;
            padding: 6px 12px;
            border-radius: 6px;
            min-width: 32px;
            text-align: center;
        }}
        .coin-name {{
            font-size: 18px;
            font-weight: 700;
            color: #1a202c;
            letter-spacing: 0.3px;
            flex: 1;
            margin-left: 12px;
        }}
        .coin-ticker {{
            font-size: 14px;
            font-weight: 600;
            color: #718096;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .price-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 12px 0;
            padding: 12px;
            background: #f7fafc;
            border-radius: 8px;
        }}
        .price {{
            font-size: 20px;
            font-weight: 700;
            color: #2d3748;
        }}
        .change {{
            font-size: 17px;
            font-weight: 700;
            letter-spacing: -0.2px;
        }}
        .change.positive {{ color: #10b981; }}
        .change.negative {{ color: #ef4444; }}
        .metrics {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 12px;
        }}
        @media only screen and (min-width: 400px) {{
            .metrics {{
                grid-template-columns: 1fr 1fr;
            }}
        }}
        .metric {{
            padding: 10px;
            background: #f7fafc;
            border-radius: 8px;
        }}
        .metric-label {{
            font-size: 12px;
            color: #718096;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }}
        .metric-value {{
            font-size: 15px;
            font-weight: 700;
            color: #2d3748;
        }}
        .volatility-score {{
            background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
            padding: 12px;
            border-radius: 8px;
            margin-top: 12px;
            border-left: 4px solid #f59e0b;
        }}
        .volatility-score .label {{
            font-size: 12px;
            color: #78350f;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .volatility-score .value {{
            font-size: 18px;
            font-weight: 800;
            color: #d97706;
            margin-top: 4px;
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
            .crypto-card {{ padding: 16px; }}
            .metrics {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header" style="background: #1e3a8a; color: #ffffff; padding: 40px 30px; text-align: center;">
            <h1 style="margin: 0; font-size: 24px; font-weight: 700; color: #ffffff;">🚀 Crypto Volatility Watchlist — {date_str}</h1>
        </div>

        <div class="section">
            <div class="intro">
                <strong style="color: #1a202c;">Top 10 cryptocurrencies ranked by trading potential</strong> — based on 24h volatility + volume.
                <br><br>
                <strong style="color: #d97706;">🔥 Hot Now:</strong> <span style="color: #2d3748;">Price moved >2% in the last hour (building momentum)</span>
                <br>
                <strong style="color: #667eea;">Volatility Score:</strong> <span style="color: #2d3748;">Higher = more price movement + liquidity (scale: 0-20+)</span>
            </div>
"""

    # Add crypto cards
    for rank, coin in enumerate(top_coins, 1):
        name = coin.get('name', 'Unknown')
        symbol = coin.get('symbol', '').upper()
        price = coin.get('current_price', 0)
        change_1h = coin.get('price_change_percentage_1h_in_currency', 0)
        change_24h = coin.get('price_change_percentage_24h', 0)
        volume_24h = coin.get('total_volume', 0)
        market_cap = coin.get('market_cap', 0)
        volatility_score = coin.get('volatility_score', 0)

        change_symbol = '+' if change_24h >= 0 else ''
        change_24h_color = '#10b981' if change_24h >= 0 else '#ef4444'

        # 1-hour momentum indicator
        change_1h_symbol = '+' if change_1h and change_1h >= 0 else ''
        hot_indicator = '🔥 ' if change_1h and abs(change_1h) > 2 else ''  # Flag if 1h change > 2%

        # Format large numbers
        volume_str = f"${volume_24h / 1_000_000_000:.2f}B" if volume_24h >= 1_000_000_000 else f"${volume_24h / 1_000_000:.1f}M"
        mcap_str = f"${market_cap / 1_000_000_000:.2f}B" if market_cap >= 1_000_000_000 else f"${market_cap / 1_000_000:.1f}M"
        price_str = f"${price:,.2f}" if price >= 1 else f"${price:.6f}"
        change_1h_str = f"{change_1h:.2f}" if change_1h else "0.00"
        change_1h_color = '#10b981' if change_1h and change_1h >= 0 else '#ef4444'

        html += f"""
            <div class="crypto-card" style="background: #ffffff; border: 2px solid #cbd5e0; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);">
                <div class="crypto-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                    <span class="rank" style="background: #1e3a8a; color: white; font-weight: 800; font-size: 14px; padding: 6px 12px; border-radius: 6px;">#{rank}</span>
                    <span class="coin-name" style="font-size: 18px; font-weight: 700; color: #1a202c; flex: 1; margin-left: 12px;">{hot_indicator}{name}</span>
                    <span class="coin-ticker" style="font-size: 14px; font-weight: 600; color: #718096; text-transform: uppercase;">{symbol}</span>
                </div>
                <div class="price-row" style="display: flex; justify-content: space-between; align-items: center; margin: 12px 0; padding: 12px; background: #f7fafc; border-radius: 8px;">
                    <span class="price" style="font-size: 20px; font-weight: 700; color: #2d3748;">{price_str}</span>
                    <span class="change" style="font-size: 17px; font-weight: 700; color: {change_24h_color};">{change_symbol}{change_24h:.2f}% (24h)</span>
                </div>
                <div class="metrics" style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px;">
                    <div class="metric" style="padding: 10px; background: #f7fafc; border-radius: 8px;">
                        <div class="metric-label" style="font-size: 12px; color: #718096; font-weight: 600; text-transform: uppercase; margin-bottom: 4px;">1h Momentum</div>
                        <div class="metric-value" style="font-size: 15px; font-weight: 700; color: {change_1h_color};">{change_1h_symbol}{change_1h_str}%</div>
                    </div>
                    <div class="metric" style="padding: 10px; background: #f7fafc; border-radius: 8px;">
                        <div class="metric-label" style="font-size: 12px; color: #718096; font-weight: 600; text-transform: uppercase; margin-bottom: 4px;">24h Volume</div>
                        <div class="metric-value" style="font-size: 15px; font-weight: 700; color: #2d3748;">{volume_str}</div>
                    </div>
                    <div class="metric" style="padding: 10px; background: #f7fafc; border-radius: 8px;">
                        <div class="metric-label" style="font-size: 12px; color: #718096; font-weight: 600; text-transform: uppercase; margin-bottom: 4px;">Market Cap</div>
                        <div class="metric-value" style="font-size: 15px; font-weight: 700; color: #2d3748;">{mcap_str}</div>
                    </div>
                    <div class="metric" style="padding: 10px; background: #f7fafc; border-radius: 8px;">
                        <div class="metric-label" style="font-size: 12px; color: #718096; font-weight: 600; text-transform: uppercase; margin-bottom: 4px;">Volatility Score</div>
                        <div class="metric-value" style="font-size: 15px; font-weight: 700; color: #d97706;">{volatility_score:.2f}</div>
                    </div>
                </div>
            </div>
"""

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    html += f"""
        </div>

        <div class="footer">
            <p><strong>Daily crypto watchlist for Dylan & Faysal</strong></p>
            <p>Data source: CoinGecko free API • Generated: {timestamp}</p>
            <p style="margin-top: 8px; font-size: 12px; color: #a0aec0;">Not financial advice. Always DYOR.</p>
        </div>
    </div>
</body>
</html>
"""

    # Plain text version
    plain = f"""CRYPTO VOLATILITY WATCHLIST — {date_str}

Top 10 cryptocurrencies ranked by trading potential (volatility + volume)

"""
    for rank, coin in enumerate(top_coins, 1):
        name = coin.get('name', 'Unknown')
        symbol = coin.get('symbol', '').upper()
        price = coin.get('current_price', 0)
        change_1h = coin.get('price_change_percentage_1h_in_currency', 0)
        change_24h = coin.get('price_change_percentage_24h', 0)
        volume_24h = coin.get('total_volume', 0)
        volatility_score = coin.get('volatility_score', 0)

        volume_str = f"${volume_24h / 1_000_000_000:.2f}B" if volume_24h >= 1_000_000_000 else f"${volume_24h / 1_000_000:.1f}M"
        hot_flag = "🔥 " if change_1h and abs(change_1h) > 2 else ""
        price_plain = f"${price:,.2f}" if price >= 1 else f"${price:.6f}"
        change_1h_plain = f"{change_1h:+.2f}" if change_1h else "+0.00"

        plain += f"""
#{rank} {hot_flag}{name} ({symbol})
  Price: {price_plain}
  1h Momentum: {change_1h_plain}%
  24h Change: {change_24h:+.2f}%
  24h Volume: {volume_str}
  Volatility Score: {volatility_score:.2f}
"""

    plain += f"\n---\nFor Dylan & Team | Data: CoinGecko\nGenerated: {timestamp}\nNot financial advice. DYOR.\n"

    return html, plain


def send_email(subject: str, html_content: str, plain_content: str):
    """Send email via SendGrid (reused pattern from main.py)"""

    # ALWAYS save email locally first
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"crypto_signal_{timestamp}.html"
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
        logger.info(f"To: {', '.join(crypto_recipients)}")
        logger.info(f"Subject: {subject}")
        logger.info(f"SendGrid API Key: {SENDGRID_API_KEY[:20]}... (length: {len(SENDGRID_API_KEY)})")
        logger.info(f"API Key valid format: {'✓ Yes' if SENDGRID_API_KEY.startswith('SG.') else '✗ No - should start with SG.'}")

        # Create list of To email objects for SendGrid
        to_emails_list = [To(email) for email in crypto_recipients]

        # Create the email message using SendGrid SDK
        message = Mail(
            from_email=Email(email=EMAIL_FROM, name="Daily Crypto Monitor"),
            to_emails=to_emails_list,
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

        if hasattr(e, 'body'):
            logger.error(f"Error body: {e.body}")
        if hasattr(e, 'status_code'):
            logger.error(f"Status code: {e.status_code}")

        logger.error(f"Email saved locally: {filename}")
        logger.error("="*60)

        import traceback
        logger.error("Full traceback:")
        logger.error(traceback.format_exc())

        return False


def run_crypto_analysis():
    """Main pipeline - fetch data, rank, send email"""
    logger.info("="*60)
    logger.info("Starting crypto volatility analysis")
    logger.info("="*60)

    # Step 1: Fetch data from CoinGecko
    coins = fetch_coingecko_data()
    if not coins:
        logger.error("No crypto data fetched. Aborting.")
        return

    # Step 2: Rank by volatility + volume
    top_10 = rank_cryptos(coins)
    if not top_10:
        logger.error("No cryptos ranked. Aborting.")
        return

    logger.info(f"Top 10 cryptos: {[c.get('symbol', '').upper() for c in top_10]}")

    # Step 3: Create email
    date_str = datetime.now().strftime('%A, %B %d, %Y')
    subject = f"🚀 Crypto Watchlist — {date_str}"
    html_content, plain_content = create_crypto_email(top_10, date_str)

    # Step 4: Send email
    logger.info("Sending email...")
    send_email(subject, html_content, plain_content)

    logger.info("="*60)
    logger.info("Crypto analysis complete")
    logger.info("="*60)


def schedule_job():
    """Schedule the job to run daily at 3:00 PM ET

    IMPORTANT: If running on Railway/cloud in UTC timezone:
    - 3:00 PM EDT = 19:00 UTC (during daylight saving time)
    - 3:00 PM EST = 20:00 UTC (during standard time)

    For simplicity, schedule at 19:00 UTC which = 3 PM EDT / 2 PM EST
    Adjust based on your deployment timezone!
    """
    import socket
    hostname = socket.gethostname()

    logger.info("="*60)
    logger.info("CRYPTO SIGNAL SCHEDULER STARTING")
    logger.info(f"Instance identifier: {hostname}")
    logger.info(f"Scheduled time: Daily at 15:00 (3 PM LOCAL timezone)")
    logger.info("WARNING: Cloud instances run in UTC - you may need to adjust schedule time")
    logger.info("="*60)

    # Schedule daily at 3 PM local time
    schedule.every().day.at("15:00").do(run_crypto_analysis)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        logger.info("Running immediate analysis (--now flag)")
        run_crypto_analysis()
    else:
        schedule_job()
