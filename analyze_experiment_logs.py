#!/usr/bin/env python3
"""
Experiment Log Analyzer

This script analyzes experiment logs to provide insights into system behavior
during scheduling algorithm experiments.

Usage:
    python analyze_experiment_logs.py [--logs-dir experiment_logs] [--output report.txt]
"""

import os
import re
import argparse
from datetime import datetime
from collections import defaultdict, Counter
from typing import Dict, List, Tuple


class LogEntry:
    """Represents a single log entry"""
    
    def __init__(self, timestamp: datetime, node_type: str, node_id: str, 
                 stream_type: str, message: str):
        self.timestamp = timestamp
        self.node_type = node_type
        self.node_id = node_id
        self.stream_type = stream_type
        self.message = message
    
    def __str__(self):
        return f"[{self.timestamp}] [{self.node_type}:{self.node_id}] [{self.stream_type}] {self.message}"


class ExperimentLogAnalyzer:
    """Analyzes experiment logs to extract insights"""
    
    def __init__(self, logs_dir: str = "experiment_logs"):
        self.logs_dir = logs_dir
        self.entries: List[LogEntry] = []
        self.log_pattern = re.compile(
            r'\[([^\]]+)\] \[([^:]+):([^\]]+)\] \[([^\]]+)\] (.+)'
        )
    
    def load_logs(self):
        """Load all log files from the logs directory"""
        if not os.path.exists(self.logs_dir):
            print(f"Logs directory not found: {self.logs_dir}")
            return
        
        log_files = [f for f in os.listdir(self.logs_dir) if f.endswith('.log')]
        print(f"Found {len(log_files)} log files")
        
        for log_file in log_files:
            file_path = os.path.join(self.logs_dir, log_file)
            self._load_log_file(file_path)
        
        # Sort entries by timestamp
        self.entries.sort(key=lambda x: x.timestamp)
        print(f"Loaded {len(self.entries)} log entries")
    
    def _load_log_file(self, file_path: str):
        """Load entries from a single log file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    match = self.log_pattern.match(line)
                    if match:
                        timestamp_str, node_type, node_id, stream_type, message = match.groups()
                        
                        try:
                            # Parse timestamp
                            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f")
                            
                            entry = LogEntry(timestamp, node_type, node_id, stream_type, message)
                            self.entries.append(entry)
                        except ValueError:
                            # Skip entries with invalid timestamps
                            continue
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
    
    def generate_timeline_report(self) -> str:
        """Generate a chronological timeline of events"""
        if not self.entries:
            return "No log entries found."
        
        report = ["=== EXPERIMENT TIMELINE ===\n"]
        report.append(f"Time Range: {self.entries[0].timestamp} to {self.entries[-1].timestamp}")
        report.append(f"Total Duration: {self.entries[-1].timestamp - self.entries[0].timestamp}")
        report.append(f"Total Events: {len(self.entries)}\n")
        
        # Group by time intervals
        current_minute = None
        for entry in self.entries:
            minute_key = entry.timestamp.strftime("%H:%M")
            if minute_key != current_minute:
                report.append(f"\n--- {minute_key} ---")
                current_minute = minute_key
            
            report.append(f"  {entry.timestamp.strftime('%S.%f')[:-3]} [{entry.node_type}:{entry.node_id}] {entry.message}")
        
        return '\n'.join(report)
    
    def generate_node_activity_report(self) -> str:
        """Generate report of activity by node"""
        node_stats = defaultdict(lambda: {
            'total_messages': 0,
            'stdout_messages': 0,
            'stderr_messages': 0,
            'first_activity': None,
            'last_activity': None,
            'key_events': []
        })
        
        # Algorithm and Docker-related keywords
        algorithm_keywords = ['ILP', 'MRU', 'BELADY', 'ROUND_ROBIN', 'scheduling algorithm']
        docker_keywords = ['Pull done', 'Run done', 'docker', 'container']
        
        for entry in self.entries:
            node_key = f"{entry.node_type}:{entry.node_id}"
            stats = node_stats[node_key]
            
            stats['total_messages'] += 1
            if entry.stream_type == 'STDOUT':
                stats['stdout_messages'] += 1
            else:
                stats['stderr_messages'] += 1
            
            if stats['first_activity'] is None:
                stats['first_activity'] = entry.timestamp
            stats['last_activity'] = entry.timestamp
            
            # Track key events
            message_lower = entry.message.lower()
            if any(keyword.lower() in message_lower for keyword in algorithm_keywords):
                stats['key_events'].append(f"ALGO: {entry.message}")
            elif any(keyword.lower() in message_lower for keyword in docker_keywords):
                stats['key_events'].append(f"DOCKER: {entry.message}")
            elif 'experiment' in message_lower:
                stats['key_events'].append(f"EXP: {entry.message}")
        
        report = ["=== NODE ACTIVITY REPORT ===\n"]
        
        for node_key, stats in sorted(node_stats.items()):
            report.append(f"{node_key}:")
            report.append(f"  Total Messages: {stats['total_messages']}")
            report.append(f"  STDOUT/STDERR: {stats['stdout_messages']}/{stats['stderr_messages']}")
            report.append(f"  Active Period: {stats['first_activity']} to {stats['last_activity']}")
            if stats['first_activity'] and stats['last_activity']:
                duration = stats['last_activity'] - stats['first_activity']
                report.append(f"  Duration: {duration}")
            
            if stats['key_events']:
                report.append(f"  Key Events ({len(stats['key_events'])}):")
                for event in stats['key_events'][:5]:  # Show first 5
                    report.append(f"    - {event}")
                if len(stats['key_events']) > 5:
                    report.append(f"    ... and {len(stats['key_events']) - 5} more")
            report.append("")
        
        return '\n'.join(report)
    
    def generate_algorithm_analysis(self) -> str:
        """Analyze algorithm-specific activity"""
        algorithm_mentions = Counter()
        algorithm_timeline = []
        
        for entry in self.entries:
            message = entry.message
            
            # Look for algorithm mentions
            if 'scheduling algorithm:' in message.lower():
                algorithm_timeline.append((entry.timestamp, entry.node_id, message))
            
            for algo in ['ILP', 'MRU', 'BELADY', 'ROUND_ROBIN']:
                if algo in message:
                    algorithm_mentions[algo] += 1
        
        report = ["=== ALGORITHM ANALYSIS ===\n"]
        
        report.append("Algorithm Mentions:")
        for algo, count in algorithm_mentions.most_common():
            report.append(f"  {algo}: {count} mentions")
        
        if algorithm_timeline:
            report.append("\nAlgorithm Switches:")
            for timestamp, node_id, message in algorithm_timeline:
                report.append(f"  {timestamp} [{node_id}]: {message}")
        
        return '\n'.join(report)
    
    def generate_performance_analysis(self) -> str:
        """Analyze performance-related metrics from logs"""
        docker_operations = []
        timing_data = []
        
        for entry in self.entries:
            message = entry.message
            
            # Docker operations
            if 'Pull done!' in message:
                docker_operations.append(('pull', entry.timestamp, entry.node_id))
            elif 'Run done!' in message:
                docker_operations.append(('run', entry.timestamp, entry.node_id))
            
            # Timing information
            if any(keyword in message for keyword in ['Assignment completed', 'assignment_time', 'total_cost']):
                timing_data.append((entry.timestamp, entry.node_id, message))
        
        report = ["=== PERFORMANCE ANALYSIS ===\n"]
        
        if docker_operations:
            # Analyze Docker operations by provider
            provider_ops = defaultdict(list)
            for op_type, timestamp, node_id in docker_operations:
                provider_ops[node_id].append((op_type, timestamp))
            
            report.append("Docker Operations by Provider:")
            for provider, ops in provider_ops.items():
                pulls = sum(1 for op_type, _ in ops if op_type == 'pull')
                runs = sum(1 for op_type, _ in ops if op_type == 'run')
                report.append(f"  {provider}: {pulls} pulls, {runs} runs")
        
        if timing_data:
            report.append("\nTiming Events:")
            for timestamp, node_id, message in timing_data[-10:]:  # Last 10 events
                report.append(f"  {timestamp} [{node_id}]: {message}")
        
        return '\n'.join(report)
    
    def save_report(self, output_file: str):
        """Generate and save a comprehensive report"""
        reports = [
            self.generate_timeline_report(),
            "\n" + "="*80 + "\n",
            self.generate_node_activity_report(),
            "\n" + "="*80 + "\n",
            self.generate_algorithm_analysis(),
            "\n" + "="*80 + "\n",
            self.generate_performance_analysis()
        ]
        
        full_report = '\n'.join(reports)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(full_report)
        
        print(f"Report saved to: {output_file}")
        return full_report


def main():
    parser = argparse.ArgumentParser(description="Analyze experiment logs")
    parser.add_argument("--logs-dir", default="experiment_logs", help="Directory containing log files")
    parser.add_argument("--output", default="experiment_analysis.txt", help="Output report file")
    parser.add_argument("--console", action="store_true", help="Print report to console")
    
    args = parser.parse_args()
    
    analyzer = ExperimentLogAnalyzer(args.logs_dir)
    analyzer.load_logs()
    
    if analyzer.entries:
        report = analyzer.save_report(args.output)
        
        if args.console:
            print("\n" + "="*80)
            print(report)
    else:
        print("No log entries found to analyze.")


if __name__ == "__main__":
    main() 