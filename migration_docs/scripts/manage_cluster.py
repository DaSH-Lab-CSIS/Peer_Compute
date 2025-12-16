#!/usr/bin/env python3
"""
CockroachDB cluster management tool.
Provides commands to start, stop, and check cluster status.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Add parent directory to path
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
    """Get the address to use for CockroachDB."""
    return node.get('ip') or node.get('hostname', node['ssh_alias'])

def check_node_status(host: str, port: int = 26257):
    """Check if a node is running."""
    try:
        result = subprocess.run(
            ['cockroach', 'sql', '--insecure', f'--host={host}:{port}', '-e', 'SELECT 1;'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False

def status_cluster(inventory_path: str, sql_port: int = 26257):
    """Show cluster status."""
    nodes = load_node_inventory(inventory_path)
    
    print("CockroachDB Cluster Status")
    print("=" * 60)
    print()
    
    for node in nodes:
        ssh_alias = node['ssh_alias']
        address = get_node_address(node)
        
        is_running = check_node_status(address, sql_port)
        status = "✅ Running" if is_running else "❌ Stopped"
        
        print(f"{ssh_alias}:")
        print(f"  Address: {address}:{sql_port}")
        print(f"  Status: {status}")
        print()

def stop_cluster(inventory_path: str, ssh_config_path: str = None, ssh_key_path: str = None):
    """Stop all nodes in cluster."""
    nodes = load_node_inventory(inventory_path)
    
    print("Stopping CockroachDB cluster...")
    print()
    
    for node in nodes:
        ssh_alias = node['ssh_alias']
        
        stop_script = "pkill -f 'cockroach.*start' || true"
        command = f"bash -c '{stop_script}'"
        
        ssh_cmd = build_ssh_command(
            ssh_alias,
            command,
            ssh_config_path=ssh_config_path,
            ssh_key_path=ssh_key_path
        )
        
        print(f"[{ssh_alias}] Stopping node...")
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                print(f"[{ssh_alias}] ✅ Stopped")
            else:
                print(f"[{ssh_alias}] ⚠️  Stop command completed (may already be stopped)")
        except Exception as e:
            print(f"[{ssh_alias}] ❌ Error: {e}")
    
    print()
    print("Cluster stop complete")

def main():
    parser = argparse.ArgumentParser(
        description='Manage CockroachDB cluster',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        'command',
        choices=['status', 'stop', 'start'],
        help='Command to execute'
    )
    
    parser.add_argument(
        '--inventory',
        default=None,
        help='Path to node inventory JSON (default: migration_docs/config/node_inventory.json)'
    )
    
    parser.add_argument(
        '--ssh-config',
        default=None,
        help='Path to SSH config file'
    )
    
    parser.add_argument(
        '--ssh-key',
        default=None,
        help='Path to SSH private key'
    )
    
    args = parser.parse_args()
    
    # Determine inventory path
    if args.inventory:
        inventory_path = args.inventory
    else:
        inventory_path = str(Path(__file__).parent.parent / 'config' / 'node_inventory.json')
    
    # Determine SSH config path
    if args.ssh_config:
        ssh_config_path = args.ssh_config
    else:
        import os
        current_dir_config = os.path.join(os.getcwd(), '.ssh.config')
        if os.path.exists(current_dir_config):
            ssh_config_path = current_dir_config
        else:
            ssh_config_path = os.path.expanduser('~/.ssh/config')
    
    # Determine SSH key path
    ssh_key_path = args.ssh_key
    if not ssh_key_path:
        import os
        default_key = os.path.expanduser('~/.ssh/id_peercompute')
        if os.path.exists(default_key):
            ssh_key_path = default_key
    
    if args.command == 'status':
        status_cluster(inventory_path)
    elif args.command == 'stop':
        stop_cluster(inventory_path, ssh_config_path, ssh_key_path)
    elif args.command == 'start':
        print("Use start_cockroach_cluster.py to start the cluster")
        print("  Example: python migration_docs/scripts/start_cockroach_cluster.py")

if __name__ == '__main__':
    main()
