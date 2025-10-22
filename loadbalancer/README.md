# Load Balancer with Batching

A lightweight load balancer for Django scheduler servers with request batching capabilities.

## Features

- Batches N requests together before forwarding to a scheduler
- Uses round-robin load balancing to distribute batches among schedulers
- Includes timeout mechanism (K seconds) to process partial batches
- Automatically checks scheduler availability
- Skips unavailable schedulers
- Logs scheduler status changes to stdout

## Configuration

Configuration is done via the `LB.conf` file:

```
BATCH_SIZE=10
BATCH_TIMEOUT_SECONDS=5.0
SCHEDULER_URLS=["http://10.8.1.18:8000/developers/run_service_async_batch","http://scheduler2:8000/api/process","http://scheduler3:8000/api/process"]
```

Notes:
- The load balancer runs on port 9001, while the Django scheduler servers run on port 8000
- Make sure the JSON format for SCHEDULER_URLS is valid (no trailing commas, proper quoting)
- If no valid configuration is found, the load balancer will use default settings

## Installation

1. Create a virtual environment and install dependencies:

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
# .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

Required packages:
```bash
pip install fastapi uvicorn httpx pydantic
```

2. Start the load balancer:

```bash
# Make sure virtual environment is activated
source .venv/bin/activate  # On macOS/Linux
# .venv\Scripts\activate  # On Windows

# Start the server
uvicorn loadbalancer:app --host 0.0.0.0 --port 9001 --reload
```

This will start the load balancer on port 9001, accessible at http://localhost:9001.

## API Endpoints

- `POST /submit`: Submit a request to be batched and forwarded to a scheduler
- `POST /loadbalancer/run_service/`: Submit a service request to be batched (compatible with the provided sample curl)
- `GET /status`: Get current load balancer status and configuration

## How it Works

1. Clients send individual requests to the load balancer at `/submit` or `/loadbalancer/run_service/` endpoints (port 9001)
2. Requests are collected into batches until either:
   - The batch reaches the configured size (`BATCH_SIZE` in LB.conf)
   - The batch timeout is reached (`BATCH_TIMEOUT_SECONDS` in LB.conf)
3. Before sending a batch, the load balancer checks if each scheduler is available
4. If a scheduler is unavailable, the batch is sent to the next available scheduler
5. The batch is sent to the Django scheduler servers in the format `{"requests": [request1, request2, ...]}`
6. If no schedulers are available, the batch is kept in memory and will be retried later

## Example Usage

### Basic Request

```bash
# Submit a standard request
curl -X POST "http://localhost:9001/submit" \
  -H "Content-Type: application/json" \
  -d '{"task_id": "123", "data": {"param1": "value1"}}'
```

Response:
```json
{"status": "request queued for processing"}
```

### Service Request (Sample Format)

```bash
# Submit a service request using the sample format
curl -X POST "http://localhost:9001/loadbalancer/run_service/" \
  -H "Accept: */*" \
  -H "User-Agent: Thunder Client (https://www.thunderclient.com)" \
  -H "Content-Type: application/json" \
  -d '{
    "serviceID": 17,
    "numberOfInvocations": 1,
    "chained": false,
    "input": "None",
    "runMultipleInvocations": false
  }'
```

Response:
```json
{"status": "request queued for processing"}
```

### Check Status

```bash
# Check current load balancer status
curl -X GET "http://localhost:9001/status"
```

Response:
```json
{
  "current_batch_size": 1,
  "batch_age_seconds": 2.5,
  "scheduler_health": {
    "http://10.8.1.18:8000/developers/run_service_async_batch": true,
    "http://scheduler2:8000/api/process": false,
    "http://scheduler3:8000/api/process": false
  },
  "current_scheduler_index": 0,
  "config": {
    "batch_size": 10,
    "batch_timeout": 5.0,
    "scheduler_count": 3
  }
}
```

## Batch Format

When the load balancer sends a batch to a scheduler, it uses the following format:

```json
{
  "requests": [
    {
      "serviceID": 12,
      "numberOfInvocations": 1, 
      "chained": false,
      "input": "None",
      "runMultipleInvocations": false
    },
    {
      "serviceID": 12,
      "numberOfInvocations": 1,
      "chained": false,
      "input": "None", 
      "runMultipleInvocations": false
    }
    // Additional requests in the batch...
  ]
}
```

## Troubleshooting

- **Error parsing SCHEDULER_URLS**: Check the JSON format in your LB.conf file. It should be a valid JSON array.
- **Connection check failed**: Your scheduler servers are not reachable. Verify they are running.
- **No active schedulers available**: None of the configured schedulers are responding. The batch will be kept in memory.
- **ModuleNotFoundError**: Make sure you've installed all the required packages: `pip install fastapi uvicorn httpx pydantic` 

## Experiment Logging

The load balancer supports an optional experiment logging mode. To enable logging:

1. In the scheduler's `settings.py`, set:
   ```python
   EXPERIMENT_MODE = True
   EXPERIMENT_STDOUT_LOGGING = True
   ```

2. Alternatively, set the environment variable:
   ```bash
   export EXPERIMENT_MODE=true
   ```

When enabled, logs will be saved in the `experiment_logs` directory with detailed timestamps and stream information. 