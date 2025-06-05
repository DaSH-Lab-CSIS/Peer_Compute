"""
Alternative Scheduling Algorithms for P2P Serverless Scheduler

This module implements different scheduling algorithms for comparison:
1. ILP (Integer Linear Programming) - Current implementation
2. MRU (Most Recently Used) - Schedule to providers used most recently
3. Belady's Algorithm - Optimal cache-aware scheduling (requires future knowledge)
4. Round Robin - Simple round-robin assignment
"""

import json
import time
import random
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from django.conf import settings
from django.db import transaction
from profiles.models import User
from providers.models import Job
from developers.models import Services


class SchedulingAlgorithm:
    """Base class for all scheduling algorithms"""
    
    def __init__(self):
        self.name = "Base"
        self.metrics = {
            'assignment_time': 0,
            'total_cost': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'assignments_made': 0
        }
    
    def assign_providers(self, providers: List[User], services: List[Services], 
                        cost_matrix: Dict, delay_dict: Dict) -> Tuple[Dict, float]:
        """
        Assign providers to services
        
        Args:
            providers: List of available providers
            services: List of services to be scheduled
            cost_matrix: Cost matrix {provider: {service: cost}}
            delay_dict: Provider delays {provider: delay}
            
        Returns:
            Tuple of (assignment_dict, total_cost)
        """
        raise NotImplementedError("Subclasses must implement assign_providers")
    
    def update_metrics(self, assignment: Dict, cost_matrix: Dict, delay_dict: Dict):
        """Update algorithm metrics"""
        self.metrics['assignments_made'] += len(assignment)
        
        # Calculate total cost
        total_cost = 0
        used_providers = set()
        
        for service_key, provider in assignment.items():
            if isinstance(service_key, tuple):
                _, service = service_key
            else:
                service = service_key
                
            total_cost += cost_matrix[provider][service_key]
            used_providers.add(provider)
        
        # Add delay costs for used providers
        for provider in used_providers:
            total_cost += delay_dict.get(provider, 0)
            
        self.metrics['total_cost'] += total_cost
    
    def get_metrics(self) -> Dict:
        """Get algorithm performance metrics"""
        return self.metrics.copy()
    
    def reset_metrics(self):
        """Reset metrics for new experiment"""
        self.metrics = {
            'assignment_time': 0,
            'total_cost': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'assignments_made': 0
        }


class ILPScheduler(SchedulingAlgorithm):
    """Integer Linear Programming scheduler (existing implementation)"""
    
    def __init__(self):
        super().__init__()
        self.name = "ILP"
    
    def assign_providers(self, providers: List[User], services: List[Services], 
                        cost_matrix: Dict, delay_dict: Dict) -> Tuple[Dict, float]:
        start_time = time.time()
        
        # Import here to avoid circular imports
        from providers.mincost import minimize_total_cost
        
        # Convert services to indexed format for ILP
        indexed_services = [(i, svc) for i, svc in enumerate(services)]
        
        assignment, total_cost = minimize_total_cost(providers, indexed_services, cost_matrix, delay_dict)
        
        self.metrics['assignment_time'] += time.time() - start_time
        if assignment:
            self.update_metrics(assignment, cost_matrix, delay_dict)
        
        return assignment, total_cost or 0


