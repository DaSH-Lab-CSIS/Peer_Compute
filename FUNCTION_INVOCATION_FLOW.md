# Function Invocation Control Flow

This document describes the complete control flow of a function invocation through the distributed serverless scheduler system.

## Overview

The system consists of three main components communicating via MQTT:
1. **Load Balancer** - Receives HTTP requests, batches them, and forwards to schedulers
2. **Scheduler** - Runs ILP optimization to assign jobs to providers
3. **Provider** - Executes Docker containers and returns results

## Request Tracking

Each request is "signed" with timestamps at different stages:
- **Load Balancer**: Adds `_lb_received_time` to request body when received
- **Scheduler**: Adds `_scheduler_received_time` when batch is received
- **Job Creation**: Stores both timestamps plus `assigned_to_provider_time` in database

These timestamps travel with the request through MQTT messages and are stored in the `Job` model for delay analysis. See `REQUEST_TRACKING_EXPLAINED.md` for detailed implementation.

## Complete Flow

```
┌─────────────┐
│   Client    │
│  (curl/API) │
└──────┬──────┘
       │ HTTP POST
       │ /loadbalancer/run_service/
       ▼
┌─────────────────────────────────┐
│      Load Balancer              │
│  (Port 9001, FastAPI)            │
│                                  │
│  1. Receive request              │
│  2. Add _lb_received_time        │
│  3. Add to batch                 │
│  4. Wait for BATCH_SIZE (10)     │
│     OR timeout (5.0s)            │
└──────┬──────────────────────────┘
       │ MQTT: BATCH_REQUEST:
       │ Topic: SCHEDULER_{name}
       │ Payload: {
       │   correlation_id,
       │   loadbalancer_id,
       │   batch_data: {requests: [...]}
       │ }
       ▼
┌─────────────────────────────────┐
│      Scheduler                  │
│  (Port 8000, Django)            │
│                                  │
│  1. Receive BATCH_REQUEST       │
│  2. Record scheduler_received_time
│  3. Extract services from batch │
│  4. Call request_handler()       │
│     └─> find_providers()        │
│         ├─> get_ready_providers()
│         ├─> build_cost_matrix()
│         ├─> build_delay_dict()
│         ├─> minimize_total_cost() [ILP]
│         └─> process_assignments()
│             ├─> Create Job objects
│             ├─> Store timestamps:
│             │   - lb_received_time
│             │   - scheduler_received_time
│             │   - assigned_to_provider_time
│             └─> publish_to_topic_mqtt()
│  5. Send BATCH_RESPONSE         │
│  6. Publish ILP_DONE            │
└──────┬──────────────────────────┘
       │ MQTT: Job assignment
       │ Topic: {provider_user_id}
       │ Payload: {
       │   job_id,
       │   task_link (docker_url),
       │   inputData,
       │   ...
       │ }
       ▼
┌─────────────────────────────────┐
│      Provider                    │
│  (Python script)                 │
│                                  │
│  1. Receive job on topic         │
│  2. Send ACK:{job_id}            │
│  3. Send NOT_READY               │
│  4. Execute Docker container    │
│  5. Calculate:                   │
│     - pull_time                  │
│     - run_time                   │
│     - total_time                 │
│  6. Send result JSON:            │
│     {stage: "dockerrun",         │
│      Result, pull_time,          │
│      run_time, total_time,       │
│      job_id}                     │
│  7. Send READY                   │
└──────┬──────────────────────────┘
       │ MQTT: Job completion
       │ Topic: {provider_user_id}
       │ Payload: JSON with stage="dockerrun"
       ▼
┌─────────────────────────────────┐
│      Scheduler                  │
│                                  │
│  1. Receive completion message  │
│  2. Call finish_job()            │
│  3. Update Job in DB:            │
│     - pull_time                  │
│     - run_time                   │
│     - total_time                 │
│     - cost                       │
│     - response                   │
│     - finished = True            │
└─────────────────────────────────┘
```

## Detailed Step-by-Step Flow

### Phase 1: Request Reception (Load Balancer)

1. **HTTP Request Arrives**
   - Client sends POST to `http://localhost:9001/loadbalancer/run_service/`
   - Request body: `{serviceID, numberOfInvocations, chained, input, runMultipleInvocations}`

2. **Timestamp Recording**
   - Load balancer adds `_lb_received_time` (UTC ISO format) to request body
   - This timestamp tracks when request first entered the system

3. **Batching**
   - Request added to `batch_state.current_batch`
   - Batch is sent when either:
     - **Batch is full**: `len(batch) >= BATCH_SIZE` (default: 10)
     - **Timeout reached**: `elapsed >= BATCH_TIMEOUT_SECONDS` (default: 5.0s)

4. **MQTT Publishing**
   - Load balancer sets `ilp_state = "progress"` (prevents new batches)
   - Generates `correlation_id` for request/response matching
   - Publishes to scheduler topic: `SCHEDULER_{name}`
   - Message format: `"BATCH_REQUEST:" + json.dumps({correlation_id, loadbalancer_id, batch_data})`
   - Waits for `BATCH_RESPONSE` with matching `correlation_id`

