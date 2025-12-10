# Serverless Scheduler Testbed

A comprehensive, parameterized testbed system for evaluating serverless scheduler performance across multiple dimensions.

## Overview

This testbed implements a structured, multi-dimensional methodology to systematically probe the scheduler's core responsibilities:
- Request queuing
- Load balancing
- Invocation orchestration
- Resource cleanup

It supports five scenario categories:
1. **Baseline** - Low-volume, isolated requests to establish norms
2. **Steady Load** - Constant RPS over sustained periods with ramping
3. **Bursty Load** - Sudden spikes with Poisson distribution
4. **Stress/Soak** - Maximum sustained load until failure
5. **Chaos/Edge** - Fault injection and edge case testing

## Installation

1. Install dependencies:
```bash
cd testbed
pip install -r requirements.txt
```

2. Ensure the load balancer is running on `http://localhost:9001` (or configure via `--load-balancer-url`)

3. Ensure `avg_job_times.json` exists in the project root directory

## Quick Start

### Run a Single Scenario

```bash
# Run baseline scenario
python main.py --scenario baseline

# Run steady load scenario
python main.py --scenario steady_load

# Run with custom load balancer URL
python main.py --scenario baseline --load-balancer-url http://192.168.1.100:9001

# Run with research-scale volumes (1k-10k requests)
python main.py --scenario baseline --research-mode

# Run with fixed seed for reproducibility
python main.py --scenario baseline --seed 42

# Save requests for later replay
python main.py --scenario baseline --seed 42 --save-requests

# Replay saved requests
python main.py --scenario baseline --replay testbed/results/requests/baseline_20240101_120000_requests.json
```

### Run All Scenarios

```bash
python main.py --all
```

### Run Multiple Iterations

```bash
# Run baseline scenario 5 times for statistical confidence
python main.py --scenario baseline --iterations 5
```

### Analyze Results

```bash
# Analyze a specific run
python main.py --analyze baseline_20250101_120000

# Results are automatically analyzed after single-iteration runs
```

## Research Mode

The testbed supports two operational modes:

1. **Development Mode (Default)**: Lower request volumes (100-1,000 requests) for quick testing and debugging
2. **Research Mode**: Higher request volumes (1,000-10,000 requests) aligned with publication-quality benchmarks

### Enabling Research Mode

Use the `--research-mode` flag to enable research-scale volumes:

```bash
# Run baseline with research-scale volumes (500 requests)
python main.py --scenario baseline --research-mode

# Run all scenarios in research mode
python main.py --all --research-mode
```

### Research Mode Behavior

When `--research-mode` is enabled:
- The testbed first looks for `config/scenarios_research.yaml` (if it exists)
- If not found, applies scaling multipliers to base configuration:
  - **Baseline**: 100 → 500 requests (5x)
  - **Bursty Load**: 1,000 → 2,000-5,000 requests (2-5x)
  - **Stress/Soak**: Adds `min_requests: 5000` requirement
  - **Chaos/Edge**: 200 → 1,000 requests (5x)
  - **Steady Load**: Already supports research scale (6,300+ requests at default)

### Research-Scale Recommendations

Based on established benchmarks in serverless scheduling research:

- **Baseline**: 500 requests (establishes norms with statistical significance)
- **Steady Load**: 2,000-5,000 requests (ramp from 1-50 RPS over 5-10 minutes)
- **Bursty Load**: 2,000-5,000 requests (400-500 per burst × 5-10 repeats)
- **Stress/Soak**: 5,000-10,000+ requests (100-200 RPS until 5-10% failure rate)
- **Chaos/Edge**: 500-2,000 requests (with 10-20% fault injection)

## Configuration

### Scenario Configuration

Edit `config/scenarios.yaml` to customize scenario parameters:

```yaml
baseline:
  total_requests: 100
  services: [12, 13, 14, 16, 17, 18, 19, 20, 21, 22, 24, 25, 26]
  service_weights:
    light: 0.4
    medium: 0.4
    heavy: 0.2
  frequency:
    type: uniform
    min: 1.0
    max: 5.0
  invocations: 1
  concurrency: 5
```

### Service Configuration

Edit `config/services.yaml` to configure service metadata and selection weights.

## Scenario Details

### Baseline Scenario

**Purpose**: Establish performance norms, detect baseline bugs

**Parameters**:
- Total requests: 50-100 (configurable)
- Services: Mix of light and heavy services
- Frequency: 1-5s intervals (uniform distribution)
- Concurrency: Low (max 5 parallel)

**Usage**:
```bash
python main.py --scenario baseline
```

### Steady Load Scenario

**Purpose**: Measure throughput ceilings, expose queuing bottlenecks

