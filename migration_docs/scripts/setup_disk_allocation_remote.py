#!/usr/bin/env python3
"""
Setup disk allocation for CockroachDB on all scheduler nodes remotely.
Creates dedicated directories with optional size limits.
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path

# Add parent directory to path to import remote_ssh_utils
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from remote_ssh_utils import build_ssh_command, load_env_file

def parse_ssh_config(config_path: str):
    """Parse SSH config file and return host configurations."""
    hosts = {}
    current_host = None
    
    try:
        with open(config_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                
                key = parts[0].lower()
                value = parts[1]
                
                if key == 'host':
                    host_names = value.split()
                    for host_name in host_names:
                        if host_name not in hosts:
                            hosts[host_name] = {}
                        current_host = host_name
                elif current_host and key in ['hostname', 'user', 'proxyjump', 'port']:
                    hosts[current_host][key] = value
    
    except FileNotFoundError:
        print(f"Warning: SSH config file not found: {config_path}")
    except Exception as e:
        print(f"Error parsing SSH config: {e}")
    
    return hosts

def setup_disk_on_host(
    host: str,
    data_dir: str = "/var/lib/cockroach/data",
    allocation_percent: int = 20,
    allocation_size_gb: int = None,
    jumpnode_password: str = None,
    node_password: str = None,
    ssh_config_path: str = None,
    ssh_key_path: str = None,
    verbose: bool = False
):
    """Setup disk allocation on a remote host."""
    
    # Setup script content
    setup_script = f"""#!/bin/bash
set -e
DATA_DIR="{data_dir}"
ALLOCATION_PERCENT="{allocation_percent}"
ALLOCATION_SIZE_GB="{allocation_size_gb or ''}"

echo "[{host}] Setting up disk allocation..."

# Get total disk space if percentage-based
if [ -z "${{ALLOCATION_SIZE_GB}}" ] && [ -n "${{ALLOCATION_PERCENT}}" ]; then
    TOTAL_SPACE_GB=$(df -BG / | tail -1 | awk '{{print $2}}' | sed 's/G//')
    ALLOCATION_SIZE_GB=$((TOTAL_SPACE_GB * ALLOCATION_PERCENT / 100))
    echo "[{host}] Total disk: ${{TOTAL_SPACE_GB}}GB, Allocating: ${{ALLOCATION_SIZE_GB}}GB (${{ALLOCATION_PERCENT}}%)"
fi

# Create data directory
echo "[{host}] Creating data directory: ${{DATA_DIR}}"
mkdir -p "${{DATA_DIR}}"
chmod 755 "${{DATA_DIR}}" || sudo chmod 755 "${{DATA_DIR}}" || true

# Try to set ownership (may require sudo)
chown -R "$(whoami):$(whoami)" "${{DATA_DIR}}" 2>/dev/null || \
sudo chown -R "$(whoami):$(whoami)" "${{DATA_DIR}}" 2>/dev/null || true

echo "[{host}] Disk allocation setup complete!"
echo "[{host}] Data directory: ${{DATA_DIR}}"
if [ -n "${{ALLOCATION_SIZE_GB}}" ] && [ "${{ALLOCATION_SIZE_GB}}" -gt 0 ]; then
    echo "[{host}] Allocated size: ${{ALLOCATION_SIZE_GB}}GB"
