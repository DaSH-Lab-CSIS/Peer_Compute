#!/bin/bash
# Setup disk allocation for CockroachDB on a single node
# Creates a dedicated directory with optional size limits

set -e

DATA_DIR="${DATA_DIR:-/var/lib/cockroach/data}"
ALLOCATION_PERCENT="${ALLOCATION_PERCENT:-20}"
ALLOCATION_SIZE_GB="${ALLOCATION_SIZE_GB:-}"

echo "Setting up disk allocation for CockroachDB..."

# Get total disk space if percentage-based allocation
if [ -z "${ALLOCATION_SIZE_GB}" ] && [ -n "${ALLOCATION_PERCENT}" ]; then
    TOTAL_SPACE_GB=$(df -BG / | tail -1 | awk '{print $2}' | sed 's/G//')
    ALLOCATION_SIZE_GB=$((TOTAL_SPACE_GB * ALLOCATION_PERCENT / 100))
    echo "Total disk space: ${TOTAL_SPACE_GB}GB"
    echo "Allocation percent: ${ALLOCATION_PERCENT}%"
    echo "Allocated size: ${ALLOCATION_SIZE_GB}GB"
fi

# Create data directory
echo "Creating data directory: ${DATA_DIR}"
mkdir -p "${DATA_DIR}"
chmod 755 "${DATA_DIR}"

# If size limit specified, create a loop device with limited size
if [ -n "${ALLOCATION_SIZE_GB}" ] && [ "${ALLOCATION_SIZE_GB}" -gt 0 ]; then
    DISK_IMG="${DATA_DIR}/../disk.img"
    echo "Creating ${ALLOCATION_SIZE_GB}GB disk image: ${DISK_IMG}"
    
    # Create sparse file
    dd if=/dev/zero of="${DISK_IMG}" bs=1G count=0 seek="${ALLOCATION_SIZE_GB}" 2>/dev/null || \
    dd if=/dev/zero of="${DISK_IMG}" bs=1M count=$((ALLOCATION_SIZE_GB * 1024))
    
    # Setup loop device (requires sudo)
    if command -v losetup >/dev/null 2>&1; then
        LOOP_DEV=$(sudo losetup --find --show "${DISK_IMG}" 2>/dev/null || echo "")
        if [ -n "${LOOP_DEV}" ]; then
            echo "Formatting loop device: ${LOOP_DEV}"
            sudo mkfs.ext4 -F "${LOOP_DEV}" >/dev/null 2>&1 || true
            echo "Mounting to ${DATA_DIR}"
            sudo mount "${LOOP_DEV}" "${DATA_DIR}" || true
            sudo chown -R "$(whoami):$(whoami)" "${DATA_DIR}" || true
        fi
    fi
fi

# Set permissions
chown -R "$(whoami):$(whoami)" "${DATA_DIR}" 2>/dev/null || true

echo "Disk allocation setup complete!"
echo "  Data directory: ${DATA_DIR}"
if [ -n "${ALLOCATION_SIZE_GB}" ]; then
    echo "  Allocated size: ${ALLOCATION_SIZE_GB}GB"
fi
echo ""
echo "Available space:"
df -h "${DATA_DIR}" | tail -1
