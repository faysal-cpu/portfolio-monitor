#!/bin/bash
# Portfolio Monitor - Status Check

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "================================================"
echo "Portfolio Monitor - Status Check"
echo "================================================"
echo ""

# Check PID file
if [ -f monitor.pid ]; then
    PID=$(cat monitor.pid)
    echo "PID File: monitor.pid exists (PID: $PID)"

    if ps -p $PID > /dev/null 2>&1; then
        echo "Status: ✓ RUNNING"
        echo ""
        echo "Process info:"
        ps -p $PID -o pid,etime,cmd
    else
        echo "Status: ✗ NOT RUNNING (stale PID file)"
    fi
else
    echo "PID File: Not found"
    echo "Status: ✗ NOT RUNNING"
fi

echo ""
echo "All python main.py processes:"
ps aux | grep "python.*main.py" | grep -v grep || echo "  (none found)"

echo ""
echo "Last 15 lines of log:"
echo "---"
if [ -f monitor.log ]; then
    tail -n 15 monitor.log
else
    echo "No log file found"
fi
echo ""
