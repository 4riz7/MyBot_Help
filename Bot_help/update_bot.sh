#!/bin/bash

# Define paths
BOT_DIR=$(dirname "$0")
cd "$BOT_DIR"

PID_FILE="bot.pid"
MAINT_PID_FILE="maintenance.pid"

# Function to stop the main bot
stop_bot() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null; then
            echo "🛑 Stopping main bot (PID: $PID)..."
            kill $PID
            # Wait for it to close
            sleep 2
        else
            echo "⚠️  Main bot PID file exists but process is not running."
        fi
        rm "$PID_FILE"
    else
        echo "⚠️  No PID file found. Trying to find by name..."
        pkill -f "python main.py"
    fi
}

# Function to start maintenance mode
start_maintenance() {
    echo "🛠  Starting maintenance mode..."
    # Check if we have venv
    if [ -d "venv" ]; then
        PY_EXEC="./venv/bin/python"
    else
        PY_EXEC="python3"
    fi
    
    nohup $PY_EXEC maintenance.py > maintenance.log 2>&1 &
    echo "✅ Maintenance mode active."
}

# Function to stop maintenance mode
stop_maintenance() {
    if [ -f "$MAINT_PID_FILE" ]; then
        PID=$(cat "$MAINT_PID_FILE")
        echo "🛑 Stopping maintenance mode (PID: $PID)..."
        kill $PID
        rm "$MAINT_PID_FILE"
    else
        pkill -f "python maintenance.py"
    fi
}

# Function to start main bot
start_bot() {
    echo "🚀 Starting main bot..."
    if [ -d "venv" ]; then
        PY_EXEC="./venv/bin/python"
    else
        PY_EXEC="python3"
    fi
    
    nohup $PY_EXEC main.py > bot.log 2>&1 &
    
    # Wait a bit to see if it crashes
    sleep 2
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null; then
             echo "✅ Bot started successfully (PID: $PID)!"
        else
             echo "❌ Bot failed to start! Check bot.log"
        fi
    else
        echo "✅ Bot started (no PID file yet, check logs)"
    fi
}

# --- Main Workflow ---

echo "=========================================="
echo "🤖 Bot Update Manager"
echo "=========================================="

stop_bot
start_maintenance

echo ""
echo "⏳ The bot is now in MAINTENANCE MODE."
echo "   Users will see a 'Technical break' message."
echo ""
echo "👉 You can now safely update code, git pull, pip install, etc."
echo ""
read -p "⌨️  Press [ENTER] when you are ready to restart the main bot..."

stop_maintenance
start_bot

echo "=========================================="
echo "🎉 Update cycle complete!"
echo "=========================================="
