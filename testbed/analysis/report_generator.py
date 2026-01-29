"""
Report Generator - Generates vulnerability reports from analysis results.
"""
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
from analysis.metrics_analyzer import MetricsAnalyzer


class ReportGenerator:
    """Generates vulnerability reports from test analysis."""
    
    def __init__(self, results_dir: str = "testbed/results"):
        """
        Initialize the report generator.
        
        Args:
            results_dir: Directory containing results
        """
        self.results_dir = Path(results_dir)
        self.analyzer = MetricsAnalyzer(results_dir)
    
    def identify_vulnerabilities(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Identify vulnerabilities from analysis results.
        
        Args:
            analysis: Analysis results dictionary
            
        Returns:
            List of identified vulnerabilities
        """
        vulnerabilities = []
        
        # Latency degradation
        latency_analysis = analysis.get('latency_analysis', {})
        if latency_analysis.get('has_degradation'):
            degradation = latency_analysis.get('degradation_percentage', 0)
            vulnerabilities.append({
                'severity': 'high' if degradation > 50 else 'medium',
                'category': 'latency_degradation',
                'title': f'Latency Degradation ({degradation:.1f}% increase)',
                'description': f'Latency increased by {degradation:.1f}% from first half to second half of test',
                'metrics': {
                    'first_half_avg': latency_analysis.get('first_half_avg', 0),
                    'second_half_avg': latency_analysis.get('second_half_avg', 0),
                    'degradation': degradation
                },
                'repro_steps': [
                    'Run steady_load or stress_soak scenario',
                    'Compare latency metrics from first and second half',
                    'Observe degradation > 20%'
                ]
            })
        
        # Latency spikes
        if latency_analysis.get('spike_count', 0) > 0:
            spike_pct = latency_analysis.get('spike_percentage', 0)
            if spike_pct > 5:  # More than 5% of requests are spikes
                vulnerabilities.append({
                    'severity': 'medium',
                    'category': 'latency_spikes',
                    'title': f'Latency Spikes ({spike_pct:.1f}% of requests)',
                    'description': f'{spike_pct:.1f}% of requests exceeded 2x median latency',
                    'metrics': {
                        'spike_count': latency_analysis.get('spike_count', 0),
                        'spike_percentage': spike_pct,
                        'spike_threshold': latency_analysis.get('spike_threshold', 0)
                    },
                    'repro_steps': [
                        'Run any scenario with sufficient load',
                        'Analyze latency distribution',
                        'Identify requests > 2x median latency'
                    ]
                })
        
        # Throughput instability
        throughput_analysis = analysis.get('throughput_analysis', {})
        if not throughput_analysis.get('is_stable', True):
            cv = throughput_analysis.get('coefficient_of_variation', 0)
            vulnerabilities.append({
                'severity': 'medium',
                'category': 'throughput_instability',
                'title': f'Throughput Instability (CV: {cv:.1f}%)',
                'description': f'Throughput varies significantly across time windows (CV: {cv:.1f}%)',
                'metrics': {
                    'coefficient_of_variation': cv,
                    'avg_throughput': throughput_analysis.get('avg_window_throughput', 0)
                },
                'repro_steps': [
                    'Run steady_load scenario',
                    'Analyze throughput across time windows',
                    'Observe high coefficient of variation (>20%)'
                ]
            })
        
        # Cascading failures
        error_analysis = analysis.get('error_analysis', {})
        if error_analysis.get('has_cascading_failures'):
            vulnerabilities.append({
                'severity': 'high',
                'category': 'cascading_failures',
                'title': 'Cascading Failures Detected',
                'description': 'Error rate increases significantly over time, indicating cascading failures',
                'metrics': {
                    'error_rate': error_analysis.get('error_rate', 0),
                    'error_rates_by_window': error_analysis.get('error_rates_by_window', [])
                },
                'repro_steps': [
                    'Run stress_soak or high-load scenario',
                    'Monitor error rates over time windows',
                    'Observe increasing error rate trend'
                ]
            })
        
        # High error rate
        error_rate = error_analysis.get('error_rate', 0)
        if error_rate > 0.10:  # >10% error rate
            vulnerabilities.append({
                'severity': 'high' if error_rate > 0.20 else 'medium',
                'category': 'high_error_rate',
                'title': f'High Error Rate ({error_rate:.1%})',
                'description': f'Error rate of {error_rate:.1%} exceeds acceptable threshold',
                'metrics': {
                    'error_rate': error_rate,
                    'total_errors': error_analysis.get('total_errors', 0),
                    'error_breakdown': error_analysis.get('error_breakdown', {})
                },
                'repro_steps': [
                    'Run any scenario',
                    'Check aggregate error rate',
                    'Identify error types from breakdown'
                ]
            })
        
        # Unfair service distribution
        service_dist = analysis.get('service_distribution', {})
        if not service_dist.get('is_fair', True):
            cv = service_dist.get('fairness_cv', 0)
            unfair_services = service_dist.get('unfair_services', {})
            vulnerabilities.append({
                'severity': 'low',
                'category': 'unfair_distribution',
                'title': f'Unfair Service Distribution (CV: {cv:.1f}%)',
                'description': f'Requests are not evenly distributed across services (CV: {cv:.1f}%)',
                'metrics': {
                    'fairness_cv': cv,
                    'unfair_services': unfair_services,
                    'service_counts': service_dist.get('service_counts', {})
                },
                'repro_steps': [
                    'Run scenario with multiple services',
                    'Analyze service distribution',
                    'Check coefficient of variation'
                ]
            })
        
        # ILP-specific vulnerabilities
        ilp_analysis = analysis.get('ilp_analysis', {})
        if ilp_analysis and 'error' not in ilp_analysis:
            # Batch size instability
            batch_size = ilp_analysis.get('batch_size', {})
            if batch_size and not batch_size.get('is_stable', True):
                cv = batch_size.get('cv', 0)
                vulnerabilities.append({
                    'severity': 'medium',
                    'category': 'batch_size_instability',
                    'title': f'Batch Size Instability (CV: {cv:.1f}%)',
                    'description': f'Batch sizes vary significantly (CV: {cv:.1f}%), indicating inconsistent batching behavior',
                    'metrics': {
                        'avg_batch_size': batch_size.get('avg', 0),
                        'std_batch_size': batch_size.get('std', 0),
                        'cv': cv
                    },
                    'repro_steps': [
                        'Run scenario with ILP batching enabled',
                        'Analyze batch size distribution',
                        'Check coefficient of variation'
                    ]
                })
            
            # ILP solve time degradation
            ilp_solve_time = ilp_analysis.get('ilp_solve_time', {})
            if ilp_solve_time and ilp_solve_time.get('has_degradation', False):
                degradation = ilp_solve_time.get('degradation_percentage', 0)
                vulnerabilities.append({
                    'severity': 'high' if degradation > 50 else 'medium',
                    'category': 'ilp_solve_time_degradation',
                    'title': f'ILP Solve Time Degradation ({degradation:.1f}% increase)',
                    'description': f'ILP solve time increased by {degradation:.1f}% from first half to second half',
                    'metrics': {
                        'first_half_avg': ilp_solve_time.get('first_half_avg', 0),
                        'second_half_avg': ilp_solve_time.get('second_half_avg', 0),
                        'degradation': degradation
                    },
                    'repro_steps': [
                        'Run scenario with ILP batching',
                        'Compare ILP solve times from first and second half',
                        'Observe degradation > 20%'
                    ]
                })
            
            # Queue depth spikes
            queue_depth = ilp_analysis.get('queue_depth', {})
            if queue_depth and queue_depth.get('has_spikes', False):
                spike_pct = queue_depth.get('spike_percentage', 0)
                if spike_pct > 10:  # More than 10% of batches have queue depth spikes
                    vulnerabilities.append({
                        'severity': 'medium',
                        'category': 'queue_depth_spikes',
                        'title': f'Queue Depth Spikes ({spike_pct:.1f}% of batches)',
                        'description': f'{spike_pct:.1f}% of batches show queue depth spikes (>2x average)',
                        'metrics': {
                            'avg_queue_depth': queue_depth.get('avg', 0),
                            'max_queue_depth': queue_depth.get('max', 0),
                            'spike_count': queue_depth.get('spike_count', 0),
                            'spike_percentage': spike_pct
                        },
                        'repro_steps': [
                            'Run scenario with ILP batching',
                            'Monitor queue depth at batch formation',
                            'Identify batches with queue depth > 2x average'
                        ]
                    })
            
            # Batch formation delays
            if ilp_analysis.get('has_formation_delays', False):
                formation_rate = ilp_analysis.get('batch_formation_rate', 0)
                vulnerabilities.append({
                    'severity': 'medium',
                    'category': 'batch_formation_delays',
                    'title': f'Batch Formation Delays (Rate: {formation_rate:.3f} batches/s)',
                    'description': f'Low batch formation rate ({formation_rate:.3f} batches/s) indicates delays in batch processing',
                    'metrics': {
                        'batch_formation_rate': formation_rate
                    },
                    'repro_steps': [
                        'Run scenario with ILP batching',
                        'Monitor batch formation rate',
                        'Observe rate < 0.1 batches/second'
                ]
            })
        
        return vulnerabilities
    
    def generate_report(self, run_id: str, output_path: Optional[str] = None) -> str:
        """
        Generate a comprehensive vulnerability report.
        
        Args:
            run_id: Run identifier
            output_path: Optional output file path
            
        Returns:
            Path to generated report
        """
        analysis = self.analyzer.analyze_run(run_id)
        vulnerabilities = self.identify_vulnerabilities(analysis)
        
        # Sort by severity
        severity_order = {'high': 0, 'medium': 1, 'low': 2}
        vulnerabilities.sort(key=lambda v: severity_order.get(v.get('severity', 'low'), 2))
        
        # Generate report text
        report_lines = [
            "=" * 80,
            f"Vulnerability Report for Run: {run_id}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 80,
            "",
            "EXECUTIVE SUMMARY",
            "-" * 80,
            f"Total Vulnerabilities Identified: {len(vulnerabilities)}",
            f"  High Severity: {sum(1 for v in vulnerabilities if v.get('severity') == 'high')}",
            f"  Medium Severity: {sum(1 for v in vulnerabilities if v.get('severity') == 'medium')}",
            f"  Low Severity: {sum(1 for v in vulnerabilities if v.get('severity') == 'low')}",
            "",
            "AGGREGATE METRICS",
            "-" * 80,
        ]
        
        agg_metrics = analysis.get('aggregate_metrics', {})
        report_lines.extend([
            f"Total Requests: {agg_metrics.get('total_requests', 0)}",
            f"Successful: {agg_metrics.get('successful_requests', 0)}",
            f"Failed: {agg_metrics.get('failed_requests', 0)}",
            f"Success Rate: {agg_metrics.get('success_rate', 0.0):.2%}",
            f"Error Rate: {agg_metrics.get('error_rate', 0.0):.2%}",
            f"Throughput: {agg_metrics.get('throughput_rps', 0.0):.2f} RPS",
            ""
        ])
        
        # ILP metrics section
        ilp_metrics = agg_metrics.get('ilp_metrics', {})
        if ilp_metrics:
            report_lines.extend([
                "ILP METRICS",
                "-" * 80,
                f"Total Batches: {ilp_metrics.get('total_batches', 0)}",
            ])
            
            batch_size = ilp_metrics.get('batch_size', {})
            if batch_size:
                avg_batch_size = batch_size.get('avg', 0)
                report_lines.extend([
                    f"Average Batch Size: {avg_batch_size:.2f}",
                    f"Batch Size - Min: {batch_size.get('min', 0)}, "
                    f"Max: {batch_size.get('max', 0)}, "
                    f"P95: {batch_size.get('p95', 0):.1f}, "
                    f"Median: {batch_size.get('median', 0):.1f}",
                ])
            
            ilp_solve_time = ilp_metrics.get('ilp_solve_time', {})
            if ilp_solve_time:
                report_lines.extend([
                    f"ILP Solve Time - Avg: {ilp_solve_time.get('avg', 0):.3f}s, "
                    f"Median: {ilp_solve_time.get('median', 0):.3f}s, "
                    f"P95: {ilp_solve_time.get('p95', 0):.3f}s",
                ])
            
            queue_depth = ilp_metrics.get('queue_depth', {})
            if queue_depth:
                report_lines.extend([
                    f"Queue Depth - Avg: {queue_depth.get('avg', 0):.1f}, "
                    f"Max: {queue_depth.get('max', 0)}",
                ])
            
            batch_formation_rate = ilp_metrics.get('batch_formation_rate')
            if batch_formation_rate:
                report_lines.append(f"Batch Formation Rate: {batch_formation_rate:.3f} batches/second")
            
            report_lines.append("")
        
        # Top 5 vulnerabilities
        report_lines.extend([
            "TOP VULNERABILITIES",
            "-" * 80,
            ""
        ])
        
        top_vulns = vulnerabilities[:5]
        for i, vuln in enumerate(top_vulns, 1):
            report_lines.extend([
                f"{i}. [{vuln.get('severity', 'unknown').upper()}] {vuln.get('title', 'Unknown')}",
                f"   Category: {vuln.get('category', 'unknown')}",
                f"   Description: {vuln.get('description', 'No description')}",
                "",
                "   Reproduction Steps:",
            ])
            for step in vuln.get('repro_steps', []):
                report_lines.append(f"     - {step}")
            report_lines.append("")
        
        # All vulnerabilities
        if len(vulnerabilities) > 5:
            report_lines.extend([
                f"ADDITIONAL VULNERABILITIES ({len(vulnerabilities) - 5} more)",
                "-" * 80,
                ""
            ])
            for vuln in vulnerabilities[5:]:
                report_lines.extend([
                    f"- [{vuln.get('severity', 'unknown').upper()}] {vuln.get('title', 'Unknown')}",
                    f"  {vuln.get('description', 'No description')}",
                    ""
                ])
        
        report_text = "\n".join(report_lines)
        
        # Save report
        if output_path is None:
            output_path = self.results_dir / "reports" / f"{run_id}_vulnerability_report.txt"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            f.write(report_text)
        
        return str(output_path)

