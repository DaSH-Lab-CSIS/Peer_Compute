#!/usr/bin/env python3
"""
MQTT Dashboard Service

A FastAPI service that subscribes to all MQTT topics, stores messages,
tracks provider/scheduler status, and provides a real-time web dashboard.

Usage:
    uvicorn mqtt_dashboard:app --host 0.0.0.0 --port 9020
"""

import asyncio
import json
import os
import time
import threading
import uuid
from collections import deque
from datetime import datetime
from typing import Optional, Dict, List
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import paho.mqtt.client as mqtt
import httpx

# Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MESSAGE_RETENTION = int(os.getenv("MESSAGE_RETENTION", "10000"))
PROVIDER_TIMEOUT = int(os.getenv("PROVIDER_TIMEOUT", "60"))
SCHEDULER_TIMEOUT = int(os.getenv("SCHEDULER_TIMEOUT", "120"))
LOADBALANCER_URL = os.getenv("LOADBALANCER_URL", "http://localhost:9001")

# Global storage
messages = deque(maxlen=MESSAGE_RETENTION)
providers: Dict[str, Dict] = {}  # {user_id: {last_seen, status, message_count, first_seen}}
schedulers: Dict[str, Dict] = {}  # {name: {last_seen, status, topic, message_count, first_seen}}
system_topics = {"EVERYONE": [], "ROTATION": [], "SCHEDULER_ANNOUNCEMENTS": []}
loadbalancers: Dict[str, Dict] = {}  # {name: {last_seen, status, topic, message_count}}
subscribed_provider_topics = set()  # Track which provider topics we've subscribed to

# Load balancer scheduler order (from round-robin)
lb_scheduler_order: List[str] = []  # List of scheduler names in round-robin order
lb_scheduler_order_lock = threading.Lock()
lb_scheduler_order_last_update = 0

# Thread safety
storage_lock = threading.Lock()

# MQTT Client
mqtt_client = None

def categorize_topic(topic: str) -> str:
    """Categorize topic into provider, scheduler, system, or loadbalancer"""
    if topic in system_topics:
        return "system"
    elif topic.startswith("SCHEDULER_"):
        return "scheduler"
    elif topic.startswith("LOADBALANCER_"):
        return "loadbalancer"
    else:
        # Check if it's a UUID (provider topic)
        try:
            uuid.UUID(topic)
            return "provider"
        except ValueError:
            # Unknown topic type
            return "unknown"

def is_provider_topic(topic: str) -> bool:
    """Check if topic is a provider topic (UUID)"""
    try:
        uuid.UUID(topic)
        return topic not in system_topics and not topic.startswith("SCHEDULER_") and not topic.startswith("LOADBALANCER_")
    except ValueError:
        return False

def is_scheduler_topic(topic: str) -> bool:
    """Check if topic is a scheduler topic"""
    return topic.startswith("SCHEDULER_") and topic != "SCHEDULER_ANNOUNCEMENTS"

def extract_scheduler_name(topic: str) -> Optional[str]:
    """Extract scheduler name from topic"""
    if topic.startswith("SCHEDULER_"):
        return topic.replace("SCHEDULER_", "", 1)
    return None

def extract_loadbalancer_name(topic: str) -> Optional[str]:
    """Extract load balancer name from topic"""
    if topic.startswith("LOADBALANCER_"):
        return topic.replace("LOADBALANCER_", "", 1)
    return None

def update_provider_status(user_id: str):
    """Update provider status based on last seen"""
    with storage_lock:
        if user_id in providers:
            current_time = time.time()
            last_seen = providers[user_id]["last_seen"]
            timeout = current_time - last_seen
            providers[user_id]["status"] = "active" if timeout < PROVIDER_TIMEOUT else "inactive"

def update_scheduler_status(scheduler_name: str):
    """Update scheduler status based on last seen"""
    with storage_lock:
        if scheduler_name in schedulers:
            current_time = time.time()
            last_seen = schedulers[scheduler_name]["last_seen"]
            timeout = current_time - last_seen
            schedulers[scheduler_name]["status"] = "active" if timeout < SCHEDULER_TIMEOUT else "inactive"

def update_loadbalancer_status(lb_name: str):
    """Update load balancer status based on last seen"""
    with storage_lock:
        if lb_name in loadbalancers:
            current_time = time.time()
            last_seen = loadbalancers[lb_name]["last_seen"]
            timeout = current_time - last_seen
            loadbalancers[lb_name]["status"] = "active" if timeout < SCHEDULER_TIMEOUT else "inactive"

# MQTT Callbacks
def on_connect(client, userdata, flags, rc, properties=None):
    """Callback when MQTT client connects"""
    import sys
    if rc == 0:
        print(f"[MQTT Dashboard] Connected to MQTT broker {MQTT_BROKER}:{MQTT_PORT}", flush=True)
        print(f"[MQTT Dashboard] Connection flags: {flags}", flush=True)
        print(f"[MQTT Dashboard] Client is_connected: {client.is_connected()}", flush=True)
        
        # Subscribe to all topics using wildcard (catches everything)
        # Use QoS 1 to ensure at least once delivery
        try:
            result, mid = client.subscribe("#", qos=1)
            print(f"[MQTT Dashboard] Subscribed to all topics (#), result: {result}, mid: {mid}", flush=True)
        except Exception as e:
            print(f"[MQTT Dashboard] Warning: # wildcard subscription failed: {e}", flush=True)
            print("[MQTT Dashboard] Will rely on explicit topic subscriptions", flush=True)
        
        # Also explicitly subscribe to known system topics (backup in case # is restricted)
        system_topics_list = ["EVERYONE", "ROTATION", "SCHEDULER_ANNOUNCEMENTS"]
        for topic in system_topics_list:
            try:
                result, mid = client.subscribe(topic, qos=1)
                print(f"[MQTT Dashboard] Subscribed to {topic}, result: {result}, mid: {mid}", flush=True)
            except Exception as e:
                print(f"[MQTT Dashboard] Error subscribing to {topic}: {e}", flush=True)
        
        print("[MQTT Dashboard] Subscriptions complete. Will capture:", flush=True)
        print("  - System topics: EVERYONE, ROTATION, SCHEDULER_ANNOUNCEMENTS", flush=True)
        print("  - Dynamic topics: SCHEDULER_*, LOADBALANCER_*, provider UUIDs (via # wildcard)", flush=True)
        print("[MQTT Dashboard] Note: Topics like SCHEDULER_anjuna2 are single-level, so # wildcard should catch them", flush=True)
        
        # Re-subscribe to all previously discovered provider topics after reconnection
        with storage_lock:
            # Get all provider IDs from both subscribed_provider_topics and providers dict
            provider_ids_to_resubscribe = set(subscribed_provider_topics)
            provider_ids_to_resubscribe.update(providers.keys())
            
            if provider_ids_to_resubscribe:
                print(f"[MQTT Dashboard] Re-subscribing to {len(provider_ids_to_resubscribe)} provider topics after reconnection...", flush=True)
                for provider_id in provider_ids_to_resubscribe:
                    try:
                        result, mid = client.subscribe(provider_id, qos=1)
                        subscribed_provider_topics.add(provider_id)  # Update tracking set
                        print(f"[MQTT Dashboard] Re-subscribed to provider topic: {provider_id}, result: {result}, mid: {mid}", flush=True)
                    except Exception as e:
                        print(f"[MQTT Dashboard] Error re-subscribing to {provider_id}: {e}", flush=True)
        
        print("[MQTT Dashboard] Waiting for messages...", flush=True)
    else:
        print(f"[MQTT Dashboard] Failed to connect to MQTT broker. Code: {rc}", flush=True)
        try:
            error_msg = mqtt.error_string(rc)
            print(f"[MQTT Dashboard] Connection error: {error_msg}", flush=True)
        except:
            pass

def detect_message_source(payload: str, topic: str) -> Optional[str]:
    """Detect if message is from a load balancer based on payload content"""
    # Check for BATCH_REQUEST: prefix (load balancer sends this to schedulers)
    if payload.startswith("BATCH_REQUEST:"):
        try:
            # Extract loadbalancer_id from the JSON payload
            json_str = payload[15:]  # Remove "BATCH_REQUEST:" prefix
            data = json.loads(json_str)
            lb_id = data.get('loadbalancer_id')
            if lb_id:
                return lb_id.replace("LOADBALANCER_", "")  # Return just the name part
        except:
            pass
    return None

def extract_provider_id_from_payload(payload: str) -> Optional[str]:
    """Extract provider UUID from payload messages on EVERYONE topic"""
    # Check for "start_connect{user_id}" pattern
    if payload.startswith("start_connect"):
        user_id = payload[13:]  # Remove "start_connect" prefix
        # Validate it's a UUID
        try:
            uuid.UUID(user_id)
            return user_id
        except ValueError:
            pass
    
    # Check for "get_efficiency_score{user_id}" pattern
    if payload.startswith("get_efficiency_score"):
        user_id = payload[19:]  # Remove "get_efficiency_score" prefix
        try:
            uuid.UUID(user_id)
            return user_id
        except ValueError:
            pass
    
    return None

def subscribe_to_provider_topic(user_id: str):
    """Dynamically subscribe to a provider UUID topic"""
    global mqtt_client, subscribed_provider_topics
    
    if not mqtt_client or not mqtt_client.is_connected():
        return False
    
    # Check if already subscribed (outside lock to avoid deadlock)
    with storage_lock:
        if user_id in subscribed_provider_topics:
            return False  # Already subscribed
    
    # Subscribe outside the lock to avoid blocking MQTT loop
    try:
        result, mid = mqtt_client.subscribe(user_id, qos=1)
        with storage_lock:
            subscribed_provider_topics.add(user_id)
        print(f"[MQTT Dashboard] Dynamically subscribed to provider topic: {user_id}, result: {result}, mid: {mid}", flush=True)
        return True
    except Exception as e:
        print(f"[MQTT Dashboard] Error subscribing to provider topic {user_id}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False

def on_message(client, userdata, msg):
    """Callback when MQTT message is received"""
    import sys
    try:
        payload = msg.payload.decode('utf-8')
    except UnicodeDecodeError:
        payload = f"<binary data: {len(msg.payload)} bytes>"
    except Exception as e:
        print(f"[MQTT Dashboard] ERROR decoding payload: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return  # Don't process if we can't decode
    
    timestamp = time.time()
    topic = msg.topic
    category = categorize_topic(topic)
    
    # Detect if message is from a load balancer (even if on scheduler topic)
    source_lb = detect_message_source(payload, topic)
    
    # Debug: print received messages (first 100 chars) - force flush to ensure it shows up
    payload_preview = payload[:100] + "..." if len(payload) > 100 else payload
    if source_lb:
        print(f"[MQTT Dashboard] Received: topic={topic}, category={category}, from_loadbalancer={source_lb}, payload={payload_preview}", flush=True)
    else:
        print(f"[MQTT Dashboard] Received: topic={topic}, category={category}, payload={payload_preview}", flush=True)
    
    # Create message entry
    message_entry = {
        "timestamp": timestamp,
        "topic": topic,
        "payload": payload,
        "qos": msg.qos,
        "retain": msg.retain,
        "category": category,
        "source_loadbalancer": source_lb  # Track which LB sent this message
    }
    
    # Variables to track if we need to subscribe (outside lock)
    needs_subscription = False
    needs_subscription_everyone = False
    provider_id_from_everyone = None
    
    try:
        with storage_lock:
            # Add to messages
            messages.append(message_entry)
            print(f"[MQTT Dashboard] Stored message. Total messages: {len(messages)}", flush=True)
            
            # Update entity tracking
            if category == "provider" and is_provider_topic(topic):
                user_id = topic
                
                if user_id not in providers:
                    providers[user_id] = {
                        "user_id": user_id,
                        "last_seen": timestamp,
                        "first_seen": timestamp,
                        "status": "active",
                        "message_count": 0
                    }
                providers[user_id]["last_seen"] = timestamp
                providers[user_id]["message_count"] += 1
                update_provider_status(user_id)
                
                # Check if we need to subscribe (outside lock to avoid blocking)
                needs_subscription = user_id not in subscribed_provider_topics
                
            elif category == "scheduler":
                scheduler_name = extract_scheduler_name(topic)
                if scheduler_name:
                    if scheduler_name not in schedulers:
                        schedulers[scheduler_name] = {
                            "name": scheduler_name,
                            "topic": topic,
                            "last_seen": timestamp,
                            "first_seen": timestamp,
                            "status": "active",
                            "message_count": 0
                        }
                    schedulers[scheduler_name]["last_seen"] = timestamp
                    schedulers[scheduler_name]["message_count"] += 1
                    update_scheduler_status(scheduler_name)
                    
            elif category == "loadbalancer":
                lb_name = extract_loadbalancer_name(topic)
                if lb_name:
                    if lb_name not in loadbalancers:
                        loadbalancers[lb_name] = {
                            "name": lb_name,
                            "topic": topic,
                            "last_seen": timestamp,
                            "first_seen": timestamp,
                            "status": "active",
                            "message_count": 0
                        }
                    loadbalancers[lb_name]["last_seen"] = timestamp
                    loadbalancers[lb_name]["message_count"] += 1
                    update_loadbalancer_status(lb_name)
            
            # Also track load balancer activity when they publish to scheduler topics
            if source_lb:
                if source_lb not in loadbalancers:
                    loadbalancers[source_lb] = {
                        "name": source_lb,
                        "topic": f"LOADBALANCER_{source_lb}",  # Expected topic
                        "last_seen": timestamp,
                        "first_seen": timestamp,
                        "status": "active",
                        "message_count": 0
                    }
                loadbalancers[source_lb]["last_seen"] = timestamp
                loadbalancers[source_lb]["message_count"] += 1
                update_loadbalancer_status(source_lb)
                    
            elif category == "system" and topic in system_topics:
                # Keep last 100 messages per system topic
                system_topics[topic].append(message_entry)
                if len(system_topics[topic]) > 100:
                    system_topics[topic].pop(0)
                
                # Detect provider UUIDs from EVERYONE topic messages and subscribe
                if topic == "EVERYONE":
                    provider_id_from_everyone = extract_provider_id_from_payload(payload)
                    if provider_id_from_everyone:
                        # Mark that we need to subscribe (do it outside lock)
                        needs_subscription_everyone = provider_id_from_everyone not in subscribed_provider_topics
                        if needs_subscription_everyone:
                            print(f"[MQTT Dashboard] Detected provider {provider_id_from_everyone} from EVERYONE message, subscribing...", flush=True)
    except Exception as e:
        print(f"[MQTT Dashboard] ERROR storing message: {e}", flush=True)
        import traceback
        traceback.print_exc()
    
    # Subscribe to provider topics OUTSIDE the lock to avoid blocking MQTT loop
    # This prevents deadlocks and allows the MQTT message processing to continue
    try:
        if needs_subscription and category == "provider" and is_provider_topic(topic):
            subscribe_to_provider_topic(topic)
        elif needs_subscription_everyone and provider_id_from_everyone:
            subscribe_to_provider_topic(provider_id_from_everyone)
    except Exception as e:
        print(f"[MQTT Dashboard] ERROR in subscription logic: {e}", flush=True)
        import traceback
        traceback.print_exc()
    
    # Try to parse JSON payload for better display
    try:
        json.loads(payload)
        message_entry["payload_is_json"] = True
    except (json.JSONDecodeError, ValueError):
        message_entry["payload_is_json"] = False
    except Exception as e:
        print(f"[MQTT Dashboard] ERROR parsing JSON: {e}", flush=True)
        message_entry["payload_is_json"] = False

def on_subscribe(client, userdata, mid, granted_qos, properties=None):
    """Callback when subscription is confirmed"""
    # granted_qos can be a list, tuple, or a single value
    # Handle different formats
    subscription_failed = False
    
    if granted_qos is None:
        qos_str = "None (FAILED)"
        subscription_failed = True
    elif isinstance(granted_qos, (list, tuple)):
        if len(granted_qos) > 0:
            qos_val = granted_qos[0]
            if isinstance(qos_val, int):
                if qos_val == 128:  # MQTT error code for subscription failure
                    qos_str = "FAILED (QoS 128)"
                    subscription_failed = True
                elif qos_val < 0 or qos_val > 2:
                    qos_str = f"INVALID QoS {qos_val} (FAILED)"
                    subscription_failed = True
                else:
                    qos_str = f"Granted QoS {qos_val}"
            elif isinstance(qos_val, str) and ("error" in str(qos_val).lower() or "fail" in str(qos_val).lower()):
                qos_str = f"FAILED: {qos_val}"
                subscription_failed = True
            else:
                qos_str = f"Granted QoS {qos_val}"
        else:
            qos_str = "Empty list (FAILED)"
            subscription_failed = True
    elif isinstance(granted_qos, int):
        if granted_qos == 128:  # MQTT error code for subscription failure
            qos_str = "FAILED (QoS 128)"
            subscription_failed = True
        elif granted_qos < 0 or granted_qos > 2:
            qos_str = f"INVALID QoS {granted_qos} (FAILED)"
            subscription_failed = True
        else:
            qos_str = f"Granted QoS {granted_qos}"
    elif isinstance(granted_qos, str):
        if "error" in granted_qos.lower() or "fail" in granted_qos.lower():
            qos_str = f"FAILED: {granted_qos}"
            subscription_failed = True
        else:
            qos_str = f"Granted QoS {granted_qos}"
    else:
        qos_str = f"Unknown format: {type(granted_qos).__name__} = {granted_qos}"
        # If it's not a recognized format, assume failure
        subscription_failed = True
    
    if subscription_failed:
        print(f"[MQTT Dashboard] WARNING: Subscription rejected/failed (mid: {mid}, {qos_str})", flush=True)
        print(f"[MQTT Dashboard] Broker may not support wildcard subscriptions. Will rely on explicit topic subscriptions.", flush=True)
    else:
        print(f"[MQTT Dashboard] Subscription confirmed (mid: {mid}, {qos_str})", flush=True)

def on_disconnect(client, userdata, rc, flags=None, properties=None):
    """Callback when MQTT client disconnects"""
    # Handle both VERSION1 (rc only) and VERSION2 (rc, flags, properties) signatures
    print(f"[MQTT Dashboard] Disconnected from MQTT broker. Code: {rc}", flush=True)
    if rc != 0:
        print("[MQTT Dashboard] Unexpected disconnection, will attempt to reconnect", flush=True)

def start_mqtt_client():
    """Start MQTT client in a separate thread"""
    global mqtt_client
    
    # Generate unique client ID to avoid conflicts
    import random
    client_id = f"mqtt_dashboard_{random.randint(1000, 9999)}"
    
    mqtt_client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.on_subscribe = on_subscribe
    mqtt_client.on_disconnect = on_disconnect
    
    # Enable debug logging to see what's happening
    import logging
    mqtt_logger = logging.getLogger("paho.mqtt.client")
    mqtt_logger.setLevel(logging.DEBUG)
    mqtt_client.enable_logger(mqtt_logger)
    
    try:
        print(f"[MQTT Dashboard] Connecting to {MQTT_BROKER}:{MQTT_PORT}...")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"[MQTT Dashboard] MQTT client started (client_id: {client_id})")
        
        # Give it a moment to connect
        import time
        time.sleep(1)
    except Exception as e:
        print(f"[MQTT Dashboard] Error starting MQTT client: {e}")
        import traceback
        traceback.print_exc()

def periodic_status_update():
    """Periodically update status of all entities"""
    while True:
        time.sleep(10)  # Update every 10 seconds
        with storage_lock:
            for user_id in list(providers.keys()):
                update_provider_status(user_id)
            for scheduler_name in list(schedulers.keys()):
                update_scheduler_status(scheduler_name)
            for lb_name in list(loadbalancers.keys()):
                update_loadbalancer_status(lb_name)

# FastAPI App
app = FastAPI(title="MQTT Dashboard")

@app.on_event("startup")
async def startup_event():
    """Start MQTT client and status update thread on startup"""
    print("[MQTT Dashboard] Starting MQTT dashboard service...")
    start_mqtt_client()
    
    # Start periodic status update thread
    status_thread = threading.Thread(target=periodic_status_update, daemon=True)
    status_thread.start()
    print("[MQTT Dashboard] Status update thread started")
    
    # Start periodic load balancer polling
    asyncio.create_task(periodic_loadbalancer_poll())
    print(f"[MQTT Dashboard] Load balancer polling started (URL: {LOADBALANCER_URL})")
    
    # Initial fetch
    await fetch_loadbalancer_scheduler_order()

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global mqtt_client
    if mqtt_client:
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
            print("[MQTT Dashboard] MQTT client stopped", flush=True)
        except Exception as e:
            print(f"[MQTT Dashboard] Error stopping MQTT client: {e}", flush=True)

@app.get("/", response_class=HTMLResponse)
def index():
    """Main dashboard HTML page"""
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>MQTT Dashboard</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/ryanoasis/nerd-fonts@latest/css/nerd-fonts-generated.css">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            display: flex;
            height: 100vh;
            overflow: hidden;
        }
        
        .sidebar {
            width: 300px;
            background: #252525;
            border-right: 1px solid #333;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }
        
        .sidebar-section {
            padding: 15px;
            border-bottom: 1px solid #333;
        }
        
        .sidebar-section h3 {
            color: #4a9eff;
            margin-bottom: 10px;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .filter-select {
            width: 100%;
            padding: 8px;
            background: #2a2a2a;
            border: 1px solid #444;
            color: #e0e0e0;
            border-radius: 4px;
            font-size: 13px;
            cursor: pointer;
        }
        
        .filter-select option {
            background: #2a2a2a;
            color: #e0e0e0;
        }
        
        .filter-select option:disabled {
            color: #666;
            font-style: italic;
        }
        
        .filter-select option[data-status="inactive"] {
            color: #888;
            opacity: 0.6;
        }
        
        .system-topics {
            list-style: none;
        }
        
        .system-topics li {
            padding: 8px;
            margin: 4px 0;
            background: #2a2a2a;
            border-radius: 4px;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .system-topics li:hover {
            background: #333;
        }
        
        .system-topics li.active {
            background: #4a9eff;
            color: #fff;
        }
        
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        
        .header {
            padding: 15px 20px;
            background: #252525;
            border-bottom: 1px solid #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header h1 {
            font-size: 20px;
            color: #4a9eff;
        }
        
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #0f0;
            animation: pulse 2s infinite;
        }
        
        .status-dot.disconnected {
            background: #f00;
            animation: none;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .message-count {
            color: #888;
            font-size: 12px;
        }
        
        .messages-container {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            font-family: 'JetBrains Mono', 'JetBrainsMono Nerd Font', 'Courier New', monospace;
            font-size: 13px;
            display: flex;
            flex-direction: column; /* Normal direction, we'll prepend to show latest at top */
        }
        
        .message-entry {
            margin-bottom: 15px;
            padding: 12px;
            background: #2a2a2a;
            border-left: 3px solid #444;
            border-radius: 4px;
            transition: border-color 0.2s;
            animation: slideInFromTop 0.3s ease-out;
            transform-origin: top;
        }
        
        @keyframes slideInFromTop {
            from {
                opacity: 0;
                transform: translateY(-20px) scale(0.98);
            }
            to {
                opacity: 1;
                transform: translateY(0) scale(1);
            }
        }
        
        .message-entry:hover {
            border-left-color: #4a9eff;
        }
        
        .message-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 11px;
        }
        
        .message-timestamp {
            color: #888;
        }
        
        .message-topic {
            color: #4a9eff;
            font-weight: bold;
        }
        
        .message-category {
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
            text-transform: uppercase;
        }
        
        .category-provider { background: #4a9eff; color: #fff; }
        .category-scheduler { background: #0f0; color: #000; }
        .category-system { background: #ff0; color: #000; }
        .category-loadbalancer { background: #ff8800; color: #000; }
        .category-unknown { background: #666; color: #fff; }
        
        .message-payload {
            color: #e0e0e0;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 300px;
            overflow-y: auto;
            background: #1a1a1a;
            padding: 8px;
            border-radius: 3px;
            margin-top: 8px;
        }
        
        .message-payload.json {
            color: #0f0;
        }
        
        .message-meta {
            margin-top: 8px;
            font-size: 11px;
            color: #666;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        
        .clear-filter {
            margin-top: 10px;
            padding: 6px 12px;
            background: #4a9eff;
            color: #fff;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }
        
        .clear-filter:hover {
            background: #3a8eef;
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-section">
            <h3>Providers</h3>
            <select id="provider-filter" class="filter-select">
                <option value="">All Providers</option>
            </select>
            <button class="clear-filter" onclick="clearFilter('provider')">Clear</button>
        </div>
        
        <div class="sidebar-section">
            <h3>Schedulers</h3>
            <select id="scheduler-filter" class="filter-select">
                <option value="">All Schedulers</option>
            </select>
            <button class="clear-filter" onclick="clearFilter('scheduler')">Clear</button>
        </div>
        
        <div class="sidebar-section">
            <h3>Load Balancers</h3>
            <select id="loadbalancer-filter" class="filter-select">
                <option value="">All Load Balancers</option>
            </select>
            <button class="clear-filter" onclick="clearFilter('loadbalancer')">Clear</button>
        </div>
        
        <div class="sidebar-section">
            <h3>System Topics</h3>
            <ul class="system-topics" id="system-topics">
                <li data-topic="EVERYONE" onclick="selectSystemTopic('EVERYONE')">EVERYONE</li>
                <li data-topic="ROTATION" onclick="selectSystemTopic('ROTATION')">ROTATION</li>
                <li data-topic="SCHEDULER_ANNOUNCEMENTS" onclick="selectSystemTopic('SCHEDULER_ANNOUNCEMENTS')">SCHEDULER_ANNOUNCEMENTS</li>
            </ul>
            <button class="clear-filter" onclick="clearFilter('system')">Clear</button>
        </div>
    </div>
    
    <div class="main-content">
        <div class="header">
            <h1>MQTT Message Dashboard</h1>
            <div class="status-indicator">
                <div class="status-dot" id="status-dot"></div>
                <span id="status-text">Connecting...</span>
                <span class="message-count" id="message-count">0 messages</span>
            </div>
        </div>
        
        <div class="messages-container" id="messages-container">
            <div class="empty-state">Waiting for MQTT messages...</div>
        </div>
    </div>
    
    <script>
        let currentFilter = {
            provider: null,
            scheduler: null,
            loadbalancer: null,
            system: null
        };
        
        let seenMessages = 0;
        let allMessages = [];
        
        // Update provider dropdown
        async function updateProviderDropdown() {
            const response = await fetch('/api/providers');
            const providers = await response.json();
            const select = document.getElementById('provider-filter');
            
            // Clear existing options except "All Providers"
            select.innerHTML = '<option value="">All Providers</option>';
            
            // Sort: active first, then inactive
            const sorted = providers.sort((a, b) => {
                if (a.status === 'active' && b.status !== 'active') return -1;
                if (a.status !== 'active' && b.status === 'active') return 1;
                return 0;
            });
            
            sorted.forEach(provider => {
                const option = document.createElement('option');
                option.value = provider.user_id;
                option.textContent = `${provider.user_id} (${provider.status})`;
                if (provider.status === 'inactive') {
                    option.style.color = '#888';
                    option.style.opacity = '0.6';
                }
                select.appendChild(option);
            });
        }
        
        // Update scheduler dropdown (ordered by load balancer round-robin)
        async function updateSchedulerDropdown() {
            try {
                const response = await fetch('/api/schedulers');
                const schedulers = await response.json();
                const select = document.getElementById('scheduler-filter');
                
                // Preserve current selection
                const currentValue = select.value;
                
                select.innerHTML = '<option value="">All Schedulers</option>';
                
                // Backend already sorts by round-robin order, so use as-is
                schedulers.forEach(scheduler => {
                    const option = document.createElement('option');
                    option.value = scheduler.name;
                    const statusText = scheduler.status === 'unknown' ? 'not seen' : scheduler.status;
                    option.textContent = `${scheduler.name} (${statusText})`;
                    if (scheduler.status === 'inactive' || scheduler.status === 'unknown') {
                        option.style.color = '#888';
                        option.style.opacity = '0.6';
                    }
                    select.appendChild(option);
                });
                
                // Restore selection if it still exists
                if (currentValue && select.querySelector(`option[value="${currentValue}"]`)) {
                    select.value = currentValue;
                }
                
                // Debug: log scheduler order
                if (schedulers.length > 0) {
                    const order = schedulers.map(s => s.name).join(', ');
                    console.log(`[Dashboard] Scheduler dropdown updated. Order: ${order}`);
                }
            } catch (error) {
                console.error('[Dashboard] Error updating scheduler dropdown:', error);
            }
        }
        
        // Update load balancer dropdown
        async function updateLoadBalancerDropdown() {
            const response = await fetch('/api/loadbalancers');
            const loadbalancers = await response.json();
            const select = document.getElementById('loadbalancer-filter');
            
            select.innerHTML = '<option value="">All Load Balancers</option>';
            
            const sorted = loadbalancers.sort((a, b) => {
                if (a.status === 'active' && b.status !== 'active') return -1;
                if (a.status !== 'active' && b.status === 'active') return 1;
                return 0;
            });
            
            sorted.forEach(lb => {
                const option = document.createElement('option');
                option.value = lb.name;
                option.textContent = `${lb.name} (${lb.status})`;
                if (lb.status === 'inactive') {
                    option.style.color = '#888';
                    option.style.opacity = '0.6';
                }
                select.appendChild(option);
            });
        }
        
        // Filter setup
        document.getElementById('provider-filter').addEventListener('change', (e) => {
            currentFilter.provider = e.target.value || null;
            currentFilter.scheduler = null;
            currentFilter.loadbalancer = null;
            currentFilter.system = null;
            document.getElementById('scheduler-filter').value = '';
            document.getElementById('loadbalancer-filter').value = '';
            document.querySelectorAll('.system-topics li').forEach(li => li.classList.remove('active'));
            applyFilter();
        });
        
        document.getElementById('scheduler-filter').addEventListener('change', (e) => {
            currentFilter.scheduler = e.target.value || null;
            currentFilter.provider = null;
            currentFilter.loadbalancer = null;
            currentFilter.system = null;
            document.getElementById('provider-filter').value = '';
            document.getElementById('loadbalancer-filter').value = '';
            document.querySelectorAll('.system-topics li').forEach(li => li.classList.remove('active'));
            applyFilter();
        });
        
        document.getElementById('loadbalancer-filter').addEventListener('change', (e) => {
            currentFilter.loadbalancer = e.target.value || null;
            currentFilter.provider = null;
            currentFilter.scheduler = null;
            currentFilter.system = null;
            document.getElementById('provider-filter').value = '';
            document.getElementById('scheduler-filter').value = '';
            document.querySelectorAll('.system-topics li').forEach(li => li.classList.remove('active'));
            applyFilter();
        });
        
        function selectSystemTopic(topic) {
            currentFilter.system = topic;
            currentFilter.provider = null;
            currentFilter.scheduler = null;
            currentFilter.loadbalancer = null;
            document.getElementById('provider-filter').value = '';
            document.getElementById('scheduler-filter').value = '';
            document.getElementById('loadbalancer-filter').value = '';
            document.querySelectorAll('.system-topics li').forEach(li => {
                li.classList.toggle('active', li.dataset.topic === topic);
            });
            applyFilter();
        }
        
        function clearFilter(type) {
            if (type === 'provider') {
                currentFilter.provider = null;
                document.getElementById('provider-filter').value = '';
            } else if (type === 'scheduler') {
                currentFilter.scheduler = null;
                document.getElementById('scheduler-filter').value = '';
            } else if (type === 'loadbalancer') {
                currentFilter.loadbalancer = null;
                document.getElementById('loadbalancer-filter').value = '';
            } else if (type === 'system') {
                currentFilter.system = null;
                document.querySelectorAll('.system-topics li').forEach(li => li.classList.remove('active'));
            }
            applyFilter();
        }
        
        function applyFilter() {
            const container = document.getElementById('messages-container');
            container.innerHTML = '';
            
            let filtered = allMessages;
            
            if (currentFilter.provider) {
                filtered = filtered.filter(m => m.topic === currentFilter.provider);
            } else if (currentFilter.scheduler) {
                filtered = filtered.filter(m => m.topic.startsWith('SCHEDULER_') && m.topic.includes(currentFilter.scheduler));
            } else if (currentFilter.loadbalancer) {
                // Show messages on LOADBALANCER_ topics OR messages from this load balancer
                filtered = filtered.filter(m => 
                    (m.topic.startsWith('LOADBALANCER_') && m.topic.includes(currentFilter.loadbalancer)) ||
                    (m.source_loadbalancer === currentFilter.loadbalancer)
                );
            } else if (currentFilter.system) {
                filtered = filtered.filter(m => m.topic === currentFilter.system);
            }
            
            if (filtered.length === 0) {
                container.innerHTML = '<div class="empty-state">No messages match the current filter</div>';
                return;
            }
            
            // Reverse order: newest first (latest at top)
            filtered.reverse();
            
            filtered.forEach(msg => {
                const entry = createMessageElement(msg);
                container.insertBefore(entry, container.firstChild);
            });
            
            // Keep scroll at top (since latest is at top)
            container.scrollTop = 0;
        }
        
        function formatTimestamp(timestamp) {
            // Convert Unix timestamp to IST (UTC+5:30)
            const date = new Date(timestamp * 1000);
            
            // IST is UTC+5:30, so add 5 hours and 30 minutes
            const istOffset = (5 * 60 + 30) * 60 * 1000; // 5:30 in milliseconds
            const istDate = new Date(date.getTime() + istOffset);
            
            // Use UTC methods since we've already applied the offset
            const day = String(istDate.getUTCDate()).padStart(2, '0');
            const month = String(istDate.getUTCMonth() + 1).padStart(2, '0');
            const hours = String(istDate.getUTCHours()).padStart(2, '0');
            const minutes = String(istDate.getUTCMinutes()).padStart(2, '0');
            const seconds = String(istDate.getUTCSeconds()).padStart(2, '0');
            const milliseconds = String(istDate.getUTCMilliseconds()).padStart(3, '0');
            
            const istTime = `${day}/${month} ${hours}:${minutes}:${seconds}.${milliseconds}`;
            const epochTime = Math.floor(timestamp);
            
            return `${istTime}  | ${epochTime}`;
        }
        
        function createMessageElement(msg) {
            const div = document.createElement('div');
            div.className = 'message-entry';
            div.setAttribute('data-message-id', msg.timestamp + '_' + msg.topic);
            
            const timestampFormatted = formatTimestamp(msg.timestamp);
            const categoryClass = `category-${msg.category}`;
            
            let payloadDisplay = msg.payload;
            if (msg.payload_is_json) {
                try {
                    const parsed = JSON.parse(msg.payload);
                    payloadDisplay = JSON.stringify(parsed, null, 2);
                } catch (e) {
                    // Keep original if parsing fails
                }
            }
            
            // Show source load balancer if message is from one
            let sourceInfo = '';
            if (msg.source_loadbalancer) {
                sourceInfo = ` | From: ${msg.source_loadbalancer}`;
            }
            
            div.innerHTML = `
                <div class="message-header">
                    <span class="message-timestamp">${escapeHtml(timestampFormatted)}</span>
                    <span class="message-topic">${escapeHtml(msg.topic)}</span>
                    <span class="message-category ${categoryClass}">${escapeHtml(msg.category)}</span>
                </div>
                <div class="message-payload ${msg.payload_is_json ? 'json' : ''}">${escapeHtml(payloadDisplay)}</div>
                <div class="message-meta">QoS: ${msg.qos} | Retain: ${msg.retain}${escapeHtml(sourceInfo)}</div>
            `;
            
            return div;
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // SSE Connection
        let reconnectAttempts = 0;
        const maxReconnectAttempts = 10;
        
        function connect() {
            const es = new EventSource('/api/stream');
            
            es.onopen = function() {
                document.getElementById('status-dot').classList.remove('disconnected');
                document.getElementById('status-text').textContent = 'Connected';
                reconnectAttempts = 0;
            };
            
            es.onmessage = function(e) {
                const msg = JSON.parse(e.data);
                allMessages.push(msg);
                
                // Keep only last 5000 messages in memory for performance
                if (allMessages.length > 5000) {
                    allMessages.shift();
                }
                
                // Apply current filter and add to display
                if (shouldShowMessage(msg)) {
                    const container = document.getElementById('messages-container');
                    if (container.querySelector('.empty-state')) {
                        container.innerHTML = '';
                    }
                    
                    // Check if message already exists (avoid duplicates)
                    const msgId = msg.timestamp + '_' + msg.topic;
                    if (!container.querySelector(`[data-message-id="${msgId}"]`)) {
                        const entry = createMessageElement(msg, true);
                        // Insert at top (latest first)
                        container.insertBefore(entry, container.firstChild);
                        
                        // Keep scroll at top if user is at top, otherwise maintain position
                        const wasAtTop = container.scrollTop < 50;
                        if (!wasAtTop) {
                            // User scrolled down, maintain position by removing oldest if needed
                            const maxMessages = 200; // Limit visible messages for performance
                            while (container.children.length > maxMessages) {
                                container.removeChild(container.lastChild);
                            }
                        } else {
                            // User at top, keep at top
                            container.scrollTop = 0;
                        }
                    }
                }
                
                // Update message count
                document.getElementById('message-count').textContent = `${allMessages.length} messages`;
            };
            
            es.onerror = function() {
                document.getElementById('status-dot').classList.add('disconnected');
                document.getElementById('status-text').textContent = 'Disconnected';
                es.close();
                
                if (reconnectAttempts < maxReconnectAttempts) {
                    reconnectAttempts++;
                    document.getElementById('status-text').textContent = `Reconnecting... (${reconnectAttempts}/${maxReconnectAttempts})`;
                    setTimeout(connect, 2000);
                } else {
                    document.getElementById('status-text').textContent = 'Connection failed';
                }
            };
        }
        
        function shouldShowMessage(msg) {
            if (currentFilter.provider) {
                return msg.topic === currentFilter.provider;
            } else if (currentFilter.scheduler) {
                return msg.topic.startsWith('SCHEDULER_') && msg.topic.includes(currentFilter.scheduler);
            } else if (currentFilter.loadbalancer) {
                // Show messages on LOADBALANCER_ topics OR messages from this load balancer
                return (msg.topic.startsWith('LOADBALANCER_') && msg.topic.includes(currentFilter.loadbalancer)) ||
                       (msg.source_loadbalancer === currentFilter.loadbalancer);
            } else if (currentFilter.system) {
                return msg.topic === currentFilter.system;
            }
            return true;
        }
        
        // Initialize
        connect();
        updateProviderDropdown();
        updateSchedulerDropdown();
        updateLoadBalancerDropdown();
        
        // Update dropdowns every 5 seconds
        setInterval(() => {
            updateProviderDropdown();
            updateSchedulerDropdown();
            updateLoadBalancerDropdown();
        }, 5000);
    </script>
</body>
</html>
    """)

@app.get("/api/stream")
async def stream():
    """Server-Sent Events endpoint for real-time message streaming"""
    async def gen():
        seen = 0
        while True:
            with storage_lock:
                current_messages = list(messages)
            
            if len(current_messages) > seen:
                for msg in current_messages[seen:]:
                    yield f"data: {json.dumps(msg)}\n\n"
                seen = len(current_messages)
            await asyncio.sleep(0.1)  # Check every 100ms for real-time updates
    
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/api/messages")
async def get_messages(
    topic: Optional[str] = Query(None, description="Filter by topic"),
    provider_id: Optional[str] = Query(None, description="Filter by provider ID"),
    scheduler_name: Optional[str] = Query(None, description="Filter by scheduler name"),
    limit: int = Query(200, description="Maximum number of messages to return")
):
    """Get filtered messages"""
    with storage_lock:
        filtered = list(messages)
    
    if topic:
        filtered = [m for m in filtered if m["topic"] == topic]
    elif provider_id:
        filtered = [m for m in filtered if m["topic"] == provider_id]
    elif scheduler_name:
        filtered = [m for m in filtered if m["topic"].startswith("SCHEDULER_") and scheduler_name in m["topic"]]
    
    return filtered[-limit:]

@app.get("/api/providers")
async def get_providers():
    """List all providers with status"""
    with storage_lock:
        provider_list = []
        current_time = time.time()
        for user_id, info in providers.items():
            # Update status
            update_provider_status(user_id)
            provider_list.append({
                "user_id": user_id,
                "status": info["status"],
                "last_seen": info["last_seen"],
                "last_seen_ago": current_time - info["last_seen"],
                "message_count": info["message_count"],
                "first_seen": info["first_seen"]
            })
    return sorted(provider_list, key=lambda x: (x["status"] != "active", x["last_seen"]), reverse=True)

@app.get("/api/schedulers")
async def get_schedulers():
    """List all schedulers with status, ordered by load balancer round-robin order"""
    with storage_lock:
        scheduler_dict = {}
        current_time = time.time()
        for name, info in schedulers.items():
            # Update status
            update_scheduler_status(name)
            scheduler_dict[name] = {
                "name": name,
                "topic": info["topic"],
                "status": info["status"],
                "last_seen": info["last_seen"],
                "last_seen_ago": current_time - info["last_seen"],
                "message_count": info["message_count"],
                "first_seen": info["first_seen"]
            }
    
    # Add schedulers from load balancer order that haven't been seen via MQTT yet
    current_time = time.time()
    with lb_scheduler_order_lock:
        if lb_scheduler_order:
            for scheduler_name in lb_scheduler_order:
                if scheduler_name not in scheduler_dict:
                    # Add scheduler from load balancer order even if not seen via MQTT
                    scheduler_dict[scheduler_name] = {
                        "name": scheduler_name,
                        "topic": f"SCHEDULER_{scheduler_name}",
                        "status": "unknown",  # Mark as unknown since we haven't seen it via MQTT
                        "last_seen": 0,
                        "last_seen_ago": 999999999,  # Use a large number instead of inf for JSON compatibility
                        "message_count": 0,
                        "first_seen": 0
                    }
    
    scheduler_list = list(scheduler_dict.values())
    
    # Sort by load balancer round-robin order if available
    with lb_scheduler_order_lock:
        if lb_scheduler_order:
            # Create a mapping of scheduler names to their order index
            order_map = {name: idx for idx, name in enumerate(lb_scheduler_order)}
            
            # Debug: log what we're sorting
            scheduler_names_before = [s["name"] for s in scheduler_list]
            print(f"[MQTT Dashboard] /api/schedulers: Found {len(scheduler_list)} schedulers: {scheduler_names_before}", flush=True)
            print(f"[MQTT Dashboard] /api/schedulers: Round-robin order: {lb_scheduler_order}", flush=True)
            
            # Sort: first by round-robin order, then by status (active first), then by last_seen
            def sort_key(sched):
                # Get order index (high number if not in round-robin list)
                order_idx = order_map.get(sched["name"], 9999)
                # Status priority: active=0, inactive=1, unknown=2
                if sched["status"] == "active":
                    status_priority = 0
                elif sched["status"] == "inactive":
                    status_priority = 1
                else:
                    status_priority = 2
                return (order_idx, status_priority, -sched["last_seen"])
            
            scheduler_list.sort(key=sort_key)
            scheduler_names_after = [s["name"] for s in scheduler_list]
            print(f"[MQTT Dashboard] /api/schedulers: After sorting: {scheduler_names_after}", flush=True)
        else:
            # Fallback: sort by status and last_seen if no round-robin order available
            scheduler_list.sort(key=lambda x: (x["status"] != "active", -x["last_seen"]))
            print(f"[MQTT Dashboard] /api/schedulers: No round-robin order available, using fallback sort", flush=True)
    
    return scheduler_list

@app.get("/api/loadbalancers")
async def get_loadbalancers():
    """List all load balancers with status"""
    with storage_lock:
        lb_list = []
        current_time = time.time()
        for name, info in loadbalancers.items():
            # Update status
            update_loadbalancer_status(name)
            lb_list.append({
                "name": name,
                "topic": info["topic"],
                "status": info["status"],
                "last_seen": info["last_seen"],
                "last_seen_ago": current_time - info["last_seen"],
                "message_count": info["message_count"],
                "first_seen": info["first_seen"]
            })
    return sorted(lb_list, key=lambda x: (x["status"] != "active", x["last_seen"]), reverse=True)

@app.get("/api/system-topics")
async def get_system_topics():
    """List system topics and their messages"""
    with storage_lock:
        result = {}
        for topic, msgs in system_topics.items():
            result[topic] = msgs[-50:]  # Last 50 messages per topic
    return result

async def fetch_loadbalancer_scheduler_order():
    """Fetch scheduler order from load balancer"""
    global lb_scheduler_order, lb_scheduler_order_last_update
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{LOADBALANCER_URL}/status")
            if response.status_code == 200:
                data = response.json()
                scheduler_order = data.get("scheduler_order", [])
                
                with lb_scheduler_order_lock:
                    lb_scheduler_order = scheduler_order
                    lb_scheduler_order_last_update = time.time()
                    print(f"[MQTT Dashboard] Updated scheduler order from load balancer: {scheduler_order}", flush=True)
            else:
                print(f"[MQTT Dashboard] Failed to fetch load balancer status: HTTP {response.status_code}", flush=True)
    except Exception as e:
        print(f"[MQTT Dashboard] Error fetching load balancer scheduler order: {e}", flush=True)

async def periodic_loadbalancer_poll():
    """Periodically poll load balancer for scheduler order"""
    while True:
        await asyncio.sleep(5)  # Poll every 5 seconds
        await fetch_loadbalancer_scheduler_order()

@app.get("/api/loadbalancer-schedulers")
async def get_loadbalancer_schedulers():
    """Get scheduler order from load balancer"""
    await fetch_loadbalancer_scheduler_order()
    with lb_scheduler_order_lock:
        return {
            "scheduler_order": lb_scheduler_order,
            "last_update": lb_scheduler_order_last_update
        }

@app.get("/api/stats")
async def get_stats():
    """Get dashboard statistics"""
    with storage_lock:
        current_time = time.time()
        active_providers = sum(1 for p in providers.values() if p["status"] == "active")
        active_schedulers = sum(1 for s in schedulers.values() if s["status"] == "active")
        
        return {
            "total_messages": len(messages),
            "providers": {
                "total": len(providers),
                "active": active_providers,
                "inactive": len(providers) - active_providers
            },
            "schedulers": {
                "total": len(schedulers),
                "active": active_schedulers,
                "inactive": len(schedulers) - active_schedulers
            },
            "loadbalancers": {
                "total": len(loadbalancers),
                "active": sum(1 for lb in loadbalancers.values() if lb["status"] == "active")
            },
            "system_topics": list(system_topics.keys()),
            "message_retention": MESSAGE_RETENTION,
            "uptime_seconds": time.time() - (min([p["first_seen"] for p in providers.values()] + [s["first_seen"] for s in schedulers.values()] + [time.time()])),
            "loadbalancer_url": LOADBALANCER_URL,
            "lb_scheduler_order": lb_scheduler_order
        }

if __name__ == "__main__":
    import uvicorn
    import signal
    
    def signal_handler(sig, frame):
        """Handle Ctrl+C gracefully"""
        print("\n[MQTT Dashboard] Shutting down...", flush=True)
        global mqtt_client
        if mqtt_client:
            try:
                mqtt_client.loop_stop()
                mqtt_client.disconnect()
            except:
                pass
        import sys
        sys.exit(0)
    
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    port = int(os.getenv("DASHBOARD_PORT", "9020"))
    uvicorn.run(app, host="0.0.0.0", port=port)

