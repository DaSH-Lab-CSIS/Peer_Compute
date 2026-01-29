"""
Visualizer - Creates charts and visualizations from metrics.
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np


class MetricsVisualizer:
    """Creates visualizations from test metrics."""
    
    def __init__(self, results_dir: str = "testbed/results"):
        """
        Initialize the visualizer.
        
        Args:
            results_dir: Directory containing results
        """
        self.results_dir = Path(results_dir)
    
    def load_run_metrics(self, run_id: str) -> Dict[str, Any]:
        """Load metrics for a run."""
        json_path = self.results_dir / "json" / f"{run_id}_metrics.json"
        with open(json_path, 'r') as f:
            return json.load(f)
    
    def plot_latency_over_time(
        self,
        run_id: str,
        output_path: Optional[str] = None,
        window_size: int = 100
    ):
        """
        Plot latency over time.
        
        Args:
            run_id: Run identifier
            output_path: Optional output file path
            window_size: Number of requests per data point
        """
        metrics = self.load_run_metrics(run_id)
        request_details = metrics.get('request_details', [])
        
        # Extract latency data
        latencies = []
        times = []
        for req in request_details:
            if req.get('latency') and req.get('enqueue_time'):
                latencies.append(req.get('latency'))
                times.append(req.get('enqueue_time'))
        
        if not latencies:
            return
        
        # Create time windows for smoothing
        if len(latencies) > window_size:
            windowed_latencies = []
            windowed_times = []
            
            for i in range(0, len(latencies), window_size):
                window = latencies[i:i+window_size]
                window_time = times[i]
                windowed_latencies.append(np.mean(window))
                windowed_times.append(window_time)
            
            latencies = windowed_latencies
            times = windowed_times
        
        # Plot
        plt.figure(figsize=(12, 6))
        plt.plot(times, latencies, alpha=0.7, linewidth=1)
        plt.xlabel('Time (seconds since start)')
        plt.ylabel('Latency (seconds)')
        plt.title(f'Latency Over Time - Run: {run_id}')
        plt.grid(True, alpha=0.3)
        
        if output_path is None:
            output_path = self.results_dir / "reports" / f"{run_id}_latency_over_time.png"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        return str(output_path)
    
    def plot_throughput_curve(
        self,
        run_id: str,
        output_path: Optional[str] = None,
        window_size: float = 60.0
    ):
        """
        Plot throughput curve.
        
        Args:
            run_id: Run identifier
            output_path: Optional output file path
            window_size: Time window size in seconds
        """
        metrics = self.load_run_metrics(run_id)
        request_details = metrics.get('request_details', [])
        
        if not request_details:
            return
        
        # Extract timing data
        enqueue_times = [r.get('enqueue_time') for r in request_details if r.get('enqueue_time')]
        if not enqueue_times:
            return
        
        min_time = min(enqueue_times)
        max_time = max(enqueue_times)
        
        # Calculate throughput in time windows
        window_starts = []
        throughputs = []
        
        current_time = min_time
        while current_time < max_time:
            window_end = current_time + window_size
            window_requests = [
                t for t in enqueue_times
                if current_time <= t < window_end
            ]
            
            throughput = len(window_requests) / window_size
            window_starts.append(current_time - min_time)
            throughputs.append(throughput)
            
            current_time = window_end
        
        # Plot
        plt.figure(figsize=(12, 6))
        plt.plot(window_starts, throughputs, linewidth=2)
        plt.xlabel('Time (seconds since start)')
        plt.ylabel('Throughput (RPS)')
        plt.title(f'Throughput Over Time - Run: {run_id}')
        plt.grid(True, alpha=0.3)
        
        if output_path is None:
            output_path = self.results_dir / "reports" / f"{run_id}_throughput.png"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        return str(output_path)
    
    def plot_error_rate_trend(
        self,
        run_id: str,
        output_path: Optional[str] = None,
        window_size: float = 60.0
    ):
        """
        Plot error rate trend over time.
        
        Args:
            run_id: Run identifier
            output_path: Optional output file path
            window_size: Time window size in seconds
        """
        metrics = self.load_run_metrics(run_id)
        request_details = metrics.get('request_details', [])
        
        if not request_details:
            return
        
        # Extract timing and success data
        request_data = [
            (r.get('enqueue_time'), r.get('success', False))
            for r in request_details
            if r.get('enqueue_time') is not None
        ]
        
        if not request_data:
            return
        
        enqueue_times, successes = zip(*request_data)
        min_time = min(enqueue_times)
        max_time = max(enqueue_times)
        
        # Calculate error rates in time windows
        window_starts = []
        error_rates = []
        
        current_time = min_time
        while current_time < max_time:
            window_end = current_time + window_size
            
            window_requests = [
                (t, s) for t, s in zip(enqueue_times, successes)
                if current_time <= t < window_end
            ]
            
            if window_requests:
                window_errors = sum(1 for _, s in window_requests if not s)
                error_rate = (window_errors / len(window_requests)) * 100
            else:
                error_rate = 0
            
            window_starts.append(current_time - min_time)
            error_rates.append(error_rate)
            
            current_time = window_end
        
        # Plot
        plt.figure(figsize=(12, 6))
        plt.plot(window_starts, error_rates, linewidth=2, color='red')
        plt.xlabel('Time (seconds since start)')
        plt.ylabel('Error Rate (%)')
        plt.title(f'Error Rate Trend - Run: {run_id}')
        plt.grid(True, alpha=0.3)
        plt.axhline(y=10, color='orange', linestyle='--', label='10% threshold')
        plt.legend()
        
        if output_path is None:
            output_path = self.results_dir / "reports" / f"{run_id}_error_rate.png"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        return str(output_path)
    
    def plot_service_distribution(
        self,
        run_id: str,
        output_path: Optional[str] = None
    ):
        """
        Plot service distribution heatmap.
        
        Args:
            run_id: Run identifier
            output_path: Optional output file path
        """
        metrics = self.load_run_metrics(run_id)
        service_metrics = metrics.get('aggregate_metrics', {}).get('service_metrics', {})
        
        if not service_metrics:
            return
        
        services = list(service_metrics.keys())
        counts = [service_metrics[s].get('total', 0) for s in services]
        
        # Plot bar chart
        plt.figure(figsize=(12, 6))
        plt.bar(services, counts, alpha=0.7)
        plt.xlabel('Service ID')
        plt.ylabel('Request Count')
        plt.title(f'Service Distribution - Run: {run_id}')
        plt.grid(True, alpha=0.3, axis='y')
        plt.xticks(rotation=45)
        
        if output_path is None:
            output_path = self.results_dir / "reports" / f"{run_id}_service_distribution.png"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        return str(output_path)
    
    def plot_batch_size_distribution(
        self,
        run_id: str,
        output_path: Optional[str] = None
    ):
        """
        Plot batch size distribution histogram.
        
        Args:
            run_id: Run identifier
            output_path: Optional output file path
        """
        metrics = self.load_run_metrics(run_id)
        ilp_batches = metrics.get('ilp_batches', [])
        
        if not ilp_batches:
            return
        
        batch_sizes = [b.get('batch_size') for b in ilp_batches if b.get('batch_size') is not None]
        
        if not batch_sizes:
            return
        
        # Plot histogram
        plt.figure(figsize=(12, 6))
        plt.hist(batch_sizes, bins=20, alpha=0.7, edgecolor='black')
        plt.xlabel('Batch Size (requests)')
        plt.ylabel('Frequency')
        plt.title(f'Batch Size Distribution - Run: {run_id}')
        plt.grid(True, alpha=0.3, axis='y')
        
        # Add statistics
        avg_size = np.mean(batch_sizes)
        median_size = np.median(batch_sizes)
        plt.axvline(avg_size, color='red', linestyle='--', label=f'Mean: {avg_size:.1f}')
        plt.axvline(median_size, color='green', linestyle='--', label=f'Median: {median_size:.1f}')
        plt.legend()
        
        if output_path is None:
            output_path = self.results_dir / "reports" / f"{run_id}_batch_size_distribution.png"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        return str(output_path)
    
    def plot_ilp_solve_time(
        self,
        run_id: str,
        output_path: Optional[str] = None
    ):
        """
        Plot ILP solve time over time.
        
        Args:
            run_id: Run identifier
            output_path: Optional output file path
        """
        metrics = self.load_run_metrics(run_id)
        ilp_batches = metrics.get('ilp_batches', [])
        
        if not ilp_batches:
            return
        
        # Extract solve times and formation times
        solve_times = []
        formation_times = []
        
        for batch in ilp_batches:
            solve_time = batch.get('ilp_solve_time')
            formation_time = batch.get('batch_formation_time')
            if solve_time is not None and formation_time is not None:
                solve_times.append(solve_time)
                formation_times.append(formation_time)
        
        if not solve_times:
            return
        
        # Normalize times to start from 0
        min_time = min(formation_times)
        normalized_times = [t - min_time for t in formation_times]
        
        # Plot
        plt.figure(figsize=(12, 6))
        plt.plot(normalized_times, solve_times, marker='o', alpha=0.7, markersize=4)
        plt.xlabel('Time (seconds since start)')
        plt.ylabel('ILP Solve Time (seconds)')
        plt.title(f'ILP Solve Time Over Time - Run: {run_id}')
        plt.grid(True, alpha=0.3)
        
        if output_path is None:
            output_path = self.results_dir / "reports" / f"{run_id}_ilp_solve_time.png"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        return str(output_path)
    
    def plot_queue_depth(
        self,
        run_id: str,
        output_path: Optional[str] = None
    ):
        """
        Plot queue depth over time.
        
        Args:
            run_id: Run identifier
            output_path: Optional output file path
        """
        metrics = self.load_run_metrics(run_id)
        ilp_batches = metrics.get('ilp_batches', [])
        
        if not ilp_batches:
            return
        
        # Extract queue depths and formation times
        queue_depths = []
        formation_times = []
        
        for batch in ilp_batches:
            queue_depth = batch.get('queue_depth_at_batch')
            formation_time = batch.get('batch_formation_time')
            if queue_depth is not None and formation_time is not None:
                queue_depths.append(queue_depth)
                formation_times.append(formation_time)
        
        if not queue_depths:
            return
        
        # Normalize times to start from 0
        min_time = min(formation_times)
        normalized_times = [t - min_time for t in formation_times]
        
        # Plot
        plt.figure(figsize=(12, 6))
        plt.plot(normalized_times, queue_depths, marker='o', alpha=0.7, markersize=4, color='orange')
        plt.xlabel('Time (seconds since start)')
        plt.ylabel('Queue Depth (requests)')
        plt.title(f'Queue Depth Over Time - Run: {run_id}')
        plt.grid(True, alpha=0.3)
        
        if output_path is None:
            output_path = self.results_dir / "reports" / f"{run_id}_queue_depth.png"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        return str(output_path)
    
    def plot_batch_formation_rate(
        self,
        run_id: str,
        output_path: Optional[str] = None,
        window_size: float = 60.0
    ):
        """
        Plot batch formation rate over time.
        
        Args:
            run_id: Run identifier
            output_path: Optional output file path
            window_size: Time window size in seconds
        """
        metrics = self.load_run_metrics(run_id)
        ilp_batches = metrics.get('ilp_batches', [])
        
        if not ilp_batches:
            return
        
        # Extract formation times
        formation_times = [b.get('batch_formation_time') for b in ilp_batches if b.get('batch_formation_time') is not None]
        
        if not formation_times or len(formation_times) < 2:
            return
        
        min_time = min(formation_times)
        max_time = max(formation_times)
        
        # Calculate batch formation rate in time windows
        window_starts = []
        formation_rates = []
        
        current_time = min_time
        while current_time < max_time:
            window_end = current_time + window_size
            window_batches = [
                t for t in formation_times
                if current_time <= t < window_end
            ]
            
            rate = len(window_batches) / window_size
            window_starts.append(current_time - min_time)
            formation_rates.append(rate)
            
            current_time = window_end
        
        # Plot
        plt.figure(figsize=(12, 6))
        plt.plot(window_starts, formation_rates, linewidth=2, color='purple')
        plt.xlabel('Time (seconds since start)')
        plt.ylabel('Batch Formation Rate (batches/second)')
        plt.title(f'Batch Formation Rate Over Time - Run: {run_id}')
        plt.grid(True, alpha=0.3)
        
        if output_path is None:
            output_path = self.results_dir / "reports" / f"{run_id}_batch_formation_rate.png"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        return str(output_path)
    
    def create_all_visualizations(self, run_id: str):
        """Create all visualizations for a run."""
        results = []
        
        try:
            results.append(self.plot_latency_over_time(run_id))
        except Exception as e:
            print(f"Error creating latency plot: {e}")
        
        try:
            results.append(self.plot_throughput_curve(run_id))
        except Exception as e:
            print(f"Error creating throughput plot: {e}")
        
        try:
            results.append(self.plot_error_rate_trend(run_id))
        except Exception as e:
            print(f"Error creating error rate plot: {e}")
        
        try:
            results.append(self.plot_service_distribution(run_id))
        except Exception as e:
            print(f"Error creating service distribution plot: {e}")
        
        # ILP visualizations
        try:
            results.append(self.plot_batch_size_distribution(run_id))
        except Exception as e:
            print(f"Error creating batch size distribution plot: {e}")
        
        try:
            results.append(self.plot_ilp_solve_time(run_id))
        except Exception as e:
            print(f"Error creating ILP solve time plot: {e}")
        
        try:
            results.append(self.plot_queue_depth(run_id))
        except Exception as e:
            print(f"Error creating queue depth plot: {e}")
        
        try:
            results.append(self.plot_batch_formation_rate(run_id))
        except Exception as e:
            print(f"Error creating batch formation rate plot: {e}")
        
        return results



