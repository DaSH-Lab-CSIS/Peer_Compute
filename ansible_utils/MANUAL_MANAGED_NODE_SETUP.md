# Manual Managed Node Setup (Single-Node Test)

The **Ansible playbook** runs *from* the control node (e.g. utorda2) and targets managed nodes; the play’s tasks run *on* each managed host over SSH. This doc is the **manual equivalent**: you SSH into **one managed node** (e.g. palolem1@10.1.19.137) and run the same steps by hand. The control node (scheduler) must already be running and reachable on port 8000.

**Env file (no manual substitution):**

You need a `.env` on the **managed node** with the variables below. That machine won’t have `ansible_utils` until after you clone the repo (step 4), so create `.env` in your home directory (e.g. copy from the control node or create manually):

```bash
# On the managed node: create ~/.env (e.g. copy .env.example from control node, or create by hand)
# Required:
#   export YOUR_USER=palolem1
#   export YOUR_GITHUB_PAT=<your-token>
#   export PROJECT_DIR="/home/${YOUR_USER}/deploy/Serverless_Scheduler"
#   export SCHEDULER_HOST=utorda1.dashlab.in
# Then:
source ~/.env
```

Use `YOUR_USER` as the user on **this** managed node (e.g. `palolem1`). After sourcing, `$PROJECT_DIR`, `$YOUR_USER`, `$YOUR_GITHUB_PAT`, and `$SCHEDULER_HOST` are set.

**Project dir:** `$PROJECT_DIR` = `/home/YOUR_USER/deploy/Serverless_Scheduler`

---

## 1. Bootstrap python3-apt

```bash
sudo apt-get update && sudo apt-get install -y python3-apt
```

---

## 2. Install dependencies

```bash
sudo apt-get update
sudo apt-get install -y git python3-pip python3-venv curl jq
```

---

## 3. Create deployment directory

```bash
mkdir -p "$PROJECT_DIR"
sudo chown -R "$YOUR_USER:$YOUR_USER" "$PROJECT_DIR"
```

---

## 4. Clone repository

```bash
git clone "https://${YOUR_GITHUB_PAT}@github.com/aalhadsawane/Serverless_Scheduler" "$PROJECT_DIR"
cd "$PROJECT_DIR"
git config --global --add safe.directory "$PROJECT_DIR"
git checkout main
```

---

## 5. Remove broken venv (if any)

```bash
rm -rf "$PROJECT_DIR/.venv"
```

---

## 6. Create virtualenv

**Option A – system Python (default):**

```bash
python3 -m venv "$PROJECT_DIR/.venv"
```

**Option B – conda / Miniforge:**

```bash
# If conda/miniforge is not installed yet (one-time per host):
# curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh
# bash Miniforge3-*.sh -b -p "$HOME/miniforge3"
# $HOME/miniforge3/bin/conda init bash && source ~/.bashrc

# Ensure you own the project dir (e.g. if it was created by root/Ansible)
sudo chown -R "$YOUR_USER:$YOUR_USER" "$PROJECT_DIR"

# Create env at project path (so $PROJECT_DIR/.venv/bin/python and pip still work)
conda create -p "$PROJECT_DIR/.venv" python=3.13 -y
```

If you get **EnvironmentNotWritableError**, the `.venv` path is not owned by you. Run `sudo chown -R "$YOUR_USER:$YOUR_USER" "$PROJECT_DIR"`, remove any existing `.venv` with `rm -rf "$PROJECT_DIR/.venv"`, then run the `conda create` again.

---

## 7. Ensure pip in venv

**Option A – system Python venv:**

```bash
"$PROJECT_DIR/.venv/bin/python" -m ensurepip --upgrade
```

**Option B – conda:** Skip this step; conda envs already include pip.

---

## 8. Install Python requirements

```bash
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --no-input --index-url https://pypi.org/simple
```

---

## 9. Ensure Docker is running

```bash
sudo systemctl start docker
sudo systemctl enable docker
```

---

## 10. Wait for Control Node (Scheduler) to be ready

