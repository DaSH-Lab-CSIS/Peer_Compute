#!/usr/bin/env python3
"""
Remote provider startup script for multiple nodes.

This script reads SSH hosts from SSH config, extracts locations, fetches user_ids
from the scheduler API, and starts providers on each node remotely.

Usage:
    # Start providers on all hosts matching pattern
    python start_providers_remote.py --pattern "colva.*peercompute"
    
    # Start providers on specific hosts
    python start_providers_remote.py --hosts colva2peercompute colva3peercompute
    
    # Start in background
    python start_providers_remote.py --hosts colva2peercompute --background
    
    # Specify scheduler URL for API calls
    python start_providers_remote.py --pattern "colva.*peercompute" --scheduler-url http://10.8.1.18:8001
"""

import argparse
import subprocess
import sys
import re
import os
import requests
from typing import List, Dict, Optional, Tuple
import threading
import time
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


def extract_location_from_host(host: str) -> str:
    """
    Extract location from hostname.
    Pattern: <location>peercompute -> location
    Example: colva2peercompute -> colva2
    """
    # Remove 'peercompute' suffix
    if host.endswith('peercompute'):
        return host[:-11]  # Remove 'peercompute' (11 characters)
    return host


def get_user_id_for_location(scheduler_url: str, location: str) -> Optional[str]:
    """
    Get user_id for a location from the scheduler API.
    
    Args:
        scheduler_url: Base URL of the scheduler (e.g., http://10.8.1.18:8001)
        location: Location string (e.g., 'colva2')
    
    Returns:
        user_id string if found, None otherwise
    """
    try:
        api_url = f"{scheduler_url}/providers/get_user_id/"
        params = {'location': location}
        
        response = requests.get(api_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if 'user_id' in data:
            return data['user_id']
        else:
            print(f"⚠️  No user_id found for location {location}: {data.get('error', 'Unknown error')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching user_id for location {location}: {e}")
        return None


def check_docker_permissions(
    host: str,
    jumpnode_password: Optional[str] = None,
    node_password: Optional[str] = None,
    ssh_config_path: Optional[str] = None,
    ssh_key_path: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Check if Docker is accessible on remote host.
    Returns (is_accessible, error_message)
    """
    check_cmd = "docker ps > /dev/null 2>&1 && echo 'OK' || echo 'ERROR'"
    ssh_cmd = build_ssh_command(
        host, check_cmd,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path,
        ssh_key_path=ssh_key_path
    )
    
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        output = result.stdout.strip()
        if 'OK' in output:
            return True, ""
        else:
            # Try to get more details
            detail_cmd = "docker ps 2>&1 | head -1"
            detail_ssh_cmd = build_ssh_command(
                host, detail_cmd,
                jumpnode_password=jumpnode_password,
                node_password=node_password,
                ssh_config_path=ssh_config_path,
                ssh_key_path=ssh_key_path
            )
            detail_result = subprocess.run(
                detail_ssh_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            error_msg = detail_result.stderr.strip() or detail_result.stdout.strip()
            if 'Permission denied' in error_msg or 'permission denied' in error_msg.lower():
                return False, "Docker permission denied. User may need to be added to 'docker' group or use 'sudo'."
            return False, f"Docker not accessible: {error_msg[:100]}"
    except Exception as e:
        return False, f"Error checking Docker: {str(e)}"


def start_provider_on_host(
    host: str,
    user_id: str,
    background: bool = False,
    jumpnode_password: Optional[str] = None,
    node_password: Optional[str] = None,
    ssh_config_path: Optional[str] = None,
    ssh_key_path: Optional[str] = None,
    verbose: bool = False,
    check_docker: bool = True
) -> Optional[subprocess.Popen]:
    """Start provider on a remote host."""
    # Auto-detect project path
    project_path = "~/Serverless_Scheduler_sn34kyp3t3"
    
    # Build the command to run
    venv_cmd = "source .venv/bin/activate;"
    provider_cmd = f"python provider/provider1.py {user_id}"
    full_cmd = f"cd {project_path}; {venv_cmd} {provider_cmd}"
    
    if background:
        # Run in background with nohup
        full_cmd = f"nohup bash -c '{full_cmd}' > /tmp/provider_{host}.log 2>&1 &"
    
    if verbose:
        print(f"[{host}] Starting provider with user_id: {user_id}")
        print(f"[{host}] Project path: {project_path}")
        print(f"[{host}] Full command: {full_cmd}")
    
    # Check Docker permissions before starting
    if check_docker:
        if verbose:
            print(f"[{host}] Checking Docker permissions...")
        docker_ok, docker_error = check_docker_permissions(
            host,
            jumpnode_password=jumpnode_password,
            node_password=node_password,
            ssh_config_path=ssh_config_path,
            ssh_key_path=ssh_key_path
        )
        if not docker_ok:
            print(f"[{host}] ⚠️  Docker check failed: {docker_error}")
            print(f"[{host}] 💡 Fix: Run 'sudo usermod -aG docker $USER' on {host} and log out/in, or use 'sudo docker'")
            print(f"[{host}] ⚠️  Continuing anyway - provider may fail to start...")
        elif verbose:
            print(f"[{host}] ✅ Docker is accessible")
    
    # Build SSH command
    ssh_cmd = build_ssh_command(
        host, full_cmd,
        jumpnode_password=jumpnode_password,
        node_password=node_password,
        ssh_config_path=ssh_config_path,
        ssh_key_path=ssh_key_path
    )
    
    if verbose:
        print(f"[{host}] SSH command: {' '.join(ssh_cmd)}")
    
    try:
        if background:
            # For background, we just execute and return
            process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            # Wait a bit to check if it failed immediately
            time.sleep(2)
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                if verbose:
                    if stdout:
                        print(f"[{host}] STDOUT: {stdout}")
                    if stderr:
                        print(f"[{host}] STDERR: {stderr}")
                if stderr or process.returncode != 0:
                    print(f"[{host}] ❌ Failed to start provider (exit code: {process.returncode})")
                    if stderr:
                        print(f"[{host}] Error output: {stderr}")
                        # Check for common errors
                        if 'Permission denied' in stderr or 'PermissionError' in stderr:
                            print(f"[{host}] 💡 Docker permission issue detected!")
                            print(f"[{host}] 💡 Solution: Run 'sudo usermod -aG docker $USER' on {host} and log out/in")
                        if 'DockerException' in stderr or 'docker.errors' in stderr:
                            print(f"[{host}] 💡 Docker connection issue detected!")
                            print(f"[{host}] 💡 Check if Docker daemon is running: 'sudo systemctl status docker'")
                    return None
            if verbose:
                print(f"[{host}] ✅ Process started successfully")
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
        print(f"\n[{host}] Interrupted. Stopping provider...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    parser = argparse.ArgumentParser(
        description='Start providers on multiple remote nodes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start on all hosts matching pattern
  python start_providers_remote.py --pattern "colva.*peercompute"
  
  # Start on specific hosts
  python start_providers_remote.py --hosts colva2peercompute colva3peercompute
  
  # Start in background
  python start_providers_remote.py --hosts colva2peercompute --background
  
  # Specify scheduler URL
  python start_providers_remote.py --pattern "colva.*peercompute" --scheduler-url http://10.8.1.18:8001
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
        '--scheduler-url',
        default='http://localhost:8001',
        help='Base URL of the scheduler API (default: http://localhost:8001)'
    )
    
    parser.add_argument(
        '--background',
        action='store_true',
        help='Run providers in background (detached)'
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
    
    parser.add_argument(
        '--skip-docker-check',
        action='store_true',
        help='Skip Docker permission check before starting providers'
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
        hosts_to_use = filter_hosts(ssh_hosts, args.pattern)
    else:
        print("No hosts selected. Use --hosts or --pattern to specify hosts.")
        sys.exit(1)
    
    if not hosts_to_use:
        print("No hosts selected.")
        sys.exit(1)
    
    print(f"Starting providers on {len(hosts_to_use)} host(s): {', '.join(hosts_to_use)}")
    print(f"Scheduler URL: {args.scheduler_url}")
    print(f"Background: {args.background}")
    if args.verbose:
        print(f"Verbose mode: ON")
        print(f"SSH config: {ssh_config_path}")
        if ssh_key_path:
            print(f"SSH key: {ssh_key_path}")
    print()
    
    # Get user_ids for each location
    location_to_user_id = {}
    location_to_host = {}
    
    for host in hosts_to_use:
        location = extract_location_from_host(host)
        location_to_host[location] = host
        
        if location not in location_to_user_id:
            if args.verbose:
                print(f"Fetching user_id for location: {location}")
            user_id = get_user_id_for_location(args.scheduler_url, location)
            if user_id:
                location_to_user_id[location] = user_id
                if args.verbose:
                    print(f"✅ Found user_id {user_id} for location {location}")
            else:
                print(f"⚠️  Skipping {host} - no user_id found for location {location}")
    
    # Start providers
    processes = []
    threads = []
    
    for host in hosts_to_use:
        location = extract_location_from_host(host)
        user_id = location_to_user_id.get(location)
        
        if not user_id:
            print(f"⚠️  Skipping {host} - no user_id available")
            continue
        
        process = start_provider_on_host(
            host,
            user_id,
            background=args.background,
            jumpnode_password=jumpnode_password,
            node_password=node_password,
            ssh_config_path=ssh_config_path,
            ssh_key_path=ssh_key_path,
            verbose=args.verbose,
            check_docker=not args.skip_docker_check
        )
        
        if process:
            processes.append((host, process))
            
            if not args.background:
                thread = threading.Thread(
                    target=monitor_process,
                    args=(host, process, args.background),
                    daemon=True
                )
                thread.start()
                threads.append(thread)
    
    if args.background:
        print("\nAll providers started in background.")
        print("To check logs, SSH into each host and run:")
        print("  tail -f /tmp/provider_<hostname>.log")
        print("\nTo check provider status, use check_providers_remote.py")
        print("To stop providers, use stop_providers_remote.py")
        print("\n⚠️  Note: If providers fail due to Docker permissions, fix with:")
        print("  sudo usermod -aG docker $USER  # Then log out and back in")
    else:
        print("\nProviders running. Press Ctrl+C to stop all...")
        try:
            for thread in threads:
                thread.join()
        except KeyboardInterrupt:
            print("\nStopping all providers...")
            for host, process in processes:
                if process and process.poll() is None:
                    print(f"Stopping {host}...")
                    process.terminate()
            time.sleep(2)
            for host, process in processes:
                if process and process.poll() is None:
                    process.kill()


if __name__ == '__main__':
    main()

