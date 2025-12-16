#!/bin/bash
# Backup CockroachDB cluster
# Creates a full backup of the database

set -e

# Configuration
BACKUP_HOST="${1:-localhost}"
BACKUP_PORT="${2:-26257}"
DB_NAME="${3:-peercompute}"
BACKUP_DIR="${4:-$(dirname "$0")/../backups}"
BACKUP_NAME="${5:-backup_$(date +%Y%m%d_%H%M%S)}"

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

# Create backup directory
mkdir -p "${BACKUP_DIR}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

echo "Backing up CockroachDB cluster..."
echo "  Host: ${BACKUP_HOST}:${BACKUP_PORT}"
echo "  Database: ${DB_NAME}"
echo "  Backup path: ${BACKUP_PATH}"
echo ""

# Create backup
echo "Creating backup (this may take a while)..."
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${BACKUP_HOST}:${BACKUP_PORT}" \
    -e "BACKUP DATABASE ${DB_NAME} TO '${BACKUP_PATH}';"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Backup created successfully!"
    echo "  Location: ${BACKUP_PATH}"
    echo ""
    echo "To restore, use:"
    echo "  ./restore_cluster.sh ${BACKUP_HOST} ${BACKUP_PORT} ${DB_NAME} ${BACKUP_PATH}"
else
    echo "❌ Backup failed"
    exit 1
fi