fi
df -h "${{DATA_DIR}}" | tail -1
"""
    
    # Build SSH command
    command = f"bash -c '{setup_script.replace(chr(39), chr(39) + '\\' + chr(39) + chr(39))}'"
    ssh_cmd = build_ssh_command(
        host,
        command,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path,
        ssh_key_path=ssh_key_path
    )
    
    print(f"[{host}] Setting up disk allocation...")
    if verbose:
        print(f"[{host}] SSH command: {' '.join(ssh_cmd)}")
    
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            print(f"[{host}] ✅ Disk setup successful")
            if verbose and result.stdout:
                print(result.stdout)
        else:
            print(f"[{host}] ❌ Disk setup failed (exit code: {result.returncode})")
            if result.stderr:
                print(f"[{host}] Error: {result.stderr}")
            return False
    except Exception as e:
        print(f"[{host}] ❌ Error: {e}")
        return False
    
    return True

def main():
    parser = argparse.ArgumentParser(
        description='Setup disk allocation for CockroachDB on all scheduler nodes',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--hosts',
        nargs='+',
        help='Specific host names to use (from SSH config)'
    )
    
    parser.add_argument(
        '--pattern',
        help='Regex pattern to match host names from SSH config'
    )
    
    parser.add_argument(
        '--ssh-config',
        default=None,
        help='Path to SSH config file (default: .ssh.config in current dir, then ~/.ssh/config)'
    )
    
    parser.add_argument(
        '--data-dir',
        default='/var/lib/cockroach/data',
        help='Data directory path (default: /var/lib/cockroach/data)'
    )
    
    parser.add_argument(
        '--allocation-percent',
        type=int,
        default=20,
        help='Percentage of disk to allocate (default: 20)'
    )
    
    parser.add_argument(
        '--allocation-size-gb',
        type=int,
        default=None,
        help='Fixed allocation size in GB (overrides percentage)'
    )
    
    parser.add_argument(
        '--env-file',
        default='.env',
        help='Path to .env file with passwords (default: .env)'
    )
    
    parser.add_argument(
        '--ssh-key',
        default=None,
        help='Path to SSH private key'
    )
    
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Load passwords from .env file
    env_vars = load_env_file(args.env_file)
    jumpnode_password = env_vars.get('JUMPNODE_PASSWORD') or env_vars.get('JUMPNODE_PASS')
    node_password = env_vars.get('NODE_PASSWORD') or env_vars.get('NODE_PASS') or env_vars.get('USER_PASSWORD') or env_vars.get('USER_PASS')
    
    # Determine SSH key path
    ssh_key_path = args.ssh_key
    if not ssh_key_path:
        default_key = os.path.expanduser('~/.ssh/id_peercompute')
        if os.path.exists(default_key):
            ssh_key_path = default_key
    
    # Determine SSH config path
    if args.ssh_config:
        ssh_config_path = args.ssh_config
    else:
        current_dir_config = os.path.join(os.getcwd(), '.ssh.config')
        if os.path.exists(current_dir_config):
            ssh_config_path = current_dir_config
        else:
            ssh_config_path = os.path.expanduser('~/.ssh/config')
    
    # Parse SSH config
    ssh_hosts = parse_ssh_config(ssh_config_path)
    
    if not ssh_hosts:
        print(f"No hosts found in SSH config: {ssh_config_path}")
        sys.exit(1)
    
    # Determine which hosts to use
    if args.hosts:
        hosts_to_use = [h for h in args.hosts if h in ssh_hosts]
    elif args.pattern:
        import re
        regex = re.compile(args.pattern)
        hosts_to_use = [host for host in ssh_hosts.keys() if regex.search(host)]
    else:
        # Use all hosts matching scheduler pattern
        import re
        pattern = re.compile(r'(colva|anjuna).*peercompute')
        hosts_to_use = [host for host in ssh_hosts.keys() if pattern.search(host)]
    
    if not hosts_to_use:
        print("No hosts selected. Use --hosts or --pattern to specify hosts.")
        sys.exit(1)
    
    print(f"Setting up disk allocation on {len(hosts_to_use)} host(s): {', '.join(hosts_to_use)}")
    print()
    
    # Setup on each host
    success_count = 0
    for host in hosts_to_use:
        if setup_disk_on_host(
            host,
            data_dir=args.data_dir,
            allocation_percent=args.allocation_percent,
            allocation_size_gb=args.allocation_size_gb,
            jumpnode_password=jumpnode_password,
            node_password=node_password,
            ssh_config_path=ssh_config_path,
            ssh_key_path=ssh_key_path,
            verbose=args.verbose
        ):
            success_count += 1
    
    print()
    print(f"Disk setup complete: {success_count}/{len(hosts_to_use)} hosts successful")

if __name__ == '__main__':
    main()
