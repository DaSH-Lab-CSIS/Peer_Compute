# Claude Code Rules for This Project

## Git Commits
- Do NOT add `Co-Authored-By: Claude` or any Claude attribution to commit messages.

## playbook command-
- when giving user a run playbook command, always give with -vvv
- always use the format: `cd ansible_utils && ./run_playbook.sh playbooks/<name>.yml -vvv --ask-vault-pass` — never `ansible-playbook` directly