### Phase 2: Scheduler Processing

1. **Batch Reception**
   - Scheduler's `on_message()` receives `BATCH_REQUEST:` on its topic
   - Extracts `batch_data['requests']` array
   - Records `scheduler_received_time` (when batch arrived at scheduler)

2. **Service Validation**
   - For each request in batch:
     - Extract `serviceID`
     - Validate service exists and is active
     - Add `_scheduler_received_time` to request data
     - Build `services[]` and `requests_data[]` arrays

3. **ILP Processing** (`request_handler()` → `find_providers()`)
   
   a. **Get Ready Providers**
      - `get_ready_providers()`: Queries database for providers with:
        - `is_provider = True`
        - `ready = True`
        - `active = True`
      - Locks providers using `select_for_update()` to prevent concurrent assignment
   
   b. **Build Cost Matrix**
      - `build_cost_matrix()`: For each provider-service pair:
        - Gets predicted runtime (from ML models or historical data)
        - Considers provider efficiency scores
        - Returns matrix: `{provider: {service: predicted_runtime}}`
   
   c. **Build Delay Dictionary**
      - `build_delay_dict()`: Calculates current delay for each provider
      - Delay = sum of predicted runtimes for in-flight jobs
      - Accounts for provider's current workload
   
   d. **ILP Optimization** (`minimize_total_cost()`)
      - Uses PuLP (Integer Linear Programming) solver
      - Objective: Minimize total cost (runtime + delay)
      - Constraints:
        - Each service assigned to exactly one provider
        - Provider capacity limits
        - Provider-service compatibility
      - Returns: `assignment = {(index, service): provider}`
   
   e. **Process Assignments** (`process_assignments()`)
      - For each assignment:
        - Creates `Job` object in database:
          - Status: `CREATED`
          - Stores timestamps:
            - `lb_received_time` (from request data)
            - `scheduler_received_time` (from request data)
            - `assigned_to_provider_time` (current time)
        - Updates provider state:
          - Adds predicted runtime to `provider.delay`
          - Increments `function_invocations[service_id]`
        - Sends job to provider via MQTT:
          - Topic: `{provider.user_id}`
          - Payload: `{job_id, task_link, inputData, ...}`

4. **Response to Load Balancer**
   - Publishes `BATCH_RESPONSE:` to load balancer's topic
   - Includes `correlation_id`, `status`, `results`
   - Publishes `ILP_DONE` to `ROTATION` topic
   - Load balancer sets `ilp_state = "done"` (allows new batches)

### Phase 3: Provider Execution

1. **Job Reception**
   - Provider's `on_message()` receives job on its topic (`{user_id}`)
   - Extracts job data: `job_id`, `task_link` (Docker image), `inputData`

