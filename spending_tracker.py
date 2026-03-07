#!/usr/bin/env python3
"""
Monthly Spending Tracker
Monitors Google Drive for new CSV exports, categorizes with Claude AI, sends beautiful email reports
"""

import os
import sys
import json
import csv
import io
import re
import time
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import anthropic
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
import schedule


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('spending_tracker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables - AUTO-DETECT PATH
script_dir = os.path.dirname(os.path.abspath(__file__))
ENV_FILE_PATH = os.path.join(script_dir, '.env')

logger.info("="*60)
logger.info("SPENDING TRACKER - ENVIRONMENT CONFIGURATION")
logger.info("="*60)
logger.info(f"Script directory: {script_dir}")
logger.info(f".env path: {ENV_FILE_PATH}")
logger.info(f".env file exists: {os.path.exists(ENV_FILE_PATH)}")

if not os.path.exists(ENV_FILE_PATH):
    logger.error(f"CRITICAL ERROR: .env file not found at {ENV_FILE_PATH}")
    logger.error("Please create a .env file in the same directory as spending_tracker.py")
    sys.exit(1)

# Load the .env file
env_loaded = load_dotenv(ENV_FILE_PATH, override=True)
logger.info(f".env file loaded: {env_loaded}")

# Configuration
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
GOOGLE_DRIVE_FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_TO = os.getenv('EMAIL_TO')

# Debug: Show what was loaded
logger.info("Loaded credentials:")
logger.info(f"  ANTHROPIC_API_KEY: {ANTHROPIC_API_KEY[:20] + '...' if ANTHROPIC_API_KEY else '✗ MISSING'}")
logger.info(f"  GOOGLE_DRIVE_FOLDER_ID: {GOOGLE_DRIVE_FOLDER_ID[:20] + '...' if GOOGLE_DRIVE_FOLDER_ID else '✗ MISSING'}")
logger.info(f"  GOOGLE_SERVICE_ACCOUNT_FILE: {GOOGLE_SERVICE_ACCOUNT_FILE if GOOGLE_SERVICE_ACCOUNT_FILE else '✗ MISSING'}")
logger.info(f"  SENDGRID_API_KEY: {SENDGRID_API_KEY[:20] + '...' if SENDGRID_API_KEY else '✗ MISSING'}")
logger.info(f"  EMAIL_FROM: {EMAIL_FROM}")
logger.info(f"  EMAIL_TO: {EMAIL_TO}")
logger.info("="*60)

# Validate critical credentials
if not all([ANTHROPIC_API_KEY, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SERVICE_ACCOUNT_FILE,
            SENDGRID_API_KEY, EMAIL_FROM, EMAIL_TO]):
    logger.error("CRITICAL: Missing required credentials!")
    logger.error("Please ensure your .env file has:")
    logger.error("  ANTHROPIC_API_KEY=sk-ant-...")
    logger.error("  GOOGLE_DRIVE_FOLDER_ID=...")
    logger.error("  GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json")
    logger.error("  SENDGRID_API_KEY=SG...")
    logger.error("  EMAIL_FROM=your@email.com")
    logger.error("  EMAIL_TO=recipient@email.com")
    sys.exit(1)

# Data storage
DATA_DIR = Path(script_dir) / 'spending_data'
PROCESSED_DIR = DATA_DIR / 'processed_csvs'
HISTORY_FILE = DATA_DIR / 'monthly_history.json'

# Categories
CATEGORIES = [
    "Food & Dining",
    "Transport",
    "Bills & Utilities",
    "Entertainment",
    "Health",
    "Shopping",
    "Other"
]


class Transaction:
    """Normalized transaction format"""
    def __init__(self, date: datetime, description: str, amount: float,
                 merchant: str, source: str, raw_data: Dict):
        self.date = date
        self.description = description
        self.amount = abs(amount)
        self.merchant = merchant
        self.source = source
        self.raw_data = raw_data
        self.category = None
        self.is_subscription = False

    def to_dict(self) -> Dict:
        return {
            'date': self.date.isoformat(),
            'description': self.description,
            'amount': self.amount,
            'merchant': self.merchant,
            'source': self.source,
            'category': self.category,
            'is_subscription': self.is_subscription
        }


class CSVParser:
    """Parse CSVs from different banks"""

    @staticmethod
    def detect_source(headers: List[str], filename: str) -> Optional[str]:
        """Detect which bank based on headers or filename"""
        if headers is None:
            headers = []

        headers_lower = [h.lower().strip() for h in headers]
        filename_lower = filename.lower()

        # Check filename first
        if 'wealthsimple-credit-card' in filename_lower:
            return 'wealthsimple_cc'
        if filename_lower.startswith('activity'):
            return 'wealthsimple'
        if filename_lower.startswith('transactions'):
            return 'amex'
        if filename_lower.startswith('accountactivit'):
            return 'td'

        # Rogers has distinctive long header list
        if 'merchant name' in headers_lower and 'activity type' in headers_lower and 'merchant category description' in headers_lower:
            return 'rogers'

        # Wealthsimple Credit Card: transaction_date, post_date, type, details, amount, currency
        if all(h in headers_lower for h in ['transaction_date', 'post_date', 'type', 'details']):
            return 'wealthsimple_cc'

        # Wealthsimple Cash: date, transaction, description, amount, balance, currency
        if all(h in headers_lower for h in ['date', 'transaction', 'description', 'amount', 'balance', 'currency']):
            return 'wealthsimple'

        # Amex: Date, Date Processed, Description, Amount
        if 'date processed' in headers_lower and 'description' in headers_lower and 'amount' in headers_lower:
            return 'amex'

        return None

    @staticmethod
    def parse_wealthsimple(rows: List[Dict]) -> Tuple[List[Transaction], int]:
        """Parse Wealthsimple CSV format
        Headers: date, transaction, description, amount, balance, currency
        Negative amount = spending
        """
        transactions = []
        skipped = 0

        for row in rows:
            try:
                # Wealthsimple exact columns
                date_str = row.get('date') or row.get('Date')
                description = row.get('description') or row.get('Description')
                amount_str = row.get('amount') or row.get('Amount')

                if not all([date_str, description, amount_str]):
                    continue

                date = CSVParser._parse_date(date_str)
                if not date:
                    continue

                amount = CSVParser._parse_amount(amount_str)

                # Negative = spending for Wealthsimple
                if amount >= 0:
                    continue

                if CSVParser._is_payment_or_transfer(description):
                    skipped += 1
                    continue

                transactions.append(Transaction(
                    date=date,
                    description=description,
                    amount=abs(amount),
                    merchant=CSVParser._clean_merchant_name(description),
                    source='Wealthsimple',
                    raw_data=row
                ))
            except Exception as e:
                logger.error(f"Error parsing Wealthsimple row: {e}")
                continue

        return transactions, skipped

    @staticmethod
    def parse_wealthsimple_cc(rows: List[Dict]) -> Tuple[List[Transaction], int]:
        """Parse Wealthsimple Credit Card CSV format
        Headers: transaction_date, post_date, type, details, amount, currency
        Positive amount = spending (like Amex)
        """
        transactions = []
        skipped = 0

        for row in rows:
            try:
                # Wealthsimple CC columns
                date_str = row.get('transaction_date') or row.get('post_date')
                description = row.get('details') or row.get('type')
                amount_str = row.get('amount')

                if not all([date_str, description, amount_str]):
                    continue

                date = CSVParser._parse_date(date_str)
                if not date:
                    continue

                amount = CSVParser._parse_amount(amount_str)

                # Positive = spending for Wealthsimple Credit Card
                if amount <= 0:
                    continue

                if CSVParser._is_payment_or_transfer(description):
                    skipped += 1
                    continue

                transactions.append(Transaction(
                    date=date,
                    description=description,
                    amount=abs(amount),
                    merchant=CSVParser._clean_merchant_name(description),
                    source='Wealthsimple Credit Card',
                    raw_data=row
                ))
            except Exception as e:
                logger.error(f"Error parsing Wealthsimple CC row: {e}")
                continue

        return transactions, skipped

    @staticmethod
    def parse_amex(rows: List[Dict]) -> Tuple[List[Transaction], int]:
        """Parse American Express CSV format
        Headers: Date, Date Processed, Description, Amount
        Positive amount = spending
        """
        transactions = []
        skipped = 0

        for row in rows:
            try:
                date_str = row.get('Date') or row.get('date')
                description = row.get('Description') or row.get('description')
                amount_str = row.get('Amount') or row.get('amount')

                if not all([date_str, description, amount_str]):
                    continue

                date = CSVParser._parse_date(date_str)
                if not date:
                    continue

                amount = CSVParser._parse_amount(amount_str)

                # Positive = spending for Amex
                if amount <= 0:
                    continue

                if CSVParser._is_payment_or_transfer(description):
                    skipped += 1
                    continue

                transactions.append(Transaction(
                    date=date,
                    description=description,
                    amount=abs(amount),
                    merchant=CSVParser._clean_merchant_name(description),
                    source='American Express',
                    raw_data=row
                ))
            except Exception as e:
                logger.error(f"Error parsing Amex row: {e}")
                continue

        return transactions, skipped

    @staticmethod
    def parse_rogers(rows: List[Dict]) -> Tuple[List[Transaction], int]:
        """Parse Rogers Mastercard CSV format
        Many headers including: Date, Merchant Name, Amount (with $ sign)
        """
        transactions = []
        skipped = 0

        for row in rows:
            try:
                date_str = row.get('Date') or row.get('date')
                merchant = row.get('Merchant Name') or row.get('merchant name')
                amount_str = row.get('Amount') or row.get('amount')

                if not all([date_str, merchant, amount_str]):
                    continue

                date = CSVParser._parse_date(date_str)
                if not date:
                    continue

                # Rogers amount has $ sign - strip it
                amount = CSVParser._parse_amount(amount_str)

                # Check if spending (should be positive after stripping $)
                if amount <= 0:
                    continue

                if CSVParser._is_payment_or_transfer(merchant):
                    skipped += 1
                    continue

                transactions.append(Transaction(
                    date=date,
                    description=merchant,
                    amount=abs(amount),
                    merchant=CSVParser._clean_merchant_name(merchant),
                    source='Rogers Mastercard',
                    raw_data=row
                ))
            except Exception as e:
                logger.error(f"Error parsing Rogers row: {e}")
                continue

        return transactions, skipped

    @staticmethod
    def parse_td(rows: List[List[str]]) -> Tuple[List[Transaction], int]:
        """Parse TD CSV format
        NO HEADERS - data starts on row 1
        Columns: Date, Description, Amount, Balance (in that order)
        Negative amount = spending
        """
        transactions = []
        skipped = 0

        for row in rows:
            try:
                # TD has no headers, columns are: Date(0), Description(1), Amount(2), Balance(3)
                if len(row) < 3:
                    continue

                date_str = row[0]
                description = row[1]
                amount_str = row[2]

                if not all([date_str, description, amount_str]):
                    continue

                date = CSVParser._parse_date(date_str)
                if not date:
                    continue

                amount = CSVParser._parse_amount(amount_str)

                # Negative = spending for TD
                if amount >= 0:
                    continue

                if CSVParser._is_payment_or_transfer(description):
                    skipped += 1
                    continue

                transactions.append(Transaction(
                    date=date,
                    description=description,
                    amount=abs(amount),
                    merchant=CSVParser._clean_merchant_name(description),
                    source='TD',
                    raw_data={'date': date_str, 'description': description, 'amount': amount_str}
                ))
            except Exception as e:
                logger.error(f"Error parsing TD row: {e}")
                continue

        return transactions, skipped

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Try multiple date formats"""
        date_formats = [
            '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d',
            '%b %d, %Y', '%B %d, %Y', '%m-%d-%Y', '%d-%m-%Y'
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        return None

    @staticmethod
    def _parse_amount(amount_str: str) -> float:
        """Parse amount string to float"""
        clean = re.sub(r'[^\d.+-]', '', amount_str)
        return float(clean)

    @staticmethod
    def _is_payment_or_transfer(description: str) -> bool:
        """Check if transaction is a payment, transfer, or investment (not real spending)"""
        desc_lower = description.lower()
        desc_upper = description.upper()

        # Payment/transfer keywords
        payment_keywords = [
            'royal bank', 'rogers pay', 'amex', 'td payment',
            'internet transfer', 'e-transfer', 'etransfer',
            'payment', 'thank you', 'pymt', 'transfer', 'interac',
            'credit card payment', 'autopay', 'pre-authorized'
        ]

        # Wealthsimple investment keywords (case-sensitive check)
        investment_keywords = [
            'Purchase of', 'Trading fee', 'Management fee',
            'Withdrawal', 'INT ', 'E_TRFIN', 'E_TRFOUT',
            'DIV', 'BUY', 'SELL'
        ]

        # Check payment keywords (case-insensitive)
        if any(keyword in desc_lower for keyword in payment_keywords):
            return True

        # Check investment keywords (check both exact case and in description)
        if any(keyword in description for keyword in investment_keywords):
            return True

        return False

    @staticmethod
    def _clean_merchant_name(description: str) -> str:
        """Extract clean merchant name"""
        merchant = re.sub(r'\d{2}/\d{2}', '', description)
        merchant = re.sub(r'#\d+', '', merchant)
        merchant = re.sub(r'\s+', ' ', merchant).strip()
        return merchant[:50]


class GoogleDriveMonitor:
    """Monitor Google Drive folder for new CSVs"""

    def __init__(self, credentials_file: str, folder_id: str):
        self.folder_id = folder_id
        # Resolve relative path
        if not os.path.isabs(credentials_file):
            credentials_file = os.path.join(script_dir, credentials_file)

        logger.info(f"Loading Google service account from: {credentials_file}")

        creds = service_account.Credentials.from_service_account_file(
            credentials_file,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        self.service = build('drive', 'v3', credentials=creds)

    def get_new_csv_files(self) -> List[Dict]:
        """Get all CSV files from the folder that haven't been processed"""
        query = f"'{self.folder_id}' in parents and mimeType='text/csv' and trashed=false"

        results = self.service.files().list(
            q=query,
            fields='files(id, name, createdTime, modifiedTime)',
            orderBy='modifiedTime desc'
        ).execute()

        files = results.get('files', [])

        new_files = []
        for file in files:
            if not self._is_processed(file['id']):
                new_files.append(file)

        return new_files

    def download_file(self, file_id: str) -> str:
        """Download CSV file content"""
        request = self.service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.seek(0)
        return fh.read().decode('utf-8')

    def _is_processed(self, file_id: str) -> bool:
        """Check if file has already been processed"""
        processed_file = PROCESSED_DIR / f"{file_id}.marker"
        return processed_file.exists()

    def mark_as_processed(self, file_id: str, filename: str):
        """Mark file as processed"""
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        marker_file = PROCESSED_DIR / f"{file_id}.marker"
        marker_file.write_text(json.dumps({
            'file_id': file_id,
            'filename': filename,
            'processed_at': datetime.now().isoformat()
        }))


class ClaudeCategorizer:
    """Use Claude AI to categorize transactions"""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def categorize_transactions(self, transactions: List[Transaction]) -> List[Transaction]:
        """Batch categorize transactions using Claude"""
        if not transactions:
            return transactions

        tx_list = []
        for i, tx in enumerate(transactions):
            tx_list.append({
                'id': i,
                'merchant': tx.merchant,
                'description': tx.description,
                'amount': tx.amount
            })

        prompt = f"""You are a financial categorization assistant. Categorize each transaction into EXACTLY ONE of these categories (use the exact spelling):

Food & Dining
Transport
Bills & Utilities
Entertainment
Health
Shopping
Other

Also identify which transactions are recurring subscriptions.

Transactions to categorize:
{json.dumps(tx_list, indent=2)}

IMPORTANT: Return ONLY a valid JSON object with this EXACT structure (no other text):
{{
  "categorized": [
    {{"id": 0, "category": "Food & Dining", "is_subscription": false}},
    {{"id": 1, "category": "Transport", "is_subscription": false}}
  ]
}}

Categorization rules (BE SPECIFIC):
- "Food & Dining": Restaurants, cafes, bars, food delivery (UberEats, DoorDash, SkipTheDishes), grocery stores, bakeries, fast food
- "Transport": Uber, Lyft, taxis, gas stations, parking, public transit, car rental, automotive
- "Bills & Utilities": Phone bills, internet, electricity, water, gas, cell phone, cable, insurance
- "Entertainment": Netflix, Spotify, Apple Music, Disney+, gym memberships, movies, games, sports, concerts
- "Health": Pharmacies, doctors, dentists, hospitals, medical supplies, health insurance, prescriptions
- "Shopping": Amazon, clothing stores, electronics, home goods, department stores, online shopping
- "Other": Anything that doesn't clearly fit the above categories

Subscription detection: Mark is_subscription=true ONLY for: streaming services (Netflix, Spotify, etc), gym memberships, phone/internet bills, insurance. NOT for one-time purchases.

Return the JSON now:"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text
            logger.info(f"Claude response preview: {response_text[:200]}...")

            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                categorized = result.get('categorized', [])

                logger.info(f"Successfully parsed {len(categorized)} categorizations from Claude")

                for item in categorized:
                    tx_id = item.get('id')
                    if tx_id is not None and tx_id < len(transactions):
                        category = item.get('category', 'Other')
                        # Validate category is in allowed list
                        if category not in CATEGORIES:
                            logger.warning(f"Invalid category '{category}' from Claude, using 'Other'")
                            category = 'Other'

                        transactions[tx_id].category = category
                        transactions[tx_id].is_subscription = item.get('is_subscription', False)
            else:
                logger.error("Could not extract JSON from Claude response")
                logger.error(f"Full response: {response_text}")

        except Exception as e:
            logger.error(f"Error categorizing with Claude: {e}")
            import traceback
            logger.error(traceback.format_exc())
            for tx in transactions:
                if not tx.category:
                    tx.category = 'Other'
                    tx.is_subscription = False

        return transactions


class DataStore:
    """Store and retrieve historical data"""

    @staticmethod
    def save_month_data(year: int, month: int, transactions: List[Transaction],
                       category_totals: Dict, merchant_totals: Dict):
        """Save data for a specific month"""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        history = DataStore.load_history()

        month_key = f"{year}-{month:02d}"
        history[month_key] = {
            'year': year,
            'month': month,
            'total_spent': sum(tx.amount for tx in transactions),
            'transaction_count': len(transactions),
            'category_totals': category_totals,
            'merchant_totals': merchant_totals,
            'transactions': [tx.to_dict() for tx in transactions]
        }

        HISTORY_FILE.write_text(json.dumps(history, indent=2))

    @staticmethod
    def load_history() -> Dict:
        """Load all historical data"""
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text())
        return {}

    @staticmethod
    def get_previous_month_data(year: int, month: int) -> Optional[Dict]:
        """Get data from previous month"""
        history = DataStore.load_history()

        if month == 1:
            prev_year = year - 1
            prev_month = 12
        else:
            prev_year = year
            prev_month = month - 1

        prev_key = f"{prev_year}-{prev_month:02d}"
        return history.get(prev_key)


def generate_html_report(year: int, month: int, transactions: List[Transaction],
                         data_quality: Dict[str, Any] = None) -> str:
    """Generate beautiful dark-themed HTML report"""

    total_spent = sum(tx.amount for tx in transactions)

    category_totals = defaultdict(float)
    for tx in transactions:
        category_totals[tx.category or 'Other'] += tx.amount

    sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)

    merchant_totals = defaultdict(lambda: {'amount': 0.0, 'count': 0})
    for tx in transactions:
        merchant_totals[tx.merchant]['amount'] += tx.amount
        merchant_totals[tx.merchant]['count'] += 1

    top_merchants = sorted(merchant_totals.items(), key=lambda x: x[1]['amount'], reverse=True)[:10]

    subscriptions = [tx for tx in transactions if tx.is_subscription]
    subscription_total = sum(tx.amount for tx in subscriptions)

    prev_month_data = DataStore.get_previous_month_data(year, month)
    mom_change = None
    mom_percent = None
    ytd_total = None
    biggest_change_category = None
    biggest_change_amount = 0
    biggest_change_percent = 0

    if prev_month_data:
        prev_total = prev_month_data['total_spent']
        mom_change = total_spent - prev_total
        mom_percent = (mom_change / prev_total * 100) if prev_total > 0 else 0

        prev_categories = prev_month_data.get('category_totals', {})
        for category, amount in category_totals.items():
            prev_amount = prev_categories.get(category, 0)
            change = amount - prev_amount
            change_percent = (change / prev_amount * 100) if prev_amount > 0 else 100

            if abs(change) > abs(biggest_change_amount):
                biggest_change_category = category
                biggest_change_amount = change
                biggest_change_percent = change_percent

    history = DataStore.load_history()
    ytd_total = sum(
        data['total_spent']
        for key, data in history.items()
        if key.startswith(str(year))
    )

    month_name = datetime(year, month, 1).strftime('%B %Y')

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spending Report - {month_name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #0f0f1e;
            color: #e5e7eb;
            padding: 0;
            line-height: 1.5;
        }}

        .container {{
            max-width: 600px;
            margin: 0 auto;
            background: #1a1d2e;
        }}

        .header {{
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            padding: 32px 20px;
            text-align: center;
            border-bottom: 3px solid #10b981;
        }}

        .header h1 {{
            font-size: 24px;
            font-weight: 700;
            color: #ffffff;
            margin-bottom: 16px;
        }}

        .header .total {{
            font-size: 42px;
            font-weight: 800;
            color: #10b981;
            margin: 16px 0;
        }}

        .header .ytd {{
            font-size: 14px;
            color: #94a3b8;
            margin-top: 8px;
        }}

        .section {{
            padding: 24px 20px;
            border-bottom: 1px solid #2a2f3e;
        }}

        .section-title {{
            font-size: 16px;
            font-weight: 700;
            color: #f1f5f9;
            margin-bottom: 16px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .alert-box {{
            background: rgba(239, 68, 68, 0.1);
            border-left: 4px solid #ef4444;
            padding: 16px;
            margin: 0 20px 20px 20px;
            border-radius: 8px;
        }}

        .alert-box.positive {{
            background: rgba(16, 185, 129, 0.1);
            border-left-color: #10b981;
        }}

        .alert-box h3 {{
            color: #ef4444;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 6px;
            font-weight: 700;
        }}

        .alert-box.positive h3 {{
            color: #10b981;
        }}

        .alert-box p {{
            font-size: 16px;
            color: #f1f5f9;
            font-weight: 600;
        }}

        .stat-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 16px;
        }}

        .stat-card {{
            background: #252938;
            border-radius: 10px;
            padding: 16px;
            border: 1px solid #2a2f3e;
        }}

        .stat-label {{
            font-size: 11px;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 8px;
        }}

        .stat-value {{
            font-size: 22px;
            font-weight: 700;
            color: #f1f5f9;
        }}

        .stat-change {{
            font-size: 12px;
            margin-top: 6px;
            font-weight: 600;
        }}

        .stat-change.up {{ color: #ef4444; }}
        .stat-change.down {{ color: #10b981; }}

        .category-item {{
            background: #252938;
            border-radius: 8px;
            padding: 14px;
            margin-bottom: 10px;
            border: 1px solid #2a2f3e;
        }}

        .category-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}

        .category-name {{
            font-size: 14px;
            font-weight: 600;
            color: #f1f5f9;
        }}

        .category-amount {{
            font-size: 16px;
            font-weight: 700;
            color: #10b981;
        }}

        .category-meta {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
        }}

        .category-percent {{
            color: #94a3b8;
        }}

        .badge {{
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }}

        .badge.up {{
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
        }}

        .badge.down {{
            background: rgba(16, 185, 129, 0.2);
            color: #10b981;
        }}

        .list-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #2a2f3e;
        }}

        .list-item:last-child {{
            border-bottom: none;
        }}

        .list-name {{
            font-size: 14px;
            color: #f1f5f9;
            font-weight: 500;
            flex: 1;
            padding-right: 12px;
        }}

        .list-amount {{
            font-size: 15px;
            font-weight: 700;
            color: #10b981;
            white-space: nowrap;
        }}

        .list-count {{
            font-size: 11px;
            color: #94a3b8;
            margin-right: 8px;
        }}

        .subscription-box {{
            background: rgba(16, 185, 129, 0.1);
            border: 2px solid #10b981;
            border-radius: 10px;
            padding: 16px;
        }}

        .subscription-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}

        .subscription-title {{
            font-size: 15px;
            font-weight: 700;
            color: #10b981;
        }}

        .subscription-total {{
            font-size: 18px;
            font-weight: 700;
            color: #f1f5f9;
        }}

        .subscription-item {{
            display: flex;
            justify-content: space-between;
            padding: 10px;
            background: #252938;
            border-radius: 6px;
            margin-bottom: 8px;
        }}

        .subscription-item:last-child {{
            margin-bottom: 0;
        }}

        .mom-box {{
            background: linear-gradient(135deg, #252938 0%, #1a1d2e 100%);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
        }}

        .mom-label {{
            font-size: 12px;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 10px;
        }}

        .mom-value {{
            font-size: 32px;
            font-weight: 800;
        }}

        .quality-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 10px;
            margin-bottom: 16px;
        }}

        .quality-stat {{
            text-align: center;
            padding: 12px;
            background: #252938;
            border-radius: 8px;
        }}

        .quality-stat-label {{
            font-size: 10px;
            color: #94a3b8;
            text-transform: uppercase;
            margin-bottom: 6px;
        }}

        .quality-stat-value {{
            font-size: 18px;
            font-weight: 700;
            color: #10b981;
        }}

        .quality-stat-value.warn {{
            color: #ef4444;
        }}

        .footer {{
            text-align: center;
            padding: 20px;
            color: #64748b;
            font-size: 11px;
            border-top: 1px solid #2a2f3e;
        }}

        @media only screen and (max-width: 600px) {{
            .header h1 {{ font-size: 20px; }}
            .header .total {{ font-size: 36px; }}
            .stat-grid {{ grid-template-columns: 1fr; }}
            .quality-grid {{ grid-template-columns: 1fr; }}
            .section {{ padding: 20px 16px; }}
            .alert-box {{ margin: 0 16px 16px 16px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💳 {month_name}</h1>
            <div class="total">${total_spent:,.2f}</div>
            <div class="ytd">YTD: ${ytd_total:,.2f}</div>
        </div>"""

    if biggest_change_category and biggest_change_amount != 0:
        alert_class = "alert-box" if biggest_change_amount > 0 else "alert-box positive"
        arrow = "↑" if biggest_change_amount > 0 else "↓"
        title = "LARGEST INCREASE" if biggest_change_amount > 0 else "LARGEST DECREASE"
        html += f"""
        <div class="{alert_class}">
            <h3>{title}</h3>
            <p>{biggest_change_category}: {arrow} ${abs(biggest_change_amount):,.2f} ({biggest_change_percent:+.1f}%)</p>
        </div>"""

    html += """
        <div class="section">
            <h2 class="section-title">Categories</h2>"""

    for category, amount in sorted_categories:
        percentage = (amount / total_spent * 100) if total_spent > 0 else 0

        mom_category_change = ""
        if prev_month_data:
            prev_cat_amount = prev_month_data.get('category_totals', {}).get(category, 0)
            if prev_cat_amount > 0:
                cat_change = amount - prev_cat_amount
                cat_change_percent = (cat_change / prev_cat_amount * 100)
                arrow = "↑" if cat_change > 0 else "↓"
                change_class = "up" if cat_change > 0 else "down"
                mom_category_change = f'<span class="badge {change_class}">{arrow} {abs(cat_change_percent):.0f}%</span>'
            elif amount > 0:
                mom_category_change = '<span class="badge up">NEW</span>'

        html += f"""
            <div class="category-item">
                <div class="category-header">
                    <div class="category-name">{category}</div>
                    <div class="category-amount">${amount:,.2f}</div>
                </div>
                <div class="category-meta">
                    <span class="category-percent">{percentage:.1f}% of total</span>
                    {mom_category_change}
                </div>
            </div>"""

    html += """
        </div>"""

    if subscriptions:
        html += f"""
        <div class="section">
            <div class="subscription-box">
                <div class="subscription-header">
                    <div class="subscription-title">🔄 Subscriptions</div>
                    <div class="subscription-total">${subscription_total:,.2f}/mo</div>
                </div>"""

        for sub in sorted(subscriptions, key=lambda x: x.amount, reverse=True):
            html += f"""
                <div class="subscription-item">
                    <span style="color: #f1f5f9; font-weight: 500;">{sub.merchant}</span>
                    <span style="color: #10b981; font-weight: 700;">${sub.amount:,.2f}</span>
                </div>"""

        html += """
            </div>
        </div>"""

    html += """
        <div class="section">
            <h2 class="section-title">Top Merchants</h2>"""

    for merchant, data in top_merchants:
        html += f"""
            <div class="list-item">
                <div class="list-name">{merchant}</div>
                <span class="list-count">{data['count']}×</span>
                <div class="list-amount">${data['amount']:,.2f}</div>
            </div>"""

    html += """
        </div>"""

    if mom_change is not None:
        mom_color = "#ef4444" if mom_change > 0 else "#10b981"
        mom_arrow = "↑" if mom_change > 0 else "↓"
        html += f"""
        <div class="section">
            <div class="mom-box">
                <div class="mom-label">vs Last Month</div>
                <div class="mom-value" style="color: {mom_color};">
                    {mom_arrow} ${abs(mom_change):,.2f}
                </div>
                <div style="font-size: 14px; color: #94a3b8; margin-top: 8px;">
                    {mom_percent:+.1f}% change
                </div>
            </div>
        </div>"""

    # Data Quality Summary
    if data_quality:
        html += """
        <div class="section">
            <h2 class="section-title">📊 Data Quality</h2>
            <div class="quality-grid">
                <div class="quality-stat">
                    <div class="quality-stat-label">Files</div>
                    <div class="quality-stat-value">{files}</div>
                </div>
                <div class="quality-stat">
                    <div class="quality-stat-label">Found</div>
                    <div class="quality-stat-value">{total}</div>
                </div>
                <div class="quality-stat">
                    <div class="quality-stat-label">Skipped</div>
                    <div class="quality-stat-value warn">{skipped}</div>
                </div>
            </div>
""".format(
            files=data_quality.get('files_processed', 0),
            total=data_quality.get('total_found', 0),
            skipped=data_quality.get('total_skipped', 0)
        )

        # Add source breakdown
        source_breakdown = data_quality.get('source_breakdown', {})
        for source, count in sorted(source_breakdown.items(), key=lambda x: x[1], reverse=True):
            html += f"""
            <div class="list-item">
                <div class="list-name">{source}</div>
                <div class="list-amount">{count} txns</div>
            </div>"""

        html += """
        </div>
        """

    html += f"""
        <div class="footer">
            {len(transactions)} transactions · {len(category_totals)} categories<br>
            {datetime.now().strftime('%b %d, %Y %I:%M %p')}
        </div>
    </div>
</body>
</html>"""

    DataStore.save_month_data(year, month, transactions, dict(category_totals),
                              {k: v['amount'] for k, v in merchant_totals.items()})

    return html


def send_email(subject: str, html_content: str):
    """Send email via SendGrid"""

    # ALWAYS save email locally first
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"spending_email_{timestamp}.html"
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"✓ Email saved locally: {filename}")
    except Exception as save_error:
        logger.error(f"✗ Error saving email to file: {save_error}")

    try:
        logger.info("="*60)
        logger.info("EMAIL SEND ATTEMPT (SendGrid)")
        logger.info("="*60)
        logger.info(f"From: {EMAIL_FROM}")
        logger.info(f"To: {EMAIL_TO}")
        logger.info(f"Subject: {subject}")
        logger.info(f"SendGrid API Key: {SENDGRID_API_KEY[:20]}...")
        logger.info(f"API Key valid format: {'✓ Yes' if SENDGRID_API_KEY.startswith('SG.') else '✗ No - should start with SG.'}")

        message = Mail(
            from_email=Email(EMAIL_FROM),
            to_emails=To(EMAIL_TO),
            subject=subject,
            html_content=Content("text/html", html_content)
        )

        logger.info("Initializing SendGrid client...")
        sg = SendGridAPIClient(api_key=SENDGRID_API_KEY)

        logger.info("Sending email via SendGrid...")
        response = sg.send(message)

        logger.info(f"✓ Response Status: {response.status_code}")

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
        logger.error(f"Email saved locally: {filename}")
        logger.error("="*60)

        import traceback
        logger.error("Full traceback:")
        logger.error(traceback.format_exc())

        return False


