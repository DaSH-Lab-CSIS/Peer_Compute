#!/usr/bin/env python3
"""
Run provider1.py with timestamped logging to files.

Writes:
  - provider_logs/provider_{timestamp}.log  - provider stdout/stderr with timestamps
  - provider_logs/docker_{timestamp}.log    - docker container logs (when containers run)

On container failures, provider1.py also writes container logs to:
  - provider_logs/container_failure_{container_name}_{timestamp}.log

Usage:
  python provider/run_with_timestamped_logs.py <provider_id>

Example:
  python provider/run_with_timestamped_logs.py e176d551-b485-455d-9340-a930767a0478
"""

import os
import subprocess
import sys
import time
from datetime import datetime

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_with_timestamped_logs.py <provider_id>")
        sys.exit(1)

    provider_id = sys.argv[1]
    extra_args = sys.argv[2:]

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs_dir = os.path.join(project_root, 'provider_logs')
    os.makedirs(logs_dir, exist_ok=True)

    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    provider_log_path = os.path.join(logs_dir, f'provider_{run_id}.log')

    env = os.environ.copy()
    env['PROVIDER_STREAM_DOCKER_LOGS'] = '1'
    env['PROVIDER_RUN_ID'] = run_id

    provider_script = os.path.join(os.path.dirname(__file__), 'provider1.py')
    cmd = [sys.executable, '-u', provider_script, provider_id] + extra_args  # -u for unbuffered output

    print(f"Logging provider output to {provider_log_path}")
    print(f"Docker logs (if any) to {logs_dir}/docker_{run_id}.log")
    print(f"Run ID: {run_id}")
    print("-" * 60)

    with open(provider_log_path, 'w') as log_file:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        try:
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                stamped = f"{ts} {line}"
                sys.stdout.write(stamped)
                sys.stdout.flush()
                log_file.write(stamped)
                log_file.flush()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
            raise

        proc.wait()

    print("-" * 60)
    print(f"Provider exit code: {proc.returncode}")
    print(f"Logs saved to {provider_log_path}")
    if os.path.exists(os.path.join(logs_dir, f'docker_{run_id}.log')):
        print(f"Docker logs saved to {logs_dir}/docker_{run_id}.log")

    sys.exit(proc.returncode)


if __name__ == '__main__':
    main()
