#!/bin/bash

# Load Balancer with Log Viewer Startup Script
# This script starts both the load balancer and log viewer services

echo "Starting Load Balancer with Log Viewer..."

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Function to cleanup background processes on exit
cleanup() {
    echo "Shutting down services..."
    kill $LB_PID $VIEWER_PID 2>/dev/null
    exit
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Start log viewer in background
echo "Starting log viewer on port 9010..."
uvicorn lb_log_viewer:app --host 0.0.0.0 --port 9010 &
VIEWER_PID=$!

# Wait a moment for viewer to start
sleep 2

# Start load balancer in background
echo "Starting load balancer on port 9001..."
uvicorn loadbalancer_with_logging:app --host 0.0.0.0 --port 9001 &
LB_PID=$!

echo ""
echo "Services started successfully!"
echo "Load Balancer: http://localhost:9001"
echo "Log Viewer:    http://localhost:9010"
echo ""
echo "Press Ctrl+C to stop both services"

# Wait for background processes
wait $LB_PID $VIEWER_PID