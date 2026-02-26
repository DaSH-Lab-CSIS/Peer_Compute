# Ansible Setup for Cortalim Nodes

This repository contains the setup files to automate tasks across **18 Cortalim nodes** using **Ansible**.

## Files:
- `inventory.ini`: Lists all Cortalim nodes with associated usernames for SSH access.
- `ansible.cfg`: Configures Ansible defaults like SSH key and privilege escalation settings.
- `group_vars`: Store group-level variables (if needed in the future).
- `playbooks`: Contains Ansible playbooks for automating tasks (e.g., `setup.yml`).

## Steps to use:
1. public ssh key (in ~/.ssh) of Utorda1 is present in all managed nodes.
2. To add new managed nodes or run this on a different control node, the ssh public key of control node will have to be copied to managed nodes.
    
    Use ```keygen_to_all.sh hosts.txt``` on control node for this. (replace hosts.txt with txt file containing user@IP for each managed node).
2. Modify `inventory.ini` as per needed. `ansible managed -i inventory.ini -m ping` for ping check.
3. Run playbooks with `ansible-playbook -i inventory.ini playbooks/setup.yml -K --ask-vault-pass`. This will only run when your pwd is `ansible_utils` or wherever you have your conf and ini files. the password for vault is `peercompute`.

For further help, refer to the Ansible documentation or contact the team.