def run_spending_analysis():
    """Main execution function"""
    logger.info("="*60)
    logger.info("SPENDING TRACKER - STARTING RUN")
    logger.info("="*60)
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        drive_monitor = GoogleDriveMonitor(GOOGLE_SERVICE_ACCOUNT_FILE, GOOGLE_DRIVE_FOLDER_ID)
        categorizer = ClaudeCategorizer(ANTHROPIC_API_KEY)
        parser = CSVParser()

        logger.info("Checking Google Drive for new CSV files...")
        new_files = drive_monitor.get_new_csv_files()

        if not new_files:
            logger.info("No new CSV files found.")
            return

        logger.info(f"Found {len(new_files)} new file(s)\n")

        all_transactions = []
        total_skipped = 0
        source_counts = defaultdict(int)
        files_processed = 0

        for file_info in new_files:
            file_id = file_info['id']
            filename = file_info['name']

            logger.info(f"Processing: {filename}")

            csv_content = drive_monitor.download_file(file_id)

            # Try to detect source first to handle TD (no headers)
            source = parser.detect_source(None, filename)

            if source == 'td':
                # TD has no headers - parse as raw rows
                csv_reader = csv.reader(io.StringIO(csv_content))
                rows = list(csv_reader)
                transactions, skipped = parser.parse_td(rows)
            else:
                # Other banks have headers
                csv_reader = csv.DictReader(io.StringIO(csv_content))
                headers = csv_reader.fieldnames
                rows = list(csv_reader)

                source = parser.detect_source(headers, filename)

                if not source:
                    logger.warning(f"  ✗ Could not detect bank source for {filename}")
                    logger.warning(f"  → Filename: {filename}")
                    logger.warning(f"  → Headers: {headers}")
                    logger.warning(f"  → First 3 rows for debugging:")
                    for i, row in enumerate(rows[:3]):
                        logger.warning(f"      Row {i+1}: {dict(row)}")
                    continue

                logger.info(f"  Detected source: {source}")

                if source == 'wealthsimple':
                    transactions, skipped = parser.parse_wealthsimple(rows)
                elif source == 'wealthsimple_cc':
                    transactions, skipped = parser.parse_wealthsimple_cc(rows)
                elif source == 'amex':
                    transactions, skipped = parser.parse_amex(rows)
                elif source == 'rogers':
                    transactions, skipped = parser.parse_rogers(rows)
                else:
                    logger.warning(f"  ✗ Unknown source: {source}")
                    continue

            logger.info(f"  Parsed {len(transactions)} transactions, skipped {skipped} transfers/payments")
            all_transactions.extend(transactions)
            total_skipped += skipped
            source_counts[source] += len(transactions)
            files_processed += 1

            drive_monitor.mark_as_processed(file_id, filename)
            logger.info(f"  ✓ Marked as processed\n")

        if not all_transactions:
            logger.info("No valid transactions found.")
            return

        all_transactions.sort(key=lambda x: x.date)

        logger.info(f"Categorizing {len(all_transactions)} transactions with Claude AI...")
        all_transactions = categorizer.categorize_transactions(all_transactions)
        logger.info("✓ Categorization complete\n")

        transactions_by_month = defaultdict(list)
        for tx in all_transactions:
            month_key = (tx.date.year, tx.date.month)
            transactions_by_month[month_key].append(tx)

        for (year, month), transactions in sorted(transactions_by_month.items()):
            month_name = datetime(year, month, 1).strftime('%B %Y')
            logger.info(f"Generating report for {month_name}...")

            # Pass data quality metrics
            data_quality = {
                'files_processed': files_processed,
                'total_found': len(all_transactions),
                'total_skipped': total_skipped,
                'source_breakdown': dict(source_counts)
            }

            html_report = generate_html_report(year, month, transactions, data_quality)

            subject = f"💳 Spending Report: {month_name}"
            send_email(subject, html_report)

        logger.info("\n✓ All done!")

    except Exception as e:
        logger.error(f"✗ Error in spending analysis: {e}")
        import traceback
        logger.error(traceback.format_exc())

    logger.info("="*60)
    logger.info("SPENDING TRACKER - RUN COMPLETE")
    logger.info("="*60)


def main():
    """Main entry point with scheduler"""

    # Check for --now flag for immediate run
    if '--now' in sys.argv:
        logger.info("Running immediately (--now flag detected)")
        run_spending_analysis()
        return

    # Schedule daily check at 8am
    schedule.every().day.at("08:00").do(run_spending_analysis)

    logger.info("Spending Tracker scheduler started")
    logger.info("Will check for new CSVs daily at 8:00 AM")
    logger.info("Waiting for next scheduled run...")
    logger.info("(Use --now flag to run immediately)")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == '__main__':
    main()
