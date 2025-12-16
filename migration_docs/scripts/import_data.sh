#!/bin/bash
# Import data into CockroachDB
# Imports data from cleaned SQL dump

set -e

# Configuration
DB_HOST="${1:-localhost}"
DB_PORT="${2:-26257}"
DB_NAME="${3:-peercompute}"
DATA_FILE="${4:-$(dirname "$0")/../exports/supabase_dump_cleaned.sql}"

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

if [ ! -f "${DATA_FILE}" ]; then
    echo "Error: Data file not found: ${DATA_FILE}"
    echo "Usage: $0 [host] [port] [database] [data_file]"
    exit 1
fi

echo "Importing data into CockroachDB..."
echo "  Host: ${DB_HOST}:${DB_PORT}"
echo "  Database: ${DB_NAME}"
echo "  Data file: ${DATA_FILE}"
echo "  File size: $(du -h "${DATA_FILE}" | cut -f1)"
echo ""

# Check if file contains data (INSERT statements)
if ! grep -q "INSERT INTO" "${DATA_FILE}"; then
    echo "Warning: No INSERT statements found in data file"
    echo "This may be a schema-only dump. Skipping data import."
    exit 0
fi

echo "Importing data (this may take a while for large datasets)..."
echo "Progress will be shown below..."
echo ""

# Import data
# Use batch mode for better performance
"${COCKROACH_BIN}" sql \
    --insecure \
    --host="${DB_HOST}:${DB_PORT}" \
    -d "${DB_NAME}" \
    --format=csv < "${DATA_FILE}" 2>&1 | \
    while IFS= read -r line; do
        if [[ "$line" =~ (ERROR|error|Error) ]]; then
            echo "ERROR: $line" >&2
        elif [[ "$line" =~ (INSERT|CREATE|ALTER) ]]; then
            echo "$line"
        fi
    done

if [ $? -eq 0 ]; then
    echo ""
    echo "Data import complete!"
    echo ""
    echo "Verifying data..."
    "${COCKROACH_BIN}" sql \
        --insecure \
        --host="${DB_HOST}:${DB_PORT}" \
        -d "${DB_NAME}" \
        -e "SELECT table_name, (SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = t.table_name) as exists FROM information_schema.tables t WHERE table_schema = 'public' LIMIT 5;"
else
    echo "Error: Data import failed"
    exit 1
fi