class MRUScheduler(SchedulingAlgorithm):
    """Most Recently Used scheduler"""
    
    def __init__(self):
        super().__init__()
        self.name = "MRU"
        self.recent_assignments = deque(maxlen=settings.MRU_HISTORY_SIZE)
        self.provider_usage_count = defaultdict(int)
    
    def assign_providers(self, providers: List[User], services: List[Services], 
                        cost_matrix: Dict, delay_dict: Dict) -> Tuple[Dict, float]:
        start_time = time.time()
        
        if not providers or not services:
            return {}, 0
        
        assignment = {}
        total_cost = 0
        used_providers = set()
        
        # Sort providers by recent usage (most recent first)
        sorted_providers = self._sort_providers_by_recent_usage(providers)
        
        for i, service in enumerate(services):
            service_key = (i, service)
            
            # Find the most recently used provider that can handle this service
            selected_provider = None
            min_cost = float('inf')
            
            for provider in sorted_providers:
                if service_key in cost_matrix.get(provider, {}):
                    cost = cost_matrix[provider][service_key]
                    
                    # Prefer recently used providers (bias towards MRU)
                    usage_bonus = self.provider_usage_count.get(provider.id, 0) * 0.1
                    adjusted_cost = cost - usage_bonus
                    
                    if adjusted_cost < min_cost:
                        min_cost = cost  # Use original cost for actual calculation
                        selected_provider = provider
            
            if selected_provider:
                assignment[service_key] = selected_provider
                total_cost += min_cost
                used_providers.add(selected_provider)
                
                # Update usage tracking
                self.recent_assignments.append((selected_provider.id, service.id, datetime.now()))
                self.provider_usage_count[selected_provider.id] += 1
        
        # Add delay costs
        for provider in used_providers:
            total_cost += delay_dict.get(provider, 0)
        
        self.metrics['assignment_time'] += time.time() - start_time
        self.update_metrics(assignment, cost_matrix, delay_dict)
        
        return assignment, total_cost
    
    def _sort_providers_by_recent_usage(self, providers: List[User]) -> List[User]:
        """Sort providers by recent usage (most recent first)"""
        provider_scores = {}
        current_time = datetime.now()
        
        for provider in providers:
            score = 0
            # Calculate recency score based on recent assignments
            for provider_id, service_id, timestamp in self.recent_assignments:
                if provider_id == provider.id:
                    time_diff = (current_time - timestamp).total_seconds()
                    # Recent assignments get higher scores (exponential decay)
                    score += max(0, 100 * (0.95 ** (time_diff / 60)))  # Decay per minute
            
            provider_scores[provider] = score
        
        return sorted(providers, key=lambda p: provider_scores.get(p, 0), reverse=True)


class BeladyScheduler(SchedulingAlgorithm):
    """Belady's optimal algorithm for scheduling (requires future knowledge)"""
    
    def __init__(self):
        super().__init__()
        self.name = "BELADY"
        self.future_requests = deque()  # For simulation purposes
    
    def assign_providers(self, providers: List[User], services: List[Services], 
                        cost_matrix: Dict, delay_dict: Dict) -> Tuple[Dict, float]:
        start_time = time.time()
        
        if not providers or not services:
            return {}, 0
        
        assignment = {}
        total_cost = 0
        used_providers = set()
        
        # For each service, choose the provider that will minimize future cache misses
        for i, service in enumerate(services):
            service_key = (i, service)
            
            selected_provider = None
            best_score = float('-inf')
            min_cost = float('inf')
            
            for provider in providers:
                if service_key not in cost_matrix.get(provider, {}):
                    continue
                
                cost = cost_matrix[provider][service_key]
                
                # Calculate Belady's score: prefer providers that will use this service again soon
                belady_score = self._calculate_belady_score(provider, service)
                
                # Cache hit bonus
                cache_bonus = 0
                if provider.is_service_cached(service.id):
                    cache_bonus = 50  # Significant bonus for cache hits
                    self.metrics['cache_hits'] += 1
                else:
                    self.metrics['cache_misses'] += 1
                
                # Combined score: prioritize cache hits and future reuse
                combined_score = belady_score + cache_bonus - (cost / 1000)  # Normalize cost
                
                if combined_score > best_score or (combined_score == best_score and cost < min_cost):
                    best_score = combined_score
                    min_cost = cost
                    selected_provider = provider
            
            if selected_provider:
                assignment[service_key] = selected_provider
                total_cost += min_cost
                used_providers.add(selected_provider)
        
        # Add delay costs
        for provider in used_providers:
            total_cost += delay_dict.get(provider, 0)
        
        self.metrics['assignment_time'] += time.time() - start_time
        self.update_metrics(assignment, cost_matrix, delay_dict)
        
        return assignment, total_cost
    
    def _calculate_belady_score(self, provider: User, service: Services) -> float:
        """Calculate Belady's score based on future service usage"""
        # In a real implementation, this would look at future requests
        # For simulation, we can use heuristics or synthetic future data
        
        # Heuristic: services used recently are likely to be used again
        recent_jobs = Job.objects.filter(
            provider=provider,
            service=service,
            start_time__gte=datetime.now() - timedelta(hours=1)
        ).count()
        
        # Services with higher frequency get higher scores
        frequency_score = min(recent_jobs * 10, 100)
        
        # Random component to simulate unknown future (in real scenario, this would be actual future knowledge)
        future_score = random.uniform(0, 20)
        
        return frequency_score + future_score
    
    def add_future_request(self, service_id: int, provider_id: str, timestamp: datetime):
        """Add future request information (for simulation)"""
        self.future_requests.append((service_id, provider_id, timestamp))


