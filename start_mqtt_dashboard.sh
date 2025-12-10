#!/bin/bash

# MQTT Dashboard Startup Script
# This script starts the MQTT dashboard service

echo "Starting MQTT Dashboard Service..."

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Default port
DASHBOARD_PORT=${DASHBOARD_PORT:-9020}

# Function to cleanup on exit
cleanup() {
    echo "Shutting down MQTT Dashboard..."
    kill $DASHBOARD_PID 2>/dev/null
    exit
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Start dashboard
echo "Starting MQTT dashboard on port $DASHBOARD_PORT..."
echo "Access dashboard at: http://localhost:$DASHBOARD_PORT"
echo ""
echo "Press Ctrl+C to stop"
echo ""

uvicorn mqtt_dashboard:app --host 0.0.0.0 --port $DASHBOARD_PORT &
DASHBOARD_PID=$!

# Wait for background process
wait $DASHBOARD_PID