2. **Acknowledgment**
   - Publishes `ACK:{job_id}` to scheduler (on provider's topic)
   - Scheduler updates `Job.ack_time` in database
   - Publishes `NOT_READY` to mark provider as busy

3. **Container Execution** (`on_request()` → `run_and_invoke_docker()`)
   - Pulls Docker image (if not cached)
   - Measures `pull_time` (milliseconds)
   - Runs container with input data
   - Measures `run_time` (milliseconds)
   - Calculates `total_time = ceil((pull_time + run_time) / 100.0) * 100`
   - Cleans up container and image

4. **Result Transmission**
   - Publishes result JSON to scheduler (on provider's topic):
     ```json
     {
       "stage": "dockerrun",
       "Result": {...},
       "pull_time": 1234,
       "run_time": 5678,
       "total_time": 6900,
       "job_id": 123
     }
     ```
   - Publishes `READY` to mark provider as available again

### Phase 4: Job Completion (Scheduler)

1. **Completion Reception**
   - Scheduler's `on_message()` receives JSON with `stage: "dockerrun"`
   - Calls `finish_job(data)`

2. **Database Update** (`finish_job()`)
   - Loads `Job` object by `job_id`
   - Updates fields:
     - `pull_time` = from result
     - `run_time` = from result
     - `total_time` = from result
     - `cost` = `total_time`
     - `response` = JSON string of result
     - `finished` = `True`
   - Saves to database

## MQTT Topics

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `SCHEDULER_{name}` | LB → Scheduler | Batch requests from load balancer |
| `{loadbalancer_id}` | Scheduler → LB | Batch responses to load balancer |
| `{user_id}` | Scheduler ↔ Provider | Job assignments and results |
| `ROTATION` | Scheduler → All | ILP coordination (`ILP_DONE` signal) |
| `EVERYONE` | All | Broadcast messages, heartbeats |
| `SCHEDULER_ANNOUNCEMENTS` | Scheduler → LB | Scheduler discovery |

## MQTT Message Patterns

| Pattern | From | To | Purpose |
|---------|------|-----|---------|
| `BATCH_REQUEST:{json}` | Load Balancer | Scheduler | Send batch of requests |
| `BATCH_RESPONSE:{json}` | Scheduler | Load Balancer | Acknowledge batch processing |
| `ACK:{job_id}` | Provider | Scheduler | Job acknowledgment |
| `READY` | Provider | Scheduler | Provider available |
| `NOT_READY` | Provider | Scheduler | Provider busy |
| `ILP_DONE` | Scheduler | All | ILP processing complete |
| `SCHEDULER_PONG:{json}` | Scheduler | Load Balancer | Heartbeat |

## Database Models

### Job Model
- `id` - Primary key
- `provider` - ForeignKey to User (provider)
- `service` - ForeignKey to Services
- `developer` - ForeignKey to User (developer)
- `start_time` - When job was created
- `ack_time` - When provider acknowledged job
- `lb_received_time` - When request arrived at load balancer
- `scheduler_received_time` - When batch arrived at scheduler
- `assigned_to_provider_time` - When job was assigned to provider
- `pull_time` - Docker image pull time (ms)
- `run_time` - Container execution time (ms)
- `total_time` - Total time (ms)
- `cost` - Cost calculation
- `finished` - Boolean completion flag
- `response` - Job result (JSON string)

### User Model (Provider)
- `user_id` - UUID identifier
- `is_provider` - Boolean flag
- `ready` - Availability status
- `active` - Active status
- `delay` - JSON field tracking in-flight jobs
- `function_invocations` - JSON field tracking invocation counts per service

## Timing Flow

```
Request Timeline:
─────────────────────────────────────────────────────────────
t0: Request received at Load Balancer
    └─> lb_received_time recorded
    
t1: Batch sent to Scheduler (after batching delay)
    └─> scheduler_received_time recorded
    
t2: ILP runs, job assigned to Provider
    └─> assigned_to_provider_time recorded
    
t3: Provider acknowledges job
    └─> ack_time recorded
    
t4: Provider completes execution
    └─> pull_time, run_time, total_time recorded
    └─> finished = True
```

## Key Delays Measured

1. **LB to Scheduler Delay**: `scheduler_received_time - lb_received_time`
   - Includes batching wait time at load balancer
   - MQTT transmission time

2. **Scheduler Processing Delay**: `assigned_to_provider_time - scheduler_received_time`
   - ILP optimization time
   - Database operations
   - Provider selection

3. **Provider Assignment Delay**: `assigned_to_provider_time - scheduler_received_time`
   - Time from batch arrival to job assignment

4. **Total System Delay**: `assigned_to_provider_time - lb_received_time`
   - End-to-end delay from request to assignment

## Outcome Tracking for Experiments

When running experiments via `ansible_utils/playbooks/experiment.yml`, request acceptance and
provider completion are now tracked as a two-step process:

1. **Per-request to job linkage** (already present)
   - Testbed records `request_id -> job_id` in `testbed/results/json/<run_id>_job_ids.jsonl`
   - This linkage is created from load balancer HTTP responses

2. **Post-run job enrichment** (new)
   - Testbed calls scheduler endpoint `POST /providers/direct_invocation_status/` in chunks
   - Joins scheduler-side fields (`finished`, `run_time`, timestamps, provider id) back to each request
   - Writes:
     - `testbed/results/csv/<run_id>_jobs_enriched.csv`
     - `testbed/results/json/<run_id>_jobs_enriched.json`
   - Adds `outcome_breakdown` into `<run_id>_metrics.json`

### Outcome Classification Rule

For experiment reporting, outcomes are classified as:

- `success`: `finished=True` and `run_time > 0`
- `error`: `finished=True` and `run_time == 0` (non-timeout)
- `timeout`: scheduler timeout sweep sentinel in `response`
- `pending`: `finished=False`

### Stale Job Sweep

To prevent experiment drain from hanging indefinitely when providers crash, scheduler exposes:

- `POST /providers/timeout_stale_jobs/`

This endpoint marks stale dispatched jobs as `finished=True` with a timeout sentinel response:

```json
{
  "sweep": "timeout",
  "kind": "no_ack | no_result",
  "swept_at": "..."
}
```

Ansible runs this sweep after the normal pending-job drain wait, then performs a final pending check.

## Error Handling

- **No Providers Available**: `find_providers()` returns `None`, error returned to load balancer
- **Scheduler Timeout**: Load balancer waits 10s for response, then retries with different scheduler
- **Provider Failure**: Job remains in `CREATED` status, recovery process handles retry
- **Container Execution Failure**: Provider sends error in result, job marked as finished with error

## State Management

- **ILP State**: Load balancer tracks `ilp_state` (`"done"` or `"progress"`) to prevent concurrent batch processing
- **Provider State**: Tracked via `ready` flag and `delay` field in database
- **Job State**: Implicit via `finished` flag (not explicitly using status enum)

## Concurrency

- **Load Balancer**: Async FastAPI, handles multiple concurrent HTTP requests
- **Scheduler**: Django with database transactions, processes one batch at a time per scheduler
- **Provider**: Single-threaded Python script, processes one job at a time
- **Database**: Uses `select_for_update()` to lock providers during assignment

