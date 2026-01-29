#!/usr/bin/env python3
"""
Verify data migration from Supabase to CockroachDB.
Compares row counts and sample data between source and destination.
"""

import argparse
import psycopg2
import sys
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

def get_table_names(conn):
    """Get list of tables in database."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        return [row[0] for row in cur.fetchall()]

def get_row_count(conn, table_name):
    """Get row count for a table."""
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table_name};")
            return cur.fetchone()[0]
    except Exception as e:
        print(f"  Error counting {table_name}: {e}")
        return None

def get_sample_data(conn, table_name, limit=5):
    """Get sample data from a table."""
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table_name} LIMIT {limit};")
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return columns, rows
    except Exception as e:
        print(f"  Error sampling {table_name}: {e}")
        return None, None

def verify_migration(
    cockroach_host: str = "localhost",
    cockroach_port: int = 26257,
    cockroach_db: str = "peercompute",
    verbose: bool = False
):
    """Verify data migration by comparing source and destination."""
    
    print("Connecting to Supabase (source)...")
    try:
        supabase_conn = connect_supabase()
        print("✅ Connected to Supabase")
    except Exception as e:
        print(f"❌ Failed to connect to Supabase: {e}")
        return False
    
    print("Connecting to CockroachDB (destination)...")
    try:
        cockroach_conn = connect_cockroach(cockroach_host, cockroach_port, cockroach_db)
        print("✅ Connected to CockroachDB")
    except Exception as e:
        print(f"❌ Failed to connect to CockroachDB: {e}")
        supabase_conn.close()
        return False
    
    try:
        # Get table lists
        print("\nGetting table lists...")
        supabase_tables = get_table_names(supabase_conn)
        cockroach_tables = get_table_names(cockroach_conn)
        
        print(f"  Supabase tables: {len(supabase_tables)}")
        print(f"  CockroachDB tables: {len(cockroach_tables)}")
        
        # Find common tables
        common_tables = set(supabase_tables) & set(cockroach_tables)
        missing_in_cockroach = set(supabase_tables) - set(cockroach_tables)
        extra_in_cockroach = set(cockroach_tables) - set(supabase_tables)
        
        if missing_in_cockroach:
            print(f"\n⚠️  Tables in Supabase but not in CockroachDB: {missing_in_cockroach}")
        if extra_in_cockroach:
            print(f"\nℹ️  Tables in CockroachDB but not in Supabase: {extra_in_cockroach}")
        
        if not common_tables:
            print("\n❌ No common tables found!")
            return False
        
        print(f"\nComparing {len(common_tables)} common tables...")
        print("=" * 60)
        
        all_match = True
        for table in sorted(common_tables):
            print(f"\n{table}:")
            
            # Compare row counts
            supabase_count = get_row_count(supabase_conn, table)
            cockroach_count = get_row_count(cockroach_conn, table)
            
            if supabase_count is None or cockroach_count is None:
                print(f"  ⚠️  Could not get row counts")
                all_match = False
                continue
            
            print(f"  Supabase rows: {supabase_count}")
            print(f"  CockroachDB rows: {cockroach_count}")
            
            if supabase_count == cockroach_count:
                print(f"  ✅ Row counts match")
            else:
                print(f"  ❌ Row counts differ (diff: {cockroach_count - supabase_count})")
                all_match = False
            
            # Compare sample data if verbose
            if verbose and supabase_count > 0:
                print(f"  Sample data comparison:")
                supabase_cols, supabase_rows = get_sample_data(supabase_conn, table, limit=3)
                cockroach_cols, cockroach_rows = get_sample_data(cockroach_conn, table, limit=3)
                
                if supabase_cols and cockroach_cols:
                    if set(supabase_cols) == set(cockroach_cols):
                        print(f"    ✅ Column names match")
                    else:
                        print(f"    ⚠️  Column names differ")
                        print(f"      Supabase: {supabase_cols}")
                        print(f"      CockroachDB: {cockroach_cols}")
        
        print("\n" + "=" * 60)
        if all_match:
            print("\n✅ All data verified successfully!")
            return True
        else:
            print("\n⚠️  Some discrepancies found. Review above.")
            return False
    
    finally:
        supabase_conn.close()
        cockroach_conn.close()

def main():
    parser = argparse.ArgumentParser(
        description='Verify data migration from Supabase to CockroachDB',
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
        '--verbose',
        '-v',
        action='store_true',
        help='Show detailed comparison including sample data'
    )
    
    args = parser.parse_args()
    
    success = verify_migration(
        cockroach_host=args.cockroach_host,
        cockroach_port=args.cockroach_port,
        cockroach_db=args.cockroach_db,
        verbose=args.verbose
    )
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
