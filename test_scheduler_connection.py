#!/usr/bin/env python3
"""
Test script to verify scheduler setup on a remote host.
This helps debug connection and setup issues.
"""

import argparse
import subprocess
import sys
import os
from remote_ssh_utils import build_ssh_command, load_env_file, check_sshpass_available, check_expect_available

def test_connection(host, ssh_config_path=None, jumpnode_password=None, node_password=None):
    """Test basic SSH connection."""
    print(f"\n[TEST] Testing SSH connection to {host}...")
    
    # If password provided and expect available, use password auth directly
    # (skip SSH keys test to avoid password prompts)
    if (node_password or jumpnode_password) and check_expect_available():
        print(f"   Using expect for password authentication (skipping SSH keys test)...")
        test_cmd = build_ssh_command(host, "echo 'Connection successful'", 
                                     jumpnode_password=jumpnode_password,
                                     node_password=node_password,
                                     ssh_config_path=ssh_config_path)
        print(f"   Command: expect [script] (password hidden)")
        try:
            result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                output = result.stdout.strip()
                # Filter out expect's spawn output
                if "Connection successful" in output:
                    print(f"✅ SSH connection successful (using expect/password)")
                    return True
                else:
                    print(f"✅ SSH connection successful (using expect/password)")
                    print(f"   Output: {output[:100]}")
                    return True
            else:
                print(f"❌ SSH connection failed (exit code: {result.returncode})")
                if result.stderr:
                    print(f"   STDERR: {result.stderr[:500]}")
                if result.stdout:
                    print(f"   STDOUT: {result.stdout[:500]}")
                return False
        except subprocess.TimeoutExpired:
            print(f"❌ SSH connection timed out after 30 seconds")
            return False
        except Exception as e:
            print(f"❌ SSH connection error: {e}")
            return False
    
    # First try without password (using SSH keys if available)
    print(f"   Trying with SSH keys first...")
    test_cmd_no_pass = ['ssh', '-F', ssh_config_path, host, "echo 'Connection successful'"]
    try:
        # Use DEVNULL to prevent password prompts from blocking
        result = subprocess.run(test_cmd_no_pass, capture_output=True, text=True, timeout=15,
                               stdin=subprocess.DEVNULL)
        if result.returncode == 0:
            print(f"✅ SSH connection successful (using SSH keys)")
            print(f"   Output: {result.stdout.strip()}")
            return True
        else:
            print(f"   SSH keys failed (exit code: {result.returncode})")
            if result.stderr:
                print(f"   Error: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print(f"   SSH keys: Connection timed out")
    except Exception as e:
        print(f"   SSH keys error: {e}")
    
    # If password provided, try with password (fallback if expect not available)
    if node_password or jumpnode_password:
        print(f"   Trying with password authentication...")
        test_cmd = build_ssh_command(host, "echo 'Connection successful'", 
                                     jumpnode_password=jumpnode_password,
                                     node_password=node_password,
                                     ssh_config_path=ssh_config_path)
        print(f"   Command: {' '.join(test_cmd[:3])}... [password hidden]")
        try:
            result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=20)
            if result.returncode == 0:
                print(f"✅ SSH connection successful (using password)")
                print(f"   Output: {result.stdout.strip()}")
                return True
            else:
                print(f"❌ SSH connection failed (exit code: {result.returncode})")
                if result.stderr:
                    print(f"   STDERR: {result.stderr[:500]}")
                if result.stdout:
                    print(f"   STDOUT: {result.stdout[:500]}")
                return False
        except subprocess.TimeoutExpired:
            print(f"❌ SSH connection timed out after 20 seconds")
            print(f"   This usually means:")
            print(f"   - Network connectivity issue")
            print(f"   - ProxyJump authentication failing")
            print(f"   - Firewall blocking connection")
            print(f"   - Wrong password")
            return False
        except Exception as e:
            print(f"❌ SSH connection error: {e}")
            return False
    else:
        print(f"❌ No password provided and SSH keys failed")
        return False

