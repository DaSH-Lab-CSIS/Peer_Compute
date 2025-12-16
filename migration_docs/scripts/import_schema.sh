#!/bin/bash
# Import schema into CockroachDB
# Imports the cleaned SQL dump schema

set -e

# Configuration
DB_HOST="${1:-localhost}"
DB_PORT="${2:-26257}"
DB_NAME="${3:-peercompute}"
SCHEMA_FILE="${4:-$(dirname "$0")/../exports/supabase_dump_cleaned.sql}"

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

if [ ! -f "${SCHEMA_FILE}" ]; then
    echo "Error: Schema file not found: ${SCHEMA_FILE}"
    echo "Usage: $0 [host] [port] [database] [schema_file]"
    exit 1
fi

echo "Importing schema into CockroachDB..."
echo "  Host: ${DB_HOST}:${DB_PORT}"
echo "  Database: ${DB_NAME}"
echo "  Schema file: ${SCHEMA_FILE}"
echo ""

# Extract schema-only from dump (CREATE TABLE, CREATE INDEX, etc.)
# We'll import the full cleaned dump and let CockroachDB handle it
echo "Importing schema (this may take a while)..."

# Use --schema-only flag if available, otherwise filter manually
if "${COCKROACH_BIN}" sql --help 2>&1 | grep -q "schema-only"; then
    # Import schema only
    "${COCKROACH_BIN}" sql \
        --insecure \
        --host="${DB_HOST}:${DB_PORT}" \
        -d "${DB_NAME}" \
        --schema-only < "${SCHEMA_FILE}"
else
    # Filter schema statements manually and import
    grep -E "^(CREATE|ALTER|DROP)" "${SCHEMA_FILE}" | \
    "${COCKROACH_BIN}" sql \
        --insecure \
        --host="${DB_HOST}:${DB_PORT}" \
        -d "${DB_NAME}" 2>&1 | grep -v "already exists" || true
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "Schema import complete!"
    echo ""
    echo "Verifying tables..."
    "${COCKROACH_BIN}" sql \
        --insecure \
        --host="${DB_HOST}:${DB_PORT}" \
        -d "${DB_NAME}" \
        -e "SHOW TABLES;"
else
    echo "Error: Schema import failed"
    exit 1
fi
