#!/usr/bin/env python3
"""
Randomized Testbed Generator for Scheduling Algorithm Comparison

This module generates a randomized but reproducible testbed of function IDs 
and invocation counts that can be run against all scheduling algorithms 
for fair comparison.
"""

import json
import random
import time
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Any
import requests
from dataclasses import dataclass, asdict


@dataclass
class TestJob:
    """Represents a test job with function ID and invocation count"""
    function_id: int
    invocation_count: int
    batch_id: int
    job_index: int
    
    def to_request_payload(self) -> Dict[str, Any]:
        """Convert to API request payload"""
        return {
            "numberOfInvocations": self.invocation_count,
            "chained": False,
            "input": "None",
            "runMultipleInvocations": False
        }


@dataclass
class TestBatch:
    """Represents a batch of test jobs to be sent together"""
    batch_id: int
    jobs: List[TestJob]
    send_time_offset: float  # Seconds from experiment start
    from scheduler.scheduler.settings import HOST
    
    def to_batch_payload(self) -> Dict[str, Any]:
        """Convert to load balancer batch payload"""
        requests = []
        for job in self.jobs:
            request = {
                "url": f"http://{HOST}/developers/run_service_async/{job.function_id}",
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": job.to_request_payload(),
                "job_metadata": {
                    "function_id": job.function_id,
                    "batch_id": job.batch_id,
                    "job_index": job.job_index
                }
            }
            requests.append(request)
        return {"requests": requests}


class RandomizedTestbed:
    """Generates and manages randomized testbeds for algorithm comparison"""
    
    def __init__(self, seed: int = 42):
        """
        Initialize testbed generator
        
        Args:
            seed: Random seed for reproducible testbeds
        """
        self.seed = seed
        self.random = random.Random(seed)
        self.testbed_data = None
        
    def generate_testbed(self, 
                        num_batches: int = 20,
                        min_jobs_per_batch: int = 1,
                        max_jobs_per_batch: int = 8,
                        min_invocations: int = 1,
                        max_invocations: int = 3,
                        function_ids: List[int] = None,
                        min_batch_interval: float = 2.0,
                        max_batch_interval: float = 10.0) -> List[TestBatch]:
        """
        Generate a randomized testbed
        
        Args:
            num_batches: Number of batches to generate
            min_jobs_per_batch: Minimum jobs per batch
            max_jobs_per_batch: Maximum jobs per batch
            min_invocations: Minimum invocations per job
            max_invocations: Maximum invocations per job
            function_ids: List of available function IDs (if None, uses default)
            min_batch_interval: Minimum seconds between batches
            max_batch_interval: Maximum seconds between batches
            
        Returns:
            List of TestBatch objects
        """
        if function_ids is None:
            # Default function IDs - adjust based on your available services
            function_ids = [18, 19, 20, 21, 22, 23, 24, 25]
        
        batches = []
        current_time_offset = 0.0
        
        for batch_id in range(num_batches):
            # Random number of jobs in this batch
            num_jobs = self.random.randint(min_jobs_per_batch, max_jobs_per_batch)
            
            jobs = []
            for job_index in range(num_jobs):
                function_id = self.random.choice(function_ids)
                invocation_count = self.random.randint(min_invocations, max_invocations)
                
                job = TestJob(
                    function_id=function_id,
                    invocation_count=invocation_count,
                    batch_id=batch_id,
                    job_index=job_index
                )
                jobs.append(job)
            
            batch = TestBatch(
                batch_id=batch_id,
                jobs=jobs,
                send_time_offset=current_time_offset
            )
            batches.append(batch)
            
            # Random interval until next batch
            interval = self.random.uniform(min_batch_interval, max_batch_interval)
            current_time_offset += interval
        
        self.testbed_data = batches
        return batches
    
    def save_testbed(self, filename: str = None) -> str:
        """Save testbed to JSON file"""
        if self.testbed_data is None:
            raise ValueError("No testbed data to save. Call generate_testbed() first.")
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"testbed_{timestamp}_seed{self.seed}.json"
        
        # Convert to serializable format
        data = {
            "seed": self.seed,
            "generation_time": datetime.now().isoformat(),
            "batches": [asdict(batch) for batch in self.testbed_data],
            "total_jobs": sum(len(batch.jobs) for batch in self.testbed_data),
            "total_invocations": sum(sum(job.invocation_count for job in batch.jobs) for batch in self.testbed_data),
            "duration_seconds": self.testbed_data[-1].send_time_offset if self.testbed_data else 0
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"Testbed saved to: {filename}")
        print(f"  Total batches: {len(self.testbed_data)}")
        print(f"  Total jobs: {data['total_jobs']}")
        print(f"  Total invocations: {data['total_invocations']}")
        print(f"  Duration: {data['duration_seconds']:.1f} seconds")
        
        return filename
    
    def load_testbed(self, filename: str) -> List[TestBatch]:
        """Load testbed from JSON file"""
        with open(filename, 'r') as f:
            data = json.load(f)
        
        self.seed = data['seed']
        
        batches = []
        for batch_data in data['batches']:
            jobs = [TestJob(**job_data) for job_data in batch_data['jobs']]
            batch = TestBatch(
                batch_id=batch_data['batch_id'],
                jobs=jobs,
                send_time_offset=batch_data['send_time_offset']
            )
            batches.append(batch)
        
        self.testbed_data = batches
        print(f"Loaded testbed from: {filename}")
        print(f"  Seed: {self.seed}")
        print(f"  Batches: {len(batches)}")
        
        return batches
    
    def get_testbed_summary(self) -> Dict[str, Any]:
        """Get summary statistics of the current testbed"""
        if self.testbed_data is None:
            return {}
        
        function_counts = {}
        invocation_counts = {}
        batch_sizes = []
        
        for batch in self.testbed_data:
            batch_sizes.append(len(batch.jobs))
            for job in batch.jobs:
                function_counts[job.function_id] = function_counts.get(job.function_id, 0) + 1
                invocation_counts[job.invocation_count] = invocation_counts.get(job.invocation_count, 0) + 1
        
        return {
            "seed": self.seed,
            "total_batches": len(self.testbed_data),
            "total_jobs": sum(len(batch.jobs) for batch in self.testbed_data),
            "total_invocations": sum(sum(job.invocation_count for job in batch.jobs) for batch in self.testbed_data),
            "duration_seconds": self.testbed_data[-1].send_time_offset if self.testbed_data else 0,
            "function_distribution": function_counts,
            "invocation_distribution": invocation_counts,
            "avg_batch_size": sum(batch_sizes) / len(batch_sizes) if batch_sizes else 0,
            "min_batch_size": min(batch_sizes) if batch_sizes else 0,
            "max_batch_size": max(batch_sizes) if batch_sizes else 0
        }


def main():
    """Example usage"""
    print("=== Randomized Testbed Generator ===")
    
    # Create testbed generator
    testbed_gen = RandomizedTestbed(seed=12345)
    
    # Generate testbed
    print("\nGenerating testbed...")
    batches = testbed_gen.generate_testbed(
        num_batches=15,
        min_jobs_per_batch=2,
        max_jobs_per_batch=20,
        min_invocations=1,
        max_invocations=20,
        function_ids=[18, 19, 20, 21, 22, 23, 24, 25],
        min_batch_interval=0.0,
        max_batch_interval=10.0
    )
    
    # Save testbed
    filename = testbed_gen.save_testbed()
    
    # Print summary
    summary = testbed_gen.get_testbed_summary()
    print(f"\n=== Testbed Summary ===")
    print(f"Total duration: {summary['duration_seconds']:.1f} seconds")
    print(f"Function distribution: {summary['function_distribution']}")
    print(f"Invocation distribution: {summary['invocation_distribution']}")
    print(f"Batch size range: {summary['min_batch_size']}-{summary['max_batch_size']} (avg: {summary['avg_batch_size']:.1f})")
    
    # Show first few batches
    print(f"\n=== First 3 Batches ===")
    for i, batch in enumerate(batches[:3]):
        print(f"Batch {batch.batch_id} (t={batch.send_time_offset:.1f}s): {len(batch.jobs)} jobs")
        for job in batch.jobs:
            print(f"  Job {job.job_index}: function_{job.function_id} x{job.invocation_count}")


if __name__ == "__main__":
    main() 