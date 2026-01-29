#!/usr/bin/env python3
"""
Check status of schedulers running on remote nodes.

Usage:
    # Check schedulers on all hosts matching pattern
    python check_schedulers_remote.py --pattern "colva.*peercompute"
    
    # Check schedulers on specific hosts
    python check_schedulers_remote.py --hosts colva2peercompute colva3peercompute
"""

import argparse
import subprocess
import sys
import re
import os
from typing import List, Dict, Optional
from remote_ssh_utils import load_env_file, build_ssh_command


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
                elif current_host and key in ['hostname', 'user', 'proxyjump', 'port']:
                    hosts[current_host][key] = value
    
    except FileNotFoundError:
        print(f"Warning: SSH config file not found: {config_path}")
    except Exception as e:
        print(f"Error parsing SSH config: {e}")
    
    return hosts


def filter_hosts(hosts: Dict[str, Dict[str, str]], pattern: Optional[str] = None) -> List[str]:
    """Filter hosts by pattern if provided."""
    if not pattern:
        return list(hosts.keys())
    
    try:
        regex = re.compile(pattern)
        return [host for host in hosts.keys() if regex.search(host)]
    except re.error as e:
        print(f"Invalid regex pattern: {e}")
        return []


def check_scheduler_on_host(
    host: str,
    port: int = 8001,
    jumpnode_password: Optional[str] = None,
    node_password: Optional[str] = None,
    ssh_config_path: Optional[str] = None
) -> Dict[str, any]:
    """Check scheduler status on a remote host."""
    status = {
        'host': host,
        'process_running': False,
        'port_listening': False,
        'pid': None,
        'port': port
    }
    
    # Check if process is running
    check_process_cmd_str = "ps aux | grep 'python.*manage.py runserver' | grep -v grep || echo ''"
    check_process_cmd = build_ssh_command(
        host, check_process_cmd_str,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path
    )
    
    # Check if port is listening
    check_port_cmd_str = f"ss -tln 2>/dev/null | grep ':{port}' || echo ''"
    check_port_cmd = build_ssh_command(
        host, check_port_cmd_str,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path
    )
    
    # Check PID file
    check_pid_cmd_str = 'cd ~/Serverless_Scheduler_sn34kyp3t3 2>/dev/null && cat djpid.txt 2>/dev/null || echo ""'
    check_pid_cmd = build_ssh_command(
        host, check_pid_cmd_str,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path
    )
    
    try:
        # Check process
        result = subprocess.run(
            check_process_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.stdout.strip():
            status['process_running'] = True
            # Try to extract PID
            parts = result.stdout.strip().split()
            if len(parts) > 1:
                try:
                    status['pid'] = int(parts[1])
                except:
                    pass
        
        # Check port
        result = subprocess.run(
            check_port_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.stdout.strip():
            status['port_listening'] = True
        
        # Check PID file
        result = subprocess.run(
            check_pid_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        pid_str = result.stdout.strip()
        if pid_str and pid_str.isdigit():
            status['pid'] = int(pid_str)
    
    except Exception as e:
        status['error'] = str(e)
    
    return status


def main():
    parser = argparse.ArgumentParser(
        description='Check status of Django schedulers on multiple remote nodes'
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
        '--port',
        type=int,
        default=8001,
        help='Port to check (default: 8001)'
    )
    
    parser.add_argument(
        '--env-file',
        default='.env',
        help='Path to .env file with passwords (default: .env)'
    )
    
    args = parser.parse_args()
    
    # Load passwords from .env file
    env_vars = load_env_file(args.env_file)
    jumpnode_password = env_vars.get('JUMPNODE_PASSWORD') or env_vars.get('JUMPNODE_PASS')
    node_password = env_vars.get('NODE_PASSWORD') or env_vars.get('NODE_PASS') or env_vars.get('USER_PASSWORD') or env_vars.get('USER_PASS')
    
    # Determine SSH config path (check current dir first, then home dir)
    if args.ssh_config:
        ssh_config_path = args.ssh_config
    else:
        # Try .ssh.config in current directory first
        current_dir_config = os.path.join(os.getcwd(), '.ssh.config')
        if os.path.exists(current_dir_config):
            ssh_config_path = current_dir_config
        else:
            # Fall back to ~/.ssh/config
            ssh_config_path = os.path.expanduser('~/.ssh/config')
    
    # Parse SSH config
    ssh_hosts = parse_ssh_config(ssh_config_path)
    
    if not ssh_hosts:
        print("No hosts found in SSH config.")
        sys.exit(1)
    
    # Determine which hosts to use
    if args.hosts:
        hosts_to_use = [h for h in args.hosts if h in ssh_hosts]
        missing = [h for h in args.hosts if h not in ssh_hosts]
        if missing:
            print(f"Warning: Hosts not found in SSH config: {missing}")
    elif args.pattern:
        hosts_to_use = filter_hosts(ssh_hosts, args.pattern)
    else:
        hosts_to_use = list(ssh_hosts.keys())
    
    if not hosts_to_use:
        print("No hosts selected.")
        sys.exit(1)
    
    print(f"Checking schedulers on {len(hosts_to_use)} host(s)...")
    print()
    
    # Check schedulers
    all_status = []
    for host in hosts_to_use:
        status = check_scheduler_on_host(host, port=args.port,
                                        jumpnode_password=jumpnode_password,
                                        node_password=node_password,
                                        ssh_config_path=ssh_config_path)
        all_status.append(status)
    
    # Print results
    print(f"{'Host':<25} {'Process':<10} {'Port':<10} {'PID':<10} {'Status'}")
    print("-" * 80)
    
    for status in all_status:
        host = status['host']
        process = "✅ Running" if status['process_running'] else "❌ Stopped"
        port = "✅ Listening" if status['port_listening'] else "❌ Not listening"
        pid = str(status['pid']) if status['pid'] else "N/A"
        
        overall = "✅ OK" if (status['process_running'] and status['port_listening']) else "❌ Issue"
        if 'error' in status:
            overall = f"❌ Error: {status['error']}"
        
        print(f"{host:<25} {process:<10} {port:<10} {pid:<10} {overall}")
    
    print()


if __name__ == '__main__':
    main()

