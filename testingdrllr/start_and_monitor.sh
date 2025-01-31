#!/bin/bash

# start_and_monitor.sh

# ============================
# Configuration Section
# ============================

# Hardcoded Python script command
PYTHON_COMMAND="python3 drl_scheduler_train.py"

# Log file with timestamp to avoid overwriting
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="usage_${TIMESTAMP}.log"

# Monitoring interval in seconds
SLEEP_INTERVAL=0.0000001

# ============================
# Function Definitions
# ============================

# Function to monitor resource usage of a given PID
monitor_usage() {
    local PID=$1

    echo "Monitoring resource usage for PID: $PID"
    echo "Logging to $LOG_FILE"

    # Continue monitoring as long as the process is running
    while kill -0 "$PID" 2>/dev/null; do
        # Retrieve CPU and memory usage using ps
        USAGE=$(ps -p "$PID" -o %cpu,%mem,vsz,rss --no-headers)
        
        # Check if ps command was successful
        if [ $? -ne 0 ]; then
            echo "Failed to retrieve resource usage for PID $PID."
            break
        fi

        # Parse the usage metrics
        CPU_USAGE=$(echo "$USAGE" | awk '{print $1}')    # %CPU
        MEM_USAGE=$(echo "$USAGE" | awk '{print $2}')    # %MEM
        VSZ=$(echo "$USAGE" | awk '{print $3}')          # Virtual Memory Size (KB)
        RSS=$(echo "$USAGE" | awk '{print $4}')          # Resident Set Size (KB)

        # Convert memory from KB to Bytes
        VSZ_BYTES=$((VSZ * 1024))
        RSS_BYTES=$((RSS * 1024))

        # Log the metrics with a timestamp
        echo "$(date +"%Y-%m-%d %H:%M:%S"): PID $PID, CPU: ${CPU_USAGE}%, MEM: ${MEM_USAGE}%, VSZ: ${VSZ_BYTES} Bytes, RSS: ${RSS_BYTES} Bytes" >> "$LOG_FILE"

        # Echo the metrics to the terminal
        echo "PID $PID | CPU: ${CPU_USAGE}% | MEM: ${MEM_USAGE}% | VSZ: ${VSZ_BYTES} Bytes | RSS: ${RSS_BYTES} Bytes"

        # Wait for the specified interval before the next check
        sleep "$SLEEP_INTERVAL"
    done

    echo "Process with PID $PID has terminated."
}

# ============================
# Main Execution Section
# ============================

# Start the Python script in the background
echo "Starting Python script: $PYTHON_COMMAND"
$PYTHON_COMMAND &
PYTHON_PID=$!

# Give the Python script a moment to start and ensure it's running
sleep 0

# Verify if the Python script started successfully
if ! kill -0 "$PYTHON_PID" 2>/dev/null; then
    echo "Failed to start Python script."
    exit 1
fi

echo "Python script started with PID: $PYTHON_PID"

# Start monitoring the Python script's resource usage
monitor_usage "$PYTHON_PID"
