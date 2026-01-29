#!/bin/bash
# Create database in CockroachDB cluster

set -e

# Configuration
DB_HOST="${1:-localhost}"
DB_PORT="${2:-26257}"
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

echo "Creating database '${DB_NAME}' in CockroachDB..."
echo "  Host: ${DB_HOST}:${DB_PORT}"

# Create database
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${DB_HOST}:${DB_PORT}" \
    -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME};"

if [ $? -eq 0 ]; then
    echo "Database '${DB_NAME}' created successfully!"
    
    # Verify creation
    echo ""
    echo "Verifying database creation..."
    "${COCKROACH_BIN}" sql \
        --insecure \
        --host="${DB_HOST}:${DB_PORT}" \
        -e "SHOW DATABASES;"
else
    echo "Error: Database creation failed"
    exit 1
fi
