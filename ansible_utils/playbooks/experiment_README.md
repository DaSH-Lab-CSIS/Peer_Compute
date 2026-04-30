# Experiment Playbook Usage

Run these commands from `ansible_utils/`.

## 1) One-time SSH prerequisite for load balancer host

```bash
./run_playbook.sh -i inventory.ini playbooks/experiment.yml --syntax-check
```

If the playbook fails with SSH access error, run once on this node:

```bash
ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
ssh-copy-id <user>@colva2.dashlab.in
ssh -o BatchMode=yes <user>@colva2.dashlab.in "echo ok"
```

## 2) Run baseline experiment

```bash
./run_playbook.sh -i inventory.ini playbooks/experiment.yml -K --ask-vault-pass
```

## 3) Run scenario override

```bash
./run_playbook.sh -i inventory.ini playbooks/experiment.yml -K --ask-vault-pass -e scenario=steady_load -e iterations=5
```

## 4) Run research mode with seed

```bash
./run_playbook.sh -i inventory.ini playbooks/experiment.yml -K --ask-vault-pass -e scenario=steady_load -e iterations=5 -e research_mode=true -e seed=42
```

## 5) Override load balancer SSH user or URL (optional)

```bash
./run_playbook.sh -i inventory.ini playbooks/experiment.yml -K --ask-vault-pass -e lb_ssh_user=peercompute -e lb_url=http://colva2.dashlab.in:9001
```
