#!/usr/bin/env python3
"""
Complete Randomized Testbed Experiment Runner

This script demonstrates the complete workflow:
1. Generate a randomized testbed
2. Run the testbed against all algorithms with algorithm-specific logging
3. Generate analysis reports

Usage:
    python run_randomized_experiment.py
"""

import os
import sys
import subprocess
import time
from datetime import datetime
from randomized_testbed import RandomizedTestbed
from testbed_runner import TestbedRunner


def check_dependencies():
    """Check if all required services are running"""
    print("🔍 Checking system dependencies...")
    
    # Check if Django server is running
    try:
        import requests
        response = requests.get("http://localhost:8000/providers/experiment/status/", timeout=5)
        if response.status_code == 200:
            print("✅ Django server is running")
        else:
            print("❌ Django server not responding correctly")
            return False
    except:
        print("❌ Django server not accessible on localhost:8000")
        print("   Please start with: cd scheduler && python manage.py runserver 0.0.0.0:8000")
        return False
    
    # Check if load balancer is running
    try:
        response = requests.get("http://localhost:9001/status", timeout=5)
        if response.status_code == 200:
            print("✅ Load balancer is running")
        else:
            print("❌ Load balancer not responding correctly")
            return False
    except:
        print("❌ Load balancer not accessible on localhost:9001")
        print("   Please start with: cd loadbalancer && python loadbalancer_with_logging.py")
        return False
    
    return True


def generate_testbed(config=None):
    """Generate a randomized testbed"""
    print("\n📊 Generating randomized testbed...")
    
    if config is None:
        config = {
            "seed": 42,
            "num_batches": 15,
            "min_jobs_per_batch": 2,
            "max_jobs_per_batch": 6,
            "min_invocations": 1,
            "max_invocations": 3,
            "function_ids": [18, 19, 20, 21],  # Adjust based on your available services
            "min_batch_interval": 3.0,
            "max_batch_interval": 8.0
        }
    
    # Create testbed generator
    testbed_gen = RandomizedTestbed(seed=config["seed"])
    
    # Generate testbed
    batches = testbed_gen.generate_testbed(
        num_batches=config["num_batches"],
        min_jobs_per_batch=config["min_jobs_per_batch"],
        max_jobs_per_batch=config["max_jobs_per_batch"],
        min_invocations=config["min_invocations"],
        max_invocations=config["max_invocations"],
        function_ids=config["function_ids"],
        min_batch_interval=config["min_batch_interval"],
        max_batch_interval=config["max_batch_interval"]
    )
    
    # Save testbed
    testbed_file = testbed_gen.save_testbed()
    
    # Print summary
    summary = testbed_gen.get_testbed_summary()
    print(f"\n📈 Testbed Summary:")
    print(f"   File: {testbed_file}")
    print(f"   Duration: {summary['duration_seconds']:.1f} seconds")
    print(f"   Total jobs: {summary['total_jobs']}")
    print(f"   Function distribution: {summary['function_distribution']}")
    
    return testbed_file


def run_algorithm_comparison(testbed_file):
    """Run the testbed against all algorithms"""
    print(f"\n🚀 Running algorithm comparison with testbed: {testbed_file}")
    
    # Create testbed runner
    runner = TestbedRunner()
    
    # Run the comparison
    results = runner.run_full_comparison(testbed_file)
    
    if results:
        print(f"\n✅ Algorithm comparison completed!")
        print(f"   Experiment logs: experiment_logs/{runner.experiment_timestamp}/")
        return f"experiment_logs/{runner.experiment_timestamp}/"
    else:
        print(f"\n❌ Algorithm comparison failed!")
        return None


def analyze_results(logs_dir):
    """Analyze experiment results"""
    print(f"\n📊 Analyzing results in: {logs_dir}")
    
    try:
        # Run log analysis
        cmd = f"python analyze_experiment_logs.py --logs-dir {logs_dir} --console"
        print(f"Running: {cmd}")
        subprocess.run(cmd, shell=True, check=True)
        
        print(f"\n✅ Analysis completed!")
        
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Analysis failed: {e}")
    except FileNotFoundError:
        print(f"⚠️ analyze_experiment_logs.py not found")


def main():
    """Main experiment workflow"""
    print("="*80)
    print("🧪 RANDOMIZED TESTBED ALGORITHM COMPARISON EXPERIMENT")
    print("="*80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check dependencies
    if not check_dependencies():
        print("\n❌ System not ready for experiments. Please start required services.")
        return 1
    
    try:
        # Step 1: Generate testbed
        testbed_file = generate_testbed()
        
        # Step 2: Run algorithm comparison
        logs_dir = run_algorithm_comparison(testbed_file)
        
        if logs_dir:
            # Step 3: Analyze results
            analyze_results(logs_dir)
            
            print(f"\n🎉 Experiment completed successfully!")
            print(f"\n📁 Results Location:")
            print(f"   Logs: {logs_dir}")
            print(f"   Testbed: {testbed_file}")
            
            print(f"\n📋 Next Steps:")
            print(f"   1. Review experiment summary: {logs_dir}/experiment_summary.json")
            print(f"   2. Analyze individual algorithm logs in {logs_dir}/")
            print(f"   3. Compare performance metrics across algorithms")
            
        else:
            print(f"\n❌ Experiment failed during algorithm comparison")
            return 1
            
    except KeyboardInterrupt:
        print(f"\n⚠️ Experiment interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code) 