def test_project_path(host, ssh_config_path=None, jumpnode_password=None, node_password=None):
    """Test if project path exists."""
    print(f"\n[TEST] Checking project path...")
    project_path = "~/Serverless_Scheduler_sn34kyp3t3"
    
    # Use build_ssh_command which handles expect/passwords automatically
    test_cmd = build_ssh_command(host, f"test -d {project_path} && echo 'EXISTS' || echo 'NOT_FOUND'",
                                jumpnode_password=jumpnode_password,
                                node_password=node_password,
                                ssh_config_path=ssh_config_path)
    
    # If no password and expect not available, try SSH keys
    if not (node_password or jumpnode_password) and not check_expect_available():
        test_cmd_keys = ['ssh', '-F', ssh_config_path, host, f"test -d {project_path} && echo 'EXISTS' || echo 'NOT_FOUND'"]
        try:
            result = subprocess.run(test_cmd_keys, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
            output = result.stdout.strip()
            if output == "EXISTS":
                print(f"✅ Project path exists: {project_path}")
                return True
        except:
            pass
    
    # Use password/expect method
    try:
        test_cmd = build_ssh_command(host, f"test -d {project_path} && echo 'EXISTS' || echo 'NOT_FOUND'",
                                    jumpnode_password=jumpnode_password,
                                    node_password=node_password,
                                    ssh_config_path=ssh_config_path)
        try:
            result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=20)
            output = result.stdout.strip()
            if output == "EXISTS":
                print(f"✅ Project path exists: {project_path}")
                return True
            else:
                print(f"❌ Project path not found: {project_path}")
                print(f"   Trying to find actual path...")
                # Try to find the actual path
                find_cmd = build_ssh_command(host, "find ~ -maxdepth 2 -name 'Serverless_Scheduler*' -type d 2>/dev/null | head -3",
                                            jumpnode_password=jumpnode_password,
                                            node_password=node_password,
                                            ssh_config_path=ssh_config_path)
                find_result = subprocess.run(find_cmd, capture_output=True, text=True, timeout=20)
                if find_result.stdout.strip():
                    print(f"   Found possible paths:")
                    for path in find_result.stdout.strip().split('\n'):
                        print(f"     - {path}")
                return False
        except subprocess.TimeoutExpired:
            print(f"❌ Connection timed out while checking project path")
            return False
        except Exception as e:
            print(f"❌ Error checking project path: {e}")
            return False
    else:
        print(f"❌ Cannot check project path - no connection method available")
        return False

def test_venv(host, ssh_config_path=None, jumpnode_password=None, node_password=None):
    """Test if virtual environment exists."""
    print(f"\n[TEST] Checking virtual environment...")
    project_path = "~/Serverless_Scheduler_sn34kyp3t3"
    venv_path = f"{project_path}/.venv"
    test_cmd = build_ssh_command(host, f"test -d {venv_path} && echo 'EXISTS' || echo 'NOT_FOUND'",
                                jumpnode_password=jumpnode_password,
                                node_password=node_password,
                                ssh_config_path=ssh_config_path)
    
    try:
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()
        # Filter out expect spawn output
        if "EXISTS" in output:
            print(f"✅ Virtual environment exists: {venv_path}")
            return True
        elif "NOT_FOUND" in output or result.returncode != 0:
            print(f"❌ Virtual environment not found: {venv_path}")
            print(f"   💡 You may need to create it: python3 -m venv {venv_path}")
            return False
        else:
            print(f"⚠️  Could not determine virtual environment status")
            print(f"   Output: {output[:100]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"❌ Connection timed out while checking virtual environment")
        return False
    except Exception as e:
        print(f"❌ Error checking virtual environment: {e}")
        return False

def test_django(host, ssh_config_path=None, jumpnode_password=None, node_password=None):
    """Test if Django is accessible in venv."""
    print(f"\n[TEST] Testing Django installation...")
    project_path = "~/Serverless_Scheduler_sn34kyp3t3"
    # Use simpler command that's easier to escape for expect
    test_cmd = build_ssh_command(host, 
                                f"cd {project_path} && . .venv/bin/activate && python -c \"import django; print(django.get_version())\" 2>&1",
                                jumpnode_password=jumpnode_password,
                                node_password=node_password,
                                ssh_config_path=ssh_config_path)
    
    try:
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            print(f"✅ Django is installed")
            print(f"   Version: {result.stdout.strip()}")
            return True
        else:
            print(f"❌ Django not found or error")
            print(f"   Error: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Error testing Django: {e}")
        return False

def test_scheduler_running(host, port=8001, ssh_config_path=None, jumpnode_password=None, node_password=None):
    """Test if scheduler is currently running."""
    print(f"\n[TEST] Checking if scheduler is running on port {port}...")
    test_cmd = build_ssh_command(host,
                                f"curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{port}/developers/index/ || echo '000'",
                                jumpnode_password=jumpnode_password,
                                node_password=node_password,
                                ssh_config_path=ssh_config_path)
    
    try:
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=10)
        http_code = result.stdout.strip()
        if http_code == "200":
            print(f"✅ Scheduler is running on port {port}")
            return True
        elif http_code == "000":
            print(f"❌ Scheduler is not running (connection refused)")
            return False
        else:
            print(f"⚠️  Scheduler responded with HTTP {http_code}")
            return False
    except Exception as e:
        print(f"❌ Error checking scheduler: {e}")
        return False

