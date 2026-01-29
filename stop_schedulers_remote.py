#!/usr/bin/env python3
"""
Stop schedulers running on remote nodes.

Usage:
    # Stop schedulers on all hosts matching pattern
    python stop_schedulers_remote.py --pattern "colva.*peercompute"
    
    # Stop schedulers on specific hosts
    python stop_schedulers_remote.py --hosts colva2peercompute colva3peercompute
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


def stop_scheduler_on_host(
    host: str,
    force: bool = False,
    jumpnode_password: Optional[str] = None,
    node_password: Optional[str] = None,
    ssh_config_path: Optional[str] = None
) -> bool:
    """Stop scheduler on a remote host."""
    # Try to find and kill the scheduler process
    # First, try to kill by PID file
    kill_by_pid_cmd_str = (
        'cd ~/Serverless_Scheduler_sn34kyp3t3 && '
        'if [ -f djpid.txt ]; then '
        '  kill $(cat djpid.txt) 2>/dev/null && rm djpid.txt || true; '
        'fi'
    )
    kill_by_pid_cmd = build_ssh_command(
        host, kill_by_pid_cmd_str,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path
    )
    
    # Also kill any running manage.py runserver processes
    kill_by_process_cmd_str = "pkill -f 'python.*manage.py runserver' || true"
    kill_by_process_cmd = build_ssh_command(
        host, kill_by_process_cmd_str,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path
    )
    
    print(f"[{host}] Stopping scheduler...")
    
    try:
        # Try PID file first
        result = subprocess.run(
            kill_by_pid_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Also kill by process name
        subprocess.run(
            kill_by_process_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if force:
            # Force kill if still running
            force_kill_cmd_str = "pkill -9 -f 'python.*manage.py runserver' || true"
            force_kill_cmd = build_ssh_command(
                host, force_kill_cmd_str,
                jumpnode_password=jumpnode_password,
                node_password=node_password,
                ssh_config_path=ssh_config_path
            )
            subprocess.run(force_kill_cmd, capture_output=True, timeout=10)
        
        print(f"[{host}] Scheduler stopped")
        return True
    except Exception as e:
        print(f"[{host}] Error stopping scheduler: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Stop Django schedulers on multiple remote nodes'
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
        'pattern_or_host',
        nargs='?',
        help='Optional: Regex pattern or hostname to match (alternative to --pattern or --hosts)'
    )
    
    parser.add_argument(
        '--ssh-config',
        default=None,
        help='Path to SSH config file (default: .ssh.config in current dir, then ~/.ssh/config)'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force kill schedulers (SIGKILL)'
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
    # Priority: --hosts > --pattern > positional argument > all hosts
    if args.hosts:
        hosts_to_use = [h for h in args.hosts if h in ssh_hosts]
        missing = [h for h in args.hosts if h not in ssh_hosts]
        if missing:
            print(f"Warning: Hosts not found in SSH config: {missing}")
    elif args.pattern:
        hosts_to_use = filter_hosts(ssh_hosts, args.pattern)
    elif args.pattern_or_host:
        # Try as exact hostname first, then as pattern
        if args.pattern_or_host in ssh_hosts:
            hosts_to_use = [args.pattern_or_host]
        else:
            hosts_to_use = filter_hosts(ssh_hosts, args.pattern_or_host)
    else:
        hosts_to_use = list(ssh_hosts.keys())
    
    if not hosts_to_use:
        if args.pattern_or_host:
            print(f"No hosts matched pattern/hostname: {args.pattern_or_host}")
        elif args.pattern:
            print(f"No hosts matched pattern: {args.pattern}")
        elif args.hosts:
            print(f"None of the specified hosts were found in SSH config.")
        else:
            print("No hosts selected. Use --hosts, --pattern, or provide a pattern/hostname as argument.")
        sys.exit(1)
    
    print(f"Stopping schedulers on {len(hosts_to_use)} host(s): {', '.join(hosts_to_use)}")
    print()
    
    # Stop schedulers
    for host in hosts_to_use:
        stop_scheduler_on_host(host, force=args.force,
                              jumpnode_password=jumpnode_password,
                              node_password=node_password,
                              ssh_config_path=ssh_config_path)
    
    print("\nDone.")


if __name__ == '__main__':
    main()

