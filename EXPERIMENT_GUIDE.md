# Scheduling Algorithm Comparison Experiment Guide

This guide explains how to conduct experiments comparing different scheduling algorithms in the P2P Serverless Scheduler.

## Available Algorithms

1. **ILP (Integer Linear Programming)** - Current implementation using optimization
2. **MRU (Most Recently Used)** - Prefers providers used most recently  
3. **Belady's Algorithm** - Optimal cache-aware scheduling (requires future knowledge)
4. **Round Robin** - Simple round-robin assignment

## Quick Start

### 1. Configure Experiment Settings

Edit `scheduler/scheduler/settings.py`:

```python
# Set the default algorithm
SCHEDULING_ALGORITHM = 'ILP'  # Options: 'ILP', 'MRU', 'BELADY', 'ROUND_ROBIN'

# Enable experiment mode
EXPERIMENT_MODE = True

# Configure experiment parameters
MRU_HISTORY_SIZE = 100
BELADY_PREDICTION_WINDOW = 50
```

### 2. Start the Django Server

```bash
cd scheduler
python manage.py runserver 0.0.0.0:8000
```

### 3. Start a Provider

```bash
cd ..
python provider/provider1.py 34933555-5cca-41fb-aded-4ab7900c48d5
```

## Running Experiments

### Method 1: API Endpoints

#### Start an Experiment
```bash
curl -X POST "http://localhost:8000/providers/experiment/start/" \
  -H "Content-Type: application/json" \
  -d '{
    "algorithms": ["ILP", "MRU", "BELADY", "ROUND_ROBIN"],
    "iterations": 15,
    "services_per_iteration": 5
  }'
```

#### Check Experiment Status
```bash
curl "http://localhost:8000/providers/experiment/status/"
```

#### Switch Algorithm (for manual testing)
```bash
curl -X POST "http://localhost:8000/providers/algorithm/switch/" \
  -H "Content-Type: application/json" \
  -d '{"algorithm": "MRU"}'
```

#### Generate Report
```bash
curl "http://localhost:8000/providers/experiment/report/"
```

### Method 2: Python Script

Create a test script `run_experiment.py`:

```python
import requests
import time
import json

# Configuration
BASE_URL = "http://localhost:8000/providers"
ALGORITHMS = ["ILP", "MRU", "BELADY", "ROUND_ROBIN"]

def run_comprehensive_experiment():
    print("Starting comprehensive scheduling algorithm experiment...")
    
    # Start experiment
    response = requests.post(f"{BASE_URL}/experiment/start/", json={
        "algorithms": ALGORITHMS,
        "iterations": 20,
        "services_per_iteration": 5
    })
    
    if response.status_code == 200:
        print("Experiment started successfully!")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Failed to start experiment: {response.text}")
        return
    
    # Monitor progress
    while True:
        time.sleep(10)  # Check every 10 seconds
        
        status_response = requests.get(f"{BASE_URL}/experiment/status/")
        if status_response.status_code == 200:
            status = status_response.json()
            if not status['experiment']['active']:
                print("Experiment completed!")
                break
            else:
                print("Experiment still running...")
        else:
            print("Failed to get status")
            break
    
    # Generate report
    report_response = requests.get(f"{BASE_URL}/experiment/report/")
    if report_response.status_code == 200:
        report = report_response.json()
        print("Final Report:")
        print(json.dumps(report['report'], indent=2))
    else:
        print("Failed to generate report")

if __name__ == "__main__":
    run_comprehensive_experiment()
```

### Method 3: Manual Testing

1. **Switch algorithm and test manually:**

```bash
# Switch to MRU
curl -X POST "http://localhost:8000/providers/algorithm/switch/" \
  -H "Content-Type: application/json" \
  -d '{"algorithm": "MRU"}'

# Run some services
curl -X POST "http://localhost:8000/developers/run_service_async/18" \
  -H "Content-Type: application/json" \
  -d '{"numberOfInvocations": 1, "chained": false, "input": "None", "runMultipleInvocations": false}'

# Check metrics
curl "http://localhost:8000/providers/algorithm/metrics/"

# Switch to Round Robin and repeat
curl -X POST "http://localhost:8000/providers/algorithm/switch/" \
  -H "Content-Type: application/json" \
  -d '{"algorithm": "ROUND_ROBIN"}'
```

## Experiment Configuration

### Algorithm-Specific Settings

#### MRU (Most Recently Used)
- `MRU_HISTORY_SIZE`: Number of recent assignments to track (default: 100)
- Uses exponential decay for recency scoring
- Prefers providers used in the last few minutes

#### Belady's Algorithm  
- `BELADY_PREDICTION_WINDOW`: Number of future requests to consider (default: 50)
- Simulates optimal cache-aware scheduling
- Uses heuristics to predict future service usage

#### Round Robin
- Maintains state in `ROUND_ROBIN_STATE_FILE`
- Simple round-robin assignment to providers
- No optimization, purely fair distribution

#### ILP (Integer Linear Programming)
- Uses existing `mincost.py` optimization
- Considers costs, delays, and constraints
- Optimal solution for current state

## Data Analysis

### Automated Analysis

```python
# In Django shell or script
from providers.analysis_utils import quick_analysis

# Run quick analysis
analyzer = quick_analysis()

# Or specify custom files
analyzer = quick_analysis(
    algorithm_file="/path/to/algorithm_metrics.csv",
    job_file="/path/to/experiment_results.csv"
)
```