**Parameters**:
- RPS levels: Ramp from 1 to 50 (configurable)
- Duration: 5-30 minutes per RPS level
- Services: Rotate 4-6 services
- Frequency: Fixed interval

**Usage**:
```bash
python main.py --scenario steady_load
```

### Bursty Load Scenario

**Purpose**: Test load balancer responsiveness, reveal thundering herd issues

**Parameters**:
- Burst size: 100-500 requests
- Burst window: 10 seconds
- Repeat: 5-10x bursts
- Frequency: Poisson distribution

**Usage**:
```bash
python main.py --scenario bursty_load
```

### Stress/Soak Scenario

**Purpose**: Uncover memory leaks, node exhaustion, scaling limits

**Parameters**:
- Target RPS: 100+ until saturation
- Max duration: 1-2 hours or until error rate >10%
- Min requests: Optional minimum requests (research-scale: 5,000)
- Services: Heavy mix (compute/I/O intensive)
- Monitoring: Periodic error rate checks

**Termination Conditions**:
- Stops when: (max_duration OR max_error_rate) AND min_requests (if specified)
- If `min_requests` is set, the scenario continues until both the minimum is met AND one of the other conditions is satisfied

**Usage**:
```bash
python main.py --scenario stress_soak
```

### Chaos/Edge Scenario

**Purpose**: Test resilience, edge case handling

**Parameters**:
- Total requests: Variable (10-50 RPS)
- Fault rate: 10-30% faulty requests
- Fault types: Invalid services, malformed inputs, negative invocations
- Frequency: Random delays (0.1-10s)

**Usage**:
```bash
python main.py --scenario chaos_edge
```

## Metrics Collection

The testbed collects comprehensive metrics:

### Per-Request Metrics
- Request ID
- Timestamp (enqueue time)
- Service ID
- Response status
- Latency
- Error type (if failed)
- Batch metadata (if available)

### Aggregate Metrics
- Total requests sent
- Success/failure counts
- Latency percentiles (p50, p95, p99)
- Throughput (RPS)
- Error rates
- Service-specific metrics
- ILP metrics (see below)

### ILP Metrics

The testbed collects ILP (Integer Linear Programming) batch processing metrics:

#### Batch-Level Metrics
- **Batch ID**: Unique identifier for each batch
- **Batch Size**: Number of requests in the batch
- **Queue Depth at Batch**: Number of queued requests when batch was formed
- **Batch Formation Time**: Timestamp when batch was created
- **ILP Solve Time**: Time taken to solve the ILP optimization (if available)
- **Batch Processing Time**: Total time from batch formation to completion
- **Requests in Batch**: List of request IDs in the batch

#### ILP Aggregate Metrics
- **Total Batches**: Number of batches processed
- **Batch Size Statistics**: Min, max, average, median, p95, standard deviation
- **ILP Solve Time Statistics**: Min, max, average, median, p95 (if available)
- **Queue Depth Statistics**: Min, max, average, median, p95
- **Batch Processing Time Statistics**: Min, max, average, median, p95
- **Batch Formation Rate**: Batches per second

### Export Formats
- **JSON**: Detailed metrics with full request details and ILP batches (`results/json/{run_id}_metrics.json`)
- **CSV**: Request-level and aggregate metrics (`results/csv/{run_id}_metrics.csv`)
- **ILP Batches CSV**: Batch-level ILP metrics (`results/csv/{run_id}_ilp_batches.csv`)

## Analysis and Reporting

### Automatic Analysis

After running a scenario, the testbed automatically:
1. Calculates aggregate metrics
2. Identifies vulnerabilities
3. Generates a vulnerability report
4. Creates visualizations

### Vulnerability Detection

The analyzer identifies:
- **Latency Degradation**: >20% increase from first to second half
- **Latency Spikes**: Requests >2x median latency
- **Throughput Instability**: High coefficient of variation (>20%)
- **Cascading Failures**: Increasing error rate over time
- **High Error Rate**: >10% error rate
- **Unfair Distribution**: Uneven service request distribution
- **ILP-Specific Vulnerabilities**:
  - **Batch Size Instability**: High variance in batch sizes (CV >30%)
  - **ILP Solve Time Degradation**: >20% increase in solve time over time
  - **Queue Depth Spikes**: Sudden increases in queue depth (>2x average)
  - **Batch Formation Delays**: Low batch formation rate (<0.1 batches/second)

### Reports

Vulnerability reports are saved to `results/reports/{run_id}_vulnerability_report.txt` and include:
- Executive summary
- Top 5 vulnerabilities with reproduction steps
- Quantitative metrics
- Recommendations

### Visualizations

