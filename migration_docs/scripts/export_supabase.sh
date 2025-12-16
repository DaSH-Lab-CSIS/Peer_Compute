#!/bin/bash
# Export data from Supabase PostgreSQL database
# This script exports both schema and data for migration to CockroachDB

set -e

# Database connection details from settings.py
DB_HOST="aws-0-ap-south-1.pooler.supabase.com"
DB_PORT="5432"
DB_NAME="postgres"
DB_USER="postgres.uufnsxmqnwegackubear"
DB_PASSWORD="16G6MNonNa7ny9pG"

# Output files
OUTPUT_DIR="$(dirname "$0")/../exports"
SCHEMA_FILE="${OUTPUT_DIR}/supabase_schema.sql"
DATA_FILE="${OUTPUT_DIR}/supabase_data.sql"
FULL_DUMP="${OUTPUT_DIR}/supabase_full_dump.sql"

# Create output directory
mkdir -p "${OUTPUT_DIR}"

echo "Exporting schema from Supabase..."
PGPASSWORD="${DB_PASSWORD}" pg_dump \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --schema-only \
  --no-owner \
  --no-privileges \
  -f "${SCHEMA_FILE}"

echo "Exporting data from Supabase..."
PGPASSWORD="${DB_PASSWORD}" pg_dump \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --data-only \
  --no-owner \
  --no-privileges \
  -f "${DATA_FILE}"

echo "Creating full dump (schema + data)..."
cat "${SCHEMA_FILE}" "${DATA_FILE}" > "${FULL_DUMP}"

echo "Export complete!"
echo "  Schema: ${SCHEMA_FILE}"
echo "  Data: ${DATA_FILE}"
echo "  Full dump: ${FULL_DUMP}"
echo ""
echo "File sizes:"
ls -lh "${OUTPUT_DIR}"/*.sql