### Manual Analysis

```python
from providers.analysis_utils import ExperimentAnalyzer

# Load data
analyzer = ExperimentAnalyzer()
analyzer.load_experiment_data()

# Generate statistics
summary = analyzer.generate_summary_statistics()
print(summary)

# Create visualizations
analyzer.create_cost_comparison_chart(save_path="cost_comparison.png")
analyzer.create_performance_over_time_chart(save_path="performance_timeline.png")

# Export detailed report
analyzer.export_summary_report("detailed_analysis.txt")

# Compare specific algorithms
comparison = analyzer.compare_algorithms(["ILP", "MRU"])
print(comparison)
```

## Metrics Collected

### Algorithm-Level Metrics
- `assignment_time`: Time taken to make scheduling decisions
- `total_cost`: Total cost including delays and runtime
- `cache_hits/misses`: Cache performance
- `assignments_made`: Number of successful assignments
- `services_count`: Number of services scheduled
- `providers_count`: Number of providers used

### Job-Level Metrics  
- `pull_time`: Container image pull time
- `run_time`: Service execution time
- `total_time`: End-to-end time
- `cost`: Job cost
- `cache_hit`: Whether service was cached
- `provider_delay`: Provider queue delay

## Expected Results

### ILP Algorithm
- **Strengths**: Optimal cost minimization, considers all constraints
- **Weaknesses**: Higher computational overhead for assignment
- **Use Case**: When optimality is crucial and assignment time is less critical

### MRU Algorithm  
- **Strengths**: Fast assignment, good cache locality
- **Weaknesses**: May create hotspots, not globally optimal
- **Use Case**: When recent usage patterns indicate future needs

### Belady's Algorithm
- **Strengths**: Optimal cache performance (with perfect future knowledge)
- **Weaknesses**: Requires future knowledge, impractical in real scenarios
- **Use Case**: Upper bound benchmark for cache-aware scheduling

### Round Robin
- **Strengths**: Fair distribution, predictable behavior, minimal overhead
- **Weaknesses**: Ignores costs, delays, and cache state
- **Use Case**: Baseline comparison, simple load distribution

## Sample Results Interpretation

```
Algorithm     Avg Cost    Avg Time    Cache Hit Rate    Assignments
ILP           1250.45     0.0234      67.3%             150
MRU           1298.67     0.0089      71.2%             148  
BELADY        1203.12     0.0156      74.8%             152
ROUND_ROBIN   1456.89     0.0034      58.9%             149
```

**Analysis:**
- ILP provides good cost optimization but with higher assignment time
- MRU balances performance and speed with excellent cache hits
- Belady achieves the best overall performance (theoretical optimum)
- Round Robin is fastest but most expensive due to lack of optimization

## Troubleshooting

### Common Issues

1. **No providers available**: Ensure at least one provider is running and ready
2. **No services available**: Check that services exist in the database and are active
3. **Experiment not starting**: Verify Django server is running and endpoints are accessible
4. **Missing dependencies**: Install required packages: `pip install pandas matplotlib seaborn`

### Debug Commands

```bash
# Check provider status
curl "http://localhost:8000/providers/ready/34933555-5cca-41fb-aded-4ab7900c48d5"

# Check current algorithm
curl "http://localhost:8000/providers/experiment/status/"

# Reset algorithm metrics
curl -X POST "http://localhost:8000/providers/algorithm/reset/"
```

## Timeline view of all activity (requires timestamps)
find experiment_logs -name "*.log" -exec grep "2024-01-15 14:2[0-9]" {} + | sort

# Generate comprehensive log analysis report
python analyze_experiment_logs.py --logs-dir experiment_logs --output analysis_report.txt

# Print analysis to console
python analyze_experiment_logs.py --console

## Log Analysis Script Features

The `analyze_experiment_logs.py` script provides comprehensive analysis of experiment logs:

### Features:
- **Timeline Report**: Chronological view of all events across all nodes
- **Node Activity Report**: Statistics per scheduler/provider/loadbalancer
- **Algorithm Analysis**: Track algorithm mentions and switches
- **Performance Analysis**: Docker operations and timing data
- **Comprehensive Reports**: Save detailed analysis to files

### Usage Examples:
```bash
# Basic analysis with default settings
python analyze_experiment_logs.py

# Custom logs directory and output file
python analyze_experiment_logs.py --logs-dir my_experiment_logs --output my_report.txt

# Print detailed console output
python analyze_experiment_logs.py --console
```

The script automatically processes all `.log` files in the specified directory and generates insights into:
- Which nodes were most active during experiments
- Timeline of algorithm switches and key events
- Docker operation patterns across providers
- Performance bottlenecks and timing analysis

## Advanced Usage

### Custom Experiment Scenarios

1. **Load Testing**: Run experiments with increasing numbers of services
2. **Provider Scaling**: Test with different numbers of providers
3. **Cache Behavior**: Analyze cache hit rates under different algorithms
4. **Cost Analysis**: Compare total costs under different workload patterns

### Integration with Real Workloads

Replace the experiment framework's synthetic workload with real service requests:

```python
# In request_handler function
if settings.EXPERIMENT_MODE:
    # Record real request metrics
    experiment_runner.metrics.record_assignment(...)
```

This allows analysis of algorithm performance on actual production workloads. 