#!/usr/bin/env python3
"""
Test script for the Belady-based minimum cost precomputation algorithm.
This script tests the MinCostPrecomputer class under various conditions
to validate its functionality and correctness.
"""

import unittest
import json
import os
from datetime import datetime
from collections import defaultdict

from experiments.belady_precomputation import MinCostPrecomputer
from experiments.randomized_testbed import RandomizedTestbed, TestBatch, TestJob


class TestMinCostPrecomputer(unittest.TestCase):
    """Test suite for MinCostPrecomputer"""

    def setUp(self):
        """Set up test environment before each test"""
        self.seed = 12345
        self.testbed_gen = RandomizedTestbed(seed=self.seed)
        self.precomputer = MinCostPrecomputer()
        
        # Default test parameters
        self.provider_ids = ["provider_1", "provider_2", "provider_3"]
        self.provider_costs = {
            "provider_1": 1.0,  # Standard cost
            "provider_2": 0.8,  # Low cost provider
            "provider_3": 1.2,  # High cost provider
        }
        self.provider_delays = {
            "provider_1": 0.1,
            "provider_2": 0.15,
            "provider_3": 0.05,
        }
    
    def test_basic_functionality(self):
        """Test basic functionality with a small testbed"""
        print("\n=== Testing basic functionality ===")
        
        # Generate a small testbed for testing
        testbed = self.testbed_gen.generate_testbed(
            num_batches=5,
            min_jobs_per_batch=2,
            max_jobs_per_batch=4,
            function_ids=[1, 2, 3, 4, 5]
        )
        
        # Run the precomputation
        result = self.precomputer.precompute_optimal_schedule(
            testbed=testbed,
            provider_ids=self.provider_ids,
            provider_costs=self.provider_costs,
            provider_delays=self.provider_delays
        )
        
        # Verify the result contains expected fields
        self.assertIn("total_jobs", result)
        self.assertIn("total_optimization_cost", result)
        self.assertIn("cache_hit_rate", result)
        self.assertIn("assignment_log", result)
        
        # Verify all jobs were assigned
        total_jobs_in_testbed = sum(len(batch.jobs) for batch in testbed)
        self.assertEqual(result["total_jobs"], total_jobs_in_testbed)
        self.assertEqual(len(result["assignment_log"]), total_jobs_in_testbed)
        
        # Verify assignments are valid
        for assignment in result["assignment_log"]:
            self.assertIn(assignment["provider_id"], self.provider_ids)
    
    def test_cache_behavior(self):
        """Test if cache behavior is working as expected"""
        print("\n=== Testing cache behavior ===")
        
        # Generate testbed with repeated function calls to test caching
        testbed = []
        
        # Create two batches with the same functions to test cache hits
        batch1 = TestBatch(batch_id=1, send_time_offset=0.0)
        batch1.jobs = [
            TestJob(function_id=1, batch_id=1, job_index=0, invocation_count=1),
            TestJob(function_id=2, batch_id=1, job_index=1, invocation_count=1),
            TestJob(function_id=3, batch_id=1, job_index=2, invocation_count=1)
        ]
        
        # Second batch with same functions should get cache hits
        batch2 = TestBatch(batch_id=2, send_time_offset=1.0)
        batch2.jobs = [
            TestJob(function_id=1, batch_id=2, job_index=0, invocation_count=1),
            TestJob(function_id=2, batch_id=2, job_index=1, invocation_count=1),
            TestJob(function_id=3, batch_id=2, job_index=2, invocation_count=1)
        ]
        
        testbed = [batch1, batch2]
        
        # Run the precomputation
        result = self.precomputer.precompute_optimal_schedule(
            testbed=testbed,
            provider_ids=self.provider_ids,
            provider_costs=self.provider_costs,
            provider_delays=self.provider_delays
        )
        
        # We should see some cache hits in the second batch
        cache_hits = 0
        for assignment in result["assignment_log"]:
            if assignment["job"]["batch_id"] == 2 and assignment["cache_hit"]:
                cache_hits += 1
        
        # Some of the second batch jobs should be cache hits
        self.assertGreater(cache_hits, 0)
        self.assertEqual(result["cache_hits"], cache_hits)
    
    def test_cost_optimization(self):
        """Test if cost optimization is working correctly"""
        print("\n=== Testing cost optimization ===")
        
        # Create a testbed with a mix of jobs
        testbed = self.testbed_gen.generate_testbed(
            num_batches=10,
            min_jobs_per_batch=3,
            max_jobs_per_batch=5,
            function_ids=list(range(1, 11))  # Functions 1-10
        )
        
        # Set up very different provider costs to make optimization effects clear
        skewed_provider_costs = {
            "provider_1": 1.0,
            "provider_2": 0.5,  # Much cheaper
            "provider_3": 2.0,  # Much more expensive
        }
        
        # Run the precomputation
        result = self.precomputer.precompute_optimal_schedule(
            testbed=testbed,
            provider_ids=self.provider_ids,
            provider_costs=skewed_provider_costs,
            provider_delays=self.provider_delays
        )
        
        # Count assignments per provider
        provider_assignments = defaultdict(int)
        for assignment in result["assignment_log"]:
            provider_assignments[assignment["provider_id"]] += 1
        
        # The cheaper provider should have more assignments
        # (assuming all other factors being equal)
        print(f"Provider assignments: {dict(provider_assignments)}")
        
        # The cheapest provider should have a significant number of assignments
        # but not necessarily the most due to caching effects and load balancing
        self.assertGreater(provider_assignments["provider_2"], 
                          len(result["assignment_log"]) / len(self.provider_ids) * 0.8)
    
    def test_empty_batches(self):
        """Test handling of empty batches"""
        print("\n=== Testing empty batches ===")
        
        # Create a testbed with some empty batches
        batch1 = TestBatch(batch_id=1, send_time_offset=0.0)
        batch1.jobs = [
            TestJob(function_id=1, batch_id=1, job_index=0, invocation_count=1),
            TestJob(function_id=2, batch_id=1, job_index=1, invocation_count=1)
        ]
        
        # Empty batch
        batch2 = TestBatch(batch_id=2, send_time_offset=1.0)
        batch2.jobs = []
        
        batch3 = TestBatch(batch_id=3, send_time_offset=2.0)
        batch3.jobs = [
            TestJob(function_id=3, batch_id=3, job_index=0, invocation_count=1)
        ]
        
        testbed = [batch1, batch2, batch3]
        
        # Run the precomputation
        result = self.precomputer.precompute_optimal_schedule(
            testbed=testbed,
            provider_ids=self.provider_ids,
            provider_costs=self.provider_costs,
            provider_delays=self.provider_delays
        )
        
        # Verify the result contains expected fields
        self.assertIn("total_jobs", result)
        
        # Verify all jobs were assigned (should be 3 jobs)
        self.assertEqual(result["total_jobs"], 3)
        self.assertEqual(len(result["assignment_log"]), 3)
        
        # Verify the correct number of batches is reported
        self.assertEqual(result["total_batches"], 3)
    
    def test_single_provider(self):
        """Test with a single provider"""
        print("\n=== Testing single provider scenario ===")
        
        # Generate a small testbed for testing
        testbed = self.testbed_gen.generate_testbed(
            num_batches=3,
            min_jobs_per_batch=2,
            max_jobs_per_batch=3,
            function_ids=[1, 2, 3, 4]
        )
        
        # Run with a single provider
        single_provider = ["provider_solo"]
        provider_cost = {"provider_solo": 1.0}
        provider_delay = {"provider_solo": 0.1}
        
        result = self.precomputer.precompute_optimal_schedule(
            testbed=testbed,
            provider_ids=single_provider,
            provider_costs=provider_cost,
            provider_delays=provider_delay
        )
        
        # Verify all jobs were assigned to the single provider
        for assignment in result["assignment_log"]:
            self.assertEqual(assignment["provider_id"], "provider_solo")
    
    def test_large_testbed(self):
        """Test with a larger testbed to ensure scalability"""
        print("\n=== Testing large testbed scenario ===")
        
        # Generate a larger testbed
        testbed = self.testbed_gen.generate_testbed(
            num_batches=20,
            min_jobs_per_batch=5,
            max_jobs_per_batch=10,
            function_ids=list(range(1, 21))  # Functions 1-20
        )
        
        # Track time for performance analysis
        start_time = datetime.now()
        
        result = self.precomputer.precompute_optimal_schedule(
            testbed=testbed,
            provider_ids=self.provider_ids,
            provider_costs=self.provider_costs,
            provider_delays=self.provider_delays
        )
        
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        print(f"Processed large testbed in {elapsed:.2f} seconds")
        print(f"Total jobs: {result['total_jobs']}")
        print(f"Cache hit rate: {result['cache_hit_rate']:.2%}")
        
        # Check that all jobs were assigned
        total_jobs_in_testbed = sum(len(batch.jobs) for batch in testbed)
        self.assertEqual(result["total_jobs"], total_jobs_in_testbed)
        
    def test_save_and_load_results(self):
        """Test saving and creating assignment mapping"""
        print("\n=== Testing result saving and mapping creation ===")
        
        # Generate a small testbed
        testbed = self.testbed_gen.generate_testbed(
            num_batches=3,
            min_jobs_per_batch=2,
            max_jobs_per_batch=3,
            function_ids=[1, 2, 3]
        )
        
        # Run the precomputation
        result = self.precomputer.precompute_optimal_schedule(
            testbed=testbed,
            provider_ids=self.provider_ids,
            provider_costs=self.provider_costs,
            provider_delays=self.provider_delays
        )
        
        # Save results to a temporary file
        test_filename = "test_belady_result_temp.json"
        saved_filename = self.precomputer.save_optimal_schedule(result, test_filename)
        
        # Verify the file exists
        self.assertTrue(os.path.exists(saved_filename))
        
        # Create assignment mapping
        assignment_map = self.precomputer.create_assignment_mapping(result)
        
        # Verify the mapping has entries
        self.assertGreater(len(assignment_map), 0)
        
        # Clean up the temporary file
        try:
            os.remove(test_filename)
        except:
            pass


def main():
    """Run the tests"""
    unittest.main()


if __name__ == "__main__":
    main() 