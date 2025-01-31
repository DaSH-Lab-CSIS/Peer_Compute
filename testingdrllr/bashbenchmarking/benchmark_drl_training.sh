#!/bin/bash

CGROUP_NAME="drl_training_benchmark"

# Create the cgroup (requires root privileges)
sudo cgcreate -g cpuacct,memory:$CGROUP_NAME

# Run drl_scheduler_train.py in the cgroup and collect stats
sudo cgexec -g cpuacct,memory:$CGROUP_NAME /usr/bin/time -v python drl_scheduler_train.py 2>&1 | tee drl_training_benchmark_output.txt

# Get stats
CPU_USAGE=$(sudo cgget -r cpuacct.usage $CGROUP_NAME | awk '{print $2}')
MEMORY_USAGE=$(sudo cgget -r memory.max_usage_in_bytes $CGROUP_NAME | awk '{print $2}')

# Save stats to drl_training_benchmark_results.txt
echo "CPU usage (cpuacct.usage): $CPU_USAGE nanoseconds" > drl_training_benchmark_results.txt
echo "Memory usage (memory.max_usage_in_bytes): $MEMORY_USAGE bytes" >> drl_training_benchmark_results.txt

# Optionally, remove the cgroup
sudo cgdelete -g cpuacct,memory:$CGROUP_NAME

echo "Training benchmarking complete. Results saved to drl_training_benchmark_results.txt and drl_training_benchmark_output.txt"