class RoundRobinScheduler(SchedulingAlgorithm):
    """Simple Round Robin scheduler"""
    
    def __init__(self):
        super().__init__()
        self.name = "ROUND_ROBIN"
        self.current_index = 0
        self.load_state()
    
    def assign_providers(self, providers: List[User], services: List[Services], 
                        cost_matrix: Dict, delay_dict: Dict) -> Tuple[Dict, float]:
        start_time = time.time()
        
        if not providers or not services:
            return {}, 0
        
        assignment = {}
        total_cost = 0
        used_providers = set()
        
        # Sort providers for consistent ordering
        sorted_providers = sorted(providers, key=lambda p: str(p.user_id))
        
        for i, service in enumerate(services):
            service_key = (i, service)
            
            # Find next available provider in round-robin fashion
            attempts = 0
            selected_provider = None
            
            while attempts < len(sorted_providers):
                provider = sorted_providers[self.current_index % len(sorted_providers)]
                
                # Check if provider can handle this service
                if service_key in cost_matrix.get(provider, {}):
                    selected_provider = provider
                    cost = cost_matrix[provider][service_key]
                    break
                
                self.current_index = (self.current_index + 1) % len(sorted_providers)
                attempts += 1
            
            if selected_provider:
                assignment[service_key] = selected_provider
                total_cost += cost
                used_providers.add(selected_provider)
                
                # Move to next provider for next assignment
                self.current_index = (self.current_index + 1) % len(sorted_providers)
        
        # Add delay costs
        for provider in used_providers:
            total_cost += delay_dict.get(provider, 0)
        
        self.save_state()
        
        self.metrics['assignment_time'] += time.time() - start_time
        self.update_metrics(assignment, cost_matrix, delay_dict)
        
        return assignment, total_cost
    
    def load_state(self):
        """Load round robin state from file"""
        try:
            with open(settings.ROUND_ROBIN_STATE_FILE, 'r') as f:
                data = json.load(f)
                self.current_index = data.get('current_index', 0)
        except (FileNotFoundError, json.JSONDecodeError):
            self.current_index = 0
    
    def save_state(self):
        """Save round robin state to file"""
        try:
            with open(settings.ROUND_ROBIN_STATE_FILE, 'w') as f:
                json.dump({'current_index': self.current_index}, f)
        except Exception as e:
            print(f"Failed to save round robin state: {e}")


# Factory function to get the appropriate scheduler
def get_scheduler(algorithm_name: str = None) -> SchedulingAlgorithm:
    """
    Factory function to get the appropriate scheduling algorithm
    
    Args:
        algorithm_name: Name of the algorithm ('ILP', 'MRU', 'BELADY', 'ROUND_ROBIN')
                       If None, uses settings.SCHEDULING_ALGORITHM
    
    Returns:
        SchedulingAlgorithm instance
    """
    if algorithm_name is None:
        algorithm_name = settings.SCHEDULING_ALGORITHM
    
    schedulers = {
        'ILP': ILPScheduler,
        'MRU': MRUScheduler,
        'BELADY': BeladyScheduler,
        'ROUND_ROBIN': RoundRobinScheduler
    }
    
    if algorithm_name not in schedulers:
        raise ValueError(f"Unknown scheduling algorithm: {algorithm_name}")
    
    return schedulers[algorithm_name]() 