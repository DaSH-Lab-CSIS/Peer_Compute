#!/usr/bin/env python3
"""
Min-Cost Pre-computation for Optimal Scheduling

This module implements optimal assignment computation by using linear programming
to find the minimum cost assignment for the entire testbed. This provides the
theoretical optimum for cost-aware scheduling comparison.
"""

import json
import time
import copy
from collections import defaultdict, deque
from typing import Dict, List, Tuple, Any, Optional, Set
from dataclasses import dataclass
from datetime import datetime

from experiments.randomized_testbed import TestBatch, TestJob
from experiments.mincost import minimize_total_cost


@dataclass
class ProviderState:
    """Represents provider state including cache"""
    provider_id: str
    cached_functions: Set[int]
    last_used: Dict[int, float]  # function_id -> timestamp
    current_load: int = 0
    total_cost: float = 0.0
    
    def is_cached(self, function_id: int) -> bool:
        """Check if function is cached"""
        return function_id in self.cached_functions
    
    def cache_function(self, function_id: int, timestamp: float):
        """Cache a function"""
        self.cached_functions.add(function_id)
        self.last_used[function_id] = timestamp
    
    def evict_lru_if_needed(self, max_cache_size: int = 10):
        """Evict least recently used function if cache is full"""
        if len(self.cached_functions) >= max_cache_size:
            # Find least recently used
            lru_function = min(self.last_used.keys(), key=lambda f: self.last_used[f])
            self.cached_functions.discard(lru_function)
            del self.last_used[lru_function]


