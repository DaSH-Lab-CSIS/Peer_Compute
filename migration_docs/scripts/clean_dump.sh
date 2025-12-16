#!/bin/bash
# Clean SQL dump for CockroachDB compatibility
# Removes PostgreSQL-specific features that CockroachDB doesn't support

set -e

INPUT_FILE="${1:-$(dirname "$0")/../exports/supabase_full_dump.sql}"
OUTPUT_FILE="${2:-$(dirname "$0")/../exports/supabase_dump_cleaned.sql}"

if [ ! -f "${INPUT_FILE}" ]; then
    echo "Error: Input file not found: ${INPUT_FILE}"
    echo "Usage: $0 [input_file] [output_file]"
    exit 1
fi

echo "Cleaning SQL dump for CockroachDB compatibility..."
echo "Input: ${INPUT_FILE}"
echo "Output: ${OUTPUT_FILE}"

# Create output directory if needed
mkdir -p "$(dirname "${OUTPUT_FILE}")"

# Clean the dump file
cat "${INPUT_FILE}" | \
    # Remove PostgreSQL-specific extensions
    sed -E 's/CREATE EXTENSION IF NOT EXISTS [^;]+;//g' | \
    # Remove COMMENT ON statements (CockroachDB has limited support)
    sed -E 's/COMMENT ON [^;]+;//g' | \
    # Remove SET statements that are PostgreSQL-specific
    sed -E 's/^SET [^;]+;//g' | \
    # Remove ALTER TABLE ... OWNER TO (no owner concept in CockroachDB)
    sed -E 's/ALTER TABLE [^;]+ OWNER TO [^;]+;//g' | \
    # Remove ALTER SEQUENCE ... OWNED BY (if sequences are auto-managed)
    sed -E 's/ALTER SEQUENCE [^;]+ OWNED BY [^;]+;//g' | \
    # Remove GRANT/REVOKE statements (different permission model)
    sed -E 's/(GRANT|REVOKE) [^;]+;//g' | \
    # Remove CREATE INDEX CONCURRENTLY (not supported, use regular CREATE INDEX)
    sed -E 's/CREATE INDEX CONCURRENTLY/CREATE INDEX/g' | \
    # Remove TABLESPACE clauses
    sed -E 's/ TABLESPACE [^ ]+//g' | \
    # Remove WITH (storage_parameter) clauses that are PostgreSQL-specific
    sed -E 's/ WITH \(storage_parameter[^)]+\)//g' | \
    # Remove PostgreSQL-specific data types that might cause issues
    # (Keep common ones like text, integer, etc.)
    # Remove empty lines and normalize whitespace
    sed '/^[[:space:]]*$/d' | \
    # Ensure statements end with semicolon
    sed -E 's/;([^;])/;\n\1/g' > "${OUTPUT_FILE}"

echo "Cleaning complete!"
echo "Output file: ${OUTPUT_FILE}"
echo "File size: $(du -h "${OUTPUT_FILE}" | cut -f1)"

# Check for potential issues
echo ""
echo "Checking for potential compatibility issues..."
if grep -i "CREATE EXTENSION" "${OUTPUT_FILE}" 2>/dev/null; then
    echo "WARNING: Found CREATE EXTENSION statements (may need manual removal)"
fi
if grep -i "COMMENT ON" "${OUTPUT_FILE}" 2>/dev/null; then
    echo "WARNING: Found COMMENT ON statements (may need manual removal)"
fi
if grep -i "CONCURRENTLY" "${OUTPUT_FILE}" 2>/dev/null; then
    echo "WARNING: Found CONCURRENTLY keyword (should be removed)"
fi

echo ""
echo "Cleaned dump ready for CockroachDB import!"
