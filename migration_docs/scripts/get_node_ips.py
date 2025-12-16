#!/usr/bin/env python3
"""
Extract node information from .ssh.config and create node inventory.
Maps SSH host aliases to actual network addresses for CockroachDB cluster setup.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

def parse_ssh_config(config_path: str) -> Dict[str, Dict[str, str]]:
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
                elif current_host and key in ['hostname', 'user', 'proxyjump', 'port', 'identityfile']:
                    hosts[current_host][key] = value
    
    except FileNotFoundError:
        print(f"Error: SSH config file not found: {config_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error parsing SSH config: {e}")
        sys.exit(1)
    
    return hosts

def get_host_ip(hostname: str) -> Optional[str]:
    """Get IP address for a hostname."""
    try:
        result = subprocess.run(
            ['getent', 'hosts', hostname],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout:
            # Extract first IP address
            ip = result.stdout.split()[0]
            return ip
    except:
        pass
    
    # Fallback: try host command
    try:
        result = subprocess.run(
            ['host', hostname],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout:
            # Extract IP from output
            for line in result.stdout.split('\n'):
                if 'has address' in line:
                    ip = line.split()[-1]
                    return ip
    except:
        pass
    
    return None

def build_node_inventory(
    ssh_hosts: Dict[str, Dict[str, str]],
    pattern: Optional[str] = None,
    resolve_ips: bool = True
) -> List[Dict[str, str]]:
    """Build node inventory from SSH config."""
    import re
    
    # Filter hosts by pattern if provided
    if pattern:
        regex = re.compile(pattern)
        filtered_hosts = {k: v for k, v in ssh_hosts.items() if regex.search(k)}
    else:
        # Default: match scheduler nodes
        scheduler_pattern = re.compile(r'(colva|anjuna).*peercompute')
        filtered_hosts = {k: v for k, v in ssh_hosts.items() if scheduler_pattern.search(k)}
    
    inventory = []
    for ssh_alias, config in filtered_hosts.items():
        hostname = config.get('hostname', ssh_alias)
        user = config.get('user', 'peercompute')
        
        node_info = {
            'ssh_alias': ssh_alias,
            'hostname': hostname,
            'user': user,
            'port': config.get('port', '22'),
            'proxyjump': config.get('proxyjump'),
            'identityfile': config.get('identityfile'),
        }
        
        # Resolve IP address if requested
        if resolve_ips:
            ip = get_host_ip(hostname)
            if ip:
                node_info['ip'] = ip
            else:
                node_info['ip'] = hostname  # Fallback to hostname
        
        inventory.append(node_info)
    
    return inventory

def main():
    parser = argparse.ArgumentParser(
        description='Extract node information from SSH config and create inventory',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--ssh-config',
        default=None,
        help='Path to SSH config file (default: .ssh.config in current dir, then ~/.ssh/config)'
    )
    
    parser.add_argument(
        '--pattern',
        help='Regex pattern to match host names (default: scheduler nodes)'
    )
    
    parser.add_argument(
        '--output',
        default=None,
        help='Output JSON file path (default: migration_docs/config/node_inventory.json)'
    )
    
    parser.add_argument(
        '--no-resolve-ips',
        action='store_true',
        help='Do not resolve IP addresses (use hostnames only)'
    )
    
    parser.add_argument(
        '--format',
        choices=['json', 'list'],
        default='json',
        help='Output format (default: json)'
    )
    
    args = parser.parse_args()
    
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
    
    # Build inventory
    inventory = build_node_inventory(
        ssh_hosts,
        pattern=args.pattern,
        resolve_ips=not args.no_resolve_ips
    )
    
    if not inventory:
        print("No nodes found matching criteria.")
        sys.exit(1)
    
    # Determine output path
    if args.output:
        output_path = args.output
    else:
        output_dir = Path(__file__).parent.parent / 'config'
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / 'node_inventory.json')
    
    # Output results
    if args.format == 'json':
        # Save to file
        with open(output_path, 'w') as f:
            json.dump(inventory, f, indent=2)
        
        print(f"Node inventory saved to: {output_path}")
        print(f"\nFound {len(inventory)} node(s):")
        for node in inventory:
            print(f"  - {node['ssh_alias']}: {node.get('ip', node['hostname'])} ({node['hostname']})")
        
        # Also print JSON to stdout
        print("\nInventory JSON:")
        print(json.dumps(inventory, indent=2))
    else:
        # List format
        print(f"Found {len(inventory)} node(s):")
        for node in inventory:
            ip = node.get('ip', node['hostname'])
            print(f"{node['ssh_alias']}: {ip}")

if __name__ == '__main__':
    main()
