# Fixing Duplicate Emails (3 AM and 7 AM)

## Problem
You're receiving **two emails** per day:
- One at **3:00 AM**
- One at **7:00 AM**

## Root Cause
You likely have **TWO instances** of the portfolio monitor running:

1. **Cloud instance (Railway)** - Runs in **UTC timezone**
   - Scheduled for 07:00 UTC
   - UTC 07:00 = **3:00 AM Eastern Time** (EDT/EST)
   
2. **Local instance** - Runs in your **local timezone**
   - Scheduled for 07:00 local time
   - Local 07:00 = **7:00 AM Eastern Time**

## Solution Options

### Option 1: Stop the Cloud Instance (Recommended if you run locally)
If you're running the monitor on your local machine and don't need Railway:

1. Go to Railway dashboard: https://railway.app/
2. Find your `portfolio-monitor` project
3. Click on the service
4. Click "Settings" → "Danger" → "Remove Service"

### Option 2: Stop the Local Instance (Recommended if you use Railway)
If you want to keep it running on Railway:

```bash
# Check if it's running locally
ps aux | grep "main.py"

# If you find a process, stop it
kill $(cat monitor.pid)  # if using the start script
# OR
pkill -f "python.*main.py"

# Remove from crontab if auto-starting
crontab -e
# Remove any lines containing "portfolio-monitor"
```

### Option 3: Fix Railway Timezone (Advanced)
If you want Railway to send at 7 AM local time instead of 3 AM:

**For Eastern Time (EDT/EST):**
- EDT (summer): 07:00 local = 11:00 UTC
- EST (winter): 07:00 local = 12:00 UTC

Edit `main.py` line ~1340:
```python
# Change from:
schedule.every().monday.at("07:00").do(run_portfolio_analysis)

# To (for EDT):
schedule.every().monday.at("11:00").do(run_portfolio_analysis)
```

Then redeploy to Railway.

## How to Verify Which Instance Sent an Email

Check your log file (`monitor.log`) for this line at the start of each run:

```
Instance: <hostname>
```

- If hostname is something like `prod-xxxxx.railway.internal` → **Railway instance**
- If hostname is your computer name → **Local instance**

## Quick Diagnostic Commands

```bash
# Check if running locally
ps aux | grep main.py

# Check Railway status
# Visit: https://railway.app/dashboard

# View recent logs
tail -f monitor.log

# Check cron jobs
crontab -l | grep portfolio
```

## After Fixing

Once you've stopped one instance, you should receive **only ONE email** at your desired time:
- Either 3 AM (if keeping Railway with UTC schedule)
- Or 7 AM (if keeping local instance)
- Or 7 AM (if you fixed Railway's timezone)

The updated code now logs which instance is running, so you can verify in your logs!
