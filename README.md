## Experiment Logging

Experiment logs are now organized in a timestamp-based directory structure:

```
experiment_logs/
└── YYYY-MM-DD_HH-MM-SS/
    ├── scheduler_stdout.log
    ├── loadbalancer_stdout.log
    ├── provider_<provider_id>_stdout.log
    └── ...
```

Each experiment creates a unique timestamped directory to:
- Prevent log file overwriting
- Easily track experiment sessions
- Maintain consistent naming across components 

## Randomized Testbed Algorithm Comparison

The system now supports fair algorithm comparison using randomized but reproducible testbeds:

### Quick Start

1. **Start required services:**
```bash
# Terminal 1: Start Django scheduler
cd scheduler
python manage.py runserver 0.0.0.0:8000

# Terminal 2: Start Load Balancer
cd loadbalancer
python loadbalancer_with_logging.py

# Terminal 3: Start a provider
python provider/provider1.py <provider_id>
```

2. **Run complete experiment:**
```bash
# This will generate a testbed, run all algorithms, and analyze results
python run_randomized_experiment.py
```

### Manual Steps

1. **Generate a testbed:**
```bash
python randomized_testbed.py
```

2. **Run algorithms against the same testbed:**
```bash
python testbed_runner.py testbed_2024-01-15_14-30-45_seed12345.json
```

3. **Analyze results:**
```bash
python analyze_experiment_logs.py --logs-dir experiment_logs/2024-01-15_14-30-45 --console
```

### Algorithm-Specific Logging

Logs are now organized by algorithm and timestamp:

```
experiment_logs/
└── 2024-01-15_14-30-45/
    ├── experiment_summary.json
    ├── ILP/
    │   ├── scheduler_stdout.log
    │   ├── loadbalancer_stdout.log
    │   └── provider_<id>_stdout.log
    ├── MRU/
    │   └── ... (same structure)
    ├── ROUND_ROBIN/
    │   └── ...
    └── BELADY/
        └── ...
```

This ensures fair comparison by running the exact same workload against each algorithm while maintaining separate logs for detailed analysis. 