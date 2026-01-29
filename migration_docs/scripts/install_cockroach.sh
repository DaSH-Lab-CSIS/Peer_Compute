#!/bin/bash
# Install CockroachDB binary on a single node
# This script can be run locally or remotely via SSH

set -e

COCKROACH_VERSION="${COCKROACH_VERSION:-v23.2.0}"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
DATA_DIR="${DATA_DIR:-/var/lib/cockroach}"

echo "Installing CockroachDB ${COCKROACH_VERSION}..."

# Download and extract CockroachDB
cd /tmp
echo "Downloading CockroachDB..."
wget -qO- "https://binaries.cockroachdb.com/cockroach-${COCKROACH_VERSION}.linux-amd64.tgz" | tar xvz

# Install binary
echo "Installing to ${INSTALL_DIR}..."
sudo cp "cockroach-${COCKROACH_VERSION}.linux-amd64/cockroach" "${INSTALL_DIR}/cockroach"
sudo chmod +x "${INSTALL_DIR}/cockroach"

# Create data directory
echo "Creating data directory ${DATA_DIR}..."
sudo mkdir -p "${DATA_DIR}"
sudo chown -R "$(whoami):$(whoami)" "${DATA_DIR}" || true

# Verify installation
echo "Verifying installation..."
"${INSTALL_DIR}/cockroach" version

echo ""
echo "CockroachDB installed successfully!"
echo "  Binary: ${INSTALL_DIR}/cockroach"
echo "  Data directory: ${DATA_DIR}"
echo ""
echo "To use from project directory instead, set INSTALL_DIR to project path"
