"""
Analysis Utilities for Scheduling Algorithm Experiments

This module provides utilities for analyzing experiment results and generating
visualizations for comparison between different scheduling algorithms.
"""

import csv
import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from typing import Dict, List, Optional
import os
from django.conf import settings


class ExperimentAnalyzer:
    """Analyze and visualize experiment results"""
    
    def __init__(self):
        self.algorithm_data = None
        self.job_data = None
    
    def load_experiment_data(self, algorithm_file: str = None, job_file: str = None):
        """Load experiment data from CSV files"""
        if algorithm_file is None:
            algorithm_file = settings.ALGORITHM_METRICS_FILE
        if job_file is None:
            job_file = settings.EXPERIMENT_LOG_FILE
        
        try:
            self.algorithm_data = pd.read_csv(algorithm_file)
            print(f"Loaded algorithm data: {len(self.algorithm_data)} records")
        except FileNotFoundError:
            print(f"Algorithm metrics file not found: {algorithm_file}")
            self.algorithm_data = pd.DataFrame()
        
        try:
            self.job_data = pd.read_csv(job_file)
            print(f"Loaded job data: {len(self.job_data)} records")
        except FileNotFoundError:
            print(f"Job metrics file not found: {job_file}")
            self.job_data = pd.DataFrame()
    
    def generate_summary_statistics(self) -> Dict:
        """Generate summary statistics for all algorithms"""
        if self.algorithm_data.empty:
            return {}
        
        summary = {}
        
        for algorithm in self.algorithm_data['algorithm'].unique():
            algo_data = self.algorithm_data[self.algorithm_data['algorithm'] == algorithm]
            
            summary[algorithm] = {
                'total_experiments': len(algo_data),
                'avg_assignment_time': algo_data['assignment_time'].mean(),
                'avg_total_cost': algo_data['total_cost'].mean(),
                'avg_cache_hit_rate': (algo_data['cache_hits'] / (algo_data['cache_hits'] + algo_data['cache_misses'])).mean(),
                'total_assignments': algo_data['assignments_made'].sum(),
                'avg_services_per_experiment': algo_data['services_count'].mean(),
                'avg_providers_per_experiment': algo_data['providers_count'].mean()
            }
        
        return summary
    
    def create_cost_comparison_chart(self, save_path: str = None):
        """Create a cost comparison chart between algorithms"""
        if self.algorithm_data.empty:
            print("No algorithm data available for chart")
            return
        
        plt.figure(figsize=(12, 8))
        
        # Box plot of total costs by algorithm
        plt.subplot(2, 2, 1)
        sns.boxplot(data=self.algorithm_data, x='algorithm', y='total_cost')
        plt.title('Total Cost Distribution by Algorithm')
        plt.xticks(rotation=45)
        
        # Assignment time comparison
        plt.subplot(2, 2, 2)
        sns.boxplot(data=self.algorithm_data, x='algorithm', y='assignment_time')
        plt.title('Assignment Time Distribution by Algorithm')
        plt.xticks(rotation=45)
        
        # Cache hit rate comparison
        plt.subplot(2, 2, 3)
        cache_hit_rate = self.algorithm_data['cache_hits'] / (self.algorithm_data['cache_hits'] + self.algorithm_data['cache_misses'])
        combined_data = pd.DataFrame({
            'algorithm': self.algorithm_data['algorithm'],
            'cache_hit_rate': cache_hit_rate
        })
        sns.boxplot(data=combined_data, x='algorithm', y='cache_hit_rate')
        plt.title('Cache Hit Rate by Algorithm')
        plt.xticks(rotation=45)
        
        # Average cost per service
        plt.subplot(2, 2, 4)
        sns.boxplot(data=self.algorithm_data, x='algorithm', y='average_cost_per_service')
        plt.title('Average Cost per Service by Algorithm')
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Chart saved to: {save_path}")
        else:
            plt.show()
    
    def create_performance_over_time_chart(self, save_path: str = None):
        """Create a performance over time chart"""
        if self.algorithm_data.empty:
            print("No algorithm data available for chart")
            return
        
        # Convert timestamp to datetime
        self.algorithm_data['timestamp'] = pd.to_datetime(self.algorithm_data['timestamp'])
        
        plt.figure(figsize=(15, 10))
        
        # Total cost over time
        plt.subplot(2, 2, 1)
        for algorithm in self.algorithm_data['algorithm'].unique():
            algo_data = self.algorithm_data[self.algorithm_data['algorithm'] == algorithm]
            plt.plot(algo_data['timestamp'], algo_data['total_cost'], marker='o', label=algorithm)
        plt.title('Total Cost Over Time')
        plt.xlabel('Time')
        plt.ylabel('Total Cost')
        plt.legend()
        plt.xticks(rotation=45)
        
        # Assignment time over time
        plt.subplot(2, 2, 2)
        for algorithm in self.algorithm_data['algorithm'].unique():
            algo_data = self.algorithm_data[self.algorithm_data['algorithm'] == algorithm]
            plt.plot(algo_data['timestamp'], algo_data['assignment_time'], marker='o', label=algorithm)
        plt.title('Assignment Time Over Time')
        plt.xlabel('Time')
        plt.ylabel('Assignment Time (seconds)')
        plt.legend()
        plt.xticks(rotation=45)
        
        # Cache hits over time
        plt.subplot(2, 2, 3)
        for algorithm in self.algorithm_data['algorithm'].unique():
            algo_data = self.algorithm_data[self.algorithm_data['algorithm'] == algorithm]
            plt.plot(algo_data['timestamp'], algo_data['cache_hits'], marker='o', label=algorithm)
        plt.title('Cache Hits Over Time')
        plt.xlabel('Time')
        plt.ylabel('Cache Hits')
        plt.legend()
        plt.xticks(rotation=45)
        
        # Assignments made over time
        plt.subplot(2, 2, 4)
        for algorithm in self.algorithm_data['algorithm'].unique():
            algo_data = self.algorithm_data[self.algorithm_data['algorithm'] == algorithm]
            plt.plot(algo_data['timestamp'], algo_data['assignments_made'], marker='o', label=algorithm)
        plt.title('Assignments Made Over Time')
        plt.xlabel('Time')
        plt.ylabel('Assignments Made')
        plt.legend()
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Chart saved to: {save_path}")
        else:
            plt.show()
    
    def export_summary_report(self, filename: str = None) -> str:
        """Export a comprehensive summary report"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"/home/user/Documents/Serverless_Scheduler_sn34kyp3t3/analysis_report_{timestamp}.txt"
        
        summary_stats = self.generate_summary_statistics()
        
        with open(filename, 'w') as f:
            f.write("SCHEDULING ALGORITHM EXPERIMENT ANALYSIS REPORT\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            if summary_stats:
                f.write("SUMMARY STATISTICS BY ALGORITHM\n")
                f.write("-" * 40 + "\n\n")
                
                for algorithm, stats in summary_stats.items():
                    f.write(f"{algorithm} Algorithm:\n")
                    f.write(f"  Total Experiments: {stats['total_experiments']}\n")
                    f.write(f"  Avg Assignment Time: {stats['avg_assignment_time']:.4f} seconds\n")
                    f.write(f"  Avg Total Cost: {stats['avg_total_cost']:.2f}\n")
                    f.write(f"  Avg Cache Hit Rate: {stats['avg_cache_hit_rate']:.2%}\n")
                    f.write(f"  Total Assignments: {stats['total_assignments']}\n")
                    f.write(f"  Avg Services per Experiment: {stats['avg_services_per_experiment']:.1f}\n")
                    f.write(f"  Avg Providers per Experiment: {stats['avg_providers_per_experiment']:.1f}\n\n")
                
                # Find best performers
                f.write("BEST PERFORMERS\n")
                f.write("-" * 20 + "\n")
                
                best_cost = min(stats['avg_total_cost'] for stats in summary_stats.values())
                best_time = min(stats['avg_assignment_time'] for stats in summary_stats.values())
                best_cache = max(stats['avg_cache_hit_rate'] for stats in summary_stats.values())
                
                for algorithm, stats in summary_stats.items():
                    if stats['avg_total_cost'] == best_cost:
                        f.write(f"Lowest Average Cost: {algorithm} ({best_cost:.2f})\n")
                    if stats['avg_assignment_time'] == best_time:
                        f.write(f"Fastest Assignment: {algorithm} ({best_time:.4f}s)\n")
                    if stats['avg_cache_hit_rate'] == best_cache:
                        f.write(f"Best Cache Hit Rate: {algorithm} ({best_cache:.2%})\n")
            else:
                f.write("No experiment data available for analysis.\n")
        
        print(f"Analysis report saved to: {filename}")
        return filename
    
    def compare_algorithms(self, algorithms: List[str] = None) -> Dict:
        """Compare specific algorithms"""
        if self.algorithm_data.empty:
            return {}
        
        if algorithms is None:
            algorithms = self.algorithm_data['algorithm'].unique().tolist()
        
        comparison = {}
        
        for algorithm in algorithms:
            algo_data = self.algorithm_data[self.algorithm_data['algorithm'] == algorithm]
            if not algo_data.empty:
                comparison[algorithm] = {
                    'cost_stats': {
                        'mean': algo_data['total_cost'].mean(),
                        'median': algo_data['total_cost'].median(),
                        'std': algo_data['total_cost'].std(),
                        'min': algo_data['total_cost'].min(),
                        'max': algo_data['total_cost'].max()
                    },
                    'time_stats': {
                        'mean': algo_data['assignment_time'].mean(),
                        'median': algo_data['assignment_time'].median(),
                        'std': algo_data['assignment_time'].std(),
                        'min': algo_data['assignment_time'].min(),
                        'max': algo_data['assignment_time'].max()
                    },
                    'cache_performance': {
                        'total_hits': algo_data['cache_hits'].sum(),
                        'total_misses': algo_data['cache_misses'].sum(),
                        'hit_rate': algo_data['cache_hits'].sum() / (algo_data['cache_hits'].sum() + algo_data['cache_misses'].sum())
                    }
                }
        
        return comparison


def quick_analysis(algorithm_file: str = None, job_file: str = None):
    """Quick analysis function for easy use"""
    analyzer = ExperimentAnalyzer()
    analyzer.load_experiment_data(algorithm_file, job_file)
    
    print("=== QUICK EXPERIMENT ANALYSIS ===\n")
    
    summary = analyzer.generate_summary_statistics()
    if summary:
        print("Summary Statistics:")
        for algorithm, stats in summary.items():
            print(f"\n{algorithm}:")
            print(f"  Avg Cost: {stats['avg_total_cost']:.2f}")
            print(f"  Avg Time: {stats['avg_assignment_time']:.4f}s")
            print(f"  Cache Hit Rate: {stats['avg_cache_hit_rate']:.2%}")
    
    # Create visualizations
    try:
        analyzer.create_cost_comparison_chart()
        analyzer.create_performance_over_time_chart()
    except Exception as e:
        print(f"Error creating charts: {e}")
    
    # Export report
    analyzer.export_summary_report()
    
    return analyzer


if __name__ == "__main__":
    # Run quick analysis if script is executed directly
    quick_analysis() 