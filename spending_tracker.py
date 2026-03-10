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
    "Groceries",
    "Transport",
    "Travel",
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
        self.amount = amount  # Keep sign: positive = spending, negative = refund/cashback
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
            'is_subscription': self.is_subscription,
            'raw_data': self.raw_data
        }


class CSVParser:
    """Parse CSVs from different banks"""

    @staticmethod
    def detect_source(headers: List[str], filename: str) -> Optional[str]:
        """Detect bank based on CSV headers ONLY (filename used only for TD no-header case)"""
        if headers is None:
            headers = []

        headers_lower = [h.lower().strip() for h in headers]
        filename_lower = filename.lower()

        # TD special case: no headers, detect by filename
        if not headers and (filename_lower.startswith('accountactivit') or 'visa' in filename_lower):
            return 'td'

        # Use HEADERS ONLY for all other banks

        # Amex: Exactly Date, Date Processed, Description, Amount (activity*.csv files)
        # Check this FIRST before Rogers since some activity files might have similar headers
        if all(h in headers_lower for h in ['date', 'date processed', 'description', 'amount']):
            return 'amex'

        # Rogers: Has Merchant Name, Activity Type, Posted Date
        if 'merchant name' in headers_lower and 'activity type' in headers_lower and 'posted date' in headers_lower:
            return 'rogers'

        # Wealthsimple Credit Card: transaction_date, post_date, type, details, amount, currency
        if all(h in headers_lower for h in ['transaction_date', 'post_date', 'type', 'details', 'amount', 'currency']):
            return 'wealthsimple_cc'

        # Wealthsimple Chequing: date, transaction, description, amount, balance, currency
        if all(h in headers_lower for h in ['date', 'transaction', 'description', 'amount', 'balance', 'currency']):
            return 'wealthsimple'

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

                # Skip payments and transfers first
                if CSVParser._is_payment_or_transfer(description):
                    skipped += 1
                    continue

                # Skip positive amounts (income/deposits) - only track spending
                # Negative = spending for Wealthsimple
                if amount >= 0:
                    skipped += 1
                    continue

                # Convert negative (spending) to positive for storage
                transactions.append(Transaction(
                    date=date,
                    description=description,
                    amount=abs(amount),  # Convert negative to positive
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
        Positive = spending, Negative = refunds/cashback (kept as negative to reduce total)
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

                # Skip ONLY if it's a payment/transfer (not refunds/cashback)
                if CSVParser._is_payment_or_transfer(description):
                    skipped += 1
                    continue

                # Keep both positive (spending) and negative (refunds/cashback) amounts
                transactions.append(Transaction(
                    date=date,
                    description=description,
                    amount=amount,  # Keep sign: positive = spending, negative = refund
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
        Headers: Date (format: 07 Aug 2025), Date Processed, Description, Amount
        Positive = spending, Negative = refunds/cashback (kept as negative to reduce total)
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

                # Skip Amex payments
                desc_upper = description.upper()
                if 'PAYMENT RECEIVED' in desc_upper or 'PAYMENT THANK YOU' in desc_upper:
                    skipped += 1
                    continue

                # Skip other payments and transfers
                if CSVParser._is_payment_or_transfer(description):
                    skipped += 1
                    continue

                # Keep both positive (spending) and negative (refunds/cashback) amounts
                transactions.append(Transaction(
                    date=date,
                    description=description,
                    amount=amount,  # Keep sign: positive = spending, negative = refund
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
        Positive = spending, Negative = refunds/cashback (kept as negative to reduce total)
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

                # Skip ONLY if it's a payment/transfer (not refunds/cashback)
                if CSVParser._is_payment_or_transfer(merchant):
                    skipped += 1
                    continue

                # Keep both positive (spending) and negative (refunds/cashback) amounts
                transactions.append(Transaction(
                    date=date,
                    description=merchant,
                    amount=amount,  # Keep sign: positive = spending, negative = refund
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
        """Parse TD CSV format - handles malformed format with colons
        Format: 02/10/2026:01/27/2026, Amazon.ae:ROYAL BANK OF CANADA, 18.14:nan, Unnamed: 3:139.0, 18.14.1:0.0
        Actual transaction date is second part of first field (after colon)
        Description is both parts of second field joined
        Amount is in the "Unnamed: 3" field after splitting by colon
        Negative amount = spending
        """
        transactions = []
        skipped = 0

        for row in rows:
            try:
                if len(row) < 4:
                    continue

                # Split each field by colon to extract values
                # Field 0: "02/10/2026:01/27/2026" -> use second part "01/27/2026"
                # Field 1: "Amazon.ae:ROYAL BANK OF CANADA" -> join both parts
                # Field 3: "Unnamed: 3:139.0" -> use the value after "Unnamed: 3:"

                # Extract date (second part of first field after splitting by :)
                date_parts = row[0].split(':')
                if len(date_parts) < 2:
                    continue
                date_str = date_parts[1]

                # Extract description - use ONLY the second part after the colon
                # The first part (e.g., "Amazon.ae") is an export artifact, not the merchant
                desc_parts = row[1].split(':')
                if len(desc_parts) >= 2:
                    description = desc_parts[-1].strip()  # Use last part only
                else:
                    description = row[1].strip()

                # Extract amount from "Unnamed: 3:VALUE" field (row[3])
                if 'Unnamed: 3' in row[3]:
                    amount_str = row[3].split(':')[-1]  # get last part after splitting
                else:
                    amount_str = row[3]  # fallback

                if not all([date_str, description, amount_str]):
                    continue

                # Skip if amount is 'nan'
                if amount_str.strip().lower() == 'nan':
                    continue

                date = CSVParser._parse_date(date_str)
                if not date:
                    continue

                amount = CSVParser._parse_amount(amount_str)

                # Skip payments to the credit card
                if 'ROYAL BANK OF CANADA' in description.upper():
                    skipped += 1
                    continue

                if 'PAYMENT' in description.upper():
                    skipped += 1
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
                logger.error(f"Error parsing TD row: {e} | Row: {row}")
                continue

        return transactions, skipped

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Try multiple date formats"""
        date_formats = [
            '%d %b %Y',     # Amex format: 07 Aug 2025
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

        # Investment keywords (comprehensive list)
        investment_keywords = [
            # Direct investment terms
            'purchase of', 'trading fee', 'management fee',
            'withdrawal', 'int ', 'e_trfin', 'e_trfout',
            'div', 'buy', 'sell', 'dividend',
            # Asset types
            'bond', 'bonds', 'equity', 'equities', 'stock', 'stocks',
            'etf', 'index', 'fund', 'mutual fund', 'shares',
            # Specific funds/companies
            'vanguard', 'bmo', 'ishares', 'blackrock', 'fidelity',
            'corporate bond', 'aggregate bond', 'treasury',
            # Investment accounts
            'tfsa', 'rrsp', 'contribution', 'redemption'
        ]

        # Check payment keywords (case-insensitive)
        if any(keyword in desc_lower for keyword in payment_keywords):
            return True

        # Check investment keywords (case-insensitive)
        if any(keyword in desc_lower for keyword in investment_keywords):
            return True

        return False

    @staticmethod
    def _clean_merchant_name(description: str) -> str:
        """Extract clean merchant name with special case mappings"""
        # Special case mappings
        desc_upper = description.upper()

        # Rogers phone bill (Rogers ****1770 → Rogers Phone Bill)
        if 'ROGERS' in desc_upper and '****' in description:
            return 'Rogers Phone Bill'

        # DUUO insurance (DUUO BY COOPERATORS → Rent Insurance)
        if 'DUUO' in desc_upper and 'COOPERATORS' in desc_upper:
            return 'Rent Insurance'

        # General cleaning
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


def categorize_by_keywords(merchant: str, description: str) -> Optional[str]:
    """Fast keyword-based categorization - deterministic and reliable"""
    text = f"{merchant} {description}".upper()

    # STEP 1: GROCERIES
    grocery_keywords = [
        'COSTCO WHOLESALE', 'COSTCO W', 'NO FRILLS', 'NOFRILLS', 'FARM BOY', 'FARMBOY',
        'LOBLAWS', 'LOBLAW', 'METRO', 'SOBEYS', 'SOBEY', 'FOOD BASICS', 'FOODBASICS',
        'FRESHCO', 'FRESH CO', 'LONGOS', 'LONGO', 'FORTINOS', 'WALMART GROCERY',
        'WALMART SUPERCENTRE', 'SUPERSTORE', 'REAL CANADIAN SUPERSTORE', 'T&T SUPERMARKET',
        'WHOLE FOODS', 'INDEPENDENT GROCER', 'YOUR INDEPENDENT', 'VALU-MART', 'VALUMART',
        'ZEHRS', 'DOLLARAMA', 'SUPERMARKET', 'GROCERY STORE'
    ]
    # Exclude Costco Gas from groceries
    if 'COSTCO GAS' not in text and 'COSTCO FUEL' not in text:
        for keyword in grocery_keywords:
            if keyword in text:
                return 'Groceries'

    # STEP 2: TRAVEL (airlines, hotels, booking sites)
    travel_keywords = [
        'FLAIR', 'PORTER', 'PORTERAIR', 'AIR CANADA', 'AIRCANADA', 'WESTJET',
        'UNITED AIRLINES', 'UNITED AIR', 'DELTA AIRLINES', 'DELTA AIR',
        'AMERICAN AIRLINES', 'AA.COM', 'SOUTHWEST', 'ALLEGIANT', 'SPIRIT AIRLINES',
        'FRONTIER', 'BRITISH AIRWAYS', 'LUFTHANSA', 'KLM',
        'VIA RAIL', 'TRAIN', 'RAILWAY', 'GREYHOUND', 'MEGABUS',
        'CRUISE', 'CRUISE LINE', 'CARNIVAL', 'ROYAL CARIBBEAN',
        'EXPEDIA', 'BOOKING.COM', 'HOTELS.COM', 'AIRBNB',
        'MARRIOTT', 'HILTON', 'HYATT', 'HOLIDAY INN', 'RESORT',
        'ZENHOTELS', 'TRIVAGO', 'KAYAK', 'HOTWIRE',
        'TOURISM', 'TOUR OPERATOR', 'THEME PARK', 'ATTRACTION',
        'BRIGHTLINE'
    ]
    for keyword in travel_keywords:
        if keyword in text:
            return 'Travel'

    # STEP 3: TRANSPORT (ground transportation, gas, parking)
    transport_keywords = [
        'UBER', 'LYFT', 'BOLT', 'TAXI', 'CAB', 'BECK TAXI',
        'PARKING TICKET', 'PARKING METER', 'GREEN P', 'PARKING GARAGE',
        'TTC', 'GO TRANSIT', 'PRESTO', 'BUS PASS', 'TRANSIT PASS',
        'SHELL', 'ESSO', 'PETRO-CANADA', 'CHEVRON', 'MOBIL',
        'CANADIAN TIRE GAS', 'COSTCO GAS', 'COSTCO FUEL',
        'TESLA SUPERCHARGER', 'EV CHARGING', 'CHARGEPOINT',
        'CAR WASH', 'VEHICLE MAINTENANCE',
        'OIL CHANGE', 'TIRE', 'BRAKE', 'AUTOMOTIVE REPAIR',
        'REGISTRATION', 'LICENSE PLATE',
        'ZIPCAR', 'CAR2GO', 'ENTERPRISE RENT', 'SIXT', 'BUDGET RENT', 'HERTZ'
    ]
    # Also check for generic gas/fuel indicators
    if any(keyword in text for keyword in transport_keywords):
        return 'Transport'
    if ('GAS' in text or 'FUEL' in text or 'PETROL' in text) and 'STATION' in text:
        return 'Transport'

    # STEP 4: BILLS & UTILITIES
    bills_keywords = [
        'ROGERS', 'BELL CANADA', 'TELUS', 'FIDO', 'KOODO',
        'SPECTRUM', 'COMCAST', 'XFINITY', 'SHAW', 'VIDEOTRON',
        'ENBRIDGE', 'TORONTO HYDRO', 'HYDRO ONE', 'HYDRO QUEBEC',
        'ELECTRICITY', 'ELECTRIC COMPANY', 'WATER BILL', 'GARBAGE', 'WASTE MANAGEMENT',
        'MEMBERSHIP FEE', 'ANNUAL FEE', 'INSTALLMENT',
        'INSURANCE', 'COOPERATORS', 'DUUO', 'AFFIRM'
    ]
    for keyword in bills_keywords:
        if keyword in text:
            return 'Bills & Utilities'

    # STEP 5: HEALTH (exclude veterinary)
    if not any(vet_keyword in text for vet_keyword in ['VET', 'VETERINARY', 'ANIMAL']):
        health_keywords = [
            'PHARMACY', 'PHARMA', 'SHOPPERS DRUG MART', 'REXALL', 'CVS',
            'ORTHODONTIC', 'ORTHO', 'DENTAL', 'DENTIST',
            'MEDICAL', 'CLINIC', 'HOSPITAL', 'DR ', 'DOCTOR',
            'OPTOMETRY', 'OPTOMETRIST', 'OPHTHALMOLOGIST', 'VISION CARE', 'EYE CARE', 'LENSCRAFTERS',
            'THERAPIST', 'PSYCHOLOGIST', 'COUNSELOR', 'THERAPY',
            'PHYSICAL THERAPY', 'PHYSIOTHERAPY', 'PHYSIO',
            'CHIROPRACTOR', 'CHIRO', 'ACUPUNCTURE', 'ACUPUNCTURIST',
            'NUTRITIONIST', 'DIETITIAN', 'DIETICIAN',
            'LAB', 'LABORATORY', 'BLOODWORK', 'PATHOLOGY',
            'MASSAGE', 'STEP UP', 'EPPIX'
        ]
        for keyword in health_keywords:
            if keyword in text:
                return 'Health'

    # STEP 6: ENTERTAINMENT
    entertainment_keywords = [
        'NETFLIX', 'SPOTIFY', 'DISNEY', 'APPLE TV', 'AMAZON PRIME VIDEO',
        'HULU', 'HBOMAX', 'HBO MAX', 'PARAMOUNT', 'MAX STREAMING',
        'TWITCH', 'YOUTUBE PREMIUM', 'YOUTUBE MUSIC',
        'PLAYSTATION NETWORK', 'PSPLUS', 'XBOX LIVE', 'XBOX GAMEPASS', 'NINTENDO',
        'AUDIBLE', 'SCRIBD', 'KINDLE UNLIMITED',
        'HEADSPACE', 'CALM', 'MEDITOPIA',
        'PELOTON', 'BEACHBODY', 'FITBIT PREMIUM',
        'MIRVISH', 'CINEPLEX', 'LANDMARK CINEMA', 'GOODLIFE', 'LA FITNESS',
        'YMCA', 'GYM', 'THEATRE', 'THEATER', 'CONCERT', 'CLASSPASS', 'GROUPON',
        'TICKETMASTER', 'SEATGEEK', 'DICE.FM'
    ]
    for keyword in entertainment_keywords:
        if keyword in text:
            return 'Entertainment'

    # STEP 7: FOOD & DINING
    dining_keywords = [
        'RESTAURANT', 'BISTRO', 'CAFE', 'COFFEE', 'BAR', 'PUB',
        'STARBUCKS', 'TIM HORTONS', 'SECOND CUP', 'BALZAC',
        'MCDONALD', 'BURGER KING', 'WENDY', 'KFC', 'SUBWAY', 'A&W',
        'CHIPOTLE', 'QDOBA', 'TACO BELL',
        'PIZZA', 'SHAWARMA', 'RAMEN', 'SUSHI',
        'THAI', 'VIETNAMESE', 'CHINESE', 'JAPANESE', 'INDIAN',
        'STEAKHOUSE', 'DINER', 'PANCAKE HOUSE', 'BRUNCH',
        'BAKERY', 'PASTRY', 'JUICE BAR', 'SMOOTHIE',
        'UBEREATS', 'DOORDASH', 'SKIP THE DISHES', 'FOODORA', 'GRUBHUB'
    ]
    for keyword in dining_keywords:
        if keyword in text:
            return 'Food & Dining'

    # STEP 8: SHOPPING
    shopping_keywords = [
        'AMAZON.CA', 'AMAZON.COM', 'AMZN', 'BEST BUY', 'STAPLES', 'HOME DEPOT',
        'CANADIAN TIRE', 'WWW.CANADIANTIRE.CA', 'H&M', 'ZARA', 'WINNERS', 'MARSHALLS',
        'TARGET', 'WALMART', 'ALCANSIDE', 'TEMU.COM', 'TEMU',
        'SHOPIFY', 'ETSY', 'DEPOP', 'VINTED', 'POSHMARK',
        'IKEA', 'POTTERY BARN', 'WEST ELM', 'CRATE AND BARREL',
        'NIKE', 'ADIDAS', 'LULULEMON', 'ATHLETA', 'UNDER ARMOUR',
        'SHEIN', 'FASHION NOVA', 'FOREVER 21', 'UNIQLO',
        'SEPHORA', 'ULTA', 'BEAUTY COUNTER', 'MAKEUP',
        'APPLE STORE', 'MICROSOFT STORE',
        'AMERICAN EAGLE', 'BROWN\'S SHOES', 'CARTERS', 'WARBY PARKER'
    ]
    for keyword in shopping_keywords:
        if keyword in text:
            return 'Shopping'

    # No keyword match - return None to send to Claude
    return None


class ClaudeCategorizer:
    """Use Claude AI to categorize transactions"""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def categorize_transactions(self, transactions: List[Transaction]) -> List[Transaction]:
        """Hybrid categorization: keywords first, then Claude for unclear merchants"""
        if not transactions:
            return transactions

        # PHASE 1: Keyword-based categorization (fast, deterministic)
        print(f"\n{'='*80}")
        print(f"PHASE 1: KEYWORD CATEGORIZATION - Processing {len(transactions)} transactions")
        print(f"{'='*80}\n")
        logger.info(f"Starting keyword categorization for {len(transactions)} transactions")

        keyword_categorized = 0
        unclear_transactions = []

        for tx in transactions:
            category = categorize_by_keywords(tx.merchant, tx.description)
            if category:
                tx.category = category
                keyword_categorized += 1
            else:
                unclear_transactions.append(tx)

        print(f"✓ Keyword categorization complete:")
        print(f"  - {keyword_categorized} transactions categorized by keywords")
        print(f"  - {len(unclear_transactions)} unclear transactions need Claude AI")
        logger.info(f"Keyword categorization: {keyword_categorized} categorized, {len(unclear_transactions)} unclear")

        # PHASE 2: Claude AI for unclear transactions only
        if unclear_transactions:
            print(f"\n{'='*80}")
            print(f"PHASE 2: CLAUDE AI CATEGORIZATION - Processing {len(unclear_transactions)} unclear transactions")
            print(f"{'='*80}\n")
            logger.info(f"Starting Claude AI categorization for {len(unclear_transactions)} unclear transactions")

            # Split into batches of 50 to avoid rate limits
            BATCH_SIZE = 50
            total_unclear = len(unclear_transactions)

            for batch_start in range(0, total_unclear, BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, total_unclear)
                batch_transactions = unclear_transactions[batch_start:batch_end]

                print(f"\n{'='*60}")
                print(f"BATCH {batch_start//BATCH_SIZE + 1}: Processing {batch_start+1}-{batch_end} of {total_unclear} unclear transactions")
                print(f"{'='*60}\n")
                logger.info(f"Processing batch {batch_start//BATCH_SIZE + 1}: transactions {batch_start+1}-{batch_end}")

                # Build transaction list with original IDs
                tx_list = []
                for i, tx in enumerate(batch_transactions):
                    tx_list.append({
                        'id': i,  # Local batch ID
                        'merchant': tx.merchant,
                        'description': tx.description,
                        'amount': tx.amount
                    })

                # Try with detailed prompt first
                success = self._try_categorize(batch_transactions, tx_list, detailed=True)

                # If failed, retry with simpler prompt
                if not success:
                    print("\n" + "="*60)
                    print(f"RETRY BATCH {batch_start//BATCH_SIZE + 1}: First attempt failed, trying simpler prompt...")
                    print("="*60 + "\n")
                    logger.warning(f"Batch {batch_start//BATCH_SIZE + 1} categorization failed, retrying with simpler prompt")
                    success = self._try_categorize(batch_transactions, tx_list, detailed=False)

                # If still failed, assign all to Other
                if not success:
                    print("\n" + "="*60)
                    print(f"ERROR BATCH {batch_start//BATCH_SIZE + 1}: Both attempts failed, defaulting to 'Other'")
                    print("="*60 + "\n")
                    logger.error(f"Batch {batch_start//BATCH_SIZE + 1} categorization failed, defaulting to 'Other'")
                    for tx in batch_transactions:
                        if not tx.category:
                            tx.category = 'Other'
                            tx.is_subscription = False

            print(f"\n{'='*80}")
            print(f"PHASE 2 COMPLETE: Claude AI categorized {len(unclear_transactions)} transactions")
            print(f"{'='*80}\n")
        else:
            print(f"\n{'='*80}")
            print(f"✓ ALL TRANSACTIONS CATEGORIZED BY KEYWORDS - No Claude AI needed!")
            print(f"{'='*80}\n")

        print(f"\n{'='*80}")
        print(f"CATEGORIZATION COMPLETE:")
        print(f"  - Total transactions: {len(transactions)}")
        print(f"  - Keyword categorized: {keyword_categorized}")
        print(f"  - Claude AI categorized: {len(unclear_transactions)}")
        print(f"{'='*80}\n")
        logger.info(f"Categorization complete: {keyword_categorized} by keywords, {len(unclear_transactions)} by Claude AI")

        return transactions

    def _try_categorize(self, transactions: List[Transaction], tx_list: List[Dict], detailed: bool = True) -> bool:
        """Try to categorize transactions, return True if successful"""

        if detailed:
            prompt = f"""You are a financial categorization assistant. Categorize each transaction into EXACTLY ONE of these categories (use the exact spelling):

Groceries
Food & Dining
Transport
Travel
Bills & Utilities
Entertainment
Health
Shopping
Other

Transactions to categorize:
{json.dumps(tx_list, indent=2)}

IMPORTANT: Return ONLY a valid JSON object with this EXACT structure (no markdown, no other text):
{{
  "categorized": [
    {{"id": 0, "category": "Groceries", "is_subscription": false}},
    {{"id": 1, "category": "Transport", "is_subscription": false}}
  ]
}}

CATEGORIZATION RULES - CHECK IN THIS ORDER:

STEP 1: CHECK FOR GROCERIES (if merchant contains ANY of these keywords → Groceries):
- "COSTCO WHOLESALE", "COSTCO W", "COSTCO #" (but NOT "COSTCO GAS")
- "NO FRILLS", "NOFRILLS"
- "FARM BOY", "FARMBOY"
- "LOBLAWS", "LOBLAW"
- "METRO", "METRO ONTARIO"
- "SOBEYS", "SOBEY"
- "FOOD BASICS", "FOODBASICS"
- "FRESHCO", "FRESH CO"
- "LONGOS", "LONGO"
- "FORTINOS"
- "WALMART GROCERY", "WALMART SUPERCENTRE"
- "REAL CANADIAN SUPERSTORE", "SUPERSTORE"
- "T&T SUPERMARKET", "TNT SUPERMARKET"
- "WHOLE FOODS"
- "INDEPENDENT GROCER", "YOUR INDEPENDENT"
- "VALU-MART", "VALUMART"
- "ZEHRS", "DOLLARAMA"
- "SUPERMARKET", "GROCERY", "MARKET" (in name)

STEP 2: CHECK FOR TRAVEL (if merchant contains ANY of these keywords → Travel):
- Airlines: "FLAIR", "PORTER", "PORTERAIR", "AIR CANADA", "AIRCANADA", "WESTJET"
- US Airlines: "UNITED AIRLINES", "DELTA AIRLINES", "AMERICAN AIRLINES", "AA.COM", "SOUTHWEST", "ALLEGIANT", "SPIRIT AIRLINES", "FRONTIER"
- International Airlines: "BRITISH AIRWAYS", "LUFTHANSA", "KLM"
- Booking: "EXPEDIA", "BOOKING.COM", "HOTELS.COM", "AIRBNB"
- Hotels: "MARRIOTT", "HILTON", "HYATT", "HOLIDAY INN", "ZENHOTELS", "TRIVAGO", "KAYAK", "RESORT"
- Rail: "BRIGHTLINE" (Florida intercity rail), "VIA RAIL", "TRAIN", "RAILWAY"
- Bus: "GREYHOUND", "MEGABUS"
- Cruises: "CRUISE", "CRUISE LINE", "CARNIVAL", "ROYAL CARIBBEAN"
- Activities: "TOURISM", "TOUR OPERATOR", "THEME PARK", "ATTRACTION"
- Flight booking codes (numbers + letters like "6UBTM6", "DIR")

STEP 3: CHECK FOR TRANSPORT (if merchant contains ANY of these keywords → Transport):
- Rideshare: "UBER", "LYFT", "BOLT"
- Taxi: "TAXI", "CAB", "BECK TAXI"
- Parking: "PARKING TICKET", "PARKING METER", "GREEN P", "APCOA" (parking)
- Transit: "TTC", "GO TRANSIT", "PRESTO", "BUS PASS", "TRANSIT PASS"
- Gas: "SHELL", "ESSO", "PETRO-CANADA", "CANADIAN TIRE GAS", "COSTCO GAS"
- Gas stations: Anything with "GAS", "FUEL", "PETROL"
- EV Charging: "TESLA SUPERCHARGER", "EV CHARGING", "CHARGEPOINT"
- Rental: "ZIPCAR", "CAR2GO", "ENTERPRISE RENT", "SIXT", "BUDGET RENT", "HERTZ"
- Maintenance: "CAR WASH", "VEHICLE MAINTENANCE", "OIL CHANGE", "TIRE", "BRAKE", "AUTOMOTIVE REPAIR"
- Registration: "REGISTRATION", "LICENSE PLATE"

STEP 4: CHECK FOR BILLS & UTILITIES (if merchant contains ANY of these keywords → Bills & Utilities):
- Telecom: "ROGERS", "BELL CANADA", "TELUS", "FIDO", "KOODO", "SPECTRUM", "COMCAST", "XFINITY", "SHAW", "VIDEOTRON"
- Utilities: "ENBRIDGE", "TORONTO HYDRO", "HYDRO ONE", "ELECTRICITY", "ELECTRIC COMPANY", "WATER BILL", "GARBAGE", "WASTE MANAGEMENT"
- Fees: "MEMBERSHIP FEE", "ANNUAL FEE", "INSTALLMENT"
- Insurance: "INSURANCE", "COOPERATORS", "DUUO"
- Financing: "AFFIRM" (buy now pay later)
- Credit card fees with "FEE" in name

STEP 5: CHECK FOR HEALTH (if merchant contains ANY of these keywords → Health):
- Pharmacy: "PHARMACY", "PHARMA", "SHOPPERS DRUG MART", "REXALL", "CVS", "WALGREENS", "CHEMIST"
- Dental: "ORTHODONTIC", "ORTHO", "DENTAL", "DENTIST"
- Medical: "MEDICAL", "CLINIC", "HOSPITAL", "DR ", "DOCTOR"
- Vision: "OPTOMETRY", "OPTOMETRIST", "VISION CARE", "EYE CARE", "EYEGLASSES"
- Therapy: "MASSAGE", "STEP UP" (massage therapy), "PHYSICAL THERAPY", "PHYSIOTHERAPY", "PHYSIO"
- Specialists: "CHIROPRACTOR", "CHIRO", "ACUPUNCTURE", "ACUPUNCTURIST"
- Nutrition: "NUTRITIONIST", "DIETITIAN", "DIETICIAN"
- Labs: "LAB", "LABORATORY", "BLOODWORK", "PATHOLOGY"
- Mental Health: "THERAPIST", "PSYCHOLOGIST", "COUNSELOR", "THERAPY"
- Medication: "EPPIX"
- IMPORTANT: If "VET" or "VETERINARY" or "ANIMAL" → Other (NOT Health)

STEP 6: CHECK FOR ENTERTAINMENT (if merchant contains ANY of these keywords → Entertainment):
- Streaming: "NETFLIX", "SPOTIFY", "DISNEY", "HULU", "HBOMAX", "PARAMOUNT", "APPLE TV", "AMAZON PRIME VIDEO"
- Gaming: "TWITCH", "YOUTUBE PREMIUM", "PLAYSTATION", "XBOX", "NINTENDO"
- Audio/Books: "AUDIBLE", "SCRIBD", "KINDLE UNLIMITED"
- Wellness: "HEADSPACE", "CALM", "MEDITOPIA"
- Fitness: "PELOTON", "BEACHBODY", "FITBIT PREMIUM", "GOODLIFE", "LA FITNESS", "YMCA", "GYM", "CLASSPASS"
- Events/Venues: "MIRVISH", "CINEPLEX", "LANDMARK CINEMA", "THEATRE", "THEATER", "CONCERT", "GROUPON"
- Tickets: "TICKETMASTER", "SEATGEEK", "DICE.FM"

STEP 7: CHECK FOR FOOD & DINING (restaurants, cafes, fast food):
- General: "RESTAURANT", "BISTRO", "CAFE", "COFFEE", "BAR", "PUB", "DINER", "STEAKHOUSE", "BRUNCH"
- Coffee: "STARBUCKS", "TIM HORTONS", "SECOND CUP", "BALZAC"
- Fast Food: "MCDONALD", "BURGER KING", "WENDY", "KFC", "SUBWAY", "A&W", "CHIPOTLE", "QDOBA", "TACO BELL"
- Cuisine: "PIZZA", "SHAWARMA", "RAMEN", "SUSHI", "THAI", "VIETNAMESE", "CHINESE", "JAPANESE", "INDIAN"
- Specialty: "BAKERY", "PASTRY", "JUICE BAR", "SMOOTHIE", "PANCAKE HOUSE"
- Delivery: "UBEREATS", "DOORDASH", "SKIP THE DISHES", "FOODORA", "GRUBHUB"
- Local: "BIFF", "FOXLEY", "MONKEY BUSINESS"

STEP 8: CHECK FOR SHOPPING (retail, Amazon, general stores):
- Online: "AMAZON.CA", "AMAZON.COM", "AMZN", "SHOPIFY", "ETSY", "DEPOP", "VINTED", "POSHMARK"
- Electronics: "BEST BUY", "APPLE STORE", "MICROSOFT STORE"
- Home: "HOME DEPOT", "IKEA", "POTTERY BARN", "WEST ELM", "CRATE AND BARREL"
- Department: "CANADIAN TIRE", "STAPLES", "TARGET", "WALMART" (not grocery)
- Fashion: "H&M", "ZARA", "WINNERS", "MARSHALLS", "NIKE", "ADIDAS", "LULULEMON", "ATHLETA", "UNDER ARMOUR"
- Fast Fashion: "SHEIN", "FASHION NOVA", "FOREVER 21", "UNIQLO"
- Beauty: "SEPHORA", "ULTA", "BEAUTY COUNTER", "MAKEUP"
- Accessories: "ALCANSIDE" (phone cases), "AMERICAN EAGLE", "BROWN'S SHOES", "CARTERS", "WARBY PARKER"
- Other: "TEMU.COM", "TEMU"
- General retail stores

STEP 9: OTHER (everything else):
- Professional services, veterinary care, pet services, unclear merchants
- Anything that doesn't match above patterns

IMPORTANT:
- Always check keywords in ORDER from Step 1 to Step 9
- First match wins
- Case insensitive matching
- "COSTCO WHOLESALE" is Groceries, "COSTCO GAS" is Transport
- Airlines/flights are ALWAYS Travel, never Transport
- Veterinary is ALWAYS Other, never Health

Note: Do NOT mark is_subscription field - subscriptions are detected automatically by pattern analysis

Return ONLY the JSON object:"""
        else:
            # Simpler prompt for retry
            prompt = f"""Categorize these transactions. Return ONLY valid JSON, no other text.

Categories: Groceries, Food & Dining, Transport, Travel, Bills & Utilities, Entertainment, Health, Shopping, Other

Transactions: {json.dumps(tx_list, indent=2)}

Return this exact format:
{{"categorized": [{{"id": 0, "category": "Groceries", "is_subscription": false}}]}}"""

        try:
            print("\n" + "="*80)
            print("CLAUDE CATEGORIZATION REQUEST")
            print("="*80)
            print(f"Transactions to categorize: {len(transactions)}")
            print(f"Using {'DETAILED' if detailed else 'SIMPLE'} prompt")
            print(f"\nFirst 3 transactions:")
            for tx in tx_list[:3]:
                print(f"  - {tx}")
            print("="*80 + "\n")

            logger.info(f"Sending categorization request to Claude (detailed={detailed})")

            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text

            print("\n" + "="*80)
            print("CLAUDE RAW RESPONSE")
            print("="*80)
            print(response_text)
            print("="*80 + "\n")

            logger.info(f"Claude response received ({len(response_text)} chars)")

            # Try multiple JSON extraction methods
            result = None

            # Method 1: Direct JSON parse (if response is pure JSON)
            try:
                result = json.loads(response_text.strip())
                print("✓ Parsed JSON directly")
            except json.JSONDecodeError:
                pass

            # Method 2: Extract JSON from markdown code blocks
            if not result:
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group(1))
                        print("✓ Extracted JSON from markdown code block")
                    except json.JSONDecodeError:
                        pass

            # Method 3: Find any JSON object in the response
            if not result:
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group())
                        print("✓ Extracted JSON from response text")
                    except json.JSONDecodeError:
                        pass

            if result and 'categorized' in result:
                categorized = result.get('categorized', [])

                print(f"\n✓ Successfully parsed {len(categorized)} categorizations")
                print(f"\nFirst 5 categorizations:")
                for item in categorized[:5]:
                    print(f"  ID {item.get('id')}: {item.get('category')} (subscription: {item.get('is_subscription')})")
                print()

                # Apply categorizations
                successful_assignments = 0
                for item in categorized:
                    tx_id = item.get('id')
                    if tx_id is not None and tx_id < len(transactions):
                        category = item.get('category', 'Other')

                        # Validate category
                        if category not in CATEGORIES:
                            print(f"⚠ Invalid category '{category}' for ID {tx_id}, using 'Other'")
                            logger.warning(f"Invalid category '{category}' from Claude, using 'Other'")
                            category = 'Other'

                        transactions[tx_id].category = category
                        transactions[tx_id].is_subscription = item.get('is_subscription', False)
                        successful_assignments += 1

                print(f"✓ Applied {successful_assignments}/{len(transactions)} categorizations\n")
                logger.info(f"Successfully applied {successful_assignments} categorizations")
                return True
            else:
                print("✗ Could not find 'categorized' key in JSON response")
                logger.error("Could not find 'categorized' key in parsed JSON")
                return False

        except Exception as e:
            print(f"\n✗ ERROR during categorization: {e}\n")
            logger.error(f"Error during categorization attempt: {e}")
            import traceback
            traceback.print_exc()
            logger.error(traceback.format_exc())
            return False


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
            'total_spent': sum(tx.amount for tx in transactions if tx.amount > 0),
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


def get_friendly_source_name(source: str) -> str:
    """Convert internal source codes to friendly display names"""
    source_mapping = {
        'amex': 'American Express',
        'rogers': 'Rogers Mastercard',
        'wealthsimple_cc': 'Wealthsimple Credit Card',
        'wealthsimple': 'Wealthsimple Chequing',
        'td': 'TD Bank'
    }
    return source_mapping.get(source, source)


def normalize_merchant_name(merchant: str) -> str:
    """Normalize merchant name for fuzzy matching"""
    # Remove common patterns
    normalized = re.sub(r'\*+\d+', '', merchant)  # Remove ****1770
    normalized = re.sub(r'#\d+', '', normalized)   # Remove #123
    normalized = re.sub(r'\d{2}/\d{2}', '', normalized)  # Remove dates
    normalized = re.sub(r'\s+', ' ', normalized).strip().upper()
    # Return normalized or original (uppercase) if normalization resulted in empty string
    return normalized[:30] if normalized.strip() else merchant.upper()[:30]


def clean_merchant_for_display(merchant: str) -> str:
    """Clean merchant name for display - remove location codes, numbers, extra info"""
    clean = re.sub(r'#\d+', '', merchant)  # Remove #43, #524
    clean = re.sub(r'\s+W\d+', '', clean)  # Remove trailing " W524" patterns only
    clean = re.sub(r'\*+\d+', '', clean)  # Remove ****1770
    clean = re.sub(r'\d{2}/\d{2}', '', clean)  # Remove dates
    clean = re.sub(r'\s+[A-Z]{2}$', '', clean)  # Remove trailing state codes
    clean = re.sub(r'\s{2,}', ' ', clean).strip()  # Clean multiple spaces
    return clean[:50]


def calculate_spending_insights(transactions: List[Transaction]) -> Dict[str, Any]:
    """Calculate spending velocity, patterns, and insights"""
    if not transactions:
        return {
            'avg_per_day': 0, 'highest_day': (None, 0), 'weekend_pct': 0,
            'top_by_visits': [], 'foreign_total': 0, 'foreign_count': 0,
            'total_refunds': 0, 'refund_details': []
        }

    positive_txs = [tx for tx in transactions if tx.amount > 0]
    negative_txs = [tx for tx in transactions if tx.amount < 0]
    total_spending = sum(tx.amount for tx in positive_txs)
    total_refunds = abs(sum(tx.amount for tx in negative_txs))

    # Daily average
    dates = [tx.date for tx in transactions]
    if dates:
        days_in_month = (max(dates) - min(dates)).days + 1
        avg_per_day = total_spending / days_in_month if days_in_month > 0 else 0
    else:
        avg_per_day = 0

    # Highest spending day
    daily_spending = defaultdict(float)
    for tx in positive_txs:
        daily_spending[tx.date.date()] += tx.amount
    highest_day = max(daily_spending.items(), key=lambda x: x[1]) if daily_spending else (None, 0)

    # Weekend vs weekday
    weekend_spending = sum(tx.amount for tx in positive_txs if tx.date.weekday() >= 5)
    weekend_pct = (weekend_spending / total_spending * 100) if total_spending > 0 else 0

    # Most frequent merchants
    merchant_visits = defaultdict(lambda: {'count': 0, 'amount': 0.0})
    for tx in positive_txs:
        clean_name = clean_merchant_for_display(tx.merchant)
        merchant_visits[clean_name]['count'] += 1
        merchant_visits[clean_name]['amount'] += tx.amount
    top_by_visits = sorted(merchant_visits.items(), key=lambda x: x[1]['count'], reverse=True)[:5]

    # Foreign transactions - check merchant, description, and raw country data
    foreign_countries = ['USA', 'IRL', 'ARE', 'MEX', 'GBR', 'DEU', 'FRA', 'ESP', 'ITA', 'JPN', 'AUS']
    foreign_keywords = ['USD', 'EUR', 'GBP', 'MXN', 'AED', 'IRELAND', 'MEXICO', 'UAE', 'UK', 'DUBAI', 'FLORIDA',
                       'MIAMI', 'NAPLES', 'FORT LAUDERDA', 'WILTON MANORS']

    def is_foreign(tx):
        # Rogers Mastercard: check Merchant Country Code field directly
        country_code = tx.raw_data.get('Merchant Country Code', '').upper().strip()
        if country_code and country_code not in ['CAN', '']:
            return True

        # Rogers Mastercard: check Merchant City for known foreign cities
        merchant_city = tx.raw_data.get('Merchant City', '').upper()
        foreign_cities = [
            'MIAMI', 'MIAMI BEACH', 'FORT LAUDERDA', 'FT LAUDERDALE',
            'NAPLES', 'WILTON MANORS', 'SAN FRANCISCO', 'NEW YORK',
            'DUBAI', 'ABU DHABI', 'ABUDHABI', 'CANCUN', 'CIUDAD DE MEX',
            'ISLA MUJERES', 'BENITO JUAREZ', 'ALAJUELA', 'LIMASSOL',
            'EDMONTON INTE', 'PHOENIX', 'CHICAGO', 'AMSTERDAM', 'GIBRALTAR',
            'PULLACH', 'DUBLIN',
        ]
        if any(city in merchant_city for city in foreign_cities):
            return True

        # Wealthsimple CC and Amex: no country code available, use merchant name patterns
        text = (tx.description + ' ' + tx.merchant).upper()
        foreign_indicators = [
            # Mexico
            'MERPAGO', 'OXXO', 'SUPERCHE', 'CANCUN', 'CIUDAD DE MEX',
            'ISLA MUJERES', 'ISLA MUJER', 'BENITO JUAREZ',
            'CHICHIS AND CHARLIES', 'REST MONKEY BUSINESS',
            'REST MEXTREME', 'REST PALAPITA', 'MANGO CAFE',
            'ABARROTES', 'ESPIRAL', 'TICKET TOURS MXN',
            'DLO*DIDI', 'D LOCAL*DIDI', 'SELINA CANCUN',
            'PAYPAL *CANCUNSCUBA', 'HERTZ WAL MART CANCUN',
            # International data SIM
            'GIGSKY',
            # Middle East
            'DUBAI', 'ABU DHABI', 'ABUDHABI', 'TALABAT', 'QLUB',
            'CPAY-NOW-AED', 'TRYANO', 'AJMAL', 'ALMANDOOS',
            'ARABIAN HOUSE', 'ADNOC', 'FIVE HOTEL',
            'AURA SKYPOOL', 'PULL AND BEAR', 'SUPERCARE PHARMACY',
            'GEANT', 'ZARA ABU DHABI',
            # USA locations (for Amex which has no country code)
            'MIAMI', 'MIAMI BEACH', 'FORT LAUDERDA', 'WILTON MANORS',
            'NAPLES FL', 'TST* SHANE', 'CHELSEA HOTEL',
            'ROSETTA BAKERY', 'CASABLANCA CAFE', 'LSU CAVALIER',
            'DRYNK BAR', 'TST*EAGLE BAR', 'TST*HUNTERS',
            'BAILEYS LIQUORS', 'EJS BAYFRONT', 'FOUR SEASONS SUNSET',
            'BRIGHTLINE', 'LAS OLAS', 'MY TROPX', 'SEA SIDE',
            'ROSA SKY', 'NICKS PIZZA', 'SUGAR',
            'CVS/PHARMACY', 'GELATO', 'TST*OSTERIA TULIA',
            'WESTIN BEACH', 'CLUB FT LAUDERDALE', 'GROUPON',
            'GB UNIVERSAL', 'HELLOWISP', 'LYFT',
            # Costa Rica
            'ALAJUELA', 'BUDGET RENT A CAR',
            # Europe
            'SOLIHULL', 'AMSTERDAM', 'GIBRALTAR', 'PULLACH', 'DUBLIN',
            'CARROLLS IRISH GIFTS', 'VIVA*OCTOPUSSYS', 'WORKMANS DUBLIN',
            # Amazon Dubai
            'AMAZON (MARKET PLACE-EC',
        ]
        return any(indicator in text for indicator in foreign_indicators)

    foreign_txs = [tx for tx in positive_txs if is_foreign(tx)]
    foreign_total = sum(tx.amount for tx in foreign_txs)

    # Refund details
    refund_details = [
        {'merchant': clean_merchant_for_display(tx.merchant), 'amount': abs(tx.amount)}
        for tx in sorted(negative_txs, key=lambda x: x.amount)[:5]
    ]

    return {
        'avg_per_day': avg_per_day, 'highest_day': highest_day, 'weekend_pct': weekend_pct,
        'top_by_visits': top_by_visits, 'foreign_total': foreign_total, 'foreign_count': len(foreign_txs),
        'total_refunds': total_refunds, 'refund_details': refund_details
    }


def detect_pattern_subscriptions(year: int, month: int, current_month_txs: List[Transaction] = None) -> List[Dict[str, Any]]:
    """Detect subscriptions using pattern-based approach across historical data

    Criteria:
    - Merchant appears 3+ times in consecutive months
    - Amounts within 20% variation
    - Intervals of 27-36 days
    - Credit card purchases only (not bank debits/payments)

    Args:
        year: Current year
        month: Current month
        current_month_txs: Optional list of current month's transactions (not yet in history)
    """
    history = DataStore.load_history()

    # Collect all transactions from last 6 months
    all_transactions = []
    for i in range(6):
        month_offset = month - i
        year_offset = year
        while month_offset <= 0:
            month_offset += 12
            year_offset -= 1

        month_key = f"{year_offset}-{month_offset:02d}"
        if month_key in history:
            month_data = history[month_key]
            # Use actual individual transaction dates from stored history
            for tx_dict in month_data.get('transactions', []):
                all_transactions.append({
                    'merchant': tx_dict['merchant'],
                    'amount': tx_dict['amount'],
                    'date': datetime.fromisoformat(tx_dict['date'])
                })

    # Add current month's transactions if provided (not yet in history)
    if current_month_txs:
        for tx in current_month_txs:
            if tx.amount > 0:  # Only include positive amounts (spending)
                all_transactions.append({
                    'merchant': tx.merchant,
                    'amount': tx.amount,
                    'date': tx.date
                })

    # Deduplicate transactions (same transaction can appear in multiple months if CSV files overlap)
    seen_tx = set()
    deduped_all = []
    for tx in all_transactions:
        tx_key = (tx['date'].date(), tx['merchant'][:25].upper().strip(), round(tx['amount'], 2))
        if tx_key not in seen_tx:
            seen_tx.add(tx_key)
            deduped_all.append(tx)
    all_transactions = deduped_all

    # Group by normalized merchant name
    merchant_groups = defaultdict(list)
    for tx in all_transactions:
        normalized = normalize_merchant_name(tx['merchant'])
        if normalized:
            merchant_groups[normalized].append(tx)

    # Detect subscription patterns
    subscriptions = []

    for normalized_merchant, txs in merchant_groups.items():
        # Debug logging for Spotify
        if 'SPOTIFY' in normalized_merchant.upper():
            logger.info(f"DEBUG: Found Spotify merchant: {normalized_merchant}, {len(txs)} transactions")
            for tx in txs:
                logger.info(f"  - {tx['date'].date()}: ${tx['amount']:.2f}")

        # Require 3+ occurrences to reduce false positives
        if len(txs) < 3:
            if 'SPOTIFY' in normalized_merchant.upper():
                logger.info(f"DEBUG: Spotify skipped - only {len(txs)} transactions (need 3+)")
            continue

        # Skip payment/cashback/refunds (ENHANCED filtering)
        skip_keywords = [
            'cashback', 'remises', 'rebate', 'refund', 'credit', 'return',
            'reimbursement', 'payment thank you', 'payment received',
            'pymt', 'pmt', 'amex cards', 'rogrs bnk mc'
        ]
        if any(keyword in normalized_merchant.lower() for keyword in skip_keywords):
            continue

        # Sort by date
        txs_sorted = sorted(txs, key=lambda x: x['date'])

        # FILTER OUT NEGATIVE AMOUNTS (refunds/cashback)
        txs_sorted = [tx for tx in txs_sorted if tx['amount'] > 0]

        if len(txs_sorted) < 3:  # Require 3+ positive charges to avoid false positives
            continue

        # Check for consistent amount (allow small variation for taxes/fees)
        amounts_rounded = [round(tx['amount'], 2) for tx in txs_sorted]
        avg_amount = sum(amounts_rounded) / len(amounts_rounded)

        # Allow 20% variation to account for taxes, exchange rates, small plan changes
        max_variation = avg_amount * 0.20
        amount_range = max(amounts_rounded) - min(amounts_rounded)

        # If variation is too large, skip (not a subscription)
        if amount_range > max_variation:
            if 'SPOTIFY' in normalized_merchant.upper():
                logger.info(f"DEBUG: Spotify skipped - amount variation ${amount_range:.2f} > ${max_variation:.2f}")
            continue

        # Check if intervals are 27-36 days (approximately monthly)
        intervals = []
        for i in range(1, len(txs_sorted)):
            days_diff = (txs_sorted[i]['date'] - txs_sorted[i-1]['date']).days
            intervals.append(days_diff)

        if 'SPOTIFY' in normalized_merchant.upper():
            logger.info(f"DEBUG: Spotify intervals: {intervals}")

        # Check if intervals are monthly (27-36 days, expanded for February edge cases)
        if intervals and all(27 <= interval <= 36 for interval in intervals):
            subscriptions.append({
                'merchant': txs_sorted[0]['merchant'],
                'normalized': normalized_merchant,
                'avg_amount': avg_amount,
                'occurrences': len(txs_sorted),
                'annual_cost': avg_amount * 12
            })
            if 'SPOTIFY' in normalized_merchant.upper():
                logger.info(f"DEBUG: ✓ Spotify DETECTED as subscription!")
        else:
            if 'SPOTIFY' in normalized_merchant.upper():
                bad_intervals = [i for i in intervals if not (27 <= i <= 36)]
                logger.info(f"DEBUG: Spotify skipped - intervals out of range: {bad_intervals}")

    # Sort by average amount descending
    subscriptions.sort(key=lambda x: x['avg_amount'], reverse=True)

    return subscriptions


def generate_html_report(year: int, month: int, transactions: List[Transaction],
                         data_quality: Dict[str, Any] = None) -> str:
    """Generate email-compatible HTML report using only tables and inline styles"""

    total_spent = sum(tx.amount for tx in transactions if tx.amount > 0)
    transaction_count = len(transactions)

    # Category totals: only include positive amounts (spending), exclude refunds/cashback
    category_totals = defaultdict(float)
    for tx in transactions:
        if tx.amount > 0:  # Only count spending, not refunds
            category_totals[tx.category or 'Other'] += tx.amount

    sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)

    # Merchant totals: only include positive amounts, use cleaned names
    merchant_totals = defaultdict(lambda: {'amount': 0.0, 'count': 0})
    for tx in transactions:
        if tx.amount > 0:  # Only count spending, not refunds
            clean_name = clean_merchant_for_display(tx.merchant)
            merchant_totals[clean_name]['amount'] += tx.amount
            merchant_totals[clean_name]['count'] += 1

    top_merchants = sorted(merchant_totals.items(), key=lambda x: x[1]['amount'], reverse=True)[:10]

    # Use pattern-based subscription detection (pass current month's transactions)
    subscriptions = detect_pattern_subscriptions(year, month, transactions)
    # Only sum positive subscription amounts
    subscription_total = sum(sub['avg_amount'] for sub in subscriptions if sub['avg_amount'] > 0)

    # Calculate spending insights (velocity, patterns, refunds, foreign)
    insights = calculate_spending_insights(transactions)

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

    # Calculate YTD: sum only months from January up to current month
    history = DataStore.load_history()
    current_key = f"{year}-{month:02d}"
    ytd_total = sum(
        data['total_spent']
        for key, data in history.items()
        if key.startswith(str(year)) and int(key.split('-')[1]) <= month
    )
    if current_key not in history:
        ytd_total += total_spent

    month_name = datetime(year, month, 1).strftime('%B %Y').upper()

    # Category color mapping - premium palette
    category_colors = {
        'Groceries': '#4CAF50',
        'Food & Dining': '#FF6B35',
        'Transport': '#4A90E2',
        'Travel': '#1ABC9C',
        'Health': '#50C878',
        'Shopping': '#9B59B6',
        'Entertainment': '#FF69B4',
        'Bills & Utilities': '#F39C12',
        'Other': '#95A5A6'
    }

    # Start building HTML with table-based layout
    html = f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>Spending Report - {month_name}</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; background-color: #f4f4f4;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f4f4f4;">
        <tr>
            <td align="center" style="padding: 40px 20px;">

                <!-- Main Container -->
                <table border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff;">

                    <!-- Header -->
                    <tr>
                        <td align="center" style="background-color: #667eea; padding: 40px 30px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td align="center" style="font-size: 11px; font-weight: bold; letter-spacing: 2px; text-transform: uppercase; color: #ffffff; padding-bottom: 15px;">
                                        {month_name}
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="font-size: 48px; font-weight: bold; color: #ffffff; padding-bottom: 10px; line-height: 1;">
                                        ${total_spent:,.2f}
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="font-size: 13px; color: #ffffff;">
                                        Total Spending
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Stats Grid -->
                    <tr>
                        <td style="padding: 30px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td width="48%" style="background-color: #f8f9fa; padding: 20px;" align="center">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                            <tr>
                                                <td align="center" style="font-size: 10px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; color: #6c757d; padding-bottom: 10px;">
                                                    YEAR TO DATE
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="font-size: 24px; font-weight: bold; color: #2d3748;">
                                                    ${ytd_total:,.2f}
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="4%"></td>
                                    <td width="48%" style="background-color: #f8f9fa; padding: 20px;" align="center">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                            <tr>
                                                <td align="center" style="font-size: 10px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; color: #6c757d; padding-bottom: 10px;">
                                                    TRANSACTIONS
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="font-size: 24px; font-weight: bold; color: #2d3748;">
                                                    {transaction_count}
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    # Add MoM comparison if available
    if mom_change is not None:
        mom_bg_color = "#fef2f2" if mom_change > 0 else "#f0fdf4"
        mom_border_color = "#dc3545" if mom_change > 0 else "#28a745"
        mom_text_color = "#dc3545" if mom_change > 0 else "#28a745"
        mom_arrow = "&#8593;" if mom_change > 0 else "&#8595;"
        mom_label = "more than last month" if mom_change > 0 else "less than last month"

        html += f"""
                    <!-- Month over Month -->
                    <tr>
                        <td style="padding: 0 30px 30px 30px;">
                            <table border="0" cellpadding="20" cellspacing="0" width="100%" style="background-color: {mom_bg_color}; border-left: 4px solid {mom_border_color};">
                                <tr>
                                    <td width="70%" style="vertical-align: middle;">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td style="font-size: 13px; font-weight: bold; color: #495057; padding-bottom: 4px;">
                                                    vs Last Month
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="font-size: 16px; font-weight: bold; color: #1a1d1f;">
                                                    {mom_arrow} ${abs(mom_change):,.2f} {mom_label}
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="30%" align="right" style="vertical-align: middle; font-size: 24px; font-weight: bold; color: {mom_text_color};">
                                        {mom_percent:+.1f}%
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    # Categories section
    html += """
                    <!-- Spending by Category -->
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="font-size: 11px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; color: #6c757d; padding-bottom: 20px; border-bottom: 2px solid #e9ecef;">
                                        SPENDING BY CATEGORY
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    for category, amount in sorted_categories:
        percentage = (amount / total_spent * 100) if total_spent > 0 else 0
        color = category_colors.get(category, '#95A5A6')
        bar_width = int(percentage)

        html += f"""
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table border="0" cellpadding="12" cellspacing="0" width="100%" style="background-color: #f8f9fa; border-left: 4px solid {color};">
                                <tr>
                                    <td width="60%" style="vertical-align: top;">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td style="font-size: 15px; font-weight: bold; color: #2d3748; padding-bottom: 6px;">
                                                    {category}
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="font-size: 12px; color: #718096;">
                                                    {percentage:.1f}% of total spending
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="40%" align="right" style="vertical-align: top; font-size: 20px; font-weight: bold; color: {color};">
                                        ${amount:,.2f}
                                    </td>
                                </tr>
                                <tr>
                                    <td colspan="2" style="padding-top: 8px;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #e9ecef; height: 6px;">
                                            <tr>
                                                <td width="{bar_width}%" style="background-color: {color}; height: 6px;"></td>
                                                <td></td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    # Subscriptions section
    if subscriptions:
        html += f"""
                    <!-- Subscriptions -->
                    <tr>
                        <td style="padding: 20px 30px 20px 30px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="font-size: 11px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; color: #6c757d; padding-bottom: 20px; border-bottom: 2px solid #e9ecef;">
                                        RECURRING SUBSCRIPTIONS
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table border="0" cellpadding="20" cellspacing="0" width="100%" style="background-color: #f8f9fa;">
                                <tr>
                                    <td width="70%" style="font-size: 15px; font-weight: bold; color: #2d3748;">
                                        {len(subscriptions)} Active Subscriptions
                                    </td>
                                    <td width="30%" align="right" style="font-size: 14px; font-weight: bold; color: #667eea;">
                                        ${subscription_total:,.2f}/month
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

        for sub in subscriptions:
            monthly_amt = sub['avg_amount']
            annual_amt = sub['annual_cost']
            merchant = clean_merchant_for_display(sub['merchant'])

            html += f"""
                    <tr>
                        <td style="padding: 0 30px 12px 30px;">
                            <table border="0" cellpadding="12" cellspacing="0" width="100%" style="background-color: #ffffff; border: 1px solid #e9ecef;">
                                <tr>
                                    <td width="60%" style="vertical-align: top;">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td style="font-size: 15px; font-weight: bold; color: #1a1d1f; padding-bottom: 4px;">
                                                    {merchant}
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="font-size: 13px; color: #495057;">
                                                    {sub['occurrences']} charges detected
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="40%" align="right" style="vertical-align: top;">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td align="right" style="font-size: 18px; font-weight: bold; color: #1a1d1f; padding-bottom: 4px;">
                                                    ${monthly_amt:,.2f}
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="right" style="font-size: 12px; color: #495057;">
                                                    ${annual_amt:,.2f}/year
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    # Returns & Refunds section
    if insights['total_refunds'] > 0:
        html += f"""
                    <!-- Refunds -->
                    <tr>
                        <td style="padding: 20px 30px 20px 30px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="font-size: 11px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; color: #6c757d; padding-bottom: 20px; border-bottom: 2px solid #e9ecef;">
                                        RETURNS &amp; REFUNDS
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table border="0" cellpadding="20" cellspacing="0" width="100%" style="background-color: #f0fdf4; border-left: 4px solid #10b981;">
                                <tr>
                                    <td width="60%" style="font-size: 15px; font-weight: bold; color: #1a1d1f;">
                                        Total Refunded
                                    </td>
                                    <td width="40%" align="right" style="font-size: 24px; font-weight: bold; color: #10b981;">
                                        ${insights['total_refunds']:,.2f}
                                    </td>
                                </tr>"""

        if insights['refund_details']:
            html += """
                                <tr>
                                    <td colspan="2" style="padding-top: 16px; border-top: 1px solid #d1fae5;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                            <tr>
                                                <td colspan="2" style="font-size: 13px; font-weight: bold; color: #495057; padding-bottom: 12px;">
                                                    Top Refunds
                                                </td>
                                            </tr>"""

            for refund in insights['refund_details']:
                html += f"""
                                            <tr>
                                                <td width="70%" style="font-size: 14px; color: #1a1d1f; padding: 8px 0; border-bottom: 1px solid #d1fae5;">
                                                    {refund['merchant']}
                                                </td>
                                                <td width="30%" align="right" style="font-size: 14px; font-weight: bold; color: #10b981; padding: 8px 0; border-bottom: 1px solid #d1fae5;">
                                                    ${refund['amount']:,.2f}
                                                </td>
                                            </tr>"""

            html += """
                                        </table>
                                    </td>
                                </tr>"""

        html += """
                            </table>
                        </td>
                    </tr>"""

    # Foreign Spending section
    if insights['foreign_count'] > 0:
        html += f"""
                    <!-- Foreign Spending -->
                    <tr>
                        <td style="padding: 20px 30px 20px 30px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="font-size: 11px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; color: #6c757d; padding-bottom: 20px; border-bottom: 2px solid #e9ecef;">
                                        FOREIGN SPENDING
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table border="0" cellpadding="20" cellspacing="0" width="100%" style="background-color: #eef2ff; border-left: 4px solid #6366f1;">
                                <tr>
                                    <td width="60%" style="vertical-align: top;">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td style="font-size: 15px; font-weight: bold; color: #1a1d1f; padding-bottom: 6px;">
                                                    International Transactions
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="font-size: 13px; color: #495057;">
                                                    {insights['foreign_count']} foreign transactions detected
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="40%" align="right" style="vertical-align: top; font-size: 24px; font-weight: bold; color: #6366f1;">
                                        ${insights['foreign_total']:,.2f}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    # Spending Patterns section
    html += f"""
                    <!-- Spending Patterns -->
                    <tr>
                        <td style="padding: 20px 30px 20px 30px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="font-size: 11px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; color: #6c757d; padding-bottom: 20px; border-bottom: 2px solid #e9ecef;">
                                        SPENDING PATTERNS
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 0 30px 20px 30px;">
                            <table border="0" cellpadding="20" cellspacing="0" width="100%" style="background-color: #f8f9fa;">
                                <tr>
                                    <td width="33%" align="center" style="vertical-align: top;">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td align="center" style="font-size: 13px; font-weight: bold; color: #495057; padding-bottom: 8px;">
                                                    Average Per Day
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="font-size: 28px; font-weight: bold; color: #1a1d1f;">
                                                    ${insights['avg_per_day']:,.2f}
                                                </td>
                                            </tr>
                                        </table>
                                    </td>"""

    if insights['highest_day'][0]:
        html += f"""
                                    <td width="33%" align="center" style="vertical-align: top;">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td align="center" style="font-size: 13px; font-weight: bold; color: #495057; padding-bottom: 8px;">
                                                    Highest Day
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="font-size: 28px; font-weight: bold; color: #ef4444;">
                                                    ${insights['highest_day'][1]:,.2f}
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="font-size: 12px; color: #495057; padding-top: 4px;">
                                                    {insights['highest_day'][0].strftime('%b %d')}
                                                </td>
                                            </tr>
                                        </table>
                                    </td>"""

    html += f"""
                                    <td width="33%" align="center" style="vertical-align: top;">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td align="center" style="font-size: 13px; font-weight: bold; color: #495057; padding-bottom: 8px;">
                                                    Weekend Spending
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="font-size: 28px; font-weight: bold; color: #667eea;">
                                                    {insights['weekend_pct']:.1f}%
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="font-size: 12px; color: #495057; padding-top: 4px;">
                                                    of total
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    # Most Visited Merchants section
    if insights['top_by_visits']:
        html += """
                    <!-- Most Visited Merchants -->
                    <tr>
                        <td style="padding: 20px 30px 20px 30px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="font-size: 11px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; color: #6c757d; padding-bottom: 20px; border-bottom: 2px solid #e9ecef;">
                                        MOST VISITED MERCHANTS
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

        for idx, (merchant, data) in enumerate(insights['top_by_visits'], 1):
            html += f"""
                    <tr>
                        <td style="padding: 0 30px 8px 30px;">
                            <table border="0" cellpadding="12" cellspacing="0" width="100%" style="background-color: #ffffff; border: 1px solid #e9ecef;">
                                <tr>
                                    <td width="10%" style="font-size: 11px; font-weight: bold; color: #9ca3af; background-color: #f8f9fa; vertical-align: top;">
                                        #{idx}
                                    </td>
                                    <td style="font-size: 14px; font-weight: bold; color: #374151; word-wrap: break-word; vertical-align: top;">
                                        {merchant}
                                    </td>
                                    <td width="25%" style="font-size: 12px; color: #6c757d; white-space: nowrap; vertical-align: top;">
                                        {data['count']} visits
                                    </td>
                                    <td width="25%" align="right" style="font-size: 15px; font-weight: bold; color: #2d3748; white-space: nowrap; vertical-align: top;">
                                        ${data['amount']:,.2f}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    # Top Merchants by Amount section
    html += """
                    <!-- Top Merchants -->
                    <tr>
                        <td style="padding: 20px 30px 20px 30px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="font-size: 11px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; color: #6c757d; padding-bottom: 20px; border-bottom: 2px solid #e9ecef;">
                                        TOP MERCHANTS BY AMOUNT
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    for idx, (merchant, data) in enumerate(top_merchants, 1):
        html += f"""
                    <tr>
                        <td style="padding: 0 30px 8px 30px;">
                            <table border="0" cellpadding="12" cellspacing="0" width="100%" style="background-color: #ffffff; border: 1px solid #e9ecef;">
                                <tr>
                                    <td width="10%" style="font-size: 11px; font-weight: bold; color: #9ca3af; background-color: #f8f9fa; vertical-align: top;">
                                        #{idx}
                                    </td>
                                    <td style="font-size: 14px; font-weight: bold; color: #374151; word-wrap: break-word; vertical-align: top;">
                                        {merchant}
                                    </td>
                                    <td width="25%" style="font-size: 12px; color: #6c757d; white-space: nowrap; vertical-align: top;">
                                        {data['count']} txns
                                    </td>
                                    <td width="25%" align="right" style="font-size: 15px; font-weight: bold; color: #2d3748; white-space: nowrap; vertical-align: top;">
                                        ${data['amount']:,.2f}
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    # Month-over-month detailed comparison
    if mom_change is not None and biggest_change_category:
        mom_color = "#ef4444" if mom_change > 0 else "#10b981"
        mom_bg = "#fef2f2" if mom_change > 0 else "#f0fdf4"
        mom_arrow = "&#8593;" if mom_change > 0 else "&#8595;"
        mom_label = "More than last month" if mom_change > 0 else "Less than last month"

        change_color = "#ef4444" if biggest_change_amount > 0 else "#10b981"
        change_arrow = "&#8593;" if biggest_change_amount > 0 else "&#8595;"

        html += f"""
                    <!-- MoM Detailed -->
                    <tr>
                        <td style="padding: 20px 30px 20px 30px;">
                            <table border="0" cellpadding="28" cellspacing="0" width="100%" style="background-color: {mom_bg}; border-left: 4px solid {mom_color};">
                                <tr>
                                    <td align="center">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td align="center" style="font-size: 13px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; color: #495057; padding-bottom: 12px;">
                                                    Month over Month
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="font-size: 42px; font-weight: bold; color: {mom_color}; line-height: 1; padding-bottom: 8px;">
                                                    {mom_arrow} ${abs(mom_change):,.2f}
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding-top: 8px;">
                                                    <table border="0" cellpadding="6" cellspacing="0" style="background-color: {mom_color};">
                                                        <tr>
                                                            <td style="font-size: 14px; font-weight: bold; color: #ffffff;">
                                                                {mom_percent:+.1f}% &middot; {mom_label}
                                                            </td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td align="center" style="padding-top: 20px; border-top: 1px solid rgba(0, 0, 0, 0.1);">
                                                    <table border="0" cellpadding="0" cellspacing="0">
                                                        <tr>
                                                            <td align="center" style="font-size: 13px; color: #495057; padding-bottom: 8px;">
                                                                Biggest Change
                                                            </td>
                                                        </tr>
                                                        <tr>
                                                            <td align="center" style="font-size: 16px; font-weight: bold; color: #1a1d1f; padding-bottom: 4px;">
                                                                {biggest_change_category}
                                                            </td>
                                                        </tr>
                                                        <tr>
                                                            <td align="center" style="font-size: 18px; font-weight: bold; color: {change_color};">
                                                                {change_arrow} ${abs(biggest_change_amount):,.2f} <span style="font-size: 14px; font-weight: bold;">({biggest_change_percent:+.1f}%)</span>
                                                            </td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>"""

    # Footer
    html += f"""
                    <!-- Footer -->
                    <tr>
                        <td align="center" style="background-color: #f8f9fa; padding: 32px; border-top: 1px solid #e9ecef;">
                            <table border="0" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center" style="font-size: 12px; color: #6c757d; line-height: 1.8;">
                                        Generated on {datetime.now().strftime('%B %d, %Y')} &bull; Powered by Claude AI
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                </table>
                <!-- End Main Container -->

            </td>
        </tr>
    </table>
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
                # Debug: Show first 3 rows if 0 transactions
                if len(transactions) == 0 and len(rows) > 0:
                    logger.warning(f"  ⚠ TD parsed 0 transactions - showing first 3 rows for debugging:")
                    for i, row in enumerate(rows[:3]):
                        logger.warning(f"      Row {i+1}: {row}")
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
                    # Debug: Show first 3 rows if 0 transactions
                    if len(transactions) == 0 and len(rows) > 0:
                        logger.warning(f"  ⚠ Amex parsed 0 transactions - showing first 3 rows for debugging:")
                        for i, row in enumerate(rows[:3]):
                            logger.warning(f"      Row {i+1}: {dict(row)}")
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

        # Deduplicate transactions (overlapping CSV files cause duplicates)
        # Use normalized merchant name for better deduplication across varying descriptions
        seen = set()
        deduped = []
        for tx in all_transactions:
            key = (tx.date.date(), round(tx.amount, 2), normalize_merchant_name(tx.merchant), tx.source)
            if key not in seen:
                seen.add(key)
                deduped.append(tx)
            else:
                logger.warning(f"Duplicate removed: {tx.date.date()} | {tx.merchant} | ${tx.amount} | {tx.source}")
        all_transactions = deduped
        logger.info(f"After deduplication: {len(all_transactions)} unique transactions")

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

            subject = f"💳 Spending Report — {month_name}"

            # Check for --skip-email flag
            if '--skip-email' not in sys.argv:
                send_email(subject, html_report)
            else:
                logger.info(f"✓ Email skipped for {month_name} (--skip-email flag)")

        logger.info("\n✓ All done!")

    except Exception as e:
        logger.error(f"✗ Error in spending analysis: {e}")
        import traceback
        logger.error(traceback.format_exc())

    logger.info("="*60)
    logger.info("SPENDING TRACKER - RUN COMPLETE")
    logger.info("="*60)


def regenerate_month_email(year: int, month: int):
    """Regenerate and send email for a specific month from existing data"""
    logger.info("="*60)
    logger.info(f"REGENERATING EMAIL FOR {year}-{month:02d}")
    logger.info("="*60)

    try:
        history = DataStore.load_history()
        month_key = f"{year}-{month:02d}"

        if month_key not in history:
            logger.error(f"✗ No data found for {month_key}")
            logger.info(f"Available months: {', '.join(sorted(history.keys()))}")
            return

        month_data = history[month_key]

        # Reconstruct transactions from stored data
        transactions = [
            Transaction(
                date=datetime.fromisoformat(tx['date']),
                description=tx['description'],
                amount=tx['amount'],
                merchant=tx['merchant'],
                source=tx['source'],
                raw_data=tx.get('raw_data', {})
            )
            for tx in month_data['transactions']
        ]

        month_name = datetime(year, month, 1).strftime('%B %Y')
        logger.info(f"Loaded {len(transactions)} transactions for {month_name}")

        # RE-CATEGORIZE using current rules (keyword matching + Claude AI)
        logger.info("Re-categorizing transactions with current rules...")
        categorizer = ClaudeCategorizer(ANTHROPIC_API_KEY)
        transactions = categorizer.categorize_transactions(transactions)

        # Generate and send email with fresh categorizations
        html_report = generate_html_report(year, month, transactions)
        subject = f"💳 Spending Report — {month_name}"
        send_email(subject, html_report)

        logger.info("✓ Email regenerated and sent!")

    except Exception as e:
        logger.error(f"✗ Error regenerating email: {e}")
        import traceback
        logger.error(traceback.format_exc())

    logger.info("="*60)


def main():
    """Main entry point with scheduler"""

    # Check for --check flag to diagnose Drive files and processing status
    if '--check' in sys.argv:
        logger.info("\n" + "="*60)
        logger.info("GOOGLE DRIVE FILE STATUS CHECK")
        logger.info("="*60)
        try:
            drive_monitor = GoogleDriveMonitor(GOOGLE_SERVICE_ACCOUNT_FILE, GOOGLE_DRIVE_FOLDER_ID)
            query = f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents and mimeType='text/csv' and trashed=false"
            results = drive_monitor.service.files().list(
                q=query,
                fields='files(id, name, modifiedTime, size)',
                orderBy='name'
            ).execute()
            files = results.get('files', [])
            logger.info(f"\nFound {len(files)} CSV files in Google Drive folder:\n")
            unprocessed_count = 0
            for f in files:
                is_processed = drive_monitor._is_processed(f['id'])
                status = "✓ PROCESSED  " if is_processed else "✗ UNPROCESSED"
                size_kb = int(f.get('size', 0)) // 1024
                logger.info(f"  {status} | {f['name']:<50} | {size_kb:>4} KB | ID: {f['id']}")
                if not is_processed:
                    unprocessed_count += 1
            logger.info(f"\nSummary: {len(files) - unprocessed_count} processed, {unprocessed_count} unprocessed")
            logger.info("\nProcessed markers on disk:")
            if PROCESSED_DIR.exists():
                markers = sorted(PROCESSED_DIR.glob('*.marker'))
                logger.info(f"  {len(markers)} marker file(s) found")
                for marker in markers:
                    data = json.loads(marker.read_text())
                    logger.info(f"  → {data.get('filename', 'unknown')} | processed: {data.get('processed_at', 'unknown')[:19]}")
            else:
                logger.info("  No processed_csvs directory found (all files are unprocessed)")
            logger.info("="*60)
        except Exception as e:
            logger.error(f"Error during check: {e}")
        return

    # Check for --reset flag to clear all historical data
    if '--reset' in sys.argv:
        import shutil
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()
            logger.info("✓ Cleared monthly_history.json")
        if PROCESSED_DIR.exists():
            shutil.rmtree(PROCESSED_DIR)
            logger.info("✓ Cleared processed_csvs markers")
        logger.info("Reset complete. Run with --now to reprocess all files.")
        return

    # Check for --month flag to regenerate specific month
    if '--month' in sys.argv:
        try:
            idx = sys.argv.index('--month')
            month_str = sys.argv[idx + 1]  # Format: YYYY-MM
            year, month = map(int, month_str.split('-'))
            logger.info(f"Regenerating email for {year}-{month:02d} (--month flag detected)")
            regenerate_month_email(year, month)
            return
        except (IndexError, ValueError) as e:
            logger.error("✗ Invalid --month format. Use: --month YYYY-MM (e.g., --month 2026-01)")
            return

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
    logger.info("(Use --month YYYY-MM to regenerate specific month)")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == '__main__':
    main()
