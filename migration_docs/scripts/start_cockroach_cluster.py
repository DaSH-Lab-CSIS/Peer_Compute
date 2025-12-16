#!/usr/bin/env python3
"""
Start CockroachDB cluster on all scheduler nodes remotely.
Reads node inventory and starts CockroachDB nodes on each host.
"""

import argparse
import json
import subprocess
import sys
import os
import time
from pathlib import Path

# Add parent directory to path to import remote_ssh_utils
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from remote_ssh_utils import build_ssh_command, load_env_file

def load_node_inventory(inventory_path: str):
    """Load node inventory from JSON file."""
    try:
        with open(inventory_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Node inventory not found: {inventory_path}")
        print("Run get_node_ips.py first to create inventory.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in inventory file: {e}")
        sys.exit(1)

def get_node_address(node: dict) -> str:
    """Get the address to use for CockroachDB (IP or hostname)."""
    return node.get('ip') or node.get('hostname', node['ssh_alias'])

def start_node_on_host(
    node: dict,
    join_list: str,
    data_dir: str = "/var/lib/cockroach/data",
    cache_size: str = ".25",
    max_sql_memory: str = ".25",
    http_port: int = 8080,
    sql_port: int = 26257,
    jumpnode_password: str = None,
    node_password: str = None,
    ssh_config_path: str = None,
    ssh_key_path: str = None,
    verbose: bool = False
):
    """Start CockroachDB node on a remote host."""
    
    ssh_alias = node['ssh_alias']
    advertise_addr = get_node_address(node)
    
    # Build locality string
    locality = f"node={ssh_alias}"
    
    # Start script content
    start_script = f"""#!/bin/bash
set -e

ADVERTISE_ADDR="{advertise_addr}"
JOIN_LIST="{join_list}"
DATA_DIR="{data_dir}"
CACHE_SIZE="{cache_size}"
MAX_SQL_MEMORY="{max_sql_memory}"
HTTP_PORT="{http_port}"
SQL_PORT="{sql_port}"
LOCALITY="{locality}"

# Find cockroach binary
COCKROACH_BIN=""
if [ -f "/usr/local/bin/cockroach" ]; then
    COCKROACH_BIN="/usr/local/bin/cockroach"
elif [ -f "$HOME/Serverless_Scheduler_sn34kyp3t3/cockroach/bin/cockroach" ]; then
    COCKROACH_BIN="$HOME/Serverless_Scheduler_sn34kyp3t3/cockroach/bin/cockroach"
elif command -v cockroach >/dev/null 2>&1; then
    COCKROACH_BIN="$(command -v cockroach)"
else
    echo "Error: CockroachDB binary not found"
    exit 1
fi

# Create data directory
mkdir -p "${{DATA_DIR}}"

# Build start command
START_CMD="${{COCKROACH_BIN}} start --insecure"
START_CMD="${{START_CMD}} --advertise-addr=${{ADVERTISE_ADDR}}"
START_CMD="${{START_CMD}} --join=${{JOIN_LIST}}"
START_CMD="${{START_CMD}} --store=path=${{DATA_DIR}}"
START_CMD="${{START_CMD}} --cache=${{CACHE_SIZE}}"
START_CMD="${{START_CMD}} --max-sql-memory=${{MAX_SQL_MEMORY}}"
START_CMD="${{START_CMD}} --http-addr=${{ADVERTISE_ADDR}}:${{HTTP_PORT}}"
START_CMD="${{START_CMD}} --locality=${{LOCALITY}}"
START_CMD="${{START_CMD}} --background"

echo "[{ssh_alias}] Starting CockroachDB node..."
echo "[{ssh_alias}] Advertise address: ${{ADVERTISE_ADDR}}"
echo "[{ssh_alias}] Join list: ${{JOIN_LIST}}"

# Kill any existing cockroach process
pkill -f "cockroach.*start" || true
sleep 1

# Execute start command
eval "${{START_CMD}}"

# Wait and verify
sleep 3
if pgrep -f "cockroach.*start" > /dev/null; then
    echo "[{ssh_alias}] Node started successfully"
    echo "[{ssh_alias}] SQL: ${{ADVERTISE_ADDR}}:${{SQL_PORT}}"
    echo "[{ssh_alias}] HTTP: http://${{ADVERTISE_ADDR}}:${{HTTP_PORT}}"
else
    echo "[{ssh_alias}] Error: Node failed to start"
    exit 1
fi
"""
    
    # Build SSH command
    command = f"bash -c '{start_script.replace(chr(39), chr(39) + '\\' + chr(39) + chr(39))}'"
    ssh_cmd = build_ssh_command(
        ssh_alias,
        command,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path,
        ssh_key_path=ssh_key_path
    )
    
    print(f"[{ssh_alias}] Starting CockroachDB node at {advertise_addr}...")
    if verbose:
        print(f"[{ssh_alias}] SSH command: {' '.join(ssh_cmd)}")
    
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            print(f"[{ssh_alias}] ✅ Node started")
            if verbose and result.stdout:
                print(result.stdout)
            return True
        else:
            print(f"[{ssh_alias}] ❌ Failed to start (exit code: {result.returncode})")
            if result.stderr:
                print(f"[{ssh_alias}] Error: {result.stderr}")
            if result.stdout:
                print(f"[{ssh_alias}] Output: {result.stdout}")
            return False
    except subprocess.TimeoutExpired:
        print(f"[{ssh_alias}] ❌ Timeout starting node")
        return False
    except Exception as e:
        print(f"[{ssh_alias}] ❌ Error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Start CockroachDB cluster on all scheduler nodes',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--inventory',
        default=None,
        help='Path to node inventory JSON (default: migration_docs/config/node_inventory.json)'
    )
    
    parser.add_argument(
        '--data-dir',
        default='/var/lib/cockroach/data',
        help='Data directory path (default: /var/lib/cockroach/data)'
    )
    
    parser.add_argument(
        '--cache-size',
        default='.25',
        help='Cache size fraction (default: .25)'
    )
    
    parser.add_argument(
        '--max-sql-memory',
        default='.25',
        help='Max SQL memory fraction (default: .25)'
    )
    
    parser.add_argument(
        '--http-port',
        type=int,
        default=8080,
        help='HTTP port (default: 8080)'
    )
    
    parser.add_argument(
        '--sql-port',
        type=int,
        default=26257,
        help='SQL port (default: 26257)'
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
        '--ssh-config',
        default=None,
        help='Path to SSH config file'
    )
    
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Load passwords
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
    
    # Load node inventory
    if args.inventory:
        inventory_path = args.inventory
    else:
        inventory_path = str(Path(__file__).parent.parent / 'config' / 'node_inventory.json')
    
    nodes = load_node_inventory(inventory_path)
    
    if not nodes:
        print("No nodes found in inventory.")
        sys.exit(1)
    
    print(f"Starting CockroachDB cluster with {len(nodes)} node(s)...")
    print()
    
    # Build join list (all node addresses)
    join_addresses = [f"{get_node_address(node)}:{args.sql_port}" for node in nodes]
    join_list = ",".join(join_addresses)
    
    print(f"Join list: {join_list}")
    print()
    
    # Start nodes sequentially (first node is special)
    success_count = 0
    for i, node in enumerate(nodes):
        if start_node_on_host(
            node,
            join_list=join_list,
            data_dir=args.data_dir,
            cache_size=args.cache_size,
            max_sql_memory=args.max_sql_memory,
            http_port=args.http_port,
            sql_port=args.sql_port,
            jumpnode_password=jumpnode_password,
            node_password=node_password,
            ssh_config_path=ssh_config_path,
            ssh_key_path=ssh_key_path,
            verbose=args.verbose
        ):
            success_count += 1
        
        # Wait a bit between starts
        if i < len(nodes) - 1:
            time.sleep(2)
    
    print()
    print(f"Cluster startup complete: {success_count}/{len(nodes)} nodes started")
    print()
    print("Next step: Run init_cluster.sh to initialize the cluster")
    print(f"  Example: ./init_cluster.sh {get_node_address(nodes[0])}")

if __name__ == '__main__':
    main()