class MinCostPrecomputer:
    """Pre-computes optimal min-cost schedule for entire testbed using linear programming"""
    
    def __init__(self):
        self.providers = {}  # provider_id -> ProviderState
        self.global_time = 0.0
        self.assignment_log = []
        self.cache_stats = {"hits": 0, "misses": 0}
        self.total_optimization_cost = 0.0
        
    def initialize_providers(self, provider_ids: List[str], 
                           initial_cache_size: int = 5,
                           max_cache_size: int = 10):
        """Initialize provider states"""
        for provider_id in provider_ids:
            self.providers[provider_id] = ProviderState(
                provider_id=provider_id,
                cached_functions=set(),
                last_used={}
            )
        
        print(f"Initialized {len(provider_ids)} providers for min-cost pre-computation")
    
    def create_cost_matrix(self, jobs: List[TestJob], provider_ids: List[str], 
                          provider_costs: Dict[str, float] = None,
                          cache_discount: float = 0.5) -> Dict[str, Dict[str, float]]:
        """
        Create cost matrix for min-cost optimization
        
        Args:
            jobs: List of jobs to assign
            provider_ids: List of available providers
            provider_costs: Base cost per provider
            cache_discount: Discount factor for cached functions (0-1)
            
        Returns:
            cost_matrix[provider][service] = cost
        """
        if provider_costs is None:
            provider_costs = {pid: 1.0 for pid in provider_ids}
        
        cost_matrix = {}
        
        for provider_id in provider_ids:
            cost_matrix[provider_id] = {}
            provider = self.providers[provider_id]
            base_cost = provider_costs[provider_id]
            
            for i, job in enumerate(jobs):
                service_key = f"job_{i}_func_{job.function_id}"
                
                # Calculate cost based on cache status and invocation count
                if provider.is_cached(job.function_id):
                    # Cache hit: reduced cost
                    cost = base_cost * job.invocation_count * cache_discount
                else:
                    # Cache miss: full cost
                    cost = base_cost * job.invocation_count
                
                # Add load penalty to encourage load balancing
                load_penalty = provider.current_load * 0.1
                cost += load_penalty
                
                cost_matrix[provider_id][service_key] = max(cost, 0.01)  # Ensure positive cost
        
        return cost_matrix
    
    def create_delay_dict(self, provider_ids: List[str], 
                         provider_delays: Dict[str, float] = None) -> Dict[str, float]:
        """
        Create delay dictionary for min-cost optimization
        
        Args:
            provider_ids: List of provider IDs
            provider_delays: Optional delay per provider
            
        Returns:
            delay dictionary
        """
        if provider_delays is None:
            # Default delays - could be based on startup costs, network latency, etc.
            provider_delays = {pid: 0.1 for pid in provider_ids}
        
        return provider_delays
    
    def extract_services_from_jobs(self, jobs: List[TestJob]) -> List[str]:
        """Extract service keys from jobs list"""
        services = []
        for i, job in enumerate(jobs):
            service_key = f"job_{i}_func_{job.function_id}"
            services.append(service_key)
        return services
    
    def compute_optimal_batch_assignment(self, batch: TestBatch, 
                                       provider_ids: List[str],
                                       provider_costs: Dict[str, float] = None,
                                       provider_delays: Dict[str, float] = None) -> Tuple[Dict[str, str], float]:
        """
        Compute optimal assignment for a single batch using min-cost optimization
        
        Args:
            batch: Test batch to optimize
            provider_ids: Available providers
            provider_costs: Cost per provider
            provider_delays: Delay per provider
            
        Returns:
            Tuple of (assignment_dict, total_cost)
        """
        if not batch.jobs:
            return {}, 0.0
        
        # Create services list from jobs
        services = self.extract_services_from_jobs(batch.jobs)
        
        # Create cost matrix
        cost_matrix = self.create_cost_matrix(batch.jobs, provider_ids, provider_costs)
        
        # Create delay dictionary
        delay_dict = self.create_delay_dict(provider_ids, provider_delays)
        
        # Run min-cost optimization
        assignment, total_cost = minimize_total_cost(provider_ids, services, cost_matrix, delay_dict)
        
        if assignment is None:
            print(f"Warning: Optimization failed for batch {batch.batch_id}")
            # Fallback to round-robin assignment
            assignment = {}
            for i, service in enumerate(services):
                assignment[service] = provider_ids[i % len(provider_ids)]
            total_cost = 0.0
        
        return assignment, total_cost
    
    def execute_batch_assignment(self, batch: TestBatch, assignment: Dict[str, str], 
                               current_time: float):
        """Execute the batch assignment and update provider states"""
        for i, job in enumerate(batch.jobs):
            service_key = f"job_{i}_func_{job.function_id}"
            provider_id = assignment[service_key]
            provider = self.providers[provider_id]
            
            # Check cache status before assignment
            cache_hit = provider.is_cached(job.function_id)
            if cache_hit:
                self.cache_stats["hits"] += 1
            else:
                self.cache_stats["misses"] += 1
            
            # Update cache
            if not cache_hit:
                provider.cache_function(job.function_id, current_time)
                provider.evict_lru_if_needed()
            else:
                # Update last used time
                provider.last_used[job.function_id] = current_time
            
            # Update load
            provider.current_load += job.invocation_count
            
            # Log assignment
            self.assignment_log.append({
                "timestamp": current_time,
                "job": {
                    "function_id": job.function_id,
                    "invocation_count": job.invocation_count,
                    "batch_id": job.batch_id,
                    "job_index": job.job_index
                },
                "provider_id": provider_id,
                "cache_hit": cache_hit,
                "provider_cache_state": list(provider.cached_functions),
                "service_key": service_key
            })
    
    def precompute_optimal_schedule(self, testbed: List[TestBatch],
                                  provider_ids: List[str] = None,
                                  provider_costs: Dict[str, float] = None,
                                  provider_delays: Dict[str, float] = None) -> Dict[str, Any]:
        """
        Pre-compute optimal min-cost schedule for entire testbed
        
        Args:
            testbed: List of test batches
            provider_ids: List of provider IDs (if None, creates default)
            provider_costs: Provider cost mapping
            provider_delays: Provider delay mapping
            
        Returns:
            Dictionary with optimal schedule and statistics
        """
        if provider_ids is None:
            provider_ids = [f"provider_{i}" for i in range(5)]  # Default 5 providers
        
        if provider_costs is None:
            provider_costs = {pid: 1.0 for pid in provider_ids}
        
        if provider_delays is None:
            provider_delays = {pid: 0.1 for pid in provider_ids}
        
        print(f"Pre-computing optimal min-cost schedule...")
        print(f"Testbed: {len(testbed)} batches")
        print(f"Providers: {len(provider_ids)}")
        
        # Initialize providers
        self.initialize_providers(provider_ids)
        
        # Process each batch in order
        total_jobs = 0
        total_optimization_cost = 0.0
        
        for batch in testbed:
            self.global_time = batch.send_time_offset
            
            # Compute optimal assignment for this batch
            assignment, batch_cost = self.compute_optimal_batch_assignment(
                batch, provider_ids, provider_costs, provider_delays
            )
            
            # Execute assignment and update states
            self.execute_batch_assignment(batch, assignment, self.global_time)
            
            total_optimization_cost += batch_cost
            total_jobs += len(batch.jobs)
            
            if len(batch.jobs) > 0:
                print(f"Batch {batch.batch_id}: {len(batch.jobs)} jobs, cost: {batch_cost:.2f}")
        
        # Calculate statistics
        cache_hit_rate = self.cache_stats["hits"] / (self.cache_stats["hits"] + self.cache_stats["misses"]) if (self.cache_stats["hits"] + self.cache_stats["misses"]) > 0 else 0.0
        
        result = {
            "algorithm": "MIN_COST_OPTIMAL",
            "total_jobs": total_jobs,
            "total_batches": len(testbed),
            "total_optimization_cost": total_optimization_cost,
            "cache_hit_rate": cache_hit_rate,
            "cache_hits": self.cache_stats["hits"],
            "cache_misses": self.cache_stats["misses"],
            "providers_used": list(provider_ids),
            "provider_costs": provider_costs,
            "provider_delays": provider_delays,
            "assignment_log": self.assignment_log,
            "provider_final_states": {
                pid: {
                    "cached_functions": list(provider.cached_functions),
                    "final_load": provider.current_load
                }
                for pid, provider in self.providers.items()
            },
            "computation_time": self.global_time
        }
        
        print(f"✅ Min-cost pre-computation complete!")
        print(f"   Total optimization cost: {total_optimization_cost:.2f}")
        print(f"   Cache hit rate: {cache_hit_rate:.2%}")
        print(f"   Total cache hits: {self.cache_stats['hits']}")
        print(f"   Total cache misses: {self.cache_stats['misses']}")
        
        return result
    
    def save_optimal_schedule(self, result: Dict[str, Any], filename: str = None) -> str:
        """Save optimal schedule to file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"mincost_optimal_schedule_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"Optimal min-cost schedule saved to: {filename}")
        return filename
    
    def create_assignment_mapping(self, result: Dict[str, Any]) -> Dict[str, str]:
        """
        Create assignment mapping for runtime use
        Returns: job_key -> provider_id mapping
        """
        assignment_map = {}
        
        for entry in result["assignment_log"]:
            job = entry["job"]
            job_key = f"batch_{job['batch_id']}_job_{job['job_index']}_func_{job['function_id']}"
            assignment_map[job_key] = entry["provider_id"]
        
        return assignment_map


def main():
    """Example usage"""
    print("=== Min-Cost Pre-computation Example ===")
    
    # Load a testbed (you would pass this from your main experiment)
    from experiments.randomized_testbed import RandomizedTestbed
    
    # Generate sample testbed
    testbed_gen = RandomizedTestbed(seed=12345)
    testbed = testbed_gen.generate_testbed(
        num_batches=5,  # Smaller for demo
        min_jobs_per_batch=2,
        max_jobs_per_batch=4,
        function_ids=[18, 19, 20, 21]
    )
    
    print("Testbed generated successfully")
    
    # Create min-cost pre-computer
    precomputer = MinCostPrecomputer()
    
    # Define providers and costs
    provider_ids = ["provider_A", "provider_B", "provider_C"]
    provider_costs = {"provider_A": 1.0, "provider_B": 0.8, "provider_C": 1.2}
    provider_delays = {"provider_A": 0.1, "provider_B": 0.15, "provider_C": 0.05}
    
    # Compute optimal schedule
    result = precomputer.precompute_optimal_schedule(
        testbed=testbed,
        provider_ids=provider_ids,
        provider_costs=provider_costs,
        provider_delays=provider_delays
    )
    
    # Save results
    filename = precomputer.save_optimal_schedule(result)
    
    # Create assignment mapping
    assignment_map = precomputer.create_assignment_mapping(result)
    print(f"Assignment mapping created with {len(assignment_map)} entries")


if __name__ == "__main__":
    main() 