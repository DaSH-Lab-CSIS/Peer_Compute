#!/usr/bin/env bash
# Run ansible-playbook with output logged to ansible_utils/logs/ with a timestamped filename.
# Usage: ./run_playbook.sh [ansible-playbook args...]
# Example: ./run_playbook.sh -i inventory.ini playbooks/setup.yml --limit managed --tags setup --ask-vault-pass

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p logs
LOG_FILE="logs/ansible-$(date +%Y%m%d-%H%M%S).log"
DEFAULT_LOG_PATH="$SCRIPT_DIR/$LOG_FILE"

# Some environments leave ansible_utils/logs owned by root; if it's not writable,
# fall back to /tmp so ansible-playbook does not abort before running.
if touch "$DEFAULT_LOG_PATH" 2>/dev/null; then
  export ANSIBLE_LOG_PATH="$DEFAULT_LOG_PATH"
  echo "Logging to $LOG_FILE"
else
  FALLBACK_LOG_PATH="/tmp/ansible-$(date +%Y%m%d-%H%M%S).log"
  export ANSIBLE_LOG_PATH="$FALLBACK_LOG_PATH"
  echo "Warning: $SCRIPT_DIR/logs is not writable; logging to $FALLBACK_LOG_PATH"
fi
exec ansible-playbook "$@"
