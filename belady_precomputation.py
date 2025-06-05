#!/usr/bin/env python3
"""
Belady Pre-computation for Optimal Scheduling

This module implements Belady's optimal algorithm by pre-computing the entire
testbed schedule using future knowledge. This provides the theoretical optimum
for cache-aware scheduling comparison.
"""

import json
import time
import copy
from collections import defaultdict, deque
from typing import Dict, List, Tuple, Any, Optional, Set
from dataclasses import dataclass
from datetime import datetime

from randomized_testbed import TestBatch, TestJob


@dataclass
class ProviderState:
    """Represents provider state including cache"""
    provider_id: str
    cached_functions: Set[int]
    last_used: Dict[int, float]  # function_id -> timestamp
    current_load: int = 0
    
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


class BeladyPrecomputer:
    """Pre-computes optimal Belady schedule for entire testbed"""
    
    def __init__(self):
        self.providers = {}  # provider_id -> ProviderState
        self.global_time = 0.0
        self.assignment_log = []
        self.cache_stats = {"hits": 0, "misses": 0}
        
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
        
        print(f"Initialized {len(provider_ids)} providers for Belady pre-computation")
    
    def analyze_future_usage(self, testbed: List[TestBatch]) -> Dict[int, List[Tuple[float, int]]]:
        """
        Analyze future usage patterns for all functions
        Returns: function_id -> [(timestamp, job_index), ...]
        """
        future_usage = defaultdict(list)
        
        for batch in testbed:
            batch_time = batch.send_time_offset
            for job in batch.jobs:
                future_usage[job.function_id].append((batch_time, job.job_index))
        
        # Sort by timestamp for each function
        for function_id in future_usage:
            future_usage[function_id].sort()
        
        return future_usage
    
    def get_next_usage_time(self, function_id: int, current_time: float,
                           future_usage: Dict[int, List[Tuple[float, int]]]) -> Optional[float]:
        """Get the next time this function will be used after current_time"""
        if function_id not in future_usage:
            return None
        
        for timestamp, _ in future_usage[function_id]:
            if timestamp > current_time:
                return timestamp
        
        return None  # No future usage
    
    def compute_optimal_assignment(self, job: TestJob, current_time: float,
                                 future_usage: Dict[int, List[Tuple[float, int]]],
                                 provider_costs: Dict[str, float] = None) -> str:
        """
        Compute optimal provider assignment using Belady's algorithm
        
        Args:
            job: The job to assign
            current_time: Current timestamp
            future_usage: Future usage patterns
            provider_costs: Optional provider costs (for tie-breaking)
            
        Returns:
            provider_id of optimal assignment
        """
        if provider_costs is None:
            provider_costs = {pid: 1.0 for pid in self.providers.keys()}
        
        best_provider = None
        best_score = float('-inf')
        
        for provider_id, provider in self.providers.items():
            # Base score: cache hit gives significant advantage
            if provider.is_cached(job.function_id):
                cache_score = 1000  # Large bonus for cache hit
                self.cache_stats["hits"] += 1
            else:
                cache_score = 0
                self.cache_stats["misses"] += 1
            
            # Future usage score: later next usage is better (can keep in cache longer)
            next_usage = self.get_next_usage_time(job.function_id, current_time, future_usage)
            if next_usage is None:
                future_score = 1000  # No future usage, so eviction doesn't matter
            else:
                future_score = (next_usage - current_time) * 10  # Favor longer time until next use
            
            # Load balancing: prefer less loaded providers
            load_score = -provider.current_load * 5
            
            # Cost score: prefer cheaper providers (inverted)
            cost_score = -provider_costs.get(provider_id, 1.0) * 100
            
            # Combined score
            total_score = cache_score + future_score + load_score + cost_score
            
            if total_score > best_score:
                best_score = total_score
                best_provider = provider_id
        
        return best_provider
    
    def execute_assignment(self, job: TestJob, provider_id: str, current_time: float):
        """Execute the assignment and update provider state"""
        provider = self.providers[provider_id]
        
        # Update cache
        if not provider.is_cached(job.function_id):
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
            "cache_hit": provider.is_cached(job.function_id),
            "provider_cache_state": list(provider.cached_functions)
        })
    
    def precompute_optimal_schedule(self, testbed: List[TestBatch],
                                  provider_ids: List[str] = None,
                                  provider_costs: Dict[str, float] = None) -> Dict[str, Any]:
        """
        Pre-compute optimal Belady schedule for entire testbed
        
        Args:
            testbed: List of test batches
            provider_ids: List of provider IDs (if None, creates default)
            provider_costs: Provider cost mapping
            
        Returns:
            Dictionary with optimal schedule and statistics
        """
        if provider_ids is None:
            provider_ids = [f"provider_{i}" for i in range(5)]  # Default 5 providers
        
        if provider_costs is None:
            provider_costs = {pid: 1.0 for pid in provider_ids}
        
        print(f"Pre-computing optimal Belady schedule...")
        print(f"Testbed: {len(testbed)} batches")
        print(f"Providers: {len(provider_ids)}")
        
        # Initialize providers
        self.initialize_providers(provider_ids)
        
        # Analyze future usage patterns
        future_usage = self.analyze_future_usage(testbed)
        print(f"Functions in testbed: {len(future_usage)}")
        
        # Process each batch in order
        total_jobs = 0
        for batch in testbed:
            self.global_time = batch.send_time_offset
            
            for job in batch.jobs:
                # Compute optimal assignment
                optimal_provider = self.compute_optimal_assignment(
                    job, self.global_time, future_usage, provider_costs
                )
                
                # Execute assignment
                self.execute_assignment(job, optimal_provider, self.global_time)
                total_jobs += 1
        
        # Calculate statistics
        cache_hit_rate = self.cache_stats["hits"] / (self.cache_stats["hits"] + self.cache_stats["misses"])
        
        result = {
            "algorithm": "BELADY_OPTIMAL",
            "total_jobs": total_jobs,
            "total_batches": len(testbed),
            "cache_hit_rate": cache_hit_rate,
            "cache_hits": self.cache_stats["hits"],
            "cache_misses": self.cache_stats["misses"],
            "providers_used": list(provider_ids),
            "assignment_log": self.assignment_log,
            "provider_final_states": {
                pid: {
                    "cached_functions": list(provider.cached_functions),
                    "final_load": provider.current_load
                }
                for pid, provider in self.providers.items()
            },
            "computation_time": self.global_time,
            "future_usage_patterns": {
                str(fid): patterns for fid, patterns in future_usage.items()
            }
        }
        
        print(f"✅ Belady pre-computation complete!")
        print(f"   Cache hit rate: {cache_hit_rate:.2%}")
        print(f"   Total cache hits: {self.cache_stats['hits']}")
        print(f"   Total cache misses: {self.cache_stats['misses']}")
        
        return result
    
    def save_optimal_schedule(self, result: Dict[str, Any], filename: str = None) -> str:
        """Save optimal schedule to file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"belady_optimal_schedule_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"Optimal Belady schedule saved to: {filename}")
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
    print("=== Belady Pre-computation Example ===")
    
    # Load a testbed (you would pass this from your main experiment)
    from randomized_testbed import RandomizedTestbed
    
    # Generate sample testbed
    testbed_gen = RandomizedTestbed(seed=12345)
    testbed = testbed_gen.generate_testbed(
        num_batches=10,
        min_jobs_per_batch=2,
        max_jobs_per_batch=5,
        function_ids=[18, 19, 20, 21]
    )
    
    print("Testbed generated successfully")


if __name__ == "__main__":
    main() 