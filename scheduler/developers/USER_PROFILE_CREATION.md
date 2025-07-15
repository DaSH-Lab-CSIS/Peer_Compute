# User Profile Creation Guide

This document explains how to create new user profiles in the Serverless Scheduler system. Users can be **Providers** (who offer computing resources), **Developers** (who create and run services), or both.

## Table of Contents

- [User Types](#user-types)
- [User Model Fields](#user-model-fields)
- [Creating User Profiles](#creating-user-profiles)
- [API Endpoints](#api-endpoints)
- [Examples](#examples)
- [Default Services](#default-services)
- [Troubleshooting](#troubleshooting)

## User Types

### Provider

- Offers computing resources (CPU, RAM) to run services
- Can cache Docker images for faster execution
- Receives reputation scores based on performance
- Must have `is_provider=True`

### Developer

- Creates and manages services
- Can invoke services on providers
- Gets a default service created automatically
- Must have `is_developer=True`

### Hybrid User

- Can be both provider and developer
- Set both `is_provider=True` and `is_developer=True`

## User Model Fields

### Required Fields

- `is_provider` (boolean): Whether user offers computing resources
- `is_developer` (boolean): Whether user creates/manages services
- `active` (boolean): Whether user is currently active in the system
- `ready` (boolean): Whether user is ready to accept jobs (mainly for providers)
- `location` (string): Geographic location (max 30 characters)
- `ram` (integer): Available RAM in MB
- `cpu` (integer): Number of CPU cores available

### Auto-Generated Fields

- `user_id` (UUID): Unique identifier, automatically generated
- `last_ready_signal` (datetime): Last time user signaled readiness

### Provider-Only Fields

- `cpu_efficiency_score` (decimal): Performance metric for CPU usage
- `memory_efficiency_score` (decimal): Performance metric for memory usage
- `function_invocations` (JSON): Track of service invocations `{service_id: count}`
- `cached_images` (JSON): Information about cached Docker images
- `disk_cache_usage` (integer): Total disk cache usage in bytes
- `reputation_score` (integer): Provider reputation based on performance
- `delay` (JSON): Job scheduling and delay information

## Creating User Profiles

### Using the API Endpoint

**Endpoint:** `POST /profiles/register_user/`

**Content-Type:** `application/json`

### Request Body Structure

```json
{
    "is_provider": boolean,
    "is_developer": boolean,
    "active": boolean,
    "ready": boolean,
    "location": "string",
    "ram": integer,
    "cpu": integer
}
```

## API Endpoints

### Register User

- **URL:** `/profiles/register_user/`
- **Method:** `POST`
- **Description:** Creates a new user profile
- **Authentication:** None required (CSRF exempt)

### Developer Endpoints

- **Create Service:** `POST /developers/new_service/`
- **Run Service:** `POST /developers/run_service/<service_id>`
- **Run Service Async:** `POST /developers/run_service_async/<service_id>`
- **Batch Service:** `POST /developers/run_service_async_batch/`

## Examples

### Example 1: Create a Provider User

```bash
curl -X POST http://localhost:8000/profiles/register_user/ \
  -H "Content-Type: application/json" \
  -d '{
    "is_provider": true,
    "is_developer": false,
    "active": true,
    "ready": true,
    "location": ".18",
    "ram": 8,
    "cpu": 4
  }'
```

**Response:**

```json
{
    "message": "User added successfully",
    "user_id": "b6345085-aecb-4260-b3f1-7fdcef6705e0"
}
```

### Example 2: Create a Developer User

```bash
curl -X POST http://localhost:8000/profiles/register_user/ \
  -H "Content-Type: application/json" \
  -d '{
    "is_provider": false,
    "is_developer": true,
    "active": true,
    "ready": false,
    "location": "us-west-2",
    "ram": 4096,
    "cpu": 2
  }'
```

**Response:**

```json
{
    "message": "User added successfully",
    "user_id": "a1234567-bcde-4890-f123-456789abcdef"
}
```

### Example 3: Create a Hybrid User (Provider + Developer)

```bash
curl -X POST http://localhost:8000/profiles/register_user/ \
  -H "Content-Type: application/json" \
  -d '{
    "is_provider": true,
    "is_developer": true,
    "active": true,
    "ready": true,
    "location": "eu-central-1",
    "ram": 16384,
    "cpu": 8
  }'
```

### Example 4: Create a Service (for Developers)

```bash
curl -X POST http://localhost:8000/developers/new_service/ \
  -H "Content-Type: application/json" \
  -d '{
    "developer": 11,
    "name": "image-processor",
    "docker_url": "https://hub.docker.com/r/myuser/image-processor:latest",
    "is_active": true
  }'
```

## Default Services

When a developer user is created, a default service is automatically added through the `add_default_service()` function. This ensures that new developers have a basic service to start with.

## Field Validation and Constraints

### Provider-Only Field Constraints

The system enforces that certain fields are only populated for provider users:

- `function_invocations`: Only providers can have this field populated
- `delay`: Only providers can have delay information
- `cached_images`: Only providers can cache images

### Unique Constraints

- Each `user_id` is unique across the system
- Service names must be unique per developer

## Resource Specifications

### RAM Values 

- Specify in GB (Gigabytes)
- Common values: 8, 16

### CPU Values

- Specify as number of cores
- Common values: 1, 2, 4, 8, 16

### Location Format

- Use cloud region format (e.g., "us-east-1", "eu-west-1")
- Or geographic locations (e.g., "new-york", "london")
- Maximum 30 characters

## Integration with Fabric (Blockchain)

If `USE_FABRIC` is enabled in settings, the system will:

1. Create a monetary account for the user with 700 initial credits
2. Handle JWT token management for blockchain operations
3. Automatically retry with new tokens if needed

## Troubleshooting

### Common Issues

1. **"Invalid request method"**

   - Ensure you're using POST method
   - Check that Content-Type is application/json
2. **User creation fails silently**

   - Check that all required fields are provided
   - Verify boolean values are actual booleans, not strings
3. **Service creation fails**

   - Ensure the developer user exists
   - Check that service name is unique for that developer
   - Verify docker_url is a valid URL
4. **Provider constraints violated**

   - Don't set provider-only fields for non-provider users
   - Ensure is_provider=true if setting function_invocations, delay, or cached_images

### Debugging Tips

1. Check Django logs for detailed error messages
2. Verify database constraints are met
3. Ensure JSON fields are properly formatted
4. Test with minimal required fields first, then add optional ones

## Additional Notes

- User profiles are automatically activated when created
- Providers should set `ready=true` to accept jobs
- Developers get default services created automatically
- The system supports both synchronous and asynchronous service execution
- Batch processing is available for multiple service invocations
