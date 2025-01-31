# benchmark_mincost_lp.py

import os
import sys
import time
import subprocess
from cgroupspy import trees

base_dir = os.path.dirname(os.path.abspath(__file__))
activate_this = os.path.join(base_dir, '.venv/bin/activate')
exec(activate_this, dict(__file__=activate_this))

def run_benchmark():
    # Generate a unique cgroup name using your username and a timestamp
    username = os.getenv('USER') or 'user'
    timestamp = int(time.time())
    CGROUP_NAME = f"user_{username}_mincost_benchmark_{timestamp}"

    # Access the cgroup hierarchy
    tree = trees.Tree()
    try:
        # Get the root cgroup
        root_cgroup = tree.get_node_by_path('/')

        # Access 'cpuacct' and 'memory' controllers
        controllers = root_cgroup.controller('cpuacct,memory')

        # Check if cgroup already exists to prevent conflicts
        if controllers.has_cgroup(CGROUP_NAME):
            print(f"Cgroup '{CGROUP_NAME}' already exists. Exiting to prevent conflicts.")
            sys.exit(1)

        # Create a new cgroup under the controllers
        cgroup = controllers.create_cgroup(CGROUP_NAME)

        # Optional: Set resource limits
        # Example: Limit memory to 500MB and CPU shares to 512
        # Uncomment the following lines to enforce limits
        # cgroup.controller('memory').set('memory.limit_in_bytes', '500M')
        # cgroup.controller('cpuacct').set('cpu.shares', '512')

        # Initialize resource usage stats
        cgroup.controller('cpuacct').set('cpuacct.usage', '0')
        cgroup.controller('memory').set('memory.max_usage_in_bytes', '0')

        # Run mincost_lp.py and collect stats
        start_time = time.time()
        process = subprocess.Popen(["python", "mincost_lp.py"])
        
        # Add the process to the cgroup
        cgroup.add_task(process.pid)
        process.wait()
        end_time = time.time()

        # Get stats
        cpu_usage = cgroup.controller('cpuacct').get('cpuacct.usage')  # in nanoseconds
        memory_usage = cgroup.controller('memory').get('memory.max_usage_in_bytes')  # in bytes

        # Save stats to a uniquely named file
        results_filename = f"benchmark_results_{CGROUP_NAME}.txt"
        with open(results_filename, "w") as f:
            f.write(f"CPU usage (cpuacct.usage): {cpu_usage} nanoseconds\n")
            f.write(f"Memory usage (memory.max_usage_in_bytes): {memory_usage} bytes\n")
            f.write(f"Execution time: {end_time - start_time:.2f} seconds\n")

        print(f"Benchmarking complete. Results saved to {results_filename}")

    except Exception as e:
        print(f"An error occurred: {e}")
        print("Ensure that you have the necessary permissions and that cgroups are supported on your system.")
    finally:
        # Cleanup: Delete the cgroup to free resources
        try:
            if 'cgroup' in locals() and cgroup.exists():
                cgroup.delete()
                print(f"Cgroup '{CGROUP_NAME}' deleted successfully.")
        except Exception as cleanup_error:
            print(f"Failed to delete cgroup '{CGROUP_NAME}': {cleanup_error}")

if __name__ == "__main__":
    run_benchmark()
