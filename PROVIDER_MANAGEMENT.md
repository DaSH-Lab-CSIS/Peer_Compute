# Provider Remote Management Scripts

This document describes the provider management scripts for starting, stopping, and checking providers on remote nodes.

## Overview

Similar to the scheduler management scripts, these scripts allow you to manage providers across multiple remote nodes without manually SSHing into each one.

## Architecture

- **Location-based identification**: Hostnames follow the pattern `<location>peercompute` (e.g., `colva2peercompute`)
- **API-based user_id lookup**: The scheduler API provides user_ids for each location
- **SSH-based execution**: Providers are started via SSH on remote hosts

## Scripts

### 1. `start_providers_remote.py`

Starts providers on remote nodes.

**Usage:**
```bash
# Start providers on all hosts matching pattern
python start_providers_remote.py --pattern "colva.*peercompute"

# Start providers on specific hosts
python start_providers_remote.py --hosts colva2peercompute colva3peercompute

# Start in background
python start_providers_remote.py --hosts colva2peercompute --background

# Specify scheduler URL for API calls
python start_providers_remote.py --pattern "colva.*peercompute" --scheduler-url http://10.8.1.18:8001
```

**How it works:**
1. Parses SSH config to find hosts matching pattern or specified hosts
2. Extracts location from hostname (e.g., `colva2peercompute` → `colva2`)
3. Calls scheduler API endpoint `/providers/get_user_id/?location=<location>` to get user_id
4. SSHs into each host and runs: `python provider/provider1.py <user_id>`

**Options:**
- `--hosts`: Specific host names (space-separated)
- `--pattern`: Regex pattern to match host names
- `--scheduler-url`: Base URL of scheduler API (default: `http://localhost:8001`)
- `--background`: Run providers in background (detached)
- `--ssh-config`: Path to SSH config file (default: `.ssh.config` in current dir, then `~/.ssh/config`)
- `--env-file`: Path to .env file with passwords (default: `.env`)
- `--ssh-key`: Path to SSH private key (default: `~/.ssh/id_peercompute`)
- `--verbose`: Enable verbose logging
- `--skip-docker-check`: Skip Docker permission check before starting (not recommended)

### 2. `stop_providers_remote.py`

Stops providers running on remote nodes.

**Usage:**
```bash
# Stop providers on all hosts matching pattern
python stop_providers_remote.py --pattern "colva.*peercompute"

# Stop providers on specific hosts
python stop_providers_remote.py --hosts colva2peercompute colva3peercompute

# Force kill
python stop_providers_remote.py --pattern "colva.*peercompute" --force
```

**How it works:**
1. Parses SSH config to find hosts
2. SSHs into each host and kills processes matching `python.*provider1.py`

**Options:**
- `--hosts`: Specific host names
- `--pattern`: Regex pattern to match host names
- `--force`: Force kill (SIGKILL)
- `--ssh-config`: Path to SSH config file
- `--env-file`: Path to .env file with passwords

### 3. `check_providers_remote.py`

Checks the status of providers on remote nodes.

**Usage:**
```bash
# Check providers on all hosts matching pattern
python check_providers_remote.py --pattern "colva.*peercompute"

# Check providers on specific hosts
python check_providers_remote.py --hosts colva2peercompute colva3peercompute
```

**Output:**
```
Checking providers on 3 host(s)...

Host                      Process    PID        Status
------------------------------------------------------------
colva2peercompute         ✅ Running  12345      ✅ OK
colva3peercompute         ❌ Stopped  N/A        ❌ Stopped
colva4peercompute         ✅ Running  67890      ✅ OK
```

**Options:**
- `--hosts`: Specific host names
- `--pattern`: Regex pattern to match host names
- `--ssh-config`: Path to SSH config file
- `--env-file`: Path to .env file with passwords

## API Endpoint

### `GET /providers/get_user_id/`

Returns the latest user_id for an active provider at a given location.

**Query Parameters:**
- `location` (required): Location string (e.g., 'colva2', 'colva3')

**Response:**
```json
{
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "location": "colva2",
    "ready": true,
    "last_ready_signal": "2024-01-01T12:00:00Z"
}
```

**Error Response:**
```json
{
    "error": "No active provider found for location: colva2"
}
```

**Implementation:**
- Queries `User.objects.filter(is_provider=True, active=True, location=location)`
- Orders by `-last_ready_signal, -id` to get the latest
- Returns the first matching user_id

## Location Extraction

The scripts extract location from hostnames using the pattern:
- Hostname: `<location>peercompute`
- Example: `colva2peercompute` → location `colva2`

This matches the SSH config naming convention where all provider hosts end with `peercompute`.

## SSH Configuration

The scripts use the same SSH configuration as the scheduler scripts:
- Default: `.ssh.config` in current directory
- Fallback: `~/.ssh/config`
- SSH key: `~/.ssh/id_peercompute` (default)
- Password authentication: Via `.env` file (if SSH keys unavailable)

## Background Execution

When running in background mode:
- Providers run with `nohup` and output is redirected to `/tmp/provider_<hostname>.log`
- Check logs: `tail -f /tmp/provider_<hostname>.log`
- Stop providers: Use `stop_providers_remote.py`

## Examples

### Start all providers on colva nodes
```bash
python start_providers_remote.py --pattern "colva.*peercompute" --scheduler-url http://10.8.1.18:8001 --background
```

### Check provider status
```bash
python check_providers_remote.py --pattern ".*peercompute"
```

### Stop all providers
```bash
python stop_providers_remote.py --pattern ".*peercompute"
```

### Start specific providers
```bash
python start_providers_remote.py --hosts colva2peercompute colva3peercompute --scheduler-url http://10.8.1.18:8001
```

## Troubleshooting

### "No user_id found for location"
- Ensure the scheduler is running and accessible
- Check that there's an active provider User record with `is_provider=True`, `active=True`, and matching `location`
- Verify the scheduler URL is correct

### "No hosts selected"
- Check your SSH config file path
- Verify hostnames match the pattern (should end with `peercompute`)
- Use `--verbose` to see available hosts

### SSH connection issues
- See `REMOTE_SCHEDULER_MANAGEMENT.md` for SSH troubleshooting
- Ensure SSH keys are set up or passwords are in `.env` file

### Docker Permission Errors

If you see errors like:
```
PermissionError: [Errno 13] Permission denied
docker.errors.DockerException: Error while fetching server API version
```

**Solution:**
1. Add user to docker group on the remote host:
   ```bash
   sudo usermod -aG docker $USER
   ```
2. Log out and log back in (or restart SSH session)
3. Verify: `docker ps` should work without sudo

**Alternative:** If you can't add user to docker group, you may need to run providers with `sudo`, but this is not recommended.

**Note:** The script now automatically checks Docker permissions before starting providers and will warn you if there are issues. You can skip this check with `--skip-docker-check`, but it's not recommended.

### Import Errors (Non-Critical)

Warnings like:
- `cannot import name 'get_experiment_log_dir'`
- `cannot import name 'Sentinel' from 'typing_extensions'`

These are handled gracefully and won't prevent providers from running. They're related to optional experiment logging features.

## Related Documentation

- `REMOTE_SCHEDULER_MANAGEMENT.md`: Scheduler management scripts documentation
- `PASSWORD_AUTH_SETUP.md`: SSH password authentication setup
- `remote_ssh_utils.py`: Shared SSH utility functions

