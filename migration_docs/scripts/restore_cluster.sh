#!/bin/bash
# Restore CockroachDB cluster from backup
# Restores a database from a backup file

set -e

# Configuration
RESTORE_HOST="${1:-localhost}"
RESTORE_PORT="${2:-26257}"
DB_NAME="${3:-peercompute}"
BACKUP_PATH="${4:-}"

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

if [ -z "${BACKUP_PATH}" ]; then
    echo "Error: Backup path not specified"
    echo "Usage: $0 [host] [port] [database] [backup_path]"
    exit 1
fi

if [ ! -d "${BACKUP_PATH}" ] && [ ! -f "${BACKUP_PATH}" ]; then
    echo "Error: Backup path not found: ${BACKUP_PATH}"
    exit 1
fi

echo "Restoring CockroachDB cluster from backup..."
echo "  Host: ${RESTORE_HOST}:${RESTORE_PORT}"
echo "  Database: ${DB_NAME}"
echo "  Backup path: ${BACKUP_PATH}"
echo ""
echo "⚠️  WARNING: This will overwrite the existing database!"
read -p "Are you sure you want to continue? (yes/no): " confirm

if [ "${confirm}" != "yes" ]; then
    echo "Restore cancelled"
    exit 0
fi

# Drop existing database if it exists
echo "Dropping existing database (if exists)..."
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${RESTORE_HOST}:${RESTORE_PORT}" \
    -e "DROP DATABASE IF EXISTS ${DB_NAME} CASCADE;" 2>/dev/null || true

# Restore from backup
echo "Restoring from backup (this may take a while)..."
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${RESTORE_HOST}:${RESTORE_PORT}" \
    -e "RESTORE DATABASE ${DB_NAME} FROM '${BACKUP_PATH}';"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Restore completed successfully!"
    echo ""
    echo "Verifying restore..."
    "${COCKROACH_BIN}" sql \
        --insecure \
        --host="${RESTORE_HOST}:${RESTORE_PORT}" \
        -d "${DB_NAME}" \
        -e "SHOW TABLES;"
else
    echo "❌ Restore failed"
    exit 1
fi
