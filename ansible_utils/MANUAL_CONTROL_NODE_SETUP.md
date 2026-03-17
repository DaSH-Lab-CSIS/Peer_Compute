# Manual Control Node Setup (Single-Node Test)

Run these steps on the **control node** (e.g. utorda1 or utorda2) to mirror the "Setup Control Node" playbook and test the full flow manually. Replace placeholders with your values.

**Use an env file so you don't substitute placeholders by hand:**

```bash
cd ansible_utils
cp .env.example .env
# Edit .env: set YOUR_USER and YOUR_GITHUB_PAT, then:
source .env
```

After that, `$YOUR_USER`, `$YOUR_GITHUB_PAT`, and `$PROJECT_DIR` are set for the rest of the session; use them in the commands below.

**Placeholders (if not using .env):**
- `YOUR_USER` — control node SSH user (e.g. `peercompute`)
- `YOUR_GITHUB_PAT` — GitHub Personal Access Token (or use the one from `ansible_utils/playbooks/secrets.yml` via `ansible-vault view playbooks/secrets.yml`)

**Project dir used below:** `$PROJECT_DIR` or `/home/YOUR_USER/deploy/Serverless_Scheduler`

---

## 1. Bootstrap python3-apt

```bash
sudo apt-get update && sudo apt-get install -y python3-apt
```

---

## 2. Install dependencies

```bash
sudo apt-get update
sudo apt-get install -y git python3-pip python3-venv
```

---

## 3. Create deployment directory

```bash
mkdir -p "$PROJECT_DIR"
# ensure ownership (if needed)
sudo chown -R "$YOUR_USER:$YOUR_USER" "$PROJECT_DIR"
```

---

## 4. Clone repository

```bash
git clone "https://${YOUR_GITHUB_PAT}@github.com/aalhadsawane/Serverless_Scheduler" "$PROJECT_DIR"
cd "$PROJECT_DIR"
git checkout main
# If repo already exists and you want to refresh:
# cd "$PROJECT_DIR" && git fetch && git reset --hard origin/main
```

---

## 5. Remove broken venv (if any)

```bash
rm -rf "$PROJECT_DIR/.venv"
```

---

## 6. Create virtualenv

```bash
python3 -m venv "$PROJECT_DIR/.venv"
```

---

## 7. Ensure pip in venv

```bash
"$PROJECT_DIR/.venv/bin/python" -m ensurepip --upgrade
```

---

## 8. Install Python requirements

```bash
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --no-input --index-url https://pypi.org/simple
```

---

## 9. Check if Django server is already running

```bash
pgrep -f 'manage.py runserver' || true
```

If this prints a PID, the server is already running; skip the next step or stop it first with `pkill -f 'manage.py runserver'`.

---

## 10. Start Django server

```bash
nohup "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scheduler/manage.py" runserver 0.0.0.0:8000 > "$PROJECT_DIR/django.log" 2>&1 &
```

Verify:

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/
# or
tail -f "$PROJECT_DIR/django.log"
```

---

## One-shot script (after sourcing .env)

Run `source .env` first (or set the exports below), then run:

```bash
# If you haven't already: source .env
sudo apt-get update && sudo apt-get install -y python3-apt git python3-pip python3-venv
mkdir -p "$PROJECT_DIR"
sudo chown -R "$YOUR_USER:$YOUR_USER" "$PROJECT_DIR"
git clone "https://${YOUR_GITHUB_PAT}@github.com/aalhadsawane/Serverless_Scheduler" "$PROJECT_DIR"
cd "$PROJECT_DIR" && git checkout main
rm -rf "$PROJECT_DIR/.venv"
python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/python" -m ensurepip --upgrade
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --no-input --index-url https://pypi.org/simple
pkill -f 'manage.py runserver' || true
nohup "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scheduler/manage.py" runserver 0.0.0.0:8000 > "$PROJECT_DIR/django.log" 2>&1 &
echo "Django should be starting; check $PROJECT_DIR/django.log and http://$(hostname -I | awk '{print $1}'):8000/"
```
