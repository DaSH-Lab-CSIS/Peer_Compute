#!/usr/bin/env python3
"""
Remote scheduler startup script for multiple nodes.

This script reads SSH hosts from SSH config or command-line arguments and
starts the Django scheduler on each node remotely.

Usage:
    # Use all hosts from SSH config that match a pattern
    python start_schedulers_remote.py --pattern "colva.*peercompute|anjuna.*peercompute"
    
    # Use specific hosts
    python start_schedulers_remote.py --hosts colva2peercompute colva3peercompute
    
    # Use hosts from SSH config file
    python start_schedulers_remote.py --ssh-config ~/.ssh/config --pattern ".*peercompute"
    
    # Run in background (detached)
    python start_schedulers_remote.py --hosts colva2peercompute --background
    
    # Custom port and scheduler name
    python start_schedulers_remote.py --hosts colva2peercompute --port 8001 --scheduler-name colva2
"""

import argparse
import subprocess
import sys
import re
import os
from pathlib import Path
from typing import List, Dict, Optional
import threading
import time
from remote_ssh_utils import load_env_file, build_ssh_command, check_sshpass_available


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
                    # Handle multiple host names (space-separated)
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


def build_ssh_command_with_background(
    host: str,
    command: str,
    background: bool = False,
    jumpnode_password: Optional[str] = None,
    node_password: Optional[str] = None,
    ssh_config_path: Optional[str] = None,
    ssh_key_path: Optional[str] = None
) -> List[str]:
    """Build SSH command with background support."""
    if background:
        # Run command in background with nohup and redirect output
        command = f"nohup bash -c '{command}' > /tmp/scheduler_{host}.log 2>&1 &"
    
    return build_ssh_command(host, command, jumpnode_password, node_password, ssh_config_path, ssh_key_path)


