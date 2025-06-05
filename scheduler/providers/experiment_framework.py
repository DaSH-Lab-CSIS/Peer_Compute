"""
Experiment Framework for Scheduling Algorithm Comparison

This module provides tools for conducting experiments to compare different
scheduling algorithms in terms of performance, cost, and efficiency.
"""

import csv
import json
import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from profiles.models import User
from providers.models import Job
from developers.models import Services
from providers.scheduling_algorithms import get_scheduler


class ExperimentMetrics:
    """Collects and manages metrics for scheduling algorithm experiments"""
    
    def __init__(self):
        self.algorithm_metrics = defaultdict(list)
        self.job_metrics = []
        self.system_metrics = []
        self.experiment_start_time = None
        self.lock = threading.Lock()
    
    def start_experiment(self, experiment_name: str, algorithms: List[str]):
        """Start a new experiment"""
        self.experiment_start_time = datetime.now()
        self.algorithm_metrics.clear()
        self.job_metrics.clear()
        self.system_metrics.clear()
        
        print(f"Starting experiment: {experiment_name}")
        print(f"Algorithms to test: {algorithms}")
        
        # Initialize CSV files
        self._initialize_csv_files()
    
    def _initialize_csv_files(self):
        """Initialize CSV files for experiment results"""
        # Algorithm metrics CSV
        with open(settings.ALGORITHM_METRICS_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'algorithm', 'assignment_time', 'total_cost',
                'cache_hits', 'cache_misses', 'assignments_made', 'services_count',
                'providers_count', 'average_cost_per_service'
            ])
        
        # Job metrics CSV
        with open(settings.EXPERIMENT_LOG_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'algorithm', 'job_id', 'service_id', 'provider_id',
                'assignment_time', 'pull_time', 'run_time', 'total_time',
                'cost', 'cache_hit', 'provider_delay'
            ])
    
    def record_assignment(self, algorithm: str, assignment: Dict, cost_matrix: Dict, 
                         delay_dict: Dict, assignment_time: float, services: List[Services]):
        """Record metrics for a scheduling assignment"""
        with self.lock:
            timestamp = datetime.now().isoformat()
            
            # Calculate metrics
            total_cost = 0
            cache_hits = 0
            cache_misses = 0
            used_providers = set()
            
            for service_key, provider in assignment.items():
                if isinstance(service_key, tuple):
                    _, service = service_key
                else:
                    service = service_key
                
                cost = cost_matrix[provider][service_key]
                total_cost += cost
                used_providers.add(provider)
                
                # Check cache hit
                if provider.is_service_cached(service.id):
                    cache_hits += 1
                else:
                    cache_misses += 1
            
            # Add delay costs
            for provider in used_providers:
                total_cost += delay_dict.get(provider, 0)
            
            # Record algorithm metrics
            avg_cost = total_cost / len(services) if services else 0
            algorithm_metrics = [
                timestamp, algorithm, assignment_time, total_cost,
                cache_hits, cache_misses, len(assignment), len(services),
                len(used_providers), avg_cost
            ]
            
            # Write to CSV
            with open(settings.ALGORITHM_METRICS_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(algorithm_metrics)
    
    def record_job_completion(self, algorithm: str, job: Job):
        """Record metrics when a job completes"""
        with self.lock:
            timestamp = datetime.now().isoformat()
            
            # Calculate assignment time (time from start to ack)
            assignment_time = 0
            if job.ack_time and job.start_time:
                assignment_time = (job.ack_time - job.start_time).total_seconds() * 1000
            
            # Check if it was a cache hit
            cache_hit = job.provider.is_service_cached(job.service.id) if job.service else False
            
            # Get provider delay
            provider_delay = 0
            if job.provider.delay and 'inflight_jobs' in job.provider.delay:
                provider_delay = sum(job.provider.delay['inflight_jobs'])
            
            job_metrics = [
                timestamp, algorithm, job.id, job.service.id if job.service else None,
                job.provider.user_id, assignment_time, job.pull_time, job.run_time,
                job.total_time, job.cost, cache_hit, provider_delay
            ]
            
            # Write to CSV
            with open(settings.EXPERIMENT_LOG_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(job_metrics)
    
    def generate_report(self, experiment_name: str) -> Dict[str, Any]:
        """Generate a comprehensive experiment report"""
        report = {
            'experiment_name': experiment_name,
            'start_time': self.experiment_start_time.isoformat() if self.experiment_start_time else None,
            'end_time': datetime.now().isoformat(),
            'algorithms': {}
        }
        
        # Read algorithm metrics
        algorithm_data = defaultdict(list)
        try:
            with open(settings.ALGORITHM_METRICS_FILE, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    algorithm_data[row['algorithm']].append(row)
        except FileNotFoundError:
            pass
        
        # Calculate summary statistics for each algorithm
        for algorithm, data in algorithm_data.items():
            if not data:
                continue
                
            costs = [float(row['total_cost']) for row in data]
            assignment_times = [float(row['assignment_time']) for row in data]
            cache_hits = sum(int(row['cache_hits']) for row in data)
            cache_misses = sum(int(row['cache_misses']) for row in data)
            total_assignments = sum(int(row['assignments_made']) for row in data)
            
            report['algorithms'][algorithm] = {
                'total_assignments': total_assignments,
                'total_cost': sum(costs),
                'average_cost': sum(costs) / len(costs) if costs else 0,
                'min_cost': min(costs) if costs else 0,
                'max_cost': max(costs) if costs else 0,
                'average_assignment_time': sum(assignment_times) / len(assignment_times) if assignment_times else 0,
                'cache_hit_rate': cache_hits / (cache_hits + cache_misses) if (cache_hits + cache_misses) > 0 else 0,
                'total_cache_hits': cache_hits,
                'total_cache_misses': cache_misses,
                'assignments_count': len(data)
            }
        
        return report
    
    def save_report(self, report: Dict[str, Any], filename: str = None):
        """Save experiment report to JSON file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"/home/user/Documents/Serverless_Scheduler_sn34kyp3t3/experiment_report_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"Experiment report saved to: {filename}")
        return filename


class ExperimentRunner:
    """Runs comparative experiments between different scheduling algorithms"""
    
    def __init__(self):
        self.metrics = ExperimentMetrics()
        self.current_algorithm = None
        self.experiment_active = False
    
    def run_algorithm_comparison(self, algorithms: List[str], num_iterations: int = 10, 
                                services_per_iteration: int = 5):
        """
        Run a comparative experiment between different algorithms
        
        Args:
            algorithms: List of algorithm names to compare
            num_iterations: Number of scheduling rounds per algorithm
            services_per_iteration: Number of services to schedule per iteration
        """
        experiment_name = f"Algorithm_Comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.metrics.start_experiment(experiment_name, algorithms)
        self.experiment_active = True
        
        print(f"\n=== Starting Algorithm Comparison Experiment ===")
        print(f"Algorithms: {algorithms}")
        print(f"Iterations per algorithm: {num_iterations}")
        print(f"Services per iteration: {services_per_iteration}")
        
        try:
            for algorithm in algorithms:
                print(f"\n--- Testing Algorithm: {algorithm} ---")
                self._test_algorithm(algorithm, num_iterations, services_per_iteration)
            
            # Generate and save report
            report = self.metrics.generate_report(experiment_name)
            report_file = self.metrics.save_report(report)
            
            print(f"\n=== Experiment Complete ===")
            print(f"Report saved to: {report_file}")
            
            # Print summary
            self._print_summary(report)
            
        finally:
            self.experiment_active = False
    
    def _test_algorithm(self, algorithm_name: str, num_iterations: int, services_per_iteration: int):
        """Test a specific algorithm"""
        scheduler = get_scheduler(algorithm_name)
        
        for iteration in range(num_iterations):
            print(f"  Iteration {iteration + 1}/{num_iterations}")
            
            # Get available providers and services
            providers = list(User.objects.filter(
                active=True, is_provider=True, ready=True
            )[:10])  # Limit to 10 providers for testing
            
            services = list(Services.objects.filter(active=True)[:services_per_iteration])
            
            if not providers or not services:
                print(f"    Skipping iteration - No providers ({len(providers)}) or services ({len(services)}) available")
                continue
            
            # Build cost matrix and delay dict (reuse existing functions)
            from providers.views import build_cost_matrix, build_delay_dict
            
            try:
                cost_matrix = build_cost_matrix(providers, services)
                delay_dict = build_delay_dict(providers)
                
                # Run the algorithm
                start_time = time.time()
                assignment, total_cost = scheduler.assign_providers(
                    providers, services, cost_matrix, delay_dict
                )
                assignment_time = time.time() - start_time
                
                if assignment:
                    # Record metrics
                    self.metrics.record_assignment(
                        algorithm_name, assignment, cost_matrix, 
                        delay_dict, assignment_time, services
                    )
                    
                    print(f"    Assignment completed - Cost: {total_cost:.2f}, Time: {assignment_time:.4f}s")
                else:
                    print(f"    Failed to create assignment")
                    
            except Exception as e:
                print(f"    Error in iteration: {str(e)}")
                continue
            
            # Small delay between iterations
            time.sleep(0.1)
    
    def _print_summary(self, report: Dict[str, Any]):
        """Print experiment summary"""
        print(f"\n=== EXPERIMENT SUMMARY ===")
        print(f"Experiment: {report['experiment_name']}")
        print(f"Duration: {report['start_time']} to {report['end_time']}")
        
        if not report['algorithms']:
            print("No algorithm data available")
            return
        
        print(f"\n{'Algorithm':<15} {'Avg Cost':<12} {'Avg Time':<12} {'Cache Hit Rate':<15} {'Assignments':<12}")
        print("-" * 80)
        
        for algo_name, metrics in report['algorithms'].items():
            cache_rate = f"{metrics['cache_hit_rate']:.2%}"
            print(f"{algo_name:<15} {metrics['average_cost']:<12.2f} {metrics['average_assignment_time']:<12.4f} {cache_rate:<15} {metrics['assignments_count']:<12}")
        
        # Find best performing algorithm
        best_cost = min(m['average_cost'] for m in report['algorithms'].values())
        best_time = min(m['average_assignment_time'] for m in report['algorithms'].values())
        best_cache = max(m['cache_hit_rate'] for m in report['algorithms'].values())
        
        print(f"\n=== BEST PERFORMERS ===")
        for algo_name, metrics in report['algorithms'].items():
            if metrics['average_cost'] == best_cost:
                print(f"Lowest Cost: {algo_name} ({best_cost:.2f})")
            if metrics['average_assignment_time'] == best_time:
                print(f"Fastest Assignment: {algo_name} ({best_time:.4f}s)")
            if metrics['cache_hit_rate'] == best_cache:
                print(f"Best Cache Hit Rate: {algo_name} ({best_cache:.2%})")


# Global experiment runner instance
experiment_runner = ExperimentRunner()


def start_experiment(algorithms: List[str] = None, iterations: int = 10, services_per_iteration: int = 5):
    """
    Start a scheduling algorithm comparison experiment
    
    Args:
        algorithms: List of algorithms to test. If None, tests all algorithms
        iterations: Number of iterations per algorithm
        services_per_iteration: Number of services per iteration
    """
    if algorithms is None:
        algorithms = ['ILP', 'MRU', 'BELADY', 'ROUND_ROBIN']
    
    # Run in a separate thread to avoid blocking
    import threading
    experiment_thread = threading.Thread(
        target=experiment_runner.run_algorithm_comparison,
        args=(algorithms, iterations, services_per_iteration)
    )
    experiment_thread.daemon = True
    experiment_thread.start()
    
    return "Experiment started in background"


def get_experiment_status():
    """Get current experiment status"""
    return {
        'active': experiment_runner.experiment_active,
        'current_algorithm': experiment_runner.current_algorithm,
        'start_time': experiment_runner.metrics.experiment_start_time.isoformat() 
                     if experiment_runner.metrics.experiment_start_time else None
    } 