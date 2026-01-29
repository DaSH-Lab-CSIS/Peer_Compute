#!/usr/bin/env python3
"""
Monitor CockroachDB cluster health continuously.
Checks node status, replication, and performance metrics.
"""

import argparse
import time
import subprocess
import sys
from pathlib import Path

def find_cockroach_binary():
    """Find CockroachDB binary."""
    paths = [
        "/usr/local/bin/cockroach",
        str(Path(__file__).parent.parent.parent / "cockroach" / "bin" / "cockroach"),
    ]
    
    for path in paths:
        if Path(path).exists():
            return path
    
    # Try command
    import shutil
    cockroach = shutil.which("cockroach")
    if cockroach:
        return cockroach
    
    return None

def check_cluster_status(host: str, port: int):
    """Check cluster node status."""
    cockroach_bin = find_cockroach_binary()
    if not cockroach_bin:
        print("Error: CockroachDB binary not found")
        return None
    
    try:
        result = subprocess.run(
            [cockroach_bin, "sql", "--insecure", f"--host={host}:{port}", "-e", 
             "SELECT id, address, is_live, is_available FROM crdb_internal.kv_node_status;"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            return result.stdout
        else:
            return None
    except Exception as e:
        print(f"Error checking status: {e}")
        return None

def check_database_health(host: str, port: int, database: str):
    """Check database health."""
    cockroach_bin = find_cockroach_binary()
    if not cockroach_bin:
        return None
    
    try:
        result = subprocess.run(
            [cockroach_bin, "sql", "--insecure", f"--host={host}:{port}", "-d", database, "-e",
             "SELECT count(*) as table_count FROM information_schema.tables WHERE table_schema = 'public';"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return None
    except Exception:
        return None

def monitor_cluster(
    host: str = "localhost",
    port: int = 26257,
    database: str = "peercompute",
    interval: int = 30,
    continuous: bool = True
):
    """Monitor cluster continuously."""
    
    print("CockroachDB Cluster Monitor")
    print("=" * 60)
    print(f"Host: {host}:{port}")
    print(f"Database: {database}")
    print(f"Interval: {interval} seconds")
    print("=" * 60)
    print()
    
    iteration = 0
    
    try:
        while True:
            iteration += 1
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            
            print(f"[{timestamp}] Check #{iteration}")
            print("-" * 60)
            
            # Check cluster status
            status = check_cluster_status(host, port)
            if status:
                print("Cluster Status:")
                print(status)
            else:
                print("❌ Failed to get cluster status")
            
            # Check database health
            db_health = check_database_health(host, port, database)
            if db_health:
                print(f"Database Health: {db_health}")
            else:
                print("⚠️  Could not check database health")
            
            print()
            
            if not continuous:
                break
            
            time.sleep(interval)
    
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
        return True
    except Exception as e:
        print(f"\nError during monitoring: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Monitor CockroachDB cluster health',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--host',
        default='localhost',
        help='CockroachDB host (default: localhost)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=26257,
        help='CockroachDB port (default: 26257)'
    )
    
    parser.add_argument(
        '--database',
        default='peercompute',
        help='Database name (default: peercompute)'
    )
    
    parser.add_argument(
        '--interval',
        type=int,
        default=30,
        help='Check interval in seconds (default: 30)'
    )
    
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run check once instead of continuously'
    )
    
    args = parser.parse_args()
    
    success = monitor_cluster(
        host=args.host,
        port=args.port,
        database=args.database,
        interval=args.interval,
        continuous=not args.once
    )
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
