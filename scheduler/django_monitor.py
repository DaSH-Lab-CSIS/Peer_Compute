#!/usr/bin/env python3
import argparse
import os
import time
import subprocess
from pathlib import Path
# usage : sudo python3 
class CgroupMonitor:
    def __init__(self, cgroup_type, pid, name):
        self.cgroup_type = cgroup_type
        self.pid = str(pid)
        self.name = name
        self.cgroup_path = f"/sys/fs/cgroup/{cgroup_type}/{name}"
        print(self.cgroup_path)
    def setup_cgroup(self):
        """Create the cgroup and add the process to it."""
        try:
            # Create cgroup directory if it doesn't exist
            Path(self.cgroup_path).mkdir(parents=True, exist_ok=True)
            
            # Add process to cgroup
            with open(f"{self.cgroup_path}/cgroup.procs", "w") as f:
                f.write(self.pid)
                
            print(f"Successfully added PID {self.pid} to cgroup {self.name}")
            return True
        except PermissionError:
            print("Error: Script requires root privileges")
            return False
        except Exception as e:
            print(f"Error setting up cgroup: {e}")
            return False

    def monitor_memory(self):
        """Monitor memory usage of the cgroup."""
        try:
            memory_usage = Path(f"{self.cgroup_path}/memory.stat").read_text().strip()
            memory_max = Path(f"{self.cgroup_path}/memory.max").read_text().strip()
            print(f"Memory Usage: {int(memory_usage) / 1024 / 1024:.2f} MB")
            if memory_max != "max":
                print(f"Memory Limit: {int(memory_max) / 1024 / 1024:.2f} MB")
        except FileNotFoundError:
            print("Memory statistics not available")

    def monitor_cpu(self):
        """Monitor CPU usage of the cgroup."""
        try:
            cpu_usage = Path(f"{self.cgroup_path}/cpu.stat").read_text()
            print("CPU Statistics:")
            print(cpu_usage)
        except FileNotFoundError:
            print("CPU statistics not available")

    def monitor_io(self):
        """Monitor I/O usage of the cgroup."""
        try:
            io_stats = Path(f"{self.cgroup_path}/io.stat").read_text()
            print("I/O Statistics:")
            print(io_stats)
        except FileNotFoundError:
            print("I/O statistics not available")

    def cleanup(self):
        """Remove the cgroup."""
        try:
            # Move processes to parent cgroup
            with open(f"{self.cgroup_path}/cgroup.procs") as f:
                processes = f.readlines()
            
            parent_procs = Path("/sys/fs/cgroup/cgroup.procs")
            for proc in processes:
                parent_procs.write_text(proc.strip())
            
            # Remove cgroup directory
            os.rmdir(self.cgroup_path)
            print(f"Successfully removed cgroup {self.name}")
        except Exception as e:
            print(f"Error cleaning up cgroup: {e}")

def main():
    parser = argparse.ArgumentParser(description='Monitor a process using cgroups')
    parser.add_argument('--type', required=True, choices=['memory', 'cpu', 'io', 'all'],
                      help='Type of resource to monitor')
    parser.add_argument('--name', required=True,
                      help='Name for the cgroup')
    parser.add_argument('--interval', type=int, default=5,
                      help='Monitoring interval in seconds (default: 5)')
    args = parser.parse_args()

    # Check if running as root
    if os.geteuid() != 0:
        print("This script must be run as root")
        return

    # Check if process exists
    with open("djpid.txt", "r") as file:
        content = file.read()
        pid = content.strip()  
        if not content.strip():  
            raise ValueError(f"Haven't started yet")
    print(pid)

    monitor = CgroupMonitor(
        "unified" if args.type == "all" else args.type,
        pid,
        args.name
    )

    if not monitor.setup_cgroup():
        return

    try:
        print(f"\nStarting monitoring of PID {pid} ")
        print("Press Ctrl+C to stop monitoring\n")
        
        while True:
            print("\n" + "="*50)
            print(f"Monitoring cgroup: {args.name}")
            if args.type in ['memory', 'all']:
                monitor.monitor_memory()
            if args.type in ['cpu', 'all']:
                monitor.monitor_cpu()
            if args.type in ['io', 'all']:
                monitor.monitor_io()
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopping monitoring...")
        monitor.cleanup()

if __name__ == "__main__":
    main()
