#!/usr/bin/env python3
"""
Testbed Runner for Algorithm Comparison

This script runs the same randomized testbed against all scheduling algorithms
and logs results in algorithm-specific directories.
"""

import os
import sys
import json
import time
import requests
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path

# Import our testbed generator
from randomized_testbed import RandomizedTestbed, TestBatch, TestJob


@dataclass
class AlgorithmResult:
    """Results for a single algorithm run"""
    algorithm: str
    start_time: datetime
    end_time: datetime
    total_batches_sent: int
    total_jobs_sent: int
    success_rate: float
    errors: List[str]
    log_directory: str


class TestbedRunner:
    """Runs the same testbed against multiple algorithms"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.providers_url = f"{base_url}/providers"
        self.loadbalancer_url = "http://localhost:9001"  # Load balancer port
        self.algorithms = ["ILP", "MRU", "ROUND_ROBIN", "BELADY"]
        self.experiment_timestamp = None
        self.results = {}
        
    def setup_experiment_logging(self) -> str:
        """Setup experiment directory structure"""
        self.experiment_timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        
        # Create base experiment directory
        base_logs_dir = f"experiment_logs/{self.experiment_timestamp}"
        os.makedirs(base_logs_dir, exist_ok=True)
        
        # Create algorithm-specific directories
        for algorithm in self.algorithms:
            algo_dir = f"{base_logs_dir}/{algorithm}"
            os.makedirs(algo_dir, exist_ok=True)
            
        print(f"Experiment logs will be saved in: {base_logs_dir}")
        return base_logs_dir
    
    def update_logging_settings(self, algorithm: str):
        """Update Django settings to use algorithm-specific log directory"""
        try:
            # This would require updating the Django settings dynamically
            # For now, we'll use environment variables or configuration files
            algo_log_dir = f"experiment_logs/{self.experiment_timestamp}/{algorithm}"
            
            # Set environment variables that the Django app can read
            os.environ['EXPERIMENT_ALGORITHM'] = algorithm
            os.environ['EXPERIMENT_LOG_DIR'] = algo_log_dir
            
            print(f"Updated logging for {algorithm} -> {algo_log_dir}")
            
        except Exception as e:
            print(f"Warning: Could not update logging settings: {e}")
    
    def check_system_status(self) -> bool:
        """Check if all required services are running"""
        print("Checking system status...")
        
        # Check Django server
        try:
            response = requests.get(f"{self.providers_url}/experiment/status/", timeout=5)
            if response.status_code != 200:
                print("❌ Django server not responding correctly")
                return False
            print("✅ Django server is running")
        except requests.RequestException as e:
            print(f"❌ Cannot connect to Django server: {e}")
            return False
        
        # Check Load Balancer
        try:
            response = requests.get(f"{self.loadbalancer_url}/status", timeout=5)
            if response.status_code != 200:
                print("❌ Load balancer not responding correctly")
                return False
            print("✅ Load balancer is running")
        except requests.RequestException as e:
            print(f"❌ Cannot connect to load balancer: {e}")
            return False
        
        return True
    
    def switch_algorithm(self, algorithm: str) -> bool:
        """Switch the scheduling algorithm"""
        try:
            response = requests.post(
                f"{self.providers_url}/algorithm/switch/",
                json={"algorithm": algorithm},
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"✅ Switched to {algorithm} algorithm")
                return True
            else:
                print(f"❌ Failed to switch to {algorithm}: {response.text}")
                return False
                
        except requests.RequestException as e:
            print(f"❌ Error switching to {algorithm}: {e}")
            return False
    
    def reset_algorithm_metrics(self) -> bool:
        """Reset algorithm metrics for clean measurement"""
        try:
            response = requests.post(f"{self.providers_url}/algorithm/reset/", timeout=5)
            if response.status_code == 200:
                print("✅ Algorithm metrics reset")
                return True
            else:
                print(f"⚠️ Could not reset metrics: {response.text}")
                return False
        except requests.RequestException as e:
            print(f"⚠️ Error resetting metrics: {e}")
            return False
    
    def wait_for_system_ready(self, timeout: int = 30) -> bool:
        """Wait for the system to be ready for next algorithm"""
        print(f"Waiting for system to be ready...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check if load balancer is ready (no pending batches)
                response = requests.get(f"{self.loadbalancer_url}/status", timeout=5)
                if response.status_code == 200:
                    status = response.json()
                    if status.get('current_batch_size', 0) == 0:
                        print("✅ System is ready")
                        return True
                
                time.sleep(1)
                
            except Exception as e:
                print(f"⚠️ Error checking system status: {e}")
                time.sleep(1)
        
        print(f"⚠️ System not ready after {timeout} seconds, proceeding anyway")
        return False
    
    def execute_testbed(self, testbed: List[TestBatch], algorithm: str) -> AlgorithmResult:
        """Execute testbed against a specific algorithm"""
        print(f"\n{'='*60}")
        print(f"RUNNING TESTBED WITH {algorithm} ALGORITHM")
        print(f"{'='*60}")
        
        start_time = datetime.now()
        errors = []
        batches_sent = 0
        jobs_sent = 0
        successful_requests = 0
        total_requests = 0
        
        # Update logging settings for this algorithm
        self.update_logging_settings(algorithm)
        
        # Switch to the algorithm
        if not self.switch_algorithm(algorithm):
            return AlgorithmResult(
                algorithm=algorithm,
                start_time=start_time,
                end_time=datetime.now(),
                total_batches_sent=0,
                total_jobs_sent=0,
                success_rate=0.0,
                errors=["Failed to switch algorithm"],
                log_directory=f"experiment_logs/{self.experiment_timestamp}/{algorithm}"
            )
        
        # Wait for system to be ready
        self.wait_for_system_ready()
        
        # Reset metrics
        self.reset_algorithm_metrics()
        
        # Record start time for accurate timing
        experiment_start = time.time()
        
        try:
            for batch in testbed:
                # Wait for the correct time to send this batch
                target_time = experiment_start + batch.send_time_offset
                current_time = time.time()
                
                if current_time < target_time:
                    sleep_time = target_time - current_time
                    print(f"Waiting {sleep_time:.1f}s before sending batch {batch.batch_id}")
                    time.sleep(sleep_time)
                
                # Send batch to load balancer
                print(f"Sending batch {batch.batch_id} with {len(batch.jobs)} jobs")
                
                try:
                    # Send each job in the batch
                    for job in batch.jobs:
                        url = f"{self.base_url}/developers/run_service_async/{job.function_id}"
                        payload = job.to_request_payload()
                        
                        response = requests.post(
                            url,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                            timeout=10
                        )
                        
                        total_requests += 1
                        if response.status_code in [200, 201, 202]:
                            successful_requests += 1
                        else:
                            error_msg = f"Job {job.function_id} failed: {response.status_code} - {response.text[:100]}"
                            errors.append(error_msg)
                            print(f"  ⚠️ {error_msg}")
                        
                        jobs_sent += 1
                        
                        # Small delay between jobs in the same batch
                        time.sleep(0.2)
                    
                    batches_sent += 1
                    print(f"  ✅ Batch {batch.batch_id} sent successfully")
                    
                except Exception as e:
                    error_msg = f"Error sending batch {batch.batch_id}: {str(e)}"
                    errors.append(error_msg)
                    print(f"  ❌ {error_msg}")
            
            # Wait a bit for all jobs to complete
            print(f"Waiting 30s for jobs to complete...")
            time.sleep(30)
            
        except KeyboardInterrupt:
            print(f"\n⚠️ Testbed execution interrupted for {algorithm}")
            errors.append("Execution interrupted by user")
        
        except Exception as e:
            error_msg = f"Unexpected error during {algorithm} execution: {str(e)}"
            errors.append(error_msg)
            print(f"❌ {error_msg}")
        
        end_time = datetime.now()
        success_rate = successful_requests / total_requests if total_requests > 0 else 0.0
        
        result = AlgorithmResult(
            algorithm=algorithm,
            start_time=start_time,
            end_time=end_time,
            total_batches_sent=batches_sent,
            total_jobs_sent=jobs_sent,
            success_rate=success_rate,
            errors=errors,
            log_directory=f"experiment_logs/{self.experiment_timestamp}/{algorithm}"
        )
        
        print(f"\n{algorithm} Results:")
        print(f"  Duration: {end_time - start_time}")
        print(f"  Batches sent: {batches_sent}/{len(testbed)}")
        print(f"  Jobs sent: {jobs_sent}")
        print(f"  Success rate: {success_rate:.2%}")
        print(f"  Errors: {len(errors)}")
        
        return result
    
    def run_full_comparison(self, testbed_file: str) -> Dict[str, AlgorithmResult]:
        """Run the complete algorithm comparison"""
        print("="*80)
        print("SCHEDULING ALGORITHM COMPARISON WITH RANDOMIZED TESTBED")
        print("="*80)
        
        # Load testbed
        testbed_gen = RandomizedTestbed()
        try:
            testbed = testbed_gen.load_testbed(testbed_file)
        except Exception as e:
            print(f"❌ Error loading testbed: {e}")
            return {}
        
        # Setup logging
        base_logs_dir = self.setup_experiment_logging()
        
        # Check system status
        if not self.check_system_status():
            print("❌ System not ready for experiments")
            return {}
        
        print(f"\nTestbed Summary:")
        summary = testbed_gen.get_testbed_summary()
        print(f"  Batches: {summary['total_batches']}")
        print(f"  Jobs: {summary['total_jobs']}")
        print(f"  Duration: {summary['duration_seconds']:.1f}s")
        print(f"  Function distribution: {summary['function_distribution']}")
        
        # Run testbed for each algorithm
        results = {}
        
        for i, algorithm in enumerate(self.algorithms):
            print(f"\n{'='*20} Algorithm {i+1}/{len(self.algorithms)}: {algorithm} {'='*20}")
            
            try:
                result = self.execute_testbed(testbed, algorithm)
                results[algorithm] = result
                
                # Wait between algorithms to let the system settle
                if i < len(self.algorithms) - 1:
                    print(f"\nWaiting 10s before next algorithm...")
                    time.sleep(10)
                    
            except Exception as e:
                print(f"❌ Failed to execute testbed for {algorithm}: {e}")
                results[algorithm] = AlgorithmResult(
                    algorithm=algorithm,
                    start_time=datetime.now(),
                    end_time=datetime.now(),
                    total_batches_sent=0,
                    total_jobs_sent=0,
                    success_rate=0.0,
                    errors=[str(e)],
                    log_directory=f"experiment_logs/{self.experiment_timestamp}/{algorithm}"
                )
        
        # Save results summary
        self.save_experiment_summary(results, base_logs_dir)
        
        return results
    
    def save_experiment_summary(self, results: Dict[str, AlgorithmResult], base_logs_dir: str):
        """Save experiment summary"""
        summary = {
            "experiment_timestamp": self.experiment_timestamp,
            "testbed_file": "N/A",  # Would be passed from caller
            "start_time": datetime.now().isoformat(),
            "algorithms_tested": list(results.keys()),
            "results": {}
        }
        
        for algorithm, result in results.items():
            summary["results"][algorithm] = {
                "start_time": result.start_time.isoformat(),
                "end_time": result.end_time.isoformat(),
                "duration_seconds": (result.end_time - result.start_time).total_seconds(),
                "batches_sent": result.total_batches_sent,
                "jobs_sent": result.total_jobs_sent,
                "success_rate": result.success_rate,
                "error_count": len(result.errors),
                "errors": result.errors[:10],  # First 10 errors only
                "log_directory": result.log_directory
            }
        
        # Save to base experiment directory
        summary_file = f"{base_logs_dir}/experiment_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\n✅ Experiment summary saved to: {summary_file}")
        
        # Print final summary
        print(f"\n{'='*60}")
        print("FINAL EXPERIMENT SUMMARY")
        print(f"{'='*60}")
        print(f"Experiment ID: {self.experiment_timestamp}")
        print(f"Algorithms tested: {len(results)}")
        
        for algorithm, result in results.items():
            duration = (result.end_time - result.start_time).total_seconds()
            print(f"\n{algorithm}:")
            print(f"  Duration: {duration:.1f}s")
            print(f"  Jobs sent: {result.total_jobs_sent}")
            print(f"  Success rate: {result.success_rate:.2%}")
            print(f"  Errors: {len(result.errors)}")
            print(f"  Logs: {result.log_directory}")


def main():
    """Main function"""
    if len(sys.argv) != 2:
        print("Usage: python testbed_runner.py <testbed_file.json>")
        print("\nExample:")
        print("  # First generate a testbed:")
        print("  python randomized_testbed.py")
        print("  # Then run the comparison:")
        print("  python testbed_runner.py testbed_2024-01-15_14-30-45_seed12345.json")
        return
    
    testbed_file = sys.argv[1]
    
    if not os.path.exists(testbed_file):
        print(f"❌ Testbed file not found: {testbed_file}")
        return
    
    print(f"Using testbed file: {testbed_file}")
    
    # Create and run the testbed runner
    runner = TestbedRunner()
    results = runner.run_full_comparison(testbed_file)
    
    if results:
        print(f"\n✅ Experiment completed successfully!")
        print(f"Check the logs in: experiment_logs/{runner.experiment_timestamp}/")
    else:
        print(f"\n❌ Experiment failed!")


if __name__ == "__main__":
    main() 