#!/bin/bash

echo "================================================"
echo "Portfolio Monitor - Deployment Script"
echo "================================================"
echo ""

# Update system
echo "[1/6] Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

# Install Python 3 and pip
echo ""
echo "[2/6] Installing Python 3 and pip..."
sudo apt-get install -y python3 python3-pip python3-venv git

# Create virtual environment
echo ""
echo "[3/6] Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install requirements
echo ""
echo "[4/6] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Setup cron for auto-restart on reboot
echo ""
echo "[5/6] Setting up cron job for auto-restart on reboot..."

# Get current directory
CURRENT_DIR=$(pwd)

# Create start script
cat > start_monitor.sh << EOF
#!/bin/bash
cd $CURRENT_DIR
source venv/bin/activate
nohup python3 main.py >> monitor.log 2>&1 &
echo \$! > monitor.pid
EOF

chmod +x start_monitor.sh

# Add to crontab if not already present
(crontab -l 2>/dev/null | grep -v "portfolio-monitor"; echo "@reboot $CURRENT_DIR/start_monitor.sh") | crontab -

echo "Cron job added for auto-restart on reboot"

# Start the monitor
echo ""
echo "[6/6] Starting Portfolio Monitor..."

# Kill any existing process
if [ -f monitor.pid ]; then
    OLD_PID=$(cat monitor.pid)
    if ps -p $OLD_PID > /dev/null 2>&1; then
        echo "Stopping existing process (PID: $OLD_PID)..."
        kill $OLD_PID
        sleep 2
    fi
fi

# Start new process
nohup python3 main.py >> monitor.log 2>&1 &
NEW_PID=$!
echo $NEW_PID > monitor.pid

echo ""
echo "================================================"
echo "Deployment Complete!"
echo "================================================"
echo ""
echo "Portfolio Monitor is now running in background"
echo "Process ID: $NEW_PID"
echo ""
echo "Useful commands:"
echo "  - View logs: tail -f monitor.log"
echo "  - Test now: python3 main.py --now"
echo "  - Stop service: kill \$(cat monitor.pid)"
echo "  - Restart service: ./start_monitor.sh"
echo ""
echo "Last 10 lines of log:"
echo "---"
if [ -f monitor.log ]; then
    tail -n 10 monitor.log
else
    echo "No logs yet. Monitor just started."
fi
echo ""
