# Remote Scheduler Management

This guide explains how to start, stop, and check schedulers on multiple remote nodes without manually SSHing into each one.

## Prerequisites

1. **SSH Config Setup**: The scripts look for SSH config in this order:
   - `.ssh.config` in the current directory (project root)
   - `~/.ssh/config` (fallback)
   - Or specify with `--ssh-config` option
   
   Your SSH config file should have entries for all the nodes you want to manage. The scripts automatically use ProxyJump if configured.

2. **Password Authentication (Optional)**: If you don't have SSH keys set up, you can use password authentication via a `.env` file:
   - Create a `.env` file in the project root
   - Add your passwords:
     ```
     JUMPNODE_PASSWORD=x
     NODE_PASSWORD=y
     ```
   - Install `sshpass` if not already installed: `sudo apt-get install sshpass`
   - **Security Note**: Add `.env` to `.gitignore` to avoid committing passwords!

3. **SSH Key Authentication (Recommended)**: For better security, set up SSH key-based authentication so you don't need passwords.

4. **Project Path**: The scripts will auto-detect the project path on remote hosts. Default paths checked:
   - `~/Serverless_Scheduler_sn34kyp3t3`
   - `~/Documents/Serverless_Scheduler`
   - `~/Serverless_Scheduler`

## Scripts

### 1. `start_schedulers_remote.py` - Start Schedulers

Start Django schedulers on multiple remote nodes.

**Basic Usage:**

```bash
# Start on all hosts matching a pattern
python start_schedulers_remote.py --pattern "colva.*peercompute"

# Start on specific hosts
python start_schedulers_remote.py --hosts colva2peercompute colva3peercompute anjuna2peercompute

# Start in background (detached mode)
python start_schedulers_remote.py --hosts colva2peercompute --background

# Custom port and scheduler name
python start_schedulers_remote.py --hosts colva2peercompute --port 8001 --scheduler-name colva2
```

**Options:**
- `--hosts`: List of specific host names from SSH config
- `--pattern`: Regex pattern to match host names (e.g., `"colva.*peercompute"`)
- `--port`: Port to run scheduler on (default: 8000)
- `--scheduler-name`: Scheduler name for MQTT (default: derived from hostname)
- `--background`: Run in background (detached mode)
- `--project-path`: Override project path on remote hosts
- `--ssh-config`: Path to SSH config file (default: `.ssh.config` in current dir, then `~/.ssh/config`)

**Examples:**

```bash
# Start all colva nodes
python start_schedulers_remote.py --pattern "colva.*peercompute"

# Start all nodes in background
python start_schedulers_remote.py --pattern ".*peercompute" --background

# Start with different ports
python start_schedulers_remote.py --hosts colva2peercompute --port 8000
python start_schedulers_remote.py --hosts colva3peercompute --port 8001
python start_schedulers_remote.py --hosts colva4peercompute --port 8002
```

**Background Mode:**
When running in background mode, logs are written to `/tmp/scheduler_<hostname>.log` on each remote host. You can check logs with:

```bash
ssh colva2peercompute "tail -f /tmp/scheduler_colva2peercompute.log"
```

### 2. `stop_schedulers_remote.py` - Stop Schedulers

Stop schedulers running on remote nodes.

**Usage:**

```bash
# Stop schedulers on all hosts matching pattern
python stop_schedulers_remote.py --pattern "colva.*peercompute"

# Stop schedulers on specific hosts
python stop_schedulers_remote.py --hosts colva2peercompute colva3peercompute

# Force kill (SIGKILL)
python stop_schedulers_remote.py --hosts colva2peercompute --force
```

**Options:**
- `--hosts`: List of specific host names
- `--pattern`: Regex pattern to match host names
- `--force`: Force kill schedulers (SIGKILL instead of SIGTERM)
- `--ssh-config`: Path to SSH config file

### 3. `check_schedulers_remote.py` - Check Status

Check the status of schedulers on remote nodes.

**Usage:**

