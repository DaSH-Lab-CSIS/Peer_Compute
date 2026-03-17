#!/usr/bin/env bash
# Run ansible-playbook with output logged to ansible_utils/logs/ with a timestamped filename.
# Usage: ./run_playbook.sh [ansible-playbook args...]
# Example: ./run_playbook.sh -i inventory.ini playbooks/setup.yml --limit managed --tags setup --ask-vault-pass

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p logs
LOG_FILE="logs/ansible-$(date +%Y%m%d-%H%M%S).log"
export ANSIBLE_LOG_PATH="$SCRIPT_DIR/$LOG_FILE"
echo "Logging to $LOG_FILE"
exec ansible-playbook "$@"
