import asyncio
import time
import json
import os
from typing import List, Dict, Any, Optional
import httpx
from fastapi import FastAPI, Request, BackgroundTasks
from pydantic import BaseModel
import paho.mqtt.client as mqtt
from contextlib import asynccontextmanager

# Configuration
class Config:
    def __init__(self):
        self.BATCH_SIZE = 10
        self.BATCH_TIMEOUT_SECONDS = 5.0
        #NOTE Not for permanent use.
        self.SCHEDULER_URLS = [
            "http://10.8.1.18:8000/developers/run_service_async_batch/", #default for empty config file
        ]
        
        # Load from config file if it exists
        self.load_from_file("LB.conf")
    
    def load_from_file(self, config_file):
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        if key == 'BATCH_SIZE':
                            self.BATCH_SIZE = int(value)
                        elif key == 'BATCH_TIMEOUT_SECONDS':
                            self.BATCH_TIMEOUT_SECONDS = float(value)
                        elif key == 'SCHEDULER_URLS':
                            try:
                                self.SCHEDULER_URLS = json.loads(value)
                                print(f"SCHEDULER_URLS: {self.SCHEDULER_URLS}")
                            except json.JSONDecodeError:
                                print(f"Error parsing SCHEDULER_URLS: {value}")

# Global settings
settings = Config()

# Global variable to track ILP state - initially "done" to allow first batch to be sent
ilp_state = "done"

# Batch state
class BatchState:
    def __init__(self):
        self.current_batch: List[Dict[str, Any]] = []
        self.last_batch_time = time.time()
        self.current_scheduler_index = 0
        self.scheduler_health: Dict[str, bool] = {url: True for url in settings.SCHEDULER_URLS}  # All schedulers start as healthy
        self.lock = asyncio.Lock()

batch_state = BatchState()

# MQTT Configuration
BROKER_ID = "broker.hivemq.com"
# Add any other MQTT-related constants here

# MQTT Client callbacks
def on_connect(mqtt_client, userdata, flags, rc, callback_api_version):
    if rc == 0:
        print('Connected successfully to MQTT broker')
        mqtt_client.subscribe("EVERYONE")  # Add your topics here
        mqtt_client.subscribe("ROTATION")  # Subscribe to ROTATION topic
    else:
        print('Bad connection to MQTT broker. Code:', rc)

def on_message(mqtt_client, userdata, msg):
    print(f'Received message on topic: {msg.topic} with payload: {msg.payload}')
    global ilp_state
    
    # Check for ILP_DONE message
    payload_str = msg.payload.decode("utf-8")
    if payload_str == "ILP_DONE":
        print("Received ILP_DONE signal, setting ilp_state to 'done'")
        ilp_state = "done"
        return
    
    # Process other messages
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        # Add your message handling logic here
    except Exception as e:
        print(f"Error processing MQTT message: {e}")

def on_subscribe(mqtt_client, userdata, mid, qos, properties=None):
    print(f"Subscribed with QOS: {qos}")

# Initialize MQTT Client
mclient = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mclient.on_connect = on_connect
mclient.on_message = on_message
mclient.on_subscribe = on_subscribe

app = FastAPI(title="Load Balancer with Batching")

async def check_scheduler_availability(url: str) -> bool:
    """Check if a scheduler is available by establishing a connection"""
    try:
        # Extract base URL and host/port
        base_url = url.rsplit('/', 1)[0] if '/' in url else url
        async with httpx.AsyncClient(timeout=2.0) as client:
            # Just try to connect to the server
            response = await client.head(base_url)
            return True
    except Exception as e:
        print(f"Connection check failed for {url}: {e}")
        return False

async def get_next_active_scheduler() -> Optional[str]:
    """Get the next active scheduler URL in round-robin fashion"""
    async with batch_state.lock:
        # Get the number of schedulers
        num_schedulers = len(settings.SCHEDULER_URLS)
        
        # Try each scheduler starting from the current index
        for i in range(num_schedulers):
            idx = (batch_state.current_scheduler_index + i) % num_schedulers
            scheduler_url = settings.SCHEDULER_URLS[idx]
            
            # Quick check if scheduler is available
            is_available = await check_scheduler_availability(scheduler_url)
            batch_state.scheduler_health[scheduler_url] = is_available
            
            if is_available:
                # Update the current index for next time
                batch_state.current_scheduler_index = (idx + 1) % num_schedulers
                return scheduler_url
            else:
                print(f"Scheduler {scheduler_url} is DOWN or not responding. Skipping to next scheduler.")
                
        # If we get here, no active schedulers were found
        return None

async def process_batch():
    """Process the current batch and send to the next active scheduler if ILP is done"""
    global ilp_state
    
    # Check if ILP is in progress - if so, we need to wait
    if ilp_state == "progress":
        print("ILP is in progress. Waiting to process batch...")
        return
    
    async with batch_state.lock:
        if not batch_state.current_batch:
            return
            
        # Create a copy of the current batch
        batch_to_send = batch_state.current_batch.copy()
        
        # Clear the current batch
        batch_state.current_batch = []
        batch_state.last_batch_time = time.time()
    
    # Find an active scheduler
    scheduler_url = await get_next_active_scheduler()
    
    if scheduler_url is None:
        print("ERROR: No active schedulers available! Keeping batch in memory.")
        # Put the batch back
        async with batch_state.lock:
            batch_state.current_batch = batch_to_send
        return
    
    # Set ILP state to "progress" before sending the batch
    ilp_state = "progress"
    print("Setting ILP state to 'progress' before sending batch")
    
    # Send the batch to the scheduler
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                scheduler_url,
                json={"requests": batch_to_send},
                timeout=10.0,  # 10 second timeout for batch processing
                headers={
                    "Accept": "*/*",
                    "User-Agent": "Thunder Client (https://www.thunderclient.com)",
                    "Content-Type": "application/json"
                }
            )
            print(f"Sent batch of {len(batch_to_send)} requests to {scheduler_url}, status: {response.status_code}")
    except Exception as e:
        print(f"Error sending batch to {scheduler_url}: {e}")
        print(f"Scheduler {scheduler_url} is DOWN")
        
        # Mark this scheduler as unhealthy
        async with batch_state.lock:
            batch_state.scheduler_health[scheduler_url] = False
            
        # Reset ILP state back to "done" since our attempt failed
        ilp_state = "done"
        print("Reset ILP state to 'done' due to failed batch send")
        
        # Try again with a different scheduler
        async with batch_state.lock:
            batch_state.current_batch = batch_to_send + batch_state.current_batch
        await process_batch()

async def check_timeout_task():
    """Background task to check if batch timeout has been reached"""
    while True:
        current_time = time.time()
        async with batch_state.lock:
            elapsed = current_time - batch_state.last_batch_time
            has_items = len(batch_state.current_batch) > 0
        
        # Only process batch if we have items AND batch timeout is reached AND ILP state is "done"
        if elapsed >= settings.BATCH_TIMEOUT_SECONDS and has_items and ilp_state == "done":
            print(f"Timeout reached ({elapsed:.2f}s), processing current batch")
            await process_batch()
        elif has_items and ilp_state == "progress":
            print(f"Batch ready but waiting for ILP to complete. Elapsed time: {elapsed:.2f}s")
        
        # Check every 0.1 seconds
        await asyncio.sleep(0.1)

@app.on_event("startup")
async def startup_event():
    """Start the background task to check for batch timeouts and initialize MQTT"""
    # Start the batch timeout checker
    asyncio.create_task(check_timeout_task())
    
    # Connect to MQTT broker
    try:
        mclient.connect(host=BROKER_ID, port=1883, keepalive=100)
        mclient.loop_start()  # Start MQTT loop in separate thread
        print("MQTT client started successfully")
    except Exception as e:
        print(f"Failed to start MQTT client: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup when shutting down"""
    # Stop MQTT client
    mclient.loop_stop()
    mclient.disconnect()
    print("MQTT client stopped")

@app.post("/submit")
async def submit_request(request: Request, background_tasks: BackgroundTasks):
    """Endpoint to submit a request to be batched"""
    # Parse the request body
    body = await request.json()
    
    async with batch_state.lock:
        # Add the request to the current batch
        batch_state.current_batch.append(body)
        
        # Check if batch is full AND ILP state is "done"
        if len(batch_state.current_batch) >= settings.BATCH_SIZE and ilp_state == "done":
            # Process batch in the background to keep this request handler fast
            background_tasks.add_task(process_batch)
            
    return {"status": "request queued for processing"}

@app.post("/loadbalancer/run_service/")
async def run_service(request: Request, background_tasks: BackgroundTasks):
    """Endpoint to submit a service request to be batched - matches the sample curl format"""
    # Parse the request body
    body = await request.json()
    
    async with batch_state.lock:
        # Add the request to the current batch
        batch_state.current_batch.append(body)
        
        # Check if batch is full AND ILP state is "done"
        if len(batch_state.current_batch) >= settings.BATCH_SIZE and ilp_state == "done":
            # Process batch in the background to keep this request handler fast
            background_tasks.add_task(process_batch)
            
    return {"status": "request queued for processing"}

@app.get("/status")
async def get_status():
    """Get current status of the load balancer"""
    async with batch_state.lock:
        return {
            "current_batch_size": len(batch_state.current_batch),
            "batch_age_seconds": time.time() - batch_state.last_batch_time,
            "scheduler_health": batch_state.scheduler_health,
            "current_scheduler_index": batch_state.current_scheduler_index,
            "ilp_state": ilp_state,
            "config": {
                "batch_size": settings.BATCH_SIZE,
                "batch_timeout": settings.BATCH_TIMEOUT_SECONDS,
                "scheduler_count": len(settings.SCHEDULER_URLS)
            }
        }

# Run with: uvicorn loadbalancer:app --host 0.0.0.0 --port 9001 --reload