```bash
# Replace with your control node host if not using SCHEDULER_HOST
until curl -s -o /dev/null -w "%{http_code}" "http://${SCHEDULER_HOST}:8000/" | grep -q 200; do echo "Waiting for scheduler..."; sleep 5; done
echo "Scheduler is ready."
```

---

## 11. Register provider (if not already) and get User ID

If `$PROJECT_DIR/provider_user_id.txt` already exists, skip to step 12. Otherwise register:

```bash
RESP=$(curl -s -X POST "http://${SCHEDULER_HOST}:8000/profiles/register_user/" \
  -H "Content-Type: application/json" \
  -d '{"is_provider":true,"is_developer":false,"active":true,"ready":true,"location":"'"$(hostname)"'","ram":16,"cpu":8}')
echo "$RESP" | jq -r '.user_id' > "$PROJECT_DIR/provider_user_id.txt"
```

---

## 12. Set provider User ID

```bash
PROVIDER_USER_ID=$(cat "$PROJECT_DIR/provider_user_id.txt")
echo "Provider User ID: $PROVIDER_USER_ID"
```

---

## 13. Calculate efficiency (first-time only)

Only needed once after registration:

```bash
curl -s "http://${SCHEDULER_HOST}:8000/providers/calculate_efficiency/${PROVIDER_USER_ID}"
```

---

## 14. Start provider script

```bash
pgrep -f 'provider1.py' && echo "Provider already running" || true
# If not running:
nohup "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/provider/provider1.py" "$PROVIDER_USER_ID" > "$PROJECT_DIR/provider.log" 2>&1 &
echo "Provider started. Log: $PROJECT_DIR/provider.log"
```

---

## One-shot script (after sourcing .env)

Create `~/.env` on the managed node with `YOUR_USER`, `YOUR_GITHUB_PAT`, `PROJECT_DIR`, and `SCHEDULER_HOST` (see top of this doc). Then run:

```bash
source ~/.env
SCHEDULER_URL="http://${SCHEDULER_HOST}:8000"

sudo apt-get update && sudo apt-get install -y python3-apt git python3-pip python3-venv curl jq
mkdir -p "$PROJECT_DIR"
sudo chown -R "$YOUR_USER:$YOUR_USER" "$PROJECT_DIR"
git clone "https://${YOUR_GITHUB_PAT}@github.com/aalhadsawane/Serverless_Scheduler" "$PROJECT_DIR"
cd "$PROJECT_DIR" && git checkout main
rm -rf "$PROJECT_DIR/.venv"
python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/python" -m ensurepip --upgrade
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --no-input --index-url https://pypi.org/simple
sudo systemctl start docker
sudo systemctl enable docker

until curl -s -o /dev/null -w "%{http_code}" "${SCHEDULER_URL}/" | grep -q 200; do echo "Waiting for scheduler..."; sleep 5; done

if [ ! -f "$PROJECT_DIR/provider_user_id.txt" ]; then
  RESP=$(curl -s -X POST "${SCHEDULER_URL}/profiles/register_user/" \
    -H "Content-Type: application/json" \
    -d '{"is_provider":true,"is_developer":false,"active":true,"ready":true,"location":"'"$(hostname)"'","ram":16,"cpu":8}')
  echo "$RESP" | jq -r '.user_id' > "$PROJECT_DIR/provider_user_id.txt"
  PROVIDER_USER_ID=$(cat "$PROJECT_DIR/provider_user_id.txt")
  curl -s "${SCHEDULER_URL}/providers/calculate_efficiency/${PROVIDER_USER_ID}"
fi
PROVIDER_USER_ID=$(cat "$PROJECT_DIR/provider_user_id.txt")

pgrep -f 'provider1.py' || nohup "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/provider/provider1.py" "$PROVIDER_USER_ID" > "$PROJECT_DIR/provider.log" 2>&1 &
echo "Done. Provider log: $PROJECT_DIR/provider.log"
```

**If using conda/miniforge:** replace the venv block (after `rm -rf "$PROJECT_DIR/.venv"`) with:
```bash
conda create -p "$PROJECT_DIR/.venv" python=3.13 -y
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --no-input --index-url https://pypi.org/simple
```
Then continue from `sudo systemctl start docker`.
