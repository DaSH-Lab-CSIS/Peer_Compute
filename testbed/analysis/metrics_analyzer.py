"""
Metrics Analyzer - Analyzes collected metrics and identifies anomalies.
"""
import json
import csv
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict
import statistics


class MetricsAnalyzer:
    """Analyzes metrics from test runs to identify vulnerabilities and anomalies."""
    
    def __init__(self, results_dir: str = "testbed/results"):
        """
        Initialize the metrics analyzer.
        
        Args:
            results_dir: Directory containing results
        """
        self.results_dir = Path(results_dir)
    
    def load_run_metrics(self, run_id: str) -> Dict[str, Any]:
        """
        Load metrics for a specific run.
        
        Args:
            run_id: Run identifier
            
        Returns:
            Dictionary containing run metrics
        """
        json_path = self.results_dir / "json" / f"{run_id}_metrics.json"
        
        if not json_path.exists():
            raise FileNotFoundError(f"Metrics file not found: {json_path}")
        
        with open(json_path, 'r') as f:
            return json.load(f)
    
    def analyze_latency(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze latency patterns and identify anomalies.
        
        Args:
            metrics: Metrics dictionary
            
        Returns:
            Analysis results
        """
        request_details = metrics.get('request_details', [])
        latency_metrics = metrics.get('aggregate_metrics', {}).get('latency_metrics', {})
        
        latencies = [r.get('latency') for r in request_details if r.get('latency') is not None]
        
        if not latencies:
            return {'error': 'No latency data available'}
        
        # Identify latency spikes (>2x median)
        median_latency = statistics.median(latencies)
        spike_threshold = median_latency * 2.0
        
        spikes = [l for l in latencies if l > spike_threshold]
        
        # Analyze latency distribution over time
        latencies_by_time = []
        for req in request_details:
            if req.get('latency') and req.get('enqueue_time'):
                latencies_by_time.append({
                    'time': req.get('enqueue_time'),
                    'latency': req.get('latency')
                })
        
        latencies_by_time.sort(key=lambda x: x['time'])
        
        # Calculate latency trends (first half vs second half)
        mid_point = len(latencies_by_time) // 2
        first_half = [l['latency'] for l in latencies_by_time[:mid_point]]
        second_half = [l['latency'] for l in latencies_by_time[mid_point:]]
        
        first_half_avg = statistics.mean(first_half) if first_half else 0
        second_half_avg = statistics.mean(second_half) if second_half else 0
        
        degradation = 0.0
        if first_half_avg > 0:
            degradation = ((second_half_avg - first_half_avg) / first_half_avg) * 100
        
        return {
            'total_requests': len(latencies),
            'median_latency': median_latency,
            'spike_threshold': spike_threshold,
            'spike_count': len(spikes),
            'spike_percentage': (len(spikes) / len(latencies)) * 100 if latencies else 0,
            'first_half_avg': first_half_avg,
            'second_half_avg': second_half_avg,
            'degradation_percentage': degradation,
            'has_degradation': degradation > 20.0  # >20% increase
        }
    
    def analyze_throughput(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze throughput patterns.
        
        Args:
            metrics: Metrics dictionary
            
        Returns:
            Analysis results
        """
        aggregate = metrics.get('aggregate_metrics', {})
        duration = aggregate.get('duration', 0)
        total_requests = aggregate.get('total_requests', 0)
        throughput = aggregate.get('throughput_rps', 0)
        
        if duration == 0:
            return {'error': 'No duration data available'}
        
        # Analyze throughput over time windows
        request_details = metrics.get('request_details', [])
        
        # Divide into time windows
        if not request_details:
            return {'error': 'No request details available'}
        
        enqueue_times = [r.get('enqueue_time') for r in request_details if r.get('enqueue_time')]
        if not enqueue_times:
            return {'error': 'No timing data available'}
        
        min_time = min(enqueue_times)
        max_time = max(enqueue_times)
        actual_duration = max_time - min_time
        
        # Divide into 10 windows
        window_count = 10
        window_size = actual_duration / window_count
        
        window_throughputs = []
        for i in range(window_count):
            window_start = min_time + (i * window_size)
            window_end = window_start + window_size
            
            window_requests = [
                r for r in request_details
                if r.get('enqueue_time') and window_start <= r.get('enqueue_time') < window_end
            ]
            
            window_rps = len(window_requests) / window_size if window_size > 0 else 0
            window_throughputs.append(window_rps)
        
        # Calculate throughput stability
        if window_throughputs:
            avg_throughput = statistics.mean(window_throughputs)
            std_throughput = statistics.stdev(window_throughputs) if len(window_throughputs) > 1 else 0
            cv = (std_throughput / avg_throughput) * 100 if avg_throughput > 0 else 0
        else:
            avg_throughput = throughput
            std_throughput = 0
            cv = 0
        
        return {
            'overall_throughput': throughput,
            'duration': duration,
            'total_requests': total_requests,
            'window_throughputs': window_throughputs,
            'avg_window_throughput': avg_throughput,
            'throughput_std': std_throughput,
            'coefficient_of_variation': cv,
            'is_stable': cv < 20.0  # <20% variation is considered stable
        }
    
    def analyze_error_patterns(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze error patterns and identify failure modes.
        
        Args:
            metrics: Metrics dictionary
            
        Returns:
            Analysis results
        """
        aggregate = metrics.get('aggregate_metrics', {})
        error_breakdown = aggregate.get('error_breakdown', {})
        total_requests = aggregate.get('total_requests', 0)
        failed_requests = aggregate.get('failed_requests', 0)
        error_rate = aggregate.get('error_rate', 0)
        
        # Analyze error types
        error_analysis = {}
        for error_type, count in error_breakdown.items():
            error_analysis[error_type] = {
                'count': count,
                'percentage': (count / total_requests) * 100 if total_requests > 0 else 0
            }
        
        # Check for cascading failures (increasing error rate over time)
        request_details = metrics.get('request_details', [])
        
        if request_details:
            # Divide into time windows
            enqueue_times = [r.get('enqueue_time') for r in request_details if r.get('enqueue_time')]
            if enqueue_times:
                min_time = min(enqueue_times)
                max_time = max(enqueue_times)
                duration = max_time - min_time
                
                window_count = 10
                window_size = duration / window_count
                
                error_rates_by_window = []
                for i in range(window_count):
                    window_start = min_time + (i * window_size)
                    window_end = window_start + window_size
                    
                    window_requests = [
                        r for r in request_details
                        if r.get('enqueue_time') and window_start <= r.get('enqueue_time') < window_end
                    ]
                    
                    window_failed = sum(1 for r in window_requests if not r.get('success', False))
                    window_error_rate = (window_failed / len(window_requests)) * 100 if window_requests else 0
                    error_rates_by_window.append(window_error_rate)
                
                # Check for increasing trend
                if len(error_rates_by_window) >= 2:
                    first_half = error_rates_by_window[:len(error_rates_by_window)//2]
                    second_half = error_rates_by_window[len(error_rates_by_window)//2:]
                    
                    first_avg = statistics.mean(first_half) if first_half else 0
                    second_avg = statistics.mean(second_half) if second_half else 0
                    
                    cascading = second_avg > first_avg * 1.5  # 50% increase
                else:
                    cascading = False
            else:
                error_rates_by_window = []
                cascading = False
        else:
            error_rates_by_window = []
            cascading = False
        
        return {
            'total_errors': failed_requests,
            'error_rate': error_rate,
            'error_breakdown': error_analysis,
            'error_rates_by_window': error_rates_by_window,
            'has_cascading_failures': cascading
        }
    
    def analyze_service_distribution(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze service distribution for fairness.
        
        Args:
            metrics: Metrics dictionary
            
        Returns:
            Analysis results
        """
        service_metrics = metrics.get('aggregate_metrics', {}).get('service_metrics', {})
        request_details = metrics.get('request_details', [])
        
        # Count requests per service
        service_counts = defaultdict(int)
        for req in request_details:
            service_id = req.get('service_id')
            if service_id:
                service_counts[service_id] += 1
        
        if not service_counts:
            return {'error': 'No service distribution data available'}
        
        counts = list(service_counts.values())
        avg_count = statistics.mean(counts)
        std_count = statistics.stdev(counts) if len(counts) > 1 else 0
        
        # Calculate fairness (coefficient of variation)
        cv = (std_count / avg_count) * 100 if avg_count > 0 else 0
        
        # Identify services with significantly different request counts
        unfair_threshold = avg_count * 1.5  # 50% more than average
        unfair_services = {
            sid: count for sid, count in service_counts.items()
            if count > unfair_threshold
        }
        
        return {
            'service_counts': dict(service_counts),
            'avg_requests_per_service': avg_count,
            'std_requests_per_service': std_count,
            'fairness_cv': cv,
            'is_fair': cv < 30.0,  # <30% variation is considered fair
            'unfair_services': unfair_services
        }
    
    def analyze_ilp_metrics(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze ILP-specific metrics and identify anomalies.
        
        Args:
            metrics: Metrics dictionary
            
        Returns:
            ILP analysis results
        """
        ilp_metrics = metrics.get('aggregate_metrics', {}).get('ilp_metrics', {})
        ilp_batches = metrics.get('ilp_batches', [])
        
        if not ilp_batches and not ilp_metrics:
            return {'error': 'No ILP metrics available'}
        
        analysis = {
            'total_batches': ilp_metrics.get('total_batches', 0)
        }
        
        # Analyze batch size stability
        batch_size_metrics = ilp_metrics.get('batch_size', {})
        if batch_size_metrics:
            batch_sizes = [b.get('batch_size', 0) for b in ilp_batches if b.get('batch_size') is not None]
            if batch_sizes:
                avg_batch_size = batch_size_metrics.get('avg', 0)
                std_batch_size = batch_size_metrics.get('std', 0)
                cv_batch_size = (std_batch_size / avg_batch_size) * 100 if avg_batch_size > 0 else 0
                
                analysis['batch_size'] = {
                    'avg': avg_batch_size,
                    'std': std_batch_size,
                    'cv': cv_batch_size,
                    'is_stable': cv_batch_size < 30.0  # <30% variation is stable
                }
        
        # Analyze ILP solve time trends
        ilp_solve_time_metrics = ilp_metrics.get('ilp_solve_time', {})
        if ilp_solve_time_metrics and ilp_batches:
            solve_times = [b.get('ilp_solve_time') for b in ilp_batches if b.get('ilp_solve_time') is not None]
            if solve_times and len(solve_times) > 1:
                # Check for degradation over time
                mid_point = len(solve_times) // 2
                first_half = solve_times[:mid_point]
                second_half = solve_times[mid_point:]
                
                first_avg = statistics.mean(first_half) if first_half else 0
                second_avg = statistics.mean(second_half) if second_half else 0
                
                degradation = 0.0
                if first_avg > 0:
                    degradation = ((second_avg - first_avg) / first_avg) * 100
                
                analysis['ilp_solve_time'] = {
                    'avg': ilp_solve_time_metrics.get('avg', 0),
                    'median': ilp_solve_time_metrics.get('median', 0),
                    'p95': ilp_solve_time_metrics.get('p95', 0),
                    'first_half_avg': first_avg,
                    'second_half_avg': second_avg,
                    'degradation_percentage': degradation,
                    'has_degradation': degradation > 20.0  # >20% increase
                }
        
        # Analyze queue depth spikes
        queue_depth_metrics = ilp_metrics.get('queue_depth', {})
        if queue_depth_metrics:
            queue_depths = [b.get('queue_depth_at_batch') for b in ilp_batches if b.get('queue_depth_at_batch') is not None]
            if queue_depths:
                avg_queue_depth = queue_depth_metrics.get('avg', 0)
                max_queue_depth = queue_depth_metrics.get('max', 0)
                spike_threshold = avg_queue_depth * 2.0
                
                spikes = [d for d in queue_depths if d > spike_threshold]
                
                analysis['queue_depth'] = {
                    'avg': avg_queue_depth,
                    'max': max_queue_depth,
                    'spike_count': len(spikes),
                    'spike_percentage': (len(spikes) / len(queue_depths)) * 100 if queue_depths else 0,
                    'has_spikes': len(spikes) > 0
                }
        
        # Analyze batch formation rate
        batch_formation_rate = ilp_metrics.get('batch_formation_rate')
        if batch_formation_rate:
            analysis['batch_formation_rate'] = batch_formation_rate
            
            # Check for delays (low formation rate might indicate delays)
            if batch_formation_rate < 0.1:  # Less than 0.1 batches per second
                analysis['has_formation_delays'] = True
            else:
                analysis['has_formation_delays'] = False
        
        return analysis
    
    def analyze_run(self, run_id: str) -> Dict[str, Any]:
        """
        Perform comprehensive analysis of a test run.
        
        Args:
            run_id: Run identifier
            
        Returns:
            Comprehensive analysis results
        """
        metrics = self.load_run_metrics(run_id)
        
        return {
            'run_id': run_id,
            'latency_analysis': self.analyze_latency(metrics),
            'throughput_analysis': self.analyze_throughput(metrics),
            'error_analysis': self.analyze_error_patterns(metrics),
            'service_distribution': self.analyze_service_distribution(metrics),
            'ilp_analysis': self.analyze_ilp_metrics(metrics),
            'aggregate_metrics': metrics.get('aggregate_metrics', {})
        }



