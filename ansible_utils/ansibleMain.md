# Ansible Deployment Guide

This guide describes how to use the provided Ansible playbook (`setup.yml`) to deploy and manage the Serverless Scheduler cluster.

Ensure your `pwd` is ansible_utils before running this.

**Logging:** Playbook output is written to `ansible_utils/logs/`. By default, `ansible.cfg` appends to `logs/ansible.log`. For a separate log file per run (timestamped), use the wrapper: `./run_playbook.sh ...` (see below).

## Running the Playbook

### 1. Basic Setup (Deployment)

For a timestamped log per run use: `./run_playbook.sh -i inventory.ini playbooks/setup.yml -K --ask-vault-pass --tags setup`. Otherwise output appends to `logs/ansible.log`.

This command will:
*   Setup the Control Node (start Django Scheduler).
*   Setup Managed Nodes (install dependencies, register provider, start provider script).

```bash
ansible-playbook -i inventory.ini playbooks/setup.yml -K --ask-vault-pass --tags=setup
```

password is `peercompute`

### 1.1 Direct Provider Invocation (Internal Testing)

For a timestamped log per run use:
`./run_playbook.sh -i inventory.ini playbooks/direct_provider_invocation.yml -K --ask-vault-pass -e 'service_ids=[3,12]' -e 'direct_invocation_timeout=300'`.

Equivalent plain Ansible command:
```bash
ansible-playbook -i inventory.ini playbooks/direct_provider_invocation.yml -K --ask-vault-pass -e 'service_ids=[3,12]' -e 'direct_invocation_timeout=300'
```

### 2. Run Experiments

To trigger the experiment loop (running services on the cluster), you can use the `experiment` tag or the `run_experiment` variable.

**Using Tags (Recommended):**
This runs *only* the experiment tasks, skipping the setup verification steps.
```bash
ansible-playbook -i inventory.ini setup.yml --tags experiment --extra-vars "run_experiment=true"
```

**Run Everything (Setup + Experiment):**
This ensures setup is correct and then runs experiments.
```bash
ansible-playbook -i inventory.ini setup.yml --extra-vars "run_experiment=true"
```

### 3. Setup Only Specific Groups

If you only want to update the managed nodes or just the control node, use the `--limit` flag.

**Control Node only:**
```bash
ansible-playbook -i inventory.ini setup.yml --limit control --tags setup --ask-vault-pass
```

**Managed Nodes only:**
```bash
ansible-playbook -i inventory.ini setup.yml --limit managed --tags setup --ask-vault-pass
```

## Idempotency and State

*   **Provider Registration**: The playbook checks if a provider is already registered by looking for `provider_user_id.txt` on the managed node. It will skip registration if this file exists.
*   **Process Management**: It checks if the Django server or Provider script is already running before attempting to start them, preventing duplicate processes.

## Troubleshooting

*   **Connection Issues**: Ensure you can SSH into all nodes from the Ansible host without a password (using SSH keys).
*   **Race Conditions**: The managed nodes will wait for the Control Node (port 8000) to be ready. If this times out (default 300s), ensure the Control Node is starting correctly and there are no firewall rules blocking port 8000.
*   **Permissions**: The playbook uses `become: yes` to execute commands as root (sudo). Ensure your user has sudo privileges without a password or provide the sudo password via `-K` flag:
    ```bash
    ansible-playbook -i inventory.ini setup.yml -K --ask-vault-pass
    ```

    the ansible vault password is `peercompute`.