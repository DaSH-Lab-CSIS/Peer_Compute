#!/bin/bash
# Initialize CockroachDB cluster
# This should be run once after all nodes are started

set -e

# Configuration
INIT_HOST="${1:-localhost}"
INIT_PORT="${2:-26257}"

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

echo "Initializing CockroachDB cluster..."
echo "  Host: ${INIT_HOST}:${INIT_PORT}"

# Initialize cluster
"${COCKROACH_BIN}" init \
    --insecure \
    --host="${INIT_HOST}:${INIT_PORT}"

if [ $? -eq 0 ]; then
    echo "Cluster initialized successfully!"
    echo ""
    echo "You can now:"
    echo "  1. Check cluster status: ${COCKROACH_BIN} sql --insecure --host=${INIT_HOST}:${INIT_PORT} -e 'SHOW NODES;'"
    echo "  2. Access admin UI: http://${INIT_HOST}:8080"
    echo "  3. Import schema and data"
else
    echo "Error: Cluster initialization failed"
    exit 1
fi
