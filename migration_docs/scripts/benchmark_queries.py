#!/usr/bin/env python3
"""
Benchmark query performance between Supabase and CockroachDB.
Compares execution times for common queries.
"""

import os
import sys
import time
import psycopg2
import statistics
from pathlib import Path

def connect_supabase():
    """Connect to Supabase PostgreSQL."""
    return psycopg2.connect(
        host="aws-0-ap-south-1.pooler.supabase.com",
        port=5432,
        database="postgres",
        user="postgres.uufnsxmqnwegackubear",
        password="16G6MNonNa7ny9pG",
        options="-c pool_mode=session"
    )

def connect_cockroach(host: str = "localhost", port: int = 26257, database: str = "peercompute"):
    """Connect to CockroachDB."""
    return psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user="root",
        password="",
        sslmode="disable"
    )

def benchmark_query(conn, query: str, name: str, iterations: int = 5):
    """Benchmark a query and return average execution time."""
    times = []
    
    for i in range(iterations):
        start = time.time()
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                results = cur.fetchall()
            elapsed = time.time() - start
            times.append(elapsed)
        except Exception as e:
            print(f"  ⚠️  Query failed: {e}")
            return None
    
    avg_time = statistics.mean(times)
    min_time = min(times)
    max_time = max(times)
    
    return {
        'name': name,
        'avg': avg_time,
        'min': min_time,
        'max': max_time,
        'iterations': iterations
    }

def run_benchmarks(
    cockroach_host: str = "localhost",
    cockroach_port: int = 26257,
    cockroach_db: str = "peercompute",
    iterations: int = 5
):
    """Run benchmarks on both databases."""
    
    print("Connecting to databases...")
    try:
        supabase_conn = connect_supabase()
        print("✅ Connected to Supabase")
    except Exception as e:
        print(f"❌ Failed to connect to Supabase: {e}")
        return False
    
    try:
        cockroach_conn = connect_cockroach(cockroach_host, cockroach_port, cockroach_db)
        print("✅ Connected to CockroachDB")
    except Exception as e:
        print(f"❌ Failed to connect to CockroachDB: {e}")
        supabase_conn.close()
        return False
    
    # Define benchmark queries
    queries = [
        ("SELECT COUNT(*) FROM profiles_user;", "Count Users"),
        ("SELECT COUNT(*) FROM providers_job;", "Count Jobs"),
        ("SELECT * FROM profiles_user WHERE is_provider = true LIMIT 100;", "Get Providers"),
        ("SELECT * FROM providers_job ORDER BY start_time DESC LIMIT 50;", "Recent Jobs"),
        ("SELECT provider_id, COUNT(*) as job_count FROM providers_job GROUP BY provider_id;", "Jobs per Provider"),
        ("SELECT * FROM profiles_user WHERE active = true AND ready = true;", "Active Ready Users"),
    ]
    
    print()
    print("=" * 80)
    print("Query Performance Benchmark")
    print("=" * 80)
    print()
    
    results = []
    
    for query, name in queries:
        print(f"Benchmarking: {name}")
        print(f"  Query: {query[:60]}...")
        
        # Benchmark Supabase
        supabase_result = benchmark_query(supabase_conn, query, f"Supabase - {name}", iterations)
        
        # Benchmark CockroachDB
        cockroach_result = benchmark_query(cockroach_conn, query, f"CockroachDB - {name}", iterations)
        
        if supabase_result and cockroach_result:
            speedup = supabase_result['avg'] / cockroach_result['avg']
            results.append({
                'query': name,
                'supabase': supabase_result,
                'cockroach': cockroach_result,
                'speedup': speedup
            })
            
            print(f"  Supabase:    {supabase_result['avg']*1000:.2f}ms (avg), {supabase_result['min']*1000:.2f}ms (min), {supabase_result['max']*1000:.2f}ms (max)")
            print(f"  CockroachDB: {cockroach_result['avg']*1000:.2f}ms (avg), {cockroach_result['min']*1000:.2f}ms (min), {cockroach_result['max']*1000:.2f}ms (max)")
            
            if speedup > 1:
                print(f"  ✅ CockroachDB is {speedup:.2f}x faster")
            elif speedup < 1:
                print(f"  ⚠️  CockroachDB is {1/speedup:.2f}x slower")
            else:
                print(f"  ➡️  Performance is similar")
        
        print()
    
    # Summary
    print("=" * 80)
    print("Summary")
    print("=" * 80)
    print()
    print(f"{'Query':<30} {'Supabase (ms)':<15} {'CockroachDB (ms)':<18} {'Speedup':<10}")
    print("-" * 80)
    
    for result in results:
        supabase_avg = result['supabase']['avg'] * 1000
        cockroach_avg = result['cockroach']['avg'] * 1000
        speedup = result['speedup']
        
        print(f"{result['query']:<30} {supabase_avg:<15.2f} {cockroach_avg:<18.2f} {speedup:<10.2f}x")
    
    # Cleanup
    supabase_conn.close()
    cockroach_conn.close()
    
    return True

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Benchmark query performance between Supabase and CockroachDB',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--cockroach-host',
        default='localhost',
        help='CockroachDB host (default: localhost)'
    )
    
    parser.add_argument(
        '--cockroach-port',
        type=int,
        default=26257,
        help='CockroachDB port (default: 26257)'
    )
    
    parser.add_argument(
        '--cockroach-db',
        default='peercompute',
        help='CockroachDB database name (default: peercompute)'
    )
    
    parser.add_argument(
        '--iterations',
        type=int,
        default=5,
        help='Number of iterations per query (default: 5)'
    )
    
    args = parser.parse_args()
    
    success = run_benchmarks(
        cockroach_host=args.cockroach_host,
        cockroach_port=args.cockroach_port,
        cockroach_db=args.cockroach_db,
        iterations=args.iterations
    )
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
