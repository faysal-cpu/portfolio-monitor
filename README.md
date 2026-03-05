# Portfolio Monitor

Automated daily stock portfolio analysis system that sends detailed email reports every weekday at 7am.

## Features

- **Macro Context Analysis**: Daily geopolitical and macro factors affecting markets (via Claude AI)
- **Holdings Analysis**: Price tracking, news monitoring, Reddit sentiment, and AI-powered recommendations
- **Opportunity Discovery**: Identifies 5 trending stocks worth considering based on your investment profile
- **Auto-Updates**: Pulls latest holdings from GitHub before each run
- **Beautiful HTML Emails**: Professional formatting with color-coded recommendations
- **Robust Error Handling**: Never crashes - always sends something even if APIs fail

## Architecture

### Module 1: Macro Context
Queries Claude API for the 3 most important macro/geopolitical events affecting markets today.

### Module 2: Holdings Analysis
For each ticker in `holdings.txt`:
- Fetches current price and 1-day % change (Finnhub)
- Gets 3 most recent news headlines (Finnhub)
- Searches Reddit (r/wallstreetbets, r/stocks, r/investing, r/CanadianInvestor) for mentions and sentiment
- Sends all data to Claude for BUY MORE/HOLD/SELL/WATCH recommendations

### Module 3: New Opportunities
- Finds trending tickers from Finnhub and Reddit
- Removes tickers already in your holdings
- Claude identifies 5 stocks matching your investment profile

## Installation

### Prerequisites
- Ubuntu 22.04 LTS (tested on Oracle Cloud)
- Python 3.8+
- Git repository initialized

### API Keys Required
1. **Finnhub**: https://finnhub.io (free tier works)
2. **Reddit**: https://www.reddit.com/prefs/apps (create app for API access)
3. **Anthropic Claude**: https://console.anthropic.com
4. **Twilio SendGrid**: https://console.twilio.com (use Account SID and Auth Token)

### Deployment Steps

1. **Clone or create your repository**:
```bash
cd ~
git clone <your-repo-url> portfolio-monitor
cd portfolio-monitor
```

2. **Add all files to the repository**:
```bash
# Copy all files (main.py, requirements.txt, etc.) to this directory
git add .
git commit -m "Initial commit"
git push
```

3. **Create environment file**:
```bash
cp .env.example .env
nano .env  # Fill in your API keys
```

4. **Run deployment script**:
```bash
chmod +x deploy.sh
./deploy.sh
```

5. **Verify installation**:
```bash
# Check if process is running
ps aux | grep main.py

# View logs
tail -f monitor.log

# Test immediately (don't wait for 7am)
source venv/bin/activate
python3 main.py --now
```

## Usage

### Managing Holdings

Edit `holdings.txt` to add/remove tickers:
```bash
nano holdings.txt
git add holdings.txt
git commit -m "Updated holdings"
git push
```

The script automatically pulls updates from GitHub before each run, so changes take effect the next morning.

### Manual Run

Run analysis immediately for testing:
```bash
source venv/bin/activate
python3 main.py --now
```

### Monitoring

View real-time logs:
```bash
tail -f monitor.log
```

Check scheduler status:
```bash
ps aux | grep main.py
```

### Stopping/Restarting

Stop the service:
```bash
kill $(cat monitor.pid)
```

Restart the service:
```bash
./start_monitor.sh
```

## Scheduled Execution

The monitor runs automatically:
- **When**: Monday-Friday at 7:00 AM (server time)
- **Auto-restart**: Configured via cron on server reboot
- **Process**: Runs in background using nohup

To change the schedule, edit `main.py` and modify the schedule times:
```python
schedule.every().monday.at("07:00").do(run_portfolio_analysis)
# etc.
```

## Email Format

### Subject
```
📈 Portfolio Brief — Wednesday, March 04, 2026 | 18 positions
```

### Sections
1. **🌍 Macro Context**: 3 bullet points on key market events
2. **📊 Your Holdings**: Table with ticker, price, change %, recommendation, confidence, reason, risk, Reddit sentiment
3. **🔥 Opportunities**: 5 cards showing new stocks to consider

### Color Coding
- **BUY MORE**: Green background
- **HOLD**: Grey background
- **SELL**: Red background
- **WATCH**: Yellow background

## Error Handling

The system is designed to never fully crash:

- **Finnhub rate limit**: Waits 2s and retries once
- **Reddit API failure**: Skips Reddit data, notes "Reddit unavailable"
- **Single ticker failure**: Logs error, skips ticker, continues with others
- **Claude API failure**: Sends email with raw data only
- **Email sending failure**: Saves email as HTML file with timestamp
- **Git pull failure**: Logs error but continues with existing holdings.txt

All errors are logged to `monitor.log` with timestamps.

## File Structure

```
portfolio-monitor/
├── main.py              # Main application
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (create from .env.example)
├── .env.example         # Template for environment variables
├── holdings.txt         # Your stock tickers (one per line)
├── deploy.sh            # Deployment script
├── start_monitor.sh     # Auto-generated startup script
├── monitor.log          # Application logs
├── monitor.pid          # Process ID file
├── venv/                # Python virtual environment
└── README.md            # This file
```

## Troubleshooting

### Email not received
1. Check `monitor.log` for Twilio SendGrid errors
2. Verify Twilio Account SID and Auth Token in `.env`
3. Check spam folder
4. Look for saved HTML files in directory (fallback when email sending fails)

### No Reddit data
- Reddit API can be rate-limited
- Check credentials in `.env`
- Verify Reddit app is created at https://www.reddit.com/prefs/apps

### Schedule not running
```bash
# Check if process is running
ps aux | grep main.py

# Restart the service
./start_monitor.sh

# Check cron jobs
crontab -l
```

### API rate limits
- Finnhub free tier: 60 calls/minute
- Reddit: 60 calls/minute
- The script includes delays to respect these limits

## Investment Profile

The AI analysis is tuned for:
- **Account**: Canadian TFSA (tax-free savings account)
- **Style**: Momentum plays, binary catalysts
- **Sectors**: Defence, AI, commodities, small caps
- **Risk**: Somewhat risk tolerant
- **Focus**: Specific events and catalysts, not generic analysis

To change this profile, edit the prompts in `main.py` functions:
- `analyze_holdings()`
- `find_opportunities()`

## Security Notes

- Never commit `.env` to Git (included in `.gitignore`)
- Store API keys securely
- Use environment variables for all secrets
- Twilio: Keep Account SID and Auth Token private
- Reddit: Use read-only API scope

## License

For personal use. Not financial advice.

## Support

For issues or questions, check the logs:
```bash
tail -f monitor.log
```

All API errors, rate limits, and processing issues are logged with timestamps.
