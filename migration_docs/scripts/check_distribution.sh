#!/bin/bash
# Check data distribution across CockroachDB nodes
# Shows how data is distributed and replicated

set -e

# Configuration
CHECK_HOST="${1:-localhost}"
CHECK_PORT="${2:-26257}"
DB_NAME="${3:-peercompute}"

# Find cockroach binary
COCKROACH_BIN=""
if [ -f "/usr/local/bin/cockroach" ]; then
    COCKROACH_BIN="/usr/local/bin/cockroach"
elif [ -f "$(dirname "$0")/../../cockroach/bin/cockroach" ]; then
    COCKROACH_BIN="$(dirname "$0")/../../cockroach/bin/cockroach"
elif command -v cockroach >/dev/null 2>&1; then
    COCKROACH_BIN="$(command -v cockroach)"
else
    echo "Error: CockroachDB binary not found"
    exit 1
fi

echo "Checking data distribution in CockroachDB cluster..."
echo "  Host: ${CHECK_HOST}:${CHECK_PORT}"
echo "  Database: ${DB_NAME}"
echo ""

# Show nodes
echo "=== Cluster Nodes ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${CHECK_HOST}:${CHECK_PORT}" \
    -e "SELECT id, address, locality, is_live FROM crdb_internal.kv_node_status;"

echo ""
echo "=== Range Distribution ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${CHECK_HOST}:${CHECK_PORT}" \
    -d "${DB_NAME}" \
    -e "SELECT 
        table_name,
        count(*) as range_count,
        sum(range_size) as total_size_bytes,
        avg(range_size) as avg_range_size_bytes
    FROM [SHOW RANGES FROM DATABASE ${DB_NAME}]
    GROUP BY table_name
    ORDER BY total_size_bytes DESC;" 2>/dev/null || \
    echo "No ranges found (database may be empty)"

echo ""
echo "=== Replication Status ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${CHECK_HOST}:${CHECK_PORT}" \
    -e "SELECT 
        range_id,
        replicas,
        lease_holder,
        range_size
    FROM [SHOW RANGES FROM DATABASE ${DB_NAME}]
    LIMIT 10;" 2>/dev/null || \
    echo "No ranges found"

echo ""
echo "=== Disk Usage per Node ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${CHECK_HOST}:${CHECK_PORT}" \
    -e "SELECT 
        node_id,
        store_id,
        available / (1024*1024*1024) as available_gb,
        used / (1024*1024*1024) as used_gb,
        (used::float / (available + used) * 100) as usage_percent
    FROM crdb_internal.kv_store_status
    ORDER BY node_id;" 2>/dev/null || \
    echo "Could not retrieve disk usage"

echo ""
echo "Distribution check complete!"
