#!/bin/bash


# Example usage $ ./Monitor_Usage_PID.sh 'python provider/provider1.py 34933555-5cca-41fb-aded-4ab7900c48d5'




# Check if an argument is provided
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <Process Name>"
    exit 1
fi

# Step 1: Capture the process name from the argument
PROCESS_NAME=$1

# Step 2: Set sleep interval (in seconds)
sleepInterval=0.5

# Step 3: Monitor resource usage for the process
echo "Monitoring resource usage for process: $PROCESS_NAME"

# Step 4: Find the PID of the process by 
PID=$(pgrep -f "$PROCESS_NAME" | head -n 1)

echo "PID: $PID"

# Check if the process exists
if [ -z "$PID" ]; then
    echo "No process found with name: $PROCESS_NAME."
    exit 1
fi

while kill -0 $PID 2>/dev/null; do
    # Use ps to capture CPU and memory usage
    USAGE=$(ps -p $PID -o %cpu,%mem,vsz,rss)

    # Extracting the CPU and memory values
    # Skip the header line by using `tail -n +2`
    CPU_USAGE=$(echo "$USAGE" | tail -n +2 | awk '{print $1}')  # %CPU (as a decimal)
    MEMORY_VSZ=$(echo "$USAGE" | tail -n +2 | awk '{print $3}')  # Virtual memory size in KB
    MEMORY_RSS=$(echo "$USAGE" | tail -n +2 | awk '{print $4}')  # Resident set size in KB

    # Convert to bytes for absolute values
    MEMORY_VSZ_BYTES=$((MEMORY_VSZ * 1024))  # Convert from KB to Bytes
    MEMORY_RSS_BYTES=$((MEMORY_RSS * 1024))  # Convert from KB to Bytes

    # Log to file and echo to terminal
    echo "$(date): Process '$PROCESS_NAME' (PID $PID), CPU Usage: $CPU_USAGE%, Memory VSZ: $MEMORY_VSZ_BYTES Bytes, Memory RSS: $MEMORY_RSS_BYTES Bytes" >> usage.log
    echo "CPU Usage: $CPU_USAGE%, Memory VSZ: $MEMORY_VSZ_BYTES Bytes, Memory RSS: $MEMORY_RSS_BYTES Bytes"
    
    sleep $sleepInterval  # Wait before checking again
done

echo "Process '$PROCESS_NAME' (PID $PID) has finished."
