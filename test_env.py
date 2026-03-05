#!/usr/bin/env python3
"""
Quick test script to verify .env file is loaded correctly
Run this before running main.py to check your configuration
"""

import os
from dotenv import load_dotenv

# Get the directory where this script is located
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')

print("=" * 60)
print("TESTING .env FILE CONFIGURATION")
print("=" * 60)
print(f"Script location: {os.path.abspath(__file__)}")
print(f"Script directory: {script_dir}")
print(f"Current working directory: {os.getcwd()}")
print(f"Looking for .env at: {env_path}")
print(f".env file exists: {os.path.exists(env_path)}")
print()

if not os.path.exists(env_path):
    print("ERROR: .env file not found!")
    print(f"Please create {env_path}")
    print("Copy from .env.example and fill in your credentials")
    exit(1)

# Show .env file contents (first 20 lines)
print("=" * 60)
print(".env FILE CONTENTS (first 20 lines):")
print("=" * 60)
with open(env_path, 'r') as f:
    for i, line in enumerate(f.readlines()[:20], 1):
        print(f"{i:2d}: {line.rstrip()}")
print()

# Load environment variables
print("=" * 60)
print("LOADING ENVIRONMENT VARIABLES")
print("=" * 60)
env_loaded = load_dotenv(env_path, override=True, verbose=True)
print(f"load_dotenv() returned: {env_loaded}")
print()

# Check what was loaded
print("=" * 60)
print("LOADED VALUES:")
print("=" * 60)

credentials = {
    'FINNHUB_API_KEY': os.getenv('FINNHUB_API_KEY'),
    'REDDIT_CLIENT_ID': os.getenv('REDDIT_CLIENT_ID'),
    'REDDIT_CLIENT_SECRET': os.getenv('REDDIT_CLIENT_SECRET'),
    'REDDIT_USER_AGENT': os.getenv('REDDIT_USER_AGENT'),
    'ANTHROPIC_API_KEY': os.getenv('ANTHROPIC_API_KEY'),
    'TWILIO_ACCOUNT_SID': os.getenv('TWILIO_ACCOUNT_SID'),
    'TWILIO_AUTH_TOKEN': os.getenv('TWILIO_AUTH_TOKEN'),
    'EMAIL_FROM': os.getenv('EMAIL_FROM'),
    'EMAIL_TO': os.getenv('EMAIL_TO'),
}

for key, value in credentials.items():
    if value:
        # Show first part of value
        if len(value) > 30:
            display = f"{value[:30]}... (length: {len(value)})"
        else:
            display = value
        print(f"✓ {key:25s} = {display}")
    else:
        print(f"✗ {key:25s} = NOT SET")

print()
print("=" * 60)
print("CHECKING FOR PLACEHOLDER VALUES")
print("=" * 60)

issues = []

if credentials['EMAIL_FROM']:
    if 'example.com' in credentials['EMAIL_FROM'] or 'your-' in credentials['EMAIL_FROM']:
        issues.append(f"EMAIL_FROM is still a placeholder: {credentials['EMAIL_FROM']}")
else:
    issues.append("EMAIL_FROM is not set")

if credentials['EMAIL_TO']:
    if 'example.com' in credentials['EMAIL_TO'] or 'recipient' in credentials['EMAIL_TO']:
        issues.append(f"EMAIL_TO is still a placeholder: {credentials['EMAIL_TO']}")
else:
    issues.append("EMAIL_TO is not set")

if credentials['TWILIO_ACCOUNT_SID']:
    if 'your_' in credentials['TWILIO_ACCOUNT_SID'] or len(credentials['TWILIO_ACCOUNT_SID']) < 20:
        issues.append(f"TWILIO_ACCOUNT_SID appears invalid: {credentials['TWILIO_ACCOUNT_SID'][:30]}")
    elif not credentials['TWILIO_ACCOUNT_SID'].startswith('SG.'):
        issues.append(f"TWILIO_ACCOUNT_SID should be a SendGrid API key starting with 'SG.' - got: {credentials['TWILIO_ACCOUNT_SID'][:10]}...")
else:
    issues.append("TWILIO_ACCOUNT_SID is not set")

if issues:
    print("ISSUES FOUND:")
    for issue in issues:
        print(f"  ✗ {issue}")
    print()
    print("Please fix these issues in your .env file before running main.py")
else:
    print("✓ All critical values appear to be set correctly!")
    print()
    print("Ready to run: python main.py --now")

print("=" * 60)
