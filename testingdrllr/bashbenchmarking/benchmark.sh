#!/bin/bash

CGROUP_NAME="mincost_benchmark"

# Create the cgroup (requires root privileges)
sudo cgcreate -g cpuacct,memory:$CGROUP_NAME

# Clear previous stats (if any)
sudo cgclear $CGROUP_NAME

# Run mincost_lp.py in the cgroup and collect stats
sudo cgexec -g cpuacct,memory:$CGROUP_NAME /usr/bin/time -v python mincost_lp.py 2>&1 | tee benchmark_output.txt

# Get stats
CPU_USAGE=$(sudo cgget -r cpuacct.usage $CGROUP_NAME | awk '{print $2}')
MEMORY_USAGE=$(sudo cgget -r memory.max_usage_in_bytes $CGROUP_NAME | awk '{print $2}')

# Save stats to benchmark_results.txt
echo "CPU usage (cpuacct.usage): $CPU_USAGE nanoseconds" > benchmark_results.txt
echo "Memory usage (memory.max_usage_in_bytes): $MEMORY_USAGE bytes" >> benchmark_results.txt

# Optionally, remove the cgroup
sudo cgdelete -g cpuacct,memory:$CGROUP_NAME

echo "Benchmarking complete. Results saved to benchmark_results.txt and benchmark_output.txt"
