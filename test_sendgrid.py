#!/usr/bin/env python3
"""
Standalone SendGrid Email Test
Tests if SendGrid API is working correctly
"""

import os
import sys
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
import traceback

print("=" * 70)
print("SENDGRID EMAIL TEST")
print("=" * 70)
print()

# Hardcoded .env path
ENV_FILE_PATH = r"C:\Users\6135564\OneDrive - Thomson Reuters Incorporated\Desktop\portfolio-monitor\.env"

print(f"Loading .env from: {ENV_FILE_PATH}")
print(f".env exists: {os.path.exists(ENV_FILE_PATH)}")
print()

if not os.path.exists(ENV_FILE_PATH):
    print(f"ERROR: .env file not found at {ENV_FILE_PATH}")
    print("Please update ENV_FILE_PATH in this script or create the .env file")
    sys.exit(1)

# Load environment
load_dotenv(ENV_FILE_PATH, override=True)

# Get credentials
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL_TO = os.getenv('EMAIL_TO')

print("=" * 70)
print("LOADED CREDENTIALS")
print("=" * 70)
print(f"SENDGRID_API_KEY: {SENDGRID_API_KEY[:30] + '...' if SENDGRID_API_KEY else 'NOT SET'}")
print(f"  - Length: {len(SENDGRID_API_KEY) if SENDGRID_API_KEY else 0}")
print(f"  - Starts with 'SG.': {'✓ YES' if SENDGRID_API_KEY and SENDGRID_API_KEY.startswith('SG.') else '✗ NO'}")
print(f"EMAIL_FROM: {EMAIL_FROM}")
print(f"EMAIL_TO: {EMAIL_TO}")
print()

# Validate
if not SENDGRID_API_KEY:
    print("ERROR: SENDGRID_API_KEY not set in .env file")
    print("Add this line to your .env file:")
    print("SENDGRID_API_KEY=SG.your_actual_api_key_here")
    sys.exit(1)

if not SENDGRID_API_KEY.startswith('SG.'):
    print("WARNING: SENDGRID_API_KEY doesn't start with 'SG.'")
    print("Make sure you're using a SendGrid API key, not a Twilio API key")
    print()

if not EMAIL_FROM or not EMAIL_TO:
    print("ERROR: EMAIL_FROM and EMAIL_TO must be set in .env file")
    sys.exit(1)

# Create test email
print("=" * 70)
print("CREATING TEST EMAIL")
print("=" * 70)

subject = "🧪 SendGrid Test Email from Portfolio Monitor"
html_content = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; background-color: #f5f5f5; }
        .container { background-color: white; padding: 30px; border-radius: 8px; max-width: 600px; margin: 0 auto; }
        h1 { color: #00B386; }
        .success { background-color: #d4edda; color: #155724; padding: 15px; border-radius: 5px; margin: 20px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>✓ SendGrid Test Successful!</h1>
        <div class="success">
            <strong>Your SendGrid configuration is working correctly.</strong>
        </div>
        <p>This test email was sent from the Portfolio Monitor application.</p>
        <p>If you're seeing this, your SendGrid API key is configured properly and emails are being delivered.</p>
        <hr>
        <p style="color: #666; font-size: 12px;">
            From: {from_email}<br>
            To: {to_email}<br>
            Sent via SendGrid API
        </p>
    </div>
</body>
</html>
""".format(from_email=EMAIL_FROM, to_email=EMAIL_TO)

plain_content = f"""
SendGrid Test Email - SUCCESS

Your SendGrid configuration is working correctly!

This test email was sent from the Portfolio Monitor application.
If you're seeing this, your SendGrid API key is configured properly.

From: {EMAIL_FROM}
To: {EMAIL_TO}
Sent via SendGrid API
"""

print(f"Subject: {subject}")
print(f"From: {EMAIL_FROM}")
print(f"To: {EMAIL_TO}")
print()

# Create message
try:
    message = Mail(
        from_email=Email(EMAIL_FROM),
        to_emails=To(EMAIL_TO),
        subject=subject,
        plain_text_content=Content("text/plain", plain_content),
        html_content=Content("text/html", html_content)
    )
    print("✓ Message object created successfully")
except Exception as e:
    print(f"✗ Error creating message: {e}")
    traceback.print_exc()
    sys.exit(1)

# Send via SendGrid
print()
print("=" * 70)
print("SENDING EMAIL VIA SENDGRID")
print("=" * 70)

try:
    sg = SendGridAPIClient(api_key=SENDGRID_API_KEY)
    print("✓ SendGrid client initialized")

    print("Sending email...")
    response = sg.send(message)

    print()
    print("=" * 70)
    print("✓✓✓ SUCCESS! ✓✓✓")
    print("=" * 70)
    print(f"Status Code: {response.status_code}")
    print(f"Response Body: {response.body if hasattr(response, 'body') else '(empty)'}")
    print()
    print("Email sent successfully to SendGrid!")
    print()
    print("Next steps:")
    print(f"  1. Check your email inbox: {EMAIL_TO}")
    print("  2. Check your spam folder if not in inbox")
    print("  3. Check SendGrid Activity Feed: https://app.sendgrid.com/email_activity")
    print()
    print("If you received this email, your SendGrid setup is working perfectly!")
    print("You can now run the main portfolio monitor: python main.py --now")
    print("=" * 70)

except Exception as e:
    print()
    print("=" * 70)
    print("✗✗✗ ERROR SENDING EMAIL ✗✗✗")
    print("=" * 70)
    print(f"Error Type: {type(e).__name__}")
    print(f"Error Message: {str(e)}")
    print()

    # Extract detailed error info
    if hasattr(e, 'body'):
        print(f"Error Body: {e.body}")
    if hasattr(e, 'status_code'):
        print(f"Status Code: {e.status_code}")
    if hasattr(e, 'headers'):
        print(f"Headers: {e.headers}")

    print()
    print("Full Traceback:")
    print("-" * 70)
    traceback.print_exc()
    print("-" * 70)
    print()

    print("Common Issues:")
    print("  1. Invalid API Key - Make sure your SENDGRID_API_KEY starts with 'SG.'")
    print("  2. Unverified Sender - Verify your EMAIL_FROM in SendGrid")
    print("     → https://app.sendgrid.com/settings/sender_auth/senders")
    print("  3. API Key Permissions - Make sure the API key has 'Mail Send' permission")
    print("  4. Network Issue - Check your internet connection")
    print()
    sys.exit(1)