```bash
# Check all hosts matching pattern
python check_schedulers_remote.py --pattern "colva.*peercompute"

# Check specific hosts
python check_schedulers_remote.py --hosts colva2peercompute colva3peercompute

# Check specific port
python check_schedulers_remote.py --hosts colva2peercompute --port 8000
```

**Output:**
The script shows:
- Whether the scheduler process is running
- Whether the port is listening
- Process ID (PID)
- Overall status

## Common Workflows

### Starting Multiple Schedulers

```bash
# Start all colva nodes on default port 8000
python start_schedulers_remote.py --pattern "colva.*peercompute"

# Start all anjuna nodes on default port 8000
python start_schedulers_remote.py --pattern "anjuna.*peercompute"

# Start all nodes in background
python start_schedulers_remote.py --pattern ".*peercompute" --background
```

### Starting with Different Ports

If you need different ports for each scheduler:

```bash
python start_schedulers_remote.py --hosts colva2peercompute --port 8000 --scheduler-name colva2
python start_schedulers_remote.py --hosts colva3peercompute --port 8001 --scheduler-name colva3
python start_schedulers_remote.py --hosts colva4peercompute --port 8002 --scheduler-name colva4
```

### Checking Status

```bash
# Quick status check
python check_schedulers_remote.py --pattern ".*peercompute"
```

### Stopping All Schedulers

```bash
# Stop all schedulers
python stop_schedulers_remote.py --pattern ".*peercompute"

# Force stop if needed
python stop_schedulers_remote.py --pattern ".*peercompute" --force
```

## Password Authentication Setup

If you need to use passwords instead of SSH keys:

1. **Create a `.env` file** in the project root:
   ```bash
   # Jumpnode password (for ProxyJump/bastion host)
   JUMPNODE_PASSWORD=x
   
   # Node password (for target compute nodes)
   NODE_PASSWORD=y
   ```

2. **Install sshpass** (required for password authentication):
   ```bash
   sudo apt-get install sshpass
   ```

3. **Add `.env` to `.gitignore`** to avoid committing passwords:
   ```bash
   echo ".env" >> .gitignore
   ```

4. **Alternative variable names** (all supported):
   - `JUMPNODE_PASS`, `JUMPNODE_PASSWORD`
   - `NODE_PASS`, `NODE_PASSWORD`, `USER_PASSWORD`, `USER_PASS`

The scripts will automatically load passwords from `.env` if the file exists. If passwords are not provided, the scripts will fall back to SSH key authentication or prompt for passwords.

## Troubleshooting

### SSH Connection Issues

If you get SSH connection errors:
1. Test SSH connection manually: `ssh colva2peercompute "echo 'Connected'"`
2. Ensure ProxyJump is working: Check your SSH config
3. Verify SSH key authentication is set up, or use `.env` file for passwords

### Password Authentication Issues

If password authentication isn't working:
1. Check if `sshpass` is installed: `which sshpass`
2. Verify `.env` file exists and has correct passwords
3. Check that variable names match: `JUMPNODE_PASSWORD` and `NODE_PASSWORD`
4. For ProxyJump scenarios, ensure jumpnode password is correct

### Scheduler Not Starting

1. Check if virtual environment exists on remote host
2. Verify project path is correct (use `--project-path` to override)
3. Check logs: `ssh <host> "cat /tmp/scheduler_<host>.log"`

### Port Already in Use

If port is already in use:
1. Check what's using it: `ssh <host> "netstat -tln | grep 8000"`
2. Stop existing scheduler: `python stop_schedulers_remote.py --hosts <host>`
3. Use a different port: `--port 8001`

### Scheduler Name Issues

The scheduler name is used for MQTT topics. If you need specific names:
- Use `--scheduler-name` option
- Or set `SCHEDULER_NAME` environment variable on remote host

## Notes

- The scripts use your SSH config, so ProxyJump and other SSH options are automatically applied
- All scripts support parallel execution (multiple hosts at once)
- Background mode is recommended for production use
- The scripts handle virtual environment activation automatically
- Scheduler name defaults to hostname if not specified

