#!/bin/bash
# Check CockroachDB cluster health
# Verifies all nodes are running and healthy

set -e

# Configuration
CHECK_HOST="${1:-localhost}"
CHECK_PORT="${2:-26257}"

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

echo "Checking CockroachDB cluster health..."
echo "  Host: ${CHECK_HOST}:${CHECK_PORT}"
echo ""

# Check node status
echo "=== Node Status ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${CHECK_HOST}:${CHECK_PORT}" \
    -e "SELECT id, address, is_live, is_available FROM crdb_internal.kv_node_status;"

echo ""
echo "=== Cluster Settings ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${CHECK_HOST}:${CHECK_PORT}" \
    -e "SHOW CLUSTER SETTING version;"

echo ""
echo "=== Database List ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${CHECK_HOST}:${CHECK_PORT}" \
    -e "SHOW DATABASES;"

echo ""
echo "=== Range Distribution ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${CHECK_HOST}:${CHECK_PORT}" \
    -e "SELECT count(*) as range_count, avg(range_size) as avg_size FROM [SHOW RANGES FROM DATABASE defaultdb];" 2>/dev/null || \
    echo "No ranges found (cluster may not have data yet)"

echo ""
echo "Health check complete!"
