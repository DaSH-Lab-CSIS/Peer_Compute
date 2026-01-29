# Request Signing and Tracking Implementation

## Overview

Each request is "signed" with timestamps at different stages of processing. These timestamps are embedded in the request payload and persist through the entire flow until they're stored in the database.

## How It Works

### Step 1: Load Balancer - Initial Signing

When a request arrives at the load balancer, it's immediately "signed" with a timestamp:

**Location**: `loadbalancer/loadbalancer_with_logging.py`

```python
@app.post("/loadbalancer/run_service/")
async def run_service(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    
    # SIGN THE REQUEST: Add timestamp when received
    body['_lb_received_time'] = datetime.now(pytz.UTC).isoformat()
    
    # Add to batch (timestamp travels with the request)
    batch_state.current_batch.append(body)
```

**What happens:**
- Original request: `{serviceID: 13, numberOfInvocations: 1, ...}`
- After signing: `{serviceID: 13, numberOfInvocations: 1, ..., _lb_received_time: "2025-01-15T10:30:45.123456+00:00"}`

The `_lb_received_time` field is added to the request body and travels with it through the entire system.

### Step 2: MQTT Transmission

The signed request is included in the batch sent to the scheduler:

```python
mqtt_payload = {
    'correlation_id': correlation_id,
    'loadbalancer_id': lb_id,
    'batch_data': {
        'requests': [
            {
                'serviceID': 13,
                'numberOfInvocations': 1,
                '_lb_received_time': "2025-01-15T10:30:45.123456+00:00"  # ← Timestamp travels here
            },
            # ... more requests
        ]
    }
}
```

### Step 3: Scheduler - Additional Signing

When the scheduler receives the batch, it adds its own timestamp:

**Location**: `scheduler/providers/views.py` (BATCH_REQUEST handler)

```python
elif payload_str.startswith("BATCH_REQUEST:"):
    # Record when scheduler received the batch
    scheduler_received_time = datetime.now(tz=timezone(TIME_ZONE))
    scheduler_received_time_iso = scheduler_received_time.isoformat()
    
    for req_data in batch_data['requests']:
        # ADD SECOND TIMESTAMP: Preserve lb_received_time, add scheduler timestamp
        req_data['_scheduler_received_time'] = scheduler_received_time_iso
        # lb_received_time is already in req_data from load balancer
        
        services.append(service)
        requests_data.append(req_data)  # ← Both timestamps now in request
```

**What happens:**
- Request now has: `{serviceID: 13, ..., _lb_received_time: "...", _scheduler_received_time: "..."}`

### Step 4: Timestamp Propagation Through Call Chain

The timestamps are passed through the scheduler's processing pipeline:

```python
# In request_handler()
request_data_map = {}  # Maps service.id -> request data (with timestamps)
for svc, req_data in zip(services, data_items):
    request_data_map[svc.id] = req_data  # ← Contains both timestamps

# Pass to find_providers
assignment = find_providers(services, request_data_map=request_data_map)

# Which passes to process_assignments
process_assignments(assignment, cost_matrix, request_data_map)
```

### Step 5: Database Storage

When creating the Job object, timestamps are extracted and stored:

**Location**: `scheduler/providers/views.py` (process_assignments)

```python
def process_assignments(assignment, cost_matrix, request_data_map=None):
    assigned_time = datetime.now(tz=timezone(TIME_ZONE))  # Third timestamp
    
    for key, provider in assignment.items():
        service = # ... extract service
        
        # EXTRACT TIMESTAMPS from request data
        lb_received_time = None
        scheduler_received_time = None
        
        if request_data_map and service.id in request_data_map:
            req_data = request_data_map[service.id]
            
            # Parse _lb_received_time
            if '_lb_received_time' in req_data:
                time_str = req_data['_lb_received_time'].replace('Z', '+00:00')
                lb_received_time = datetime.fromisoformat(time_str)
                lb_received_time = lb_received_time.astimezone(timezone(TIME_ZONE))
            
            # Parse _scheduler_received_time
            if '_scheduler_received_time' in req_data:
                time_str = req_data['_scheduler_received_time'].replace('Z', '+00:00')
                scheduler_received_time = datetime.fromisoformat(time_str)
                scheduler_received_time = scheduler_received_time.astimezone(timezone(TIME_ZONE))
        
        # STORE ALL TIMESTAMPS in Job
        job = Job.objects.create(
            provider=provider,
            service=service,
            developer=service.developer,
            finished=False,
            lb_received_time=lb_received_time,              # ← From load balancer
            scheduler_received_time=scheduler_received_time, # ← From scheduler
            assigned_to_provider_time=assigned_time          # ← Current time
        )
```

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 1. HTTP Request Arrives at Load Balancer                    │
│    Original: {serviceID: 13, ...}                           │
│    ↓                                                         │
│    SIGNED: {serviceID: 13, ..., _lb_received_time: "..."}  │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ MQTT BATCH_REQUEST
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Scheduler Receives Batch                                  │
│    Request: {serviceID: 13, ..., _lb_received_time: "..."} │
│    ↓                                                         │
│    SIGNED AGAIN: {serviceID: 13, ...,                        │
│                   _lb_received_time: "...",                  │
│                   _scheduler_received_time: "..."}            │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ Passed through request_data_map
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. process_assignments()                                     │
│    Extracts timestamps from request_data_map[service.id]    │
│    ↓                                                         │
│    Creates Job with:                                         │
│    - lb_received_time (from _lb_received_time)              │
│    - scheduler_received_time (from _scheduler_received_time) │
│    - assigned_to_provider_time (current time)               │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ Saved to Database
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Job Object in Database                                    │
│    job.lb_received_time = datetime(...)                     │
│    job.scheduler_received_time = datetime(...)              │
│    job.assigned_to_provider_time = datetime(...)             │
└─────────────────────────────────────────────────────────────┘
```

## Key Points

1. **Request Signing**: Timestamps are added as metadata fields (`_lb_received_time`, `_scheduler_received_time`) in the request payload
2. **Persistence**: Timestamps travel with the request through MQTT messages and function calls
3. **Storage**: Timestamps are extracted and stored in the Job model when the job is created
4. **Tracking**: Each request can be traced from load balancer → scheduler → provider assignment

## Querying Tracked Requests

Once stored in the database, you can query and analyze delays:

```python
from scheduler.providers.models import Job

# Get a job with all timing data
job = Job.objects.get(id=job_id)

# Calculate delays
lb_to_scheduler_delay = (job.scheduler_received_time - job.lb_received_time).total_seconds()
scheduler_to_provider_delay = (job.assigned_to_provider_time - job.scheduler_received_time).total_seconds()
total_delay = (job.assigned_to_provider_time - job.lb_received_time).total_seconds()

print(f"LB → Scheduler: {lb_to_scheduler_delay:.3f}s")
print(f"Scheduler → Provider: {scheduler_to_provider_delay:.3f}s")
print(f"Total: {total_delay:.3f}s")
```

## Why This Approach?

1. **No Separate Tracking System**: Timestamps are embedded in the request itself
2. **Automatic Propagation**: Timestamps travel with the request through all components
3. **Database Persistence**: Final timestamps are stored in Job model for analysis
4. **Distributed-Friendly**: Works across separate machines via MQTT
5. **Backward Compatible**: Old requests without timestamps will have NULL values

## Migration Required

Before using this feature, run the migration:

```bash
cd scheduler
python manage.py migrate providers
```

This adds the three timestamp fields to the Job model.

