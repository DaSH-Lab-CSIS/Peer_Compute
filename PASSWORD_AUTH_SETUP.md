# Password Authentication Setup

This guide explains how to set up password authentication for remote scheduler management scripts.

## Quick Setup

1. **Copy the example file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` and add your passwords:**
   ```bash
   # Jumpnode password (for ProxyJump/bastion host like dashlab)
   JUMPNODE_PASSWORD=x
   
   # Node password (for compute nodes like colva2, colva3, etc.)
   NODE_PASSWORD=y
   ```

3. **Install sshpass (if not already installed):**
   ```bash
   sudo apt-get install sshpass
   ```

4. **Verify `.env` is in `.gitignore`** (it should already be there):
   ```bash
   grep .env .gitignore
   ```

## Usage

Once `.env` is set up, all three scripts will automatically use the passwords:

```bash
# Start schedulers (passwords loaded from .env)
python start_schedulers_remote.py --pattern "colva.*peercompute"

# Check status (passwords loaded from .env)
python check_schedulers_remote.py --pattern "colva.*peercompute"

# Stop schedulers (passwords loaded from .env)
python stop_schedulers_remote.py --pattern "colva.*peercompute"
```

## Supported Environment Variables

The scripts support multiple variable names for flexibility:

**Jumpnode Password:**
- `JUMPNODE_PASSWORD`
- `JUMPNODE_PASS`

**Node Password:**
- `NODE_PASSWORD`
- `NODE_PASS`
- `USER_PASSWORD`
- `USER_PASS`

## How It Works

1. Scripts automatically load `.env` file from the project root
2. If `sshpass` is available, passwords are passed via `sshpass -p <password> ssh ...`
3. If `sshpass` is not available, scripts fall back to SSH key authentication or prompt for passwords
4. ProxyJump (jumpnode) authentication is handled automatically by SSH config

## Security Notes

- **Never commit `.env` to git** - it's already in `.gitignore`
- Consider using SSH keys instead of passwords for better security
- If using passwords, ensure `.env` file has restricted permissions:
  ```bash
  chmod 600 .env
  ```

## Troubleshooting

**"sshpass not found" warning:**
- Install sshpass: `sudo apt-get install sshpass`
- Or set up SSH keys for passwordless authentication

**Passwords not working:**
- Verify `.env` file exists and has correct variable names
- Check that passwords are correct (no extra spaces)
- Test SSH connection manually: `ssh colva2peercompute "echo test"`

**ProxyJump issues:**
- Ensure jumpnode password is correct in `.env`
- Verify SSH config has ProxyJump configured correctly
- Test jumpnode connection: `ssh dashlab "echo test"`

