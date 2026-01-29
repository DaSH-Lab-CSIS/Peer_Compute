#!/bin/bash
# Start a single CockroachDB node
# This script is used by start_cockroach_cluster.py to start nodes remotely

set -e

# Configuration
ADVERTISE_ADDR="${1:-localhost}"
JOIN_LIST="${2:-}"
DATA_DIR="${DATA_DIR:-/var/lib/cockroach/data}"
CACHE_SIZE="${CACHE_SIZE:-.25}"
MAX_SQL_MEMORY="${MAX_SQL_MEMORY:-.25}"
HTTP_PORT="${HTTP_PORT:-8080}"
SQL_PORT="${SQL_PORT:-26257}"
LOCALITY="${LOCALITY:-}"

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

# Create data directory if it doesn't exist
mkdir -p "${DATA_DIR}"

# Build start command
START_CMD="${COCKROACH_BIN} start --insecure"

# Add advertise address
START_CMD="${START_CMD} --advertise-addr=${ADVERTISE_ADDR}"

# Add join list if provided
if [ -n "${JOIN_LIST}" ]; then
    START_CMD="${START_CMD} --join=${JOIN_LIST}"
fi

# Add storage
START_CMD="${START_CMD} --store=path=${DATA_DIR}"

# Add cache and memory settings
START_CMD="${START_CMD} --cache=${CACHE_SIZE}"
START_CMD="${START_CMD} --max-sql-memory=${MAX_SQL_MEMORY}"

# Add HTTP port
START_CMD="${START_CMD} --http-addr=${ADVERTISE_ADDR}:${HTTP_PORT}"

# Add locality if provided
if [ -n "${LOCALITY}" ]; then
    START_CMD="${START_CMD} --locality=${LOCALITY}"
fi

# Start in background
START_CMD="${START_CMD} --background"

echo "Starting CockroachDB node..."
echo "  Advertise address: ${ADVERTISE_ADDR}"
echo "  Data directory: ${DATA_DIR}"
echo "  Join list: ${JOIN_LIST}"
echo "  Command: ${START_CMD}"

# Execute start command
eval "${START_CMD}"

# Wait a moment and check if it started
sleep 2

# Check if process is running
if pgrep -f "cockroach.*start" > /dev/null; then
    echo "CockroachDB node started successfully"
    echo "  SQL endpoint: ${ADVERTISE_ADDR}:${SQL_PORT}"
    echo "  HTTP endpoint: http://${ADVERTISE_ADDR}:${HTTP_PORT}"
else
    echo "Error: CockroachDB node failed to start"
    exit 1
fi