def get_project_path(host: str, jumpnode_password: Optional[str] = None, node_password: Optional[str] = None, ssh_config_path: Optional[str] = None, ssh_key_path: Optional[str] = None) -> str:
    """Get the project path on remote host. Can be customized per host."""
    # Default paths to try
    default_paths = [
        "~/Serverless_Scheduler_sn34kyp3t3",
        "~/Documents/Serverless_Scheduler",
        "~/Serverless_Scheduler"
    ]
    
    # Try to detect the path
    for path in default_paths:
        check_cmd = build_ssh_command(host, f'test -d {path} && echo {path}', 
                                       jumpnode_password=jumpnode_password, 
                                       node_password=node_password,
                                       ssh_config_path=ssh_config_path,
                                       ssh_key_path=ssh_key_path)
        try:
            result = subprocess.run(
                check_cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except:
            continue
    
    # Default fallback
    return "~/Serverless_Scheduler_sn34kyp3t3"


def start_scheduler_on_host(
    host: str,
    port: int = 8000,
    scheduler_name: Optional[str] = None,
    background: bool = False,
    project_path: Optional[str] = None,
    jumpnode_password: Optional[str] = None,
    node_password: Optional[str] = None,
    ssh_config_path: Optional[str] = None,
    ssh_key_path: Optional[str] = None,
    verbose: bool = False
) -> subprocess.Popen:
    """Start scheduler on a remote host."""
    if project_path is None:
        if verbose:
            print(f"[{host}] Auto-detecting project path...")
        project_path = get_project_path(host, jumpnode_password=jumpnode_password, node_password=node_password, ssh_config_path=ssh_config_path, ssh_key_path=ssh_key_path)
        if verbose:
            print(f"[{host}] Detected project path: {project_path}")
    
    # Use hostname as scheduler name if not provided
    if scheduler_name is None:
        scheduler_name = host.replace('peercompute', '').replace('colva', 'colva').replace('anjuna', 'anjuna')
    
    # Build the command to run on remote host
    # Match the exact setup: cd, activate venv, then run server
    # Wrap in bash -c to ensure proper shell execution (especially for expect)
    env_vars = f"export SCHEDULER_NAME={scheduler_name}; "
    cd_cmd = f"cd {project_path}; "
    venv_cmd = "source .venv/bin/activate; "
    run_cmd = f"python scheduler/manage.py runserver 0.0.0.0:{port}"
    
    # Wrap in bash -c to ensure proper shell execution
    full_command = f"bash -c '{env_vars}{cd_cmd}{venv_cmd}{run_cmd}'"
    
    # Build SSH command (uses SSH keys by default, passwords only if provided)
    ssh_cmd = build_ssh_command_with_background(host, full_command, background,
                                                jumpnode_password=jumpnode_password,
                                                node_password=node_password,
                                                ssh_config_path=ssh_config_path,
                                                ssh_key_path=ssh_key_path)
    
    print(f"[{host}] Starting scheduler on port {port} with name '{scheduler_name}'...")
    if verbose:
        print(f"[{host}] Project path: {project_path}")
        print(f"[{host}] Full command: {full_command}")
        print(f"[{host}] SSH command: {' '.join(ssh_cmd)}")
        if ssh_config_path:
            print(f"[{host}] Using SSH config: {ssh_config_path}")
    if background:
        print(f"[{host}] Running in background. Logs: /tmp/scheduler_{host}.log")
    
    try:
        if background:
            # For background, we just execute and return
            if verbose:
                print(f"[{host}] Executing SSH command in background...")
            process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            # Wait a moment to see if there's an immediate error
            time.sleep(2)  # Increased wait time for better error detection
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                
                # Filter out harmless SSH warnings
                harmless_patterns = [
                    r'Warning: Permanently added.*to the list of known hosts',
                    r'declare -x',  # Environment variable declarations
                ]
                
                filtered_stderr = stderr
                if stderr:
                    lines = stderr.split('\n')
                    filtered_lines = []
                    for line in lines:
                        is_harmless = False
                        for pattern in harmless_patterns:
                            if re.search(pattern, line):
                                is_harmless = True
                                break
                        if not is_harmless and line.strip():
                            filtered_lines.append(line)
                    filtered_stderr = '\n'.join(filtered_lines)
                
                if verbose:
                    if stdout:
                        print(f"[{host}] STDOUT: {stdout}")
                    if stderr:
                        print(f"[{host}] STDERR (raw): {stderr}")
                    if filtered_stderr:
                        print(f"[{host}] STDERR (filtered): {filtered_stderr}")
                
                # Only fail on non-zero exit code or actual errors (not harmless warnings)
                if process.returncode != 0:
                    print(f"[{host}] ❌ Failed to start scheduler (exit code: {process.returncode})")
                    if filtered_stderr:
                        print(f"[{host}] Error output: {filtered_stderr}")
                    if stdout:
                        print(f"[{host}] Output: {stdout}")
                    return None
                elif filtered_stderr:
                    # Exit code is 0 but there are non-harmless errors
                    print(f"[{host}] ⚠️  Started but with warnings:")
                    print(f"[{host}] {filtered_stderr}")
                
                # Verify scheduler actually started by checking log file
                verify_cmd = f"test -f /tmp/scheduler_{host}.log && echo 'OK' || echo 'MISSING'"
                verify_ssh_cmd = build_ssh_command(
                    host, verify_cmd,
                    jumpnode_password=jumpnode_password,
                    node_password=node_password,
                    ssh_config_path=ssh_config_path,
                    ssh_key_path=ssh_key_path
                )
                try:
                    verify_result = subprocess.run(
                        verify_ssh_cmd,
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if 'OK' in verify_result.stdout:
                        print(f"[{host}] ✅ Scheduler started successfully (log file created)")
                    else:
                        print(f"[{host}] ⚠️  Started but log file not found yet (may take a moment)")
                except Exception:
                    # Verification failed, but don't fail the whole operation
                    if verbose:
                        print(f"[{host}] Could not verify log file creation")
                
                return process
            if verbose:
                print(f"[{host}] ✅ Process started successfully (PID: {process.pid})")
            
            # Verify scheduler started by checking log file (for processes that didn't exit immediately)
            time.sleep(1)  # Give it a moment to create the log file
            verify_cmd = f"test -f /tmp/scheduler_{host}.log && echo 'OK' || echo 'MISSING'"
            verify_ssh_cmd = build_ssh_command(
                host, verify_cmd,
                jumpnode_password=jumpnode_password,
                node_password=node_password,
                ssh_config_path=ssh_config_path,
                ssh_key_path=ssh_key_path
            )
            try:
                verify_result = subprocess.run(
                    verify_ssh_cmd,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if 'OK' in verify_result.stdout:
                    if not verbose:
                        print(f"[{host}] ✅ Scheduler started successfully")
                else:
                    print(f"[{host}] ⚠️  Started but log file not found yet (may take a moment)")
            except Exception:
                # Verification failed, but don't fail the whole operation
                if verbose:
                    print(f"[{host}] Could not verify log file creation")
            
            return process
        else:
            # For foreground, we want to see output
            if verbose:
                print(f"[{host}] Executing SSH command in foreground...")
            process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            return process
    except Exception as e:
        print(f"[{host}] ❌ Failed to start: {e}")
        if verbose:
            import traceback
            print(f"[{host}] Traceback: {traceback.format_exc()}")
        return None


def monitor_process(host: str, process: subprocess.Popen, background: bool):
    """Monitor a process and print its output."""
    if background:
        return
    
    try:
        for line in iter(process.stdout.readline, ''):
            if line:
                print(f"[{host}] {line.rstrip()}")
        process.wait()
    except KeyboardInterrupt:
        print(f"\n[{host}] Interrupted. Stopping scheduler...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    parser = argparse.ArgumentParser(
        description='Start Django schedulers on multiple remote nodes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start on all hosts matching pattern
  python start_schedulers_remote.py --pattern "colva.*peercompute"
  
  # Start on specific hosts
  python start_schedulers_remote.py --hosts colva2peercompute colva3peercompute
  
  # Start in background
  python start_schedulers_remote.py --hosts colva2peercompute --background
  
  # Custom port and name
  python start_schedulers_remote.py --hosts colva2peercompute --port 8001 --scheduler-name colva2
        """
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
        help='Port to run scheduler on (default: 8001)'
    )
    
    parser.add_argument(
        '--scheduler-name',
        help='Scheduler name (default: derived from hostname)'
    )
    
    parser.add_argument(
        '--background',
        action='store_true',
        help='Run schedulers in background (detached)'
    )
    
    parser.add_argument(
        '--project-path',
        help='Project path on remote hosts (default: auto-detect)'
    )
    
    parser.add_argument(
        '--parallel',
        action='store_true',
        default=True,
        help='Start all schedulers in parallel (default: True)'
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
        help='Enable verbose logging (show SSH commands, output, etc.)'
    )
    
    args = parser.parse_args()
    
    # Load passwords from .env file (optional - SSH keys are preferred)
    env_vars = load_env_file(args.env_file)
    jumpnode_password = env_vars.get('JUMPNODE_PASSWORD') or env_vars.get('JUMPNODE_PASS')
    node_password = env_vars.get('NODE_PASSWORD') or env_vars.get('NODE_PASS') or env_vars.get('USER_PASSWORD') or env_vars.get('USER_PASS')
    
    # Determine SSH key path
    ssh_key_path = args.ssh_key
    if not ssh_key_path:
        default_key = os.path.expanduser('~/.ssh/id_peercompute')
        if os.path.exists(default_key):
            ssh_key_path = default_key
    
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
        print(f"No hosts found in SSH config: {ssh_config_path}")
        print("Please check your SSH config file path.")
        print("Note: Script looks for .ssh.config in current directory first, then ~/.ssh/config")
        sys.exit(1)
    
    # Debug: Show available hosts if pattern/hosts not specified or if verbose
    if not args.hosts and not args.pattern:
        print(f"Found {len(ssh_hosts)} host(s) in SSH config ({ssh_config_path}):")
        for host in sorted(ssh_hosts.keys()):
            print(f"  - {host}")
        print("\nUse --hosts or --pattern to select hosts.")
        sys.exit(0)
    
    # Determine which hosts to use
    if args.hosts:
        # Use specified hosts
        hosts_to_use = [h for h in args.hosts if h in ssh_hosts]
        missing = [h for h in args.hosts if h not in ssh_hosts]
        if missing:
            print(f"Warning: Hosts not found in SSH config: {missing}")
    elif args.pattern:
        # Filter by pattern
        hosts_to_use = filter_hosts(ssh_hosts, args.pattern)
    else:
        # Use all hosts
        hosts_to_use = list(ssh_hosts.keys())
    
    if not hosts_to_use:
        print(f"No hosts matched pattern: {args.pattern}")
        print(f"\nAvailable hosts in SSH config ({len(ssh_hosts)} total) from {ssh_config_path}:")
        for host in sorted(ssh_hosts.keys()):
            print(f"  - {host}")
        print("\nTry using --hosts to specify hosts directly, or adjust your pattern.")
        sys.exit(1)
    
    print(f"Starting schedulers on {len(hosts_to_use)} host(s): {', '.join(hosts_to_use)}")
    print(f"Port: {args.port}, Background: {args.background}")
    if args.verbose:
        print(f"Verbose mode: ON")
        print(f"SSH config: {ssh_config_path}")
        if ssh_key_path:
            print(f"SSH key: {ssh_key_path}")
        else:
            print(f"SSH key: Using default SSH keys (no password needed)")
        if jumpnode_password:
            print(f"Jumpnode password: {'*' * len(jumpnode_password)} (provided, will use if keys fail)")
        if node_password:
            print(f"Node password: {'*' * len(node_password)} (provided, will use if keys fail)")
    print()
    
    # Start schedulers
    processes = []
    threads = []
    
    for host in hosts_to_use:
        process = start_scheduler_on_host(
            host,
            port=args.port,
            scheduler_name=args.scheduler_name,
            background=args.background,
            project_path=args.project_path,
            jumpnode_password=jumpnode_password,
            node_password=node_password,
            ssh_config_path=ssh_config_path,
            ssh_key_path=ssh_key_path,
            verbose=args.verbose
        )
        
        if process:
            processes.append((host, process))
            
            if not args.background:
                # Create a thread to monitor each process
                thread = threading.Thread(
                    target=monitor_process,
                    args=(host, process, args.background),
                    daemon=True
                )
                thread.start()
                threads.append(thread)
    
    if args.background:
        print("\nAll schedulers started in background.")
        print("To check logs, SSH into each host and run:")
        print("  tail -f /tmp/scheduler_<hostname>.log")
        print("\nTo stop schedulers, use stop_schedulers_remote.py")
    else:
        print("\nSchedulers running. Press Ctrl+C to stop all...")
        try:
            # Wait for all threads
            for thread in threads:
                thread.join()
        except KeyboardInterrupt:
            print("\nStopping all schedulers...")
            for host, process in processes:
                if process and process.poll() is None:
                    print(f"Stopping {host}...")
                    process.terminate()
            # Wait a bit for graceful shutdown
            time.sleep(2)
            # Force kill if still running
            for host, process in processes:
                if process and process.poll() is None:
                    process.kill()


if __name__ == '__main__':
    main()