Charts are saved to `results/reports/`:
- `{run_id}_latency_over_time.png` - Latency trends
- `{run_id}_throughput.png` - Throughput curves
- `{run_id}_error_rate.png` - Error rate trends
- `{run_id}_service_distribution.png` - Service distribution
- `{run_id}_batch_size_distribution.png` - Batch size histogram
- `{run_id}_ilp_solve_time.png` - ILP solve time over time (if available)
- `{run_id}_queue_depth.png` - Queue depth over time
- `{run_id}_batch_formation_rate.png` - Batch formation rate over time

## Advanced Usage

### Custom Configuration Directory

```bash
python main.py --scenario baseline --config /path/to/custom/config
```

### Custom Output Directory

```bash
python main.py --scenario baseline --output-dir /path/to/results
```

### Manual Analysis

```bash
# Analyze a specific run
python main.py --analyze baseline_20250101_120000

# Or use the analysis tools directly
python -c "from analysis.report_generator import ReportGenerator; ReportGenerator().generate_report('baseline_20250101_120000')"
```

## Service Analysis

The testbed uses `avg_job_times.json` from the project root to:
- Categorize services by runtime (light <5s, medium 5-10s, heavy >10s)
- Provide weighted service selection
- Optimize test scenarios

**Note**: Currently uses `run_time` only. Code is prepared for future inclusion of `total_time` and `pull_time` analysis (commented in `core/service_analyzer.py`).

## Architecture

```
testbed/
├── config/              # Scenario and service configurations
├── scenarios/           # Scenario implementations
├── core/                # Core components (client, generator, metrics)
├── utils/               # Utilities (distributions, config loader, logger)
├── analysis/            # Analysis tools (analyzer, report generator, visualizer)
├── results/             # Results storage (json/, csv/, reports/)
└── main.py              # Main orchestrator
```

## Troubleshooting

### Load Balancer Connection Errors

Ensure the load balancer is running:
```bash
# Check if load balancer is accessible
curl http://localhost:9001/status
```

### Missing avg_job_times.json

The testbed requires `avg_job_times.json` in the project root. Ensure it exists and contains service runtime data.

### Import Errors

Make sure you're running from the testbed directory or have the testbed directory in your Python path:
```bash
cd testbed
python main.py --scenario baseline
```

Or install in development mode:
```bash
pip install -e .
```

## Reproducible Runs

For comparing different scheduling techniques, you need reproducible request sequences:

### Using Random Seeds

```bash
# Generate and save requests with seed
python main.py --scenario baseline --seed 42 --save-requests

# Replay same requests with different scheduler
python main.py --scenario baseline --replay testbed/results/requests/baseline_20240101_120000_requests.json
```

### Workflow for Comparing Scheduling Techniques

1. **Generate baseline requests** (once):
   ```bash
   python main.py --scenario baseline --seed 42 --save-requests
   ```

2. **Run with Technique A**:
   ```bash
   # Configure scheduler for Technique A
   python main.py --scenario baseline --replay testbed/results/requests/baseline_20240101_120000_requests.json
   ```

3. **Run with Technique B** (same requests):
   ```bash
   # Configure scheduler for Technique B
   python main.py --scenario baseline --replay testbed/results/requests/baseline_20240101_120000_requests.json
   ```

4. **Compare results** from both runs in `testbed/results/`

### Seed Configuration

Seeds can be set in three ways (priority order):
1. CLI argument: `--seed 42` (highest priority)
2. Config file: `seed: 42` in `scenarios.yaml`
3. Auto-generated: Random seed if none specified

**Note**: Timing intervals are still generated randomly during replay (to test scheduler under varying load patterns). Only request payloads (service IDs, etc.) are fixed.

## Best Practices

1. **Start with Baseline**: Always run baseline scenario first to establish norms
2. **Multiple Iterations**: Run 3-5 iterations for statistical confidence
3. **Gradual Ramping**: Start with low RPS and gradually increase
4. **Monitor Resources**: Watch system resources during stress/soak tests
5. **Review Reports**: Always review vulnerability reports after runs
6. **Compare Runs**: Compare metrics across different runs to identify trends
7. **Research Mode for Publications**: Use `--research-mode` for publication-quality experiments (1k-10k requests)
8. **ILP Metrics Analysis**: Review ILP batch metrics to understand scheduler batching behavior
9. **Batch Size Tuning**: Use ILP config in scenarios.yaml to set expected batch sizes (200-500 jobs per ILP solve)
10. **Reproducible Comparisons**: Use `--seed` and `--save-requests` when comparing scheduling techniques

## Contributing

To add a new scenario:
1. Create a new class in `scenarios/` inheriting from `BaseScenario`
2. Implement the `run()` method
3. Add configuration to `config/scenarios.yaml`
4. Register in `main.py` SCENARIO_CLASSES dictionary

## License

See project root LICENSE file.



