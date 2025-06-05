#!/usr/bin/env python3
"""
Sample experiment runner for scheduling algorithm comparison
"""

import requests
import time
import json
import sys
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000/providers"
ALGORITHMS = ["ILP", "MRU", "BELADY", "ROUND_ROBIN"]

def check_server_status():
    """Check if the Django server is running"""
    try:
        response = requests.get(f"{BASE_URL}/experiment/status/", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False

def run_comprehensive_experiment():
    """Run a comprehensive experiment comparing all algorithms"""
    print("=" * 60)
    print("SCHEDULING ALGORITHM COMPARISON EXPERIMENT")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Testing algorithms: {', '.join(ALGORITHMS)}")
    print()
    
    # Check server status
    if not check_server_status():
        print("❌ Error: Django server is not running or not accessible")
        print("Please start the server with: cd scheduler && python manage.py runserver 0.0.0.0:8000")
        return False
    
    print("✅ Django server is running")
    
    # Start experiment
    print("\n🚀 Starting experiment...")
    try:
        response = requests.post(f"{BASE_URL}/experiment/start/", json={
            "algorithms": ALGORITHMS,
            "iterations": 15,
            "services_per_iteration": 5
        }, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Experiment started successfully!")
            print(f"   Algorithms: {result['algorithms']}")
            print(f"   Iterations: {result['iterations']}")
            print(f"   Services per iteration: {result['services_per_iteration']}")
        else:
            print(f"❌ Failed to start experiment: {response.text}")
            return False
            
    except requests.RequestException as e:
        print(f"❌ Network error starting experiment: {e}")
        return False
    
    # Monitor progress
    print("\n⏳ Monitoring experiment progress...")
    start_time = time.time()
    max_wait_time = 300  # 5 minutes maximum
    
    while time.time() - start_time < max_wait_time:
        time.sleep(5)  # Check every 5 seconds
        
        try:
            status_response = requests.get(f"{BASE_URL}/experiment/status/", timeout=5)
            if status_response.status_code == 200:
                status = status_response.json()
                if not status['experiment']['active']:
                    print("✅ Experiment completed!")
                    break
                else:
                    elapsed = time.time() - start_time
                    print(f"   Still running... ({elapsed:.0f}s elapsed)")
            else:
                print("⚠️  Warning: Failed to get experiment status")
                
        except requests.RequestException as e:
            print(f"⚠️  Warning: Network error checking status: {e}")
    else:
        print("⚠️  Experiment is taking longer than expected, continuing to generate report...")
    
    # Generate report
    print("\n📊 Generating final report...")
    try:
        report_response = requests.get(f"{BASE_URL}/experiment/report/", timeout=30)
        if report_response.status_code == 200:
            report_data = report_response.json()
            report = report_data['report']
            
            print("✅ Report generated successfully!")
            print(f"   Report file: {report_data.get('report_file', 'Not saved')}")
            
            # Display summary
            display_experiment_summary(report)
            
        else:
            print(f"❌ Failed to generate report: {report_response.text}")
            return False
            
    except requests.RequestException as e:
        print(f"❌ Network error generating report: {e}")
        return False
    
    print("\n✅ Experiment completed successfully!")
    return True

def display_experiment_summary(report):
    """Display a formatted summary of experiment results"""
    print("\n" + "=" * 60)
    print("EXPERIMENT RESULTS SUMMARY")
    print("=" * 60)
    
    if not report.get('algorithms'):
        print("No algorithm data available")
        return
    
    # Header
    print(f"{'Algorithm':<15} {'Avg Cost':<12} {'Avg Time':<12} {'Hit Rate':<12} {'Runs':<8}")
    print("-" * 65)
    
    # Results for each algorithm
    best_cost = float('inf')
    best_time = float('inf')
    best_cache = 0
    
    for algo_name, metrics in report['algorithms'].items():
        avg_cost = metrics.get('average_cost', 0)
        avg_time = metrics.get('average_assignment_time', 0)
        cache_rate = metrics.get('cache_hit_rate', 0)
        runs = metrics.get('assignments_count', 0)
        
        # Track best performers
        if avg_cost < best_cost:
            best_cost = avg_cost
        if avg_time < best_time:
            best_time = avg_time
        if cache_rate > best_cache:
            best_cache = cache_rate
        
        print(f"{algo_name:<15} {avg_cost:<12.2f} {avg_time:<12.4f} {cache_rate:<12.2%} {runs:<8}")
    
    # Best performers
    print("\n" + "🏆 BEST PERFORMERS:")
    for algo_name, metrics in report['algorithms'].items():
        if metrics.get('average_cost', float('inf')) == best_cost:
            print(f"   💰 Lowest Cost: {algo_name} ({best_cost:.2f})")
        if metrics.get('average_assignment_time', float('inf')) == best_time:
            print(f"   ⚡ Fastest: {algo_name} ({best_time:.4f}s)")
        if metrics.get('cache_hit_rate', 0) == best_cache:
            print(f"   🎯 Best Cache: {algo_name} ({best_cache:.2%})")

def run_single_algorithm_test(algorithm):
    """Test a single algorithm"""
    print(f"\n🧪 Testing {algorithm} algorithm...")
    
    # Switch to the algorithm
    try:
        response = requests.post(f"{BASE_URL}/algorithm/switch/", json={
            "algorithm": algorithm
        }, timeout=5)
        
        if response.status_code == 200:
            print(f"✅ Switched to {algorithm}")
        else:
            print(f"❌ Failed to switch to {algorithm}: {response.text}")
            return False
            
    except requests.RequestException as e:
        print(f"❌ Network error switching algorithm: {e}")
        return False
    
    # Get metrics before
    try:
        metrics_response = requests.get(f"{BASE_URL}/algorithm/metrics/", timeout=5)
        if metrics_response.status_code == 200:
            before_metrics = metrics_response.json()['metrics']
            print(f"   Current metrics: {before_metrics}")
        else:
            before_metrics = {}
    except:
        before_metrics = {}
    
    print(f"   You can now run services to test {algorithm} algorithm")
    print(f"   Example: curl -X POST 'http://localhost:8000/developers/run_service_async/18' -H 'Content-Type: application/json' -d '{{\"numberOfInvocations\": 1, \"chained\": false, \"input\": \"None\", \"runMultipleInvocations\": false}}'")
    
    return True

def main():
    """Main function"""
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "test":
            # Test single algorithm
            algorithm = sys.argv[2].upper() if len(sys.argv) > 2 else "ILP"
            if algorithm in ALGORITHMS:
                run_single_algorithm_test(algorithm)
            else:
                print(f"Invalid algorithm. Choose from: {ALGORITHMS}")
        
        elif command == "status":
            # Check status
            if check_server_status():
                try:
                    response = requests.get(f"{BASE_URL}/experiment/status/")
                    if response.status_code == 200:
                        status = response.json()
                        print("Current Status:")
                        print(json.dumps(status, indent=2))
                    else:
                        print("Failed to get status")
                except Exception as e:
                    print(f"Error: {e}")
            else:
                print("Server not accessible")
        
        elif command == "help":
            print("Usage:")
            print("  python run_experiment.py                 - Run full experiment")
            print("  python run_experiment.py test [ALGO]     - Test single algorithm")
            print("  python run_experiment.py status          - Check current status")
            print("  python run_experiment.py help            - Show this help")
            print(f"\nAvailable algorithms: {', '.join(ALGORITHMS)}")
        
        else:
            print(f"Unknown command: {command}")
            print("Use 'python run_experiment.py help' for usage information")
    
    else:
        # Run full experiment
        success = run_comprehensive_experiment()
        if success:
            print("\n💡 Next steps:")
            print("   1. Check the generated CSV files for detailed data")
            print("   2. Run analysis: python scheduler/providers/analysis_utils.py")
            print("   3. View charts and reports in the output directory")
        else:
            print("\n❌ Experiment failed. Please check the troubleshooting guide.")

if __name__ == "__main__":
    main() 