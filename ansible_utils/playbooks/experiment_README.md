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

## 6) Scheduler profile charts (runs automatically after testbed)

After the testbed finishes, the playbook runs `analyze_profile.py` on each `control` host
that has `scheduler/logs/scheduler_profile_run_*.jsonl`. Charts are written under
`scheduler/logs/profile_charts_run_*` on that host (e.g. utorda2).

```bash
# Disable post-experiment analysis
./run_playbook.sh -i inventory.ini playbooks/experiment.yml -K --ask-vault-pass -e run_profile_analysis=false

# Merge all profiling runs into one chart set
./run_playbook.sh -i inventory.ini playbooks/experiment.yml -K --ask-vault-pass -e profile_analysis_all=true
```

Fetch charts locally:

```bash
scp -r peercompute@utorda2.dashlab.in:~/deploy/Serverless_Scheduler/scheduler/logs/profile_charts_run_* .
```