def test_process_running(host, ssh_config_path=None, jumpnode_password=None, node_password=None):
    """Test if scheduler process is running."""
    print(f"\n[TEST] Checking for scheduler process...")
    test_cmd = build_ssh_command(host,
                                "ps aux | grep 'python.*manage.py runserver' | grep -v grep || echo 'NOT_FOUND'",
                                jumpnode_password=jumpnode_password,
                                node_password=node_password,
                                ssh_config_path=ssh_config_path)
    
    try:
        result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=10)
        output = result.stdout.strip()
        if output != "NOT_FOUND" and output:
            print(f"✅ Scheduler process is running:")
            print(f"   {output}")
            return True
        else:
            print(f"❌ No scheduler process found")
            return False
    except Exception as e:
        print(f"❌ Error checking process: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Test scheduler setup on remote host')
    parser.add_argument('host', help='Host name from SSH config')
    parser.add_argument('--port', type=int, default=8001, help='Port to check (default: 8001)')
    parser.add_argument('--ssh-config', default=None, help='SSH config file path')
    parser.add_argument('--env-file', default='.env', help='Path to .env file')
    parser.add_argument('--skip-connection-test', action='store_true', help='Skip SSH connection test (if you know it works)')
    
    args = parser.parse_args()
    
    # Load passwords
    env_vars = load_env_file(args.env_file)
    jumpnode_password = env_vars.get('JUMPNODE_PASSWORD') or env_vars.get('JUMPNODE_PASS')
    node_password = env_vars.get('NODE_PASSWORD') or env_vars.get('NODE_PASS') or env_vars.get('USER_PASSWORD') or env_vars.get('USER_PASS')
    
    # Determine SSH config path
    if args.ssh_config:
        ssh_config_path = args.ssh_config
    else:
        current_dir_config = os.path.join(os.getcwd(), '.ssh.config')
        if os.path.exists(current_dir_config):
            ssh_config_path = current_dir_config
        else:
            ssh_config_path = os.path.expanduser('~/.ssh/config')
    
    print(f"Testing scheduler setup on: {args.host}")
    print(f"SSH config: {ssh_config_path}")
    print("=" * 60)
    
    # Run all tests
    results = []
    if not args.skip_connection_test:
        results.append(("SSH Connection", test_connection(args.host, ssh_config_path, jumpnode_password, node_password)))
        # Only continue if connection works
        if not results[-1][1]:
            print("\n⚠️  Cannot continue tests - SSH connection failed")
            print("   Fix the connection issue first, or use --skip-connection-test")
    else:
        print("\n[Skipping SSH connection test]")
        results.append(("SSH Connection", True))  # Assume it works
    
    results.append(("Project Path", test_project_path(args.host, ssh_config_path, jumpnode_password, node_password)))
    results.append(("Virtual Environment", test_venv(args.host, ssh_config_path, jumpnode_password, node_password)))
    results.append(("Django Installation", test_django(args.host, ssh_config_path, jumpnode_password, node_password)))
    results.append(("Scheduler Process", test_process_running(args.host, ssh_config_path, jumpnode_password, node_password)))
    results.append(("Scheduler HTTP", test_scheduler_running(args.host, args.port, ssh_config_path, jumpnode_password, node_password)))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY:")
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} - {test_name}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    print(f"\nPassed: {passed}/{total}")
    
    if passed < total:
        print("\n💡 TIP: Run with --verbose flag on start_schedulers_remote.py for more details")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)

if __name__ == '__main__':
    main()

