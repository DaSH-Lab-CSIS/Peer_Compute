"""
Metrics Collector - Collects and aggregates metrics from test runs.
"""
import json
import csv
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict
import statistics
from uuid import uuid4
import time


class MetricsCollector:
    """Collects and aggregates metrics from test runs."""
    
    def __init__(self, run_id: str):
        """
        Initialize the metrics collector.
        
        Args:
            run_id: Unique identifier for this test run
        """
        self.run_id = run_id
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.requests: List[Dict[str, Any]] = []
        self.aggregate_metrics: Dict[str, Any] = {}
        self.ilp_batches: List[Dict[str, Any]] = []
    
    def start_collection(self):
        """Mark the start of metric collection."""
        self.start_time = datetime.now().timestamp()
    
    def stop_collection(self):
        """Mark the end of metric collection."""
        self.end_time = datetime.now().timestamp()
    
    def add_request(self, request_result: Dict[str, Any]):
        """
        Add a request result to the collection.
        
        Args:
            request_result: Dictionary containing request metrics
        """
        self.requests.append(request_result)
    
    def add_requests(self, request_results: List[Dict[str, Any]]):
        """
        Add multiple request results.
        
        Args:
            request_results: List of request result dictionaries
        """
        self.requests.extend(request_results)
    
    def add_ilp_batch(self, batch_metrics: Dict[str, Any]):
        """
        Add ILP batch metrics.
        
        Args:
            batch_metrics: Dictionary containing batch metrics with keys:
                - batch_id: str (optional, generated if not provided)
                - batch_size: int
                - queue_depth_at_batch: int (optional)
                - batch_formation_time: float
                - ilp_solve_time: Optional[float]
                - batch_processing_time: float
                - requests_in_batch: List[str] (request IDs)
        """
        if 'batch_id' not in batch_metrics:
            batch_metrics['batch_id'] = str(uuid4())
        
        self.ilp_batches.append(batch_metrics)
    
    def add_batch_from_metadata(self, batch_metadata: Dict[str, Any], request_id: str):
        """
        Add batch information from load balancer response metadata.
        Tracks which requests belong to which batches.
        
        Args:
            batch_metadata: Batch metadata from load balancer response
            request_id: Request ID that belongs to this batch
        """
        batch_id = batch_metadata.get('batch_id')
        if not batch_id:
            return
        
        # Find existing batch or create new one
        existing_batch = None
        for batch in self.ilp_batches:
            if batch.get('batch_id') == batch_id:
                existing_batch = batch
                break
        
        if existing_batch:
            # Add request to existing batch
            if 'requests_in_batch' not in existing_batch:
                existing_batch['requests_in_batch'] = []
            if request_id not in existing_batch['requests_in_batch']:
                existing_batch['requests_in_batch'].append(request_id)
        else:
            # Create new batch entry
            batch_info = {
                'batch_id': batch_id,
                'batch_size': batch_metadata.get('current_batch_size', 0),
                'queue_depth_at_batch': batch_metadata.get('estimated_queue_depth', 0),
                'batch_formation_time': time.time() - batch_metadata.get('batch_age_seconds', 0),
                'ilp_state': batch_metadata.get('ilp_state'),
                'requests_in_batch': [request_id]
            }
            self.ilp_batches.append(batch_info)
    
    def calculate_ilp_aggregates(self) -> Dict[str, Any]:
        """
        Calculate ILP-specific aggregate metrics.
        
        Returns:
            Dictionary of ILP aggregate metrics
        """
        if not self.ilp_batches:
            return {}
        
        batch_sizes = [b.get('batch_size', 0) for b in self.ilp_batches if b.get('batch_size') is not None]
        ilp_solve_times = [b.get('ilp_solve_time') for b in self.ilp_batches if b.get('ilp_solve_time') is not None]
        queue_depths = [b.get('queue_depth_at_batch') for b in self.ilp_batches if b.get('queue_depth_at_batch') is not None]
        batch_processing_times = [b.get('batch_processing_time') for b in self.ilp_batches if b.get('batch_processing_time') is not None]
        
        ilp_metrics = {
            'total_batches': len(self.ilp_batches),
        }
        
        if batch_sizes:
            ilp_metrics['batch_size'] = {
                'min': min(batch_sizes),
                'max': max(batch_sizes),
                'avg': statistics.mean(batch_sizes),
                'median': statistics.median(batch_sizes),
                'p95': self._percentile(batch_sizes, 0.95),
                'std': statistics.stdev(batch_sizes) if len(batch_sizes) > 1 else 0.0
            }
        
        if ilp_solve_times:
            ilp_metrics['ilp_solve_time'] = {
                'min': min(ilp_solve_times),
                'max': max(ilp_solve_times),
                'avg': statistics.mean(ilp_solve_times),
                'median': statistics.median(ilp_solve_times),
                'p95': self._percentile(ilp_solve_times, 0.95),
                'std': statistics.stdev(ilp_solve_times) if len(ilp_solve_times) > 1 else 0.0
            }
        
        if queue_depths:
            ilp_metrics['queue_depth'] = {
                'min': min(queue_depths),
                'max': max(queue_depths),
                'avg': statistics.mean(queue_depths),
                'median': statistics.median(queue_depths),
                'p95': self._percentile(queue_depths, 0.95)
            }
        
        if batch_processing_times:
            ilp_metrics['batch_processing_time'] = {
                'min': min(batch_processing_times),
                'max': max(batch_processing_times),
                'avg': statistics.mean(batch_processing_times),
                'median': statistics.median(batch_processing_times),
                'p95': self._percentile(batch_processing_times, 0.95)
            }
        
        # Calculate batch formation rate
        if self.start_time and self.end_time:
            duration = self.end_time - self.start_time
            if duration > 0:
                ilp_metrics['batch_formation_rate'] = len(self.ilp_batches) / duration
        elif self.ilp_batches:
            # Estimate from batch formation times
            formation_times = [b.get('batch_formation_time') for b in self.ilp_batches if b.get('batch_formation_time') is not None]
            if formation_times and len(formation_times) > 1:
                duration = max(formation_times) - min(formation_times)
                if duration > 0:
                    ilp_metrics['batch_formation_rate'] = len(self.ilp_batches) / duration
        
        return ilp_metrics
    
    def calculate_aggregates(self) -> Dict[str, Any]:
        """
        Calculate aggregate metrics from collected requests.
        
        Returns:
            Dictionary of aggregate metrics
        """
        if not self.requests:
            return {}
        
        total_requests = len(self.requests)
        successful = sum(1 for r in self.requests if r.get('success', False))
        failed = total_requests - successful
        
        # Latency metrics
        latencies = [r.get('latency') for r in self.requests if r.get('latency') is not None]
        
        latency_metrics = {}
        if latencies:
            latency_metrics = {
                'min_latency': min(latencies),
                'max_latency': max(latencies),
                'avg_latency': statistics.mean(latencies),
                'median_latency': statistics.median(latencies),
                'p50_latency': statistics.median(latencies),
                'p95_latency': self._percentile(latencies, 0.95),
                'p99_latency': self._percentile(latencies, 0.99),
                'std_latency': statistics.stdev(latencies) if len(latencies) > 1 else 0.0
            }
        
        # Throughput
        duration = None
        if self.start_time and self.end_time:
            duration = self.end_time - self.start_time
        elif latencies:
            # Estimate duration from request timestamps
            enqueue_times = [r.get('enqueue_time') for r in self.requests if r.get('enqueue_time')]
            if enqueue_times:
                duration = max(enqueue_times) - min(enqueue_times)
        
        throughput = None
        if duration and duration > 0:
            throughput = total_requests / duration
        
        # Error breakdown
        error_types = defaultdict(int)
        for r in self.requests:
            if not r.get('success', False):
                error = r.get('error', 'Unknown error')
                error_types[error] += 1
        
        # Service-specific metrics
        service_metrics = defaultdict(lambda: {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'latencies': []
        })
        
        for r in self.requests:
            service_id = r.get('service_id')
            if service_id:
                service_metrics[service_id]['total'] += 1
                if r.get('success', False):
                    service_metrics[service_id]['successful'] += 1
                else:
                    service_metrics[service_id]['failed'] += 1
                if r.get('latency'):
                    service_metrics[service_id]['latencies'].append(r.get('latency'))
        
        # Calculate service-specific averages
        for service_id, metrics in service_metrics.items():
            if metrics['latencies']:
                metrics['avg_latency'] = statistics.mean(metrics['latencies'])
                metrics['p95_latency'] = self._percentile(metrics['latencies'], 0.95)
            else:
                metrics['avg_latency'] = None
                metrics['p95_latency'] = None
            del metrics['latencies']  # Remove raw list from output
        
        # Calculate ILP aggregates
        ilp_metrics = self.calculate_ilp_aggregates()
        
        self.aggregate_metrics = {
            'run_id': self.run_id,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': duration,
            'total_requests': total_requests,
            'successful_requests': successful,
            'failed_requests': failed,
            'success_rate': successful / total_requests if total_requests > 0 else 0.0,
            'error_rate': failed / total_requests if total_requests > 0 else 0.0,
            'throughput_rps': throughput,
            'latency_metrics': latency_metrics,
            'error_breakdown': dict(error_types),
            'service_metrics': dict(service_metrics),
            'ilp_metrics': ilp_metrics
        }
        
        return self.aggregate_metrics
    
    def _percentile(self, data: List[float], percentile: float) -> float:
        """Calculate percentile value."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile)
        if index >= len(sorted_data):
            index = len(sorted_data) - 1
        return sorted_data[index]
    
    def export_json(self, output_dir: str):
        """
        Export metrics to JSON file.
        
        Args:
            output_dir: Directory to save JSON file
        """
        output_path = Path(output_dir) / "json" / f"{self.run_id}_metrics.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Calculate aggregates if not already done
        if not self.aggregate_metrics:
            self.calculate_aggregates()
        
        export_data = {
            'run_id': self.run_id,
            'aggregate_metrics': self.aggregate_metrics,
            'request_details': self.requests,
            'ilp_batches': self.ilp_batches
        }
        
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)
        
        return str(output_path)
    
    def export_csv(self, output_dir: str):
        """
        Export metrics to CSV file.
        
        Args:
            output_dir: Directory to save CSV file
        """
        output_path = Path(output_dir) / "csv" / f"{self.run_id}_metrics.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if not self.requests:
            return str(output_path)
        
        # CSV for request-level metrics
        fieldnames = [
            'request_id', 'job_id', 'service_id', 'enqueue_timestamp', 'enqueue_time',
            'success', 'status_code', 'latency', 'error'
        ]
        
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for req in self.requests:
                row = {
                    'request_id': req.get('request_id', ''),
                    'job_id': req.get('job_id', ''),
                    'service_id': req.get('service_id', ''),
                    'enqueue_timestamp': req.get('enqueue_timestamp', ''),
                    'enqueue_time': req.get('enqueue_time', ''),
                    'success': req.get('success', False),
                    'status_code': req.get('status_code', ''),
                    'latency': req.get('latency', ''),
                    'error': req.get('error', '')
                }
                writer.writerow(row)
        
        # Also export aggregate metrics as separate CSV
        agg_path = Path(output_dir) / "csv" / f"{self.run_id}_aggregates.csv"
        if self.aggregate_metrics:
            with open(agg_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['metric', 'value'])
                writer.writeheader()
                
                for key, value in self.aggregate_metrics.items():
                    if isinstance(value, dict):
                        for sub_key, sub_value in value.items():
                            writer.writerow({
                                'metric': f"{key}.{sub_key}",
                                'value': sub_value
                            })
                    else:
                        writer.writerow({'metric': key, 'value': value})
        
        # Export ILP batches CSV
        if self.ilp_batches:
            ilp_path = Path(output_dir) / "csv" / f"{self.run_id}_ilp_batches.csv"
            with open(ilp_path, 'w', newline='') as f:
                fieldnames = [
                    'batch_id', 'batch_size', 'queue_depth_at_batch',
                    'batch_formation_time', 'ilp_solve_time', 'batch_processing_time',
                    'requests_in_batch'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for batch in self.ilp_batches:
                    row = {
                        'batch_id': batch.get('batch_id', ''),
                        'batch_size': batch.get('batch_size', ''),
                        'queue_depth_at_batch': batch.get('queue_depth_at_batch', ''),
                        'batch_formation_time': batch.get('batch_formation_time', ''),
                        'ilp_solve_time': batch.get('ilp_solve_time', ''),
                        'batch_processing_time': batch.get('batch_processing_time', ''),
                        'requests_in_batch': ','.join(batch.get('requests_in_batch', []))
                    }
                    writer.writerow(row)
        
        return str(output_path)
    
    def export_job_ids(self, output_dir: str) -> str:
        """
        Write a JSONL file mapping each request to its scheduler job_id.

        One line per request that received a job_id, format:
            {"run_id": ..., "request_id": ..., "job_id": ..., "service_id": ..., "enqueue_timestamp": ...}

        Also writes a plain-text companion (<run_id>_job_ids.txt) with one job_id
        per line for easy grep / shell piping.

        Returns the path to the JSONL file.
        """
        jsonl_path = Path(output_dir) / "json" / f"{self.run_id}_job_ids.jsonl"
        txt_path = Path(output_dir) / "json" / f"{self.run_id}_job_ids.txt"
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        rows = [
            {
                "run_id": self.run_id,
                "request_id": req.get("request_id", ""),
                "job_id": req.get("job_id"),
                "service_id": req.get("service_id", ""),
                "enqueue_timestamp": req.get("enqueue_timestamp", ""),
            }
            for req in self.requests
            if req.get("job_id") is not None
        ]

        with open(jsonl_path, "w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        with open(txt_path, "w") as f:
            for row in rows:
                f.write(str(row["job_id"]) + "\n")

        return str(jsonl_path)

    def get_summary(self) -> str:
        """Get a text summary of metrics."""
        if not self.aggregate_metrics:
            self.calculate_aggregates()
        
        agg = self.aggregate_metrics
        ilp_metrics = agg.get('ilp_metrics', {})
        batch_size_info = ""
        if ilp_metrics:
            batch_size = ilp_metrics.get('batch_size', {})
            if batch_size:
                avg_batch_size = batch_size.get('avg', 0)
                batch_size_info = f"\nILP Batch Metrics:\n  Average Batch Size: {avg_batch_size:.2f}\n  Total Batches: {ilp_metrics.get('total_batches', 0)}"
        
        summary = f"""
Metrics Summary for Run: {self.run_id}
========================================
Total Requests: {agg.get('total_requests', 0)}
Successful: {agg.get('successful_requests', 0)}
Failed: {agg.get('failed_requests', 0)}
Success Rate: {agg.get('success_rate', 0.0):.2%}
Error Rate: {agg.get('error_rate', 0.0):.2%}
Throughput: {agg.get('throughput_rps', 0.0):.2f} RPS
Duration: {agg.get('duration', 0.0):.2f} seconds

Latency Metrics:
  Average: {agg.get('latency_metrics', {}).get('avg_latency', 0.0):.3f}s
  Median (p50): {agg.get('latency_metrics', {}).get('p50_latency', 0.0):.3f}s
  p95: {agg.get('latency_metrics', {}).get('p95_latency', 0.0):.3f}s
  p99: {agg.get('latency_metrics', {}).get('p99_latency', 0.0):.3f}s{batch_size_info}
"""
        return summary



