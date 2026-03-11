#!/bin/bash
# Portfolio Monitor - Startup Script
# Run this on your server to start the background process

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "================================================"
echo "Starting Portfolio Monitor"
echo "================================================"

# Kill any existing process
if [ -f monitor.pid ]; then
    OLD_PID=$(cat monitor.pid)
    if ps -p $OLD_PID > /dev/null 2>&1; then
        echo "Stopping existing process (PID: $OLD_PID)..."
        kill $OLD_PID
        sleep 2
    fi
fi

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "WARNING: No virtual environment found. Using system Python."
fi

# Start the monitor in background
echo "Starting main.py in background..."
nohup python3 main.py >> monitor.log 2>&1 &
NEW_PID=$!
echo $NEW_PID > monitor.pid

echo ""
echo "✓ Portfolio Monitor started successfully!"
echo "  Process ID: $NEW_PID"
echo "  Scheduled to run Mon-Fri at 11:00 AM"
echo ""
echo "Useful commands:"
echo "  - View logs:        tail -f monitor.log"
echo "  - Test now:         python3 main.py --now"
echo "  - Stop service:     kill \$(cat monitor.pid)"
echo "  - Check if running: ps aux | grep main.py"
echo ""
