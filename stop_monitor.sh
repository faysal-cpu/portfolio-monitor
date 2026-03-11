#!/bin/bash
# Portfolio Monitor - Stop Script

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ -f monitor.pid ]; then
    PID=$(cat monitor.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "Stopping Portfolio Monitor (PID: $PID)..."
        kill $PID
        rm monitor.pid
        echo "✓ Stopped successfully"
    else
        echo "Process not running (stale PID file)"
        rm monitor.pid
    fi
else
    echo "No PID file found. Checking for running processes..."
    pkill -f "python3 main.py"
    echo "Killed any running main.py processes"
fi
