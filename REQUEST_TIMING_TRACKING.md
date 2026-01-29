# Request Timing Tracking Implementation

## Overview

This implementation adds timestamp tracking to measure delays between different stages of request processing:
1. **Load Balancer Received** - When request arrives at load balancer
2. **Scheduler Received** - When batch is received at scheduler
3. **Assigned to Provider** - When job is assigned to a provider

## Changes Made

### 1. Database Schema (Job Model)

Added three new timestamp fields to `scheduler/providers/models.py`:
- `lb_received_time` - DateTimeField (nullable) - Timestamp when request was received at load balancer
- `scheduler_received_time` - DateTimeField (nullable) - Timestamp when request was received at scheduler  
- `assigned_to_provider_time` - DateTimeField (nullable) - Timestamp when job was assigned to provider

**Migration**: `scheduler/providers/migrations/0007_add_request_timing_fields.py`

### 2. Load Balancer Changes

**File**: `loadbalancer/loadbalancer_with_logging.py`

- Modified `/loadbalancer/run_service/` endpoint to add `_lb_received_time` timestamp to each request
- Modified `/submit` endpoint to add `_lb_received_time` timestamp to each request
- Timestamps are in ISO format with UTC timezone for consistency across distributed system

### 3. Scheduler Changes

**File**: `scheduler/providers/views.py`

#### BATCH_REQUEST Handler
- Records `scheduler_received_time` when batch is received
- Adds `_scheduler_received_time` to each request in the batch
- Preserves `_lb_received_time` from load balancer

#### request_handler Function
- Creates `request_data_map` mapping service.id -> request data (includes timestamps)
- Passes `request_data_map` to `find_providers()`

#### find_providers Function
- Accepts `request_data_map` parameter
- Passes it to `process_assignments()`

#### process_assignments Function
- Accepts `request_data_map` parameter
- Extracts timestamps from request data when creating Job
- Records `assigned_to_provider_time` when job is assigned
- Stores all three timestamps in Job model

## Data Flow

```
1. HTTP Request → Load Balancer
   └─> Adds _lb_received_time to request body

2. Load Balancer → Scheduler (MQTT BATCH_REQUEST)
   └─> Request includes _lb_received_time

3. Scheduler receives BATCH_REQUEST
   └─> Records scheduler_received_time
   └─> Adds _scheduler_received_time to each request

4. Scheduler processes batch
   └─> Creates request_data_map (service.id -> request data with timestamps)
   └─> Passes through find_providers() → process_assignments()

5. process_assignments creates Job
   └─> Extracts lb_received_time from request_data_map
   └─> Extracts scheduler_received_time from request_data_map
   └─> Records assigned_to_provider_time (current time)
   └─> Stores all three in Job model

6. Job saved to database with all timestamps
```

## Usage

After running migrations, the Job model will have these fields available:

```python
job = Job.objects.get(id=job_id)

# Calculate delays
lb_to_scheduler_delay = (job.scheduler_received_time - job.lb_received_time).total_seconds()
scheduler_to_provider_delay = (job.assigned_to_provider_time - job.scheduler_received_time).total_seconds()
total_delay = (job.assigned_to_provider_time - job.lb_received_time).total_seconds()
```

## Migration Instructions

1. Run the migration:
```bash
cd scheduler
python manage.py migrate providers
```

2. Restart scheduler and load balancer to apply changes

## Notes

- Timestamps use UTC timezone for consistency across distributed components
- Timestamps are stored as DateTimeField in the database
- If timestamps are missing (e.g., for old requests), fields will be NULL
- The `_lb_received_time` and `_scheduler_received_time` are prefixed with `_` in the request data to indicate they are metadata, not part of the original request

## Querying Delays

Example queries to analyze delays:

```python
from django.db.models import F, ExpressionWrapper, FloatField
from datetime import timedelta

# Jobs with all timing data
jobs_with_timing = Job.objects.filter(
    lb_received_time__isnull=False,
    scheduler_received_time__isnull=False,
    assigned_to_provider_time__isnull=False
)

# Calculate average delay from LB to Scheduler
from django.db.models import Avg
avg_lb_to_scheduler = jobs_with_timing.annotate(
    delay=ExpressionWrapper(
        F('scheduler_received_time') - F('lb_received_time'),
        output_field=FloatField()
    )
).aggregate(Avg('delay'))['delay__avg']
```


