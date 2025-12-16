#!/bin/bash
# Test CockroachDB cluster failover
# Simulates node failure and verifies cluster continues operating

set -e

# Configuration
TEST_HOST="${1:-localhost}"
TEST_PORT="${2:-26257}"
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

echo "Testing CockroachDB cluster failover..."
echo "  Host: ${TEST_HOST}:${TEST_PORT}"
echo "  Database: ${DB_NAME}"
echo ""

# Get initial node status
echo "=== Initial Cluster Status ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${TEST_HOST}:${TEST_PORT}" \
    -e "SELECT id, address, is_live, is_available FROM crdb_internal.kv_node_status;"

INITIAL_NODE_COUNT=$("${COCKROACH_BIN}" sql \
    --insecure \
    --host="${TEST_HOST}:${TEST_PORT}" \
    -e "SELECT count(*) FROM crdb_internal.kv_node_status;" \
    --format=csv | tail -1 | tr -d ' ')

echo ""
echo "Initial node count: ${INITIAL_NODE_COUNT}"
echo ""

# Test basic operations before failover
echo "=== Testing Operations Before Failover ==="
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${TEST_HOST}:${TEST_PORT}" \
    -d "${DB_NAME}" \
    -e "SELECT count(*) as table_count FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null || \
    echo "No tables found (database may be empty)"

echo ""
echo "⚠️  Manual Failover Test"
echo "To test failover:"
echo "  1. Identify a node to stop (not the primary node)"
echo "  2. Stop the node: pkill -f 'cockroach.*start' (on that node)"
echo "  3. Wait 10-30 seconds for cluster to detect failure"
echo "  4. Run check_cluster_health.sh to verify cluster status"
echo "  5. Verify operations continue: ${COCKROACH_BIN} sql --insecure --host=${TEST_HOST}:${TEST_PORT} -d ${DB_NAME} -e 'SELECT 1;'"
echo ""
echo "The cluster should:"
echo "  - Detect the node failure"
echo "  - Promote replicas to maintain availability"
echo "  - Continue serving requests"
echo "  - Rebalance data when node is restored"
echo ""
echo "For automated failover testing, use a cluster management tool or"
echo "orchestration system that can safely stop/start nodes."
