#!/usr/bin/env python3
"""
Install CockroachDB on all scheduler nodes remotely via SSH.
Uses .ssh.config to discover nodes and installs CockroachDB on each.
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path

# Add parent directory to path to import remote_ssh_utils
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from remote_ssh_utils import build_ssh_command, load_env_file, check_expect_available

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

def install_cockroach_on_host(
    host: str,
    version: str = "v23.2.0",
    install_dir: str = "/usr/local/bin",
    project_path: str = None,
    jumpnode_password: str = None,
    node_password: str = None,
    ssh_config_path: str = None,
    ssh_key_path: str = None,
    verbose: bool = False
):
    """Install CockroachDB on a remote host."""
    
    # Determine project path
    if project_path is None:
        project_path = "~/Serverless_Scheduler_sn34kyp3t3"
    
    # Installation script content
    install_script = f"""#!/bin/bash
set -e
COCKROACH_VERSION="{version}"
INSTALL_DIR="{install_dir}"

echo "[{host}] Installing CockroachDB ${{COCKROACH_VERSION}}..."

# Download and extract
cd /tmp
echo "[{host}] Downloading CockroachDB..."
wget -qO- "https://binaries.cockroachdb.com/cockroach-${{COCKROACH_VERSION}}.linux-amd64.tgz" | tar xvz

# Install binary
echo "[{host}] Installing to ${{INSTALL_DIR}}..."
sudo cp "cockroach-${{COCKROACH_VERSION}}.linux-amd64/cockroach" "${{INSTALL_DIR}}/cockroach" || {{
    # If sudo fails, try installing to project directory
    mkdir -p "{project_path}/cockroach/bin"
    cp "cockroach-${{COCKROACH_VERSION}}.linux-amd64/cockroach" "{project_path}/cockroach/bin/cockroach"
    chmod +x "{project_path}/cockroach/bin/cockroach"
    echo "[{host}] Installed to {project_path}/cockroach/bin/cockroach (no sudo access)"
    exit 0
}}
sudo chmod +x "${{INSTALL_DIR}}/cockroach"

# Verify installation
echo "[{host}] Verifying installation..."
"${{INSTALL_DIR}}/cockroach" version || "{project_path}/cockroach/bin/cockroach" version

echo "[{host}] CockroachDB installed successfully!"
"""
    
    # Build SSH command
    command = f"bash -c '{install_script.replace(chr(39), chr(39) + '\\' + chr(39) + chr(39))}'"
    ssh_cmd = build_ssh_command(
        host,
        command,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path,
        ssh_key_path=ssh_key_path
    )
    
    print(f"[{host}] Installing CockroachDB...")
    if verbose:
        print(f"[{host}] SSH command: {' '.join(ssh_cmd)}")
    
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            print(f"[{host}] ✅ Installation successful")
            if verbose and result.stdout:
                print(result.stdout)
        else:
            print(f"[{host}] ❌ Installation failed (exit code: {result.returncode})")
            if result.stderr:
                print(f"[{host}] Error: {result.stderr}")
            if result.stdout:
                print(f"[{host}] Output: {result.stdout}")
            return False
    except subprocess.TimeoutExpired:
        print(f"[{host}] ❌ Installation timed out")
        return False
    except Exception as e:
        print(f"[{host}] ❌ Error: {e}")
        return False
    
    return True

def main():
    parser = argparse.ArgumentParser(
        description='Install CockroachDB on all scheduler nodes remotely',
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
        '--version',
        default='v23.2.0',
        help='CockroachDB version to install (default: v23.2.0)'
    )
    
    parser.add_argument(
        '--install-dir',
        default='/usr/local/bin',
        help='Installation directory (default: /usr/local/bin)'
    )
    
    parser.add_argument(
        '--project-path',
        help='Project path on remote hosts (default: ~/Serverless_Scheduler_sn34kyp3t3)'
    )
    
    parser.add_argument(
        '--env-file',
        default='.env',
        help='Path to .env file with passwords (default: .env)'
    )
    
    parser.add_argument(
        '--ssh-key',
        default=None,
        help='Path to SSH private key (default: ~/.ssh/id_peercompute or auto-detect)'
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
        missing = [h for h in args.hosts if h not in ssh_hosts]
        if missing:
            print(f"Warning: Hosts not found in SSH config: {missing}")
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
    
    print(f"Installing CockroachDB {args.version} on {len(hosts_to_use)} host(s): {', '.join(hosts_to_use)}")
    print()
    
    # Install on each host
    success_count = 0
    for host in hosts_to_use:
        if install_cockroach_on_host(
            host,
            version=args.version,
            install_dir=args.install_dir,
            project_path=args.project_path,
            jumpnode_password=jumpnode_password,
            node_password=node_password,
            ssh_config_path=ssh_config_path,
            ssh_key_path=ssh_key_path,
            verbose=args.verbose
        ):
            success_count += 1
    
    print()
    print(f"Installation complete: {success_count}/{len(hosts_to_use)} hosts successful")

if __name__ == '__main__':
    main()
