#!/usr/bin/env python3
"""
Load Balancer with Experiment Logging

This script provides complete load balancer functionality with experiment logging
capabilities. It captures stdout/stderr to files when experiment mode is enabled.

Usage:
    python loadbalancer_with_logging.py
"""

import asyncio
import logging
import time
import json
import os
import sys
import uuid
import socket
import threading
from typing import List, Dict, Any, Optional
import httpx
from fastapi import FastAPI, Request, BackgroundTasks
from pydantic import BaseModel
import paho.mqtt.client as mqtt
from contextlib import asynccontextmanager
from datetime import datetime
import sys
import os
from collections import deque
# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load repo-root .env so MQTT_BROKER / MQTT_* match Django when you run without `source .env`
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(project_root, ".env"))
except ImportError:
    pass

# Removed get_scheduler_endpoints import - using dynamic MQTT discovery instead

# UDP Log Handler for sending logs to viewer
LOG_INGEST_HOST = os.getenv("LOG_INGEST_HOST", "127.0.0.1")
LOG_INGEST_PORT = int(os.getenv("LOG_INGEST_PORT", "9999"))

class UdpJSONLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    def emit(self, record):
        try:
            data = {
                "ts": time.time(),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                "module": record.module,
                "func": record.funcName,
                "line": record.lineno,
            }
            self.sock.sendto(json.dumps(data).encode(), (LOG_INGEST_HOST, LOG_INGEST_PORT))
        except Exception:
            pass  # Silently ignore UDP send failures to avoid affecting main flow

# Global to store pending responses for correlation
pending_responses = {}

# Global to track scheduler last seen timestamps
scheduler_last_seen = {}

# Global to store discovered schedulers with stable ordering
discovered_schedulers = {}  # {name: {topic, last_seen, status, order_index, failure_count}}
scheduler_order = []  # List of scheduler names in stable order
next_scheduler_index = 0  # Current position in round-robin
MAX_CONSECUTIVE_FAILURES = 3  # Mark scheduler as offline after 3 consecutive failures

def get_loadbalancer_id():
    """Get load balancer identifier"""
    lb_id = os.environ.get('LOADBALANCER_ID')
    if not lb_id:
        hostname = socket.gethostname()
        lb_id = f"LOADBALANCER_{hostname.split('.')[0]}"
    return lb_id

def handle_scheduler_failure(scheduler_name: str, reason: str):
    """Handle scheduler failure with failure counting"""
    if scheduler_name not in discovered_schedulers:
        return
        
    scheduler_info = discovered_schedulers[scheduler_name]
    
    # Increment failure count
    failure_count = scheduler_info.get('failure_count', 0) + 1
    scheduler_info['failure_count'] = failure_count
    
    logger.warning(f"Scheduler {scheduler_name} failure #{failure_count}: {reason}")
    
    # Only mark as offline after multiple consecutive failures
    if failure_count >= MAX_CONSECUTIVE_FAILURES:
        scheduler_info['status'] = 'offline'
        logger.error(f"Scheduler {scheduler_name} marked as offline after {failure_count} consecutive failures")
    else:
        logger.info(f"Scheduler {scheduler_name} still considered online (failure count: {failure_count}/{MAX_CONSECUTIVE_FAILURES})")

def handle_scheduler_success(scheduler_name: str):
    """Handle successful scheduler response - reset failure count"""
    if scheduler_name not in discovered_schedulers:
        return
        
    scheduler_info = discovered_schedulers[scheduler_name]
    
    # Reset failure count on success
    if scheduler_info.get('failure_count', 0) > 0:
        logger.info(f"Scheduler {scheduler_name} recovered - resetting failure count")
        scheduler_info['failure_count'] = 0
    
    # Ensure status is online
    if scheduler_info['status'] != 'online':
        scheduler_info['status'] = 'online'
        logger.info(f"Scheduler {scheduler_name} marked as online")

# def get_scheduler_mqtt_topics():
#     """Get list of scheduler MQTT topics from scheduler endpoints"""
#     scheduler_endpoints = get_scheduler_endpoints()
#     topics = []
    
#     for endpoint in scheduler_endpoints:
#         # Extract identifier from endpoint URL
#         # e.g., http://10.8.1.18:8000 -> SCHEDULER_10_8_1_18
#         # or http://hostname:8000 -> SCHEDULER_hostname
#         if '://' in endpoint:
#             host = endpoint.split('://')[1].split(':')[0]
#             # Replace dots with underscores for valid MQTT topic
#             scheduler_id = host.replace('.', '_')
#             topics.append(f"SCHEDULER_{scheduler_id}")
        
#     return topics

def check_experiment_mode():
    """Check if experiment mode is enabled"""
    try:
        # Try to read scheduler settings
        scheduler_settings_path = os.path.join(os.path.dirname(__file__), '..', 'scheduler', 'scheduler', 'settings.py')
        
        if os.path.exists(scheduler_settings_path):
            with open(scheduler_settings_path, 'r') as f:
                content = f.read()
                return 'EXPERIMENT_MODE = True' in content and 'EXPERIMENT_STDOUT_LOGGING = True' in content
        
        # Fallback: check environment variable
        return os.environ.get('EXPERIMENT_MODE', 'False').lower() == 'true'
    except:
        return False

def setup_logging_paths():
    """Setup logging paths based on current algorithm"""
    # Check for algorithm-specific logging
    experiment_algorithm = os.environ.get('EXPERIMENT_ALGORITHM')
    experiment_log_dir = os.environ.get('EXPERIMENT_LOG_DIR')
    
    if experiment_log_dir:
        logs_dir = experiment_log_dir
    elif experiment_algorithm:
        # Create algorithm-specific directory
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        logs_dir = os.path.join(base_dir, 'experiment_logs', timestamp, experiment_algorithm)
    else:
        # Default behavior
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        logs_dir = os.path.join(base_dir, 'experiment_logs', timestamp)
    
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir

class LoadBalancerLogger:
    """Simple logger for loadbalancer stdout/stderr"""
    
    def __init__(self, logs_dir):
        self.log_file_path = os.path.join(logs_dir, "loadbalancer_stdout.log")
        self.log_file = None
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
    def start_logging(self):
        """Start capturing stdout/stderr"""
        self.log_file = open(self.log_file_path, 'a', encoding='utf-8')
        
        # Write session start marker
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        start_msg = f"[{timestamp}] [loadbalancer] [SYSTEM] === EXPERIMENT SESSION START ===\n"
        self.log_file.write(start_msg)
        self.log_file.flush()
        
        # Replace stdout/stderr
        sys.stdout = self._LogWriter(self, "stdout")
        sys.stderr = self._LogWriter(self, "stderr")
        
        print("Experiment logging started for loadbalancer")
    
    def stop_logging(self):
        """Stop logging and restore original streams"""
        if self.log_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            end_msg = f"[{timestamp}] [loadbalancer] [SYSTEM] === EXPERIMENT SESSION END ===\n"
            self.log_file.write(end_msg)
            self.log_file.flush()
            
            # Restore original streams
            sys.stdout = self.original_stdout
            sys.stderr = self.original_stderr
            
            self.log_file.close()
            self.log_file = None
            
            print("Experiment logging stopped for loadbalancer")
    
    def write_message(self, message, stream_type="stdout"):
        """Write message to log file"""
        if self.log_file and message.strip():
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            formatted_msg = f"[{timestamp}] [loadbalancer] [{stream_type.upper()}] {message}\n"
            self.log_file.write(formatted_msg)
            self.log_file.flush()
            
            # Also write to original stream
            original_stream = self.original_stdout if stream_type == "stdout" else self.original_stderr
            original_stream.write(message)
            original_stream.flush()
    
    class _LogWriter:
        """Custom writer that logs to file and original stream"""
        
        def __init__(self, logger, stream_type):
            self.logger = logger
            self.stream_type = stream_type
        
        def write(self, message):
            if message.strip():
                self.logger.write_message(message.rstrip('\n'), self.stream_type)
        
        def flush(self):
            if self.logger.log_file:
                self.logger.log_file.flush()


# Set up logging
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt="%Y-%m-%d %H:%M:%S"
    )
logger = logging.getLogger(__name__)

# Attach UDP handler for log viewer
udp_handler = UdpJSONLogHandler()
logger.addHandler(udp_handler)

# Configuration
class Config:
    def __init__(self):
        self.BATCH_SIZE = 10
        self.BATCH_TIMEOUT_SECONDS = 5.0
        
        # Schedulers are discovered dynamically via MQTT
        # No need for static SCHEDULER_MQTT_TOPICS
        
        logger.info("Scheduler discovery enabled - will discover schedulers via MQTT announcements")

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
                                # Note: logger not available yet during config loading
                                print(f"SCHEDULER_URLS: {self.SCHEDULER_URLS}")
                            except json.JSONDecodeError:
                                print(f"Error parsing SCHEDULER_URLS: {value}")

# Global settings
settings = Config()

# Global variable to track ILP state - initially "done" to allow first batch to be sent
ilp_state = "done"

# Global logger for experiment mode
experiment_logger = None

# Batch state
class BatchState:
    def __init__(self):
        self.current_batch: List[Dict[str, Any]] = []
        self.last_batch_time = time.time()
        self.current_batch_id: Optional[str] = None
        self.current_batch_formation_time: Optional[float] = None
        # Remove current_scheduler_index since we use global next_scheduler_index
        # Remove scheduler_health since we track health in discovered_schedulers
        self.lock = asyncio.Lock()

batch_state = BatchState()

# Track processed batches for historical data (use deque for efficient FIFO)
processed_batches = deque(maxlen=100)  # Keep last 100 batches

# MQTT Configuration (match scheduler/providers/views.py and provider/provider1.py)
BROKER_ID = os.environ.get("MQTT_BROKER")
try:
    BROKER_PORT = int(os.environ.get("MQTT_PORT", "1884"))
except ValueError:
    BROKER_PORT = 1884


def _mqtt_env_truthy(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _mqtt_format_connack(reason_code, properties):
    """Human-readable CONNACK diagnostics (paho v2 ReasonCode + optional MQTTv5 properties)."""
    parts = [mqtt.connack_string(reason_code)]
    try:
        val = getattr(reason_code, "value", None)
        if val is not None:
            parts.append(f"reason_value={val}")
        if getattr(reason_code, "is_failure", False):
            parts.append("is_failure=True")
    except Exception:
        pass
    if properties is not None:
        parts.append(f"properties={properties!r}")
    return " | ".join(parts)


def _mqtt_log_connect_context(client):
    """Log safe broker/auth context (no passwords)."""
    try:
        cid = getattr(client, "_client_id", b"") or b""
        if isinstance(cid, bytes):
            cid = cid.decode("utf-8", errors="replace")
    except Exception:
        cid = "?"
    user_set = bool(os.environ.get("MQTT_USERNAME"))
    pw_set = bool(os.environ.get("MQTT_PASSWORD"))
    logger.info(
        "[MQTT] connect context: host=%s port=%s client_id=%r auth_username_env_set=%s auth_password_env_set=%s",
        BROKER_ID,
        BROKER_PORT,
        cid,
        user_set,
        pw_set,
    )


# MQTT Client callbacks
def on_connect(mqtt_client, userdata, flags, reason_code, properties):
    # paho CallbackAPIVersion.VERSION2: (client, userdata, flags, reason_code, properties)
    if reason_code == 0:
        logger.info("[MQTT] on_connect OK: flags=%r properties=%r", flags, properties)
        logger.info("Connected successfully to MQTT broker")

        # Subscribe to load balancer's own topic for responses
        lb_id = get_loadbalancer_id()
        mqtt_client.subscribe(lb_id)
        mqtt_client.subscribe("ROTATION")
        mqtt_client.subscribe("EVERYONE")  # For scheduler heartbeats
        mqtt_client.subscribe("SCHEDULER_ANNOUNCEMENTS")  # For scheduler discovery

        logger.info(
            "Subscribed to %s, ROTATION, EVERYONE, and SCHEDULER_ANNOUNCEMENTS topics",
            lb_id,
        )
    else:
        detail = _mqtt_format_connack(reason_code, properties)
        logger.warning("[MQTT] on_connect refused: %s", detail)


def on_connect_fail(mqtt_client, userdata):
    """Fired when TCP/TLS fails before a CONNACK (no broker MQTT response)."""
    sock_err = None
    try:
        sock = getattr(mqtt_client, "socket", None)
        if sock is not None:
            sock_err = getattr(sock, "error", None)
    except Exception:
        sock_err = "unavailable"
    logger.warning(
        "[MQTT] on_connect_fail: could not complete connect to %s:%s (socket_error=%r). "
        "Check host/port, firewall, TLS vs plain, and that the broker is listening.",
        BROKER_ID,
        BROKER_PORT,
        sock_err,
    )


def on_disconnect(mqtt_client, userdata, disconnect_flags, reason_code, properties):
    detail = f"flags={disconnect_flags!r}"
    try:
        detail += f" | reason={reason_code!r}"
        if getattr(reason_code, "value", None) is not None:
            detail += f" | reason_value={reason_code.value}"
    except Exception:
        pass
    if properties is not None:
        detail += f" | properties={properties!r}"
    logger.warning("[MQTT] on_disconnect: %s", detail)


def on_message(mqtt_client, userdata, msg):
    logger.info(f'Received message on topic: {msg.topic} with payload: {msg.payload}')
    global ilp_state
    
    payload_str = msg.payload.decode("utf-8")
    logger.debug(f"Decoded payload string: '{payload_str}'")
    
    # Handle scheduler announcements
    if msg.topic == "SCHEDULER_ANNOUNCEMENTS":
        try:
            announcement = json.loads(payload_str)
            scheduler_name = announcement.get('scheduler_name')
            scheduler_topic = announcement.get('scheduler_topic')
            status = announcement.get('status')
            
            if status == 'online':
                # Check if this is a new scheduler
                if scheduler_name not in discovered_schedulers:
                    # New scheduler - add to end of order
                    discovered_schedulers[scheduler_name] = {
                        'topic': scheduler_topic,
                        'last_seen': time.time(),
                        'status': 'online',
                        'order_index': len(scheduler_order),
                        'failure_count': 0
                    }
                    scheduler_order.append(scheduler_name)
                    logger.info(f"New scheduler discovered: {scheduler_name} (order index: {len(scheduler_order)-1})")
                else:
                    # Existing scheduler coming back online
                    discovered_schedulers[scheduler_name]['status'] = 'online'
                    discovered_schedulers[scheduler_name]['last_seen'] = time.time()
                    logger.info(f"Scheduler {scheduler_name} came back online")
                    
            elif status == 'offline':
                if scheduler_name in discovered_schedulers:
                    discovered_schedulers[scheduler_name]['status'] = 'offline'
                    logger.info(f"Scheduler {scheduler_name} went offline")
                    
        except Exception as e:
            logger.error(f"Error processing scheduler announcement: {e}")
        return
    
    # Handle batch responses
    if payload_str.startswith("BATCH_RESPONSE:"):
        response_json = payload_str[15:]  # Remove prefix
        try:
            response_data = json.loads(response_json)
            correlation_id = response_data.get('correlation_id')
            
            if correlation_id and correlation_id in pending_responses:
                pending_responses[correlation_id] = response_data
                logger.info(f"Received BATCH_RESPONSE for correlation_id: {correlation_id}")
        except Exception as e:
            logger.error(f"Error processing BATCH_RESPONSE: {e}")
        return
    
    # Handle scheduler heartbeat/pong messages
    if payload_str.startswith("SCHEDULER_PONG:"):
        try:
            pong_data = json.loads(payload_str[15:])  # Remove "SCHEDULER_PONG:" prefix
            scheduler_name = pong_data.get('scheduler_name')
            if scheduler_name:
                if scheduler_name in discovered_schedulers:
                    # Update existing scheduler - mark as online if sending heartbeats
                    scheduler_info = discovered_schedulers[scheduler_name]
                    scheduler_info['last_seen'] = time.time()
                    # If scheduler was offline, mark it back as online (recovery)
                    if scheduler_info.get('status') != 'online':
                        scheduler_info['status'] = 'online'
                        scheduler_info['failure_count'] = 0  # Reset failure count on recovery
                        logger.info(f"Scheduler {scheduler_name} recovered (received heartbeat, marking as online)")
                    logger.debug(f"Received heartbeat from scheduler {scheduler_name}")
                else:
                    # Discover new scheduler from heartbeat (in case we missed the announcement)
                    scheduler_topic = f"SCHEDULER_{scheduler_name}"
                    discovered_schedulers[scheduler_name] = {
                        'topic': scheduler_topic,
                        'last_seen': time.time(),
                        'status': 'online',
                        'order_index': len(scheduler_order),
                        'failure_count': 0
                    }
                    scheduler_order.append(scheduler_name)
                    logger.info(f"New scheduler discovered from heartbeat: {scheduler_name} (order index: {len(scheduler_order)-1})")
        except Exception as e:
            logger.error(f"Error processing SCHEDULER_PONG: {e}")
        return
    
    # Handle ILP_DONE signal
    if payload_str == "ILP_DONE":
        logger.info("Received ILP_DONE signal, setting ilp_state to 'done'")
        ilp_state = "done"
        return
    
    # Keep other existing message handlers if needed
    logger.debug(f"Unhandled message type: {payload_str[:50]}...")

def on_subscribe(mqtt_client, userdata, mid, qos, properties=None):
    logger.info(f"Subscribed with QOS: {qos}")

# Initialize MQTT Client lazily, same pattern as scheduler/providers/views.py
mclient = None
mqtt_username = os.environ.get("MQTT_USERNAME")
mqtt_password = os.environ.get("MQTT_PASSWORD")
MQTT_CONNECT_TIMEOUT = 5


def _do_mqtt_connect(timed_out_flag):
    """Run MQTT connect in a thread; set global mclient on success or DISCONNECTED on failure."""
    global mclient
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if mqtt_username:
            client.username_pw_set(mqtt_username, mqtt_password)
        if _mqtt_env_truthy("MQTT_DEBUG"):
            ph_logger = logging.getLogger("paho.mqtt.client")
            ph_logger.setLevel(logging.DEBUG)
            client.enable_logger(ph_logger)
        client.on_connect = on_connect
        client.on_connect_fail = on_connect_fail
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        client.on_subscribe = on_subscribe

        _mqtt_log_connect_context(client)
        client.connect(host=BROKER_ID, port=BROKER_PORT, keepalive=100)
        if timed_out_flag[0]:
            return
        client.loop_start()
        mclient = client
        logger.info(
            "[MQTT] connect() returned and loop_start() running; broker CONNACK is asynchronous "
            "(success appears in on_connect when reason_code==0)."
        )
    except Exception as e:
        if not timed_out_flag[0]:
            hint = ""
            if isinstance(e, OSError) and e.errno == 101:
                hint = (
                    " No route to broker: confirm MQTT_BROKER in .env, ping that host from this machine, "
                    "and check ip route / WiFi or VLAN."
                )
            logger.error("Failed to start MQTT client: %s%s", e, hint)
        mclient = "DISCONNECTED"


def get_mclient():
    global mclient
    if mclient is None:
        timed_out_flag = [False]
        conn_thread = threading.Thread(target=_do_mqtt_connect, args=(timed_out_flag,), daemon=True)
        conn_thread.start()
        conn_thread.join(timeout=MQTT_CONNECT_TIMEOUT)
        if conn_thread.is_alive():
            timed_out_flag[0] = True
            mclient = "DISCONNECTED"
            logger.warning(
                "MQTT connection to %s:%s timed out after %ss. MQTT functionality will be unavailable.",
                BROKER_ID,
                BROKER_PORT,
                MQTT_CONNECT_TIMEOUT,
            )
            return None
    if mclient == "DISCONNECTED":
        return None
    return mclient

app = FastAPI(title="Load Balancer with Batching")

async def check_scheduler_availability(topic: str) -> bool:
    """
    Check if a scheduler is available based on recent heartbeat
    """
    # Extract name from topic (SCHEDULER_{name})
    scheduler_name = topic.replace("SCHEDULER_", "")
    
    if scheduler_name not in discovered_schedulers:
        logger.debug(f"Scheduler {scheduler_name} not in discovered list")
        return False
        
    scheduler_info = discovered_schedulers[scheduler_name]
    last_seen = scheduler_info.get('last_seen', 0)
    current_time = time.time()
    
    # Consider available if seen within last 60 seconds (more lenient)
    is_available = (current_time - last_seen) < 60.0
    
    if is_available:
        logger.debug(f"Scheduler {scheduler_name} is available (last seen {current_time - last_seen:.1f}s ago)")
    else:
        logger.debug(f"Scheduler {scheduler_name} is unavailable (last seen {current_time - last_seen:.1f}s ago)")
    
    return is_available

async def get_next_active_scheduler() -> Optional[str]:
    """Get the next active scheduler MQTT topic in round-robin fashion"""
    global next_scheduler_index
    async with batch_state.lock:
        current_time = time.time()
        
        # Get list of online schedulers in stable order
        online_schedulers = []
        for scheduler_name in scheduler_order:
            if scheduler_name in discovered_schedulers:
                scheduler_info = discovered_schedulers[scheduler_name]
                # Consider online if status is online and seen within last 120 seconds (more lenient)
                # This prevents schedulers from being marked offline too quickly
                if (scheduler_info['status'] == 'online' and 
                    (current_time - scheduler_info['last_seen']) < 120.0):
                    online_schedulers.append(scheduler_name)
        
        num_online = len(online_schedulers)
        if num_online == 0:
            logger.error("No online schedulers found!")
            return None
            
        logger.debug(f"Found {num_online} online schedulers out of {len(scheduler_order)} total")
        logger.debug(f"Current round-robin index: {next_scheduler_index}")
        
        # Try schedulers starting from current index in scheduler_order
        # This ensures proper round-robin even when some schedulers are offline
        for i in range(len(scheduler_order)):
            # Calculate index in scheduler_order (wrap around)
            idx = (next_scheduler_index + i) % len(scheduler_order)
            scheduler_name = scheduler_order[idx]
            
            # Skip if scheduler is not online
            if scheduler_name not in online_schedulers:
                logger.debug(f"Skipping scheduler {scheduler_name} (not online)")
                continue
            
            scheduler_topic = discovered_schedulers[scheduler_name]['topic']
            logger.debug(f"Trying scheduler {scheduler_name} (position {idx} in scheduler_order) -> {scheduler_topic}")
            
            # Check if scheduler is available (based on heartbeat)
            is_available = await check_scheduler_availability(scheduler_topic)
            
            if is_available:
                # Update the round-robin index to the next position in scheduler_order
                next_scheduler_index = (idx + 1) % len(scheduler_order)
                logger.info(f"Selected scheduler: {scheduler_name} (round-robin index: {next_scheduler_index})")
                return scheduler_topic
            else:
                logger.warning(f"Scheduler {scheduler_name} is DOWN. Skipping to next scheduler.")
                
        # If we get here, no available schedulers were found
        logger.error("No available schedulers found!")
        return None

async def process_batch():
    """Process the current batch and send to scheduler via MQTT"""
    global ilp_state
    
    logger.debug(f"process_batch called, current ILP state: {ilp_state}")
    
    if ilp_state == "progress":
        logger.debug("ILP is in progress. Waiting to process batch...")
        return
    
    batch_id = None
    batch_formation_time = None
    batch_size = 0
    
    async with batch_state.lock:
        if not batch_state.current_batch:
            logger.debug("No batch to process (batch is empty)")
            return
            
        batch_to_send = batch_state.current_batch.copy()
        batch_id = batch_state.current_batch_id
        batch_formation_time = batch_state.current_batch_formation_time
        batch_size = len(batch_to_send)
        
        logger.info(f"Processing batch {batch_id} with {batch_size} requests")
        
        # Clear current batch
        batch_state.current_batch = []
        batch_state.current_batch_id = None
        batch_state.current_batch_formation_time = None
        batch_state.last_batch_time = time.time()
    
    # Find an active scheduler
    scheduler_topic = await get_next_active_scheduler()
    
    if scheduler_topic is None:
        logger.error("No active schedulers available! Keeping batch in memory.")
        async with batch_state.lock:
            batch_state.current_batch = batch_to_send
        return
    
    # Set ILP state to "progress" before sending the batch
    ilp_state = "progress"
    logger.info("Setting ILP state to 'progress' before sending batch")
    
    # Generate correlation ID
    correlation_id = str(uuid.uuid4())
    lb_id = get_loadbalancer_id()
    
    # Prepare MQTT message with prefix pattern
    mqtt_payload = {
        'correlation_id': correlation_id,
        'loadbalancer_id': lb_id,
        'batch_data': {"requests": batch_to_send}
    }
    
    # Store pending response
    pending_responses[correlation_id] = None
    
    try:
        mqtt_client = get_mclient()
        if mqtt_client is None:
            logger.error("MQTT client unavailable. Keeping batch in memory until broker is reachable.")
            ilp_state = "done"
            del pending_responses[correlation_id]
            async with batch_state.lock:
                batch_state.current_batch = batch_to_send + batch_state.current_batch
            return

        # Publish to scheduler-specific topic with BATCH_REQUEST prefix
        message = "BATCH_REQUEST:" + json.dumps(mqtt_payload)
        mqtt_client.publish(
            topic=scheduler_topic,
            payload=message,
            qos=2
        )
        logger.info(f"Sent batch of {len(batch_to_send)} requests to {scheduler_topic} via MQTT")
        
        # Wait for response (with timeout)
        timeout = 10.0
        start_time = time.time()
        while pending_responses[correlation_id] is None:
            if time.time() - start_time > timeout:
                logger.error(f"Timeout waiting for scheduler response from {scheduler_topic}")
                
                # Handle scheduler failure with failure counting
                scheduler_name = scheduler_topic.replace("SCHEDULER_", "")
                handle_scheduler_failure(scheduler_name, "timeout")
                
                # Reset ILP state and retry
                ilp_state = "done"
                del pending_responses[correlation_id]
                
                # Put batch back and try again
                async with batch_state.lock:
                    batch_state.current_batch = batch_to_send + batch_state.current_batch
                await process_batch()
                return
            
            await asyncio.sleep(0.1)
        
        # Got response
        response = pending_responses[correlation_id]
        del pending_responses[correlation_id]
        logger.info(f"Received response from {scheduler_topic}: {response}")
        
        # Record batch processing completion
        processing_end_time = time.time()
        processing_time = processing_end_time - batch_formation_time if batch_formation_time else 0
        
        batch_info = {
            'batch_id': batch_id,
            'batch_size': batch_size,
            'formation_time': batch_formation_time,
            'processing_start_time': batch_formation_time,
            'processing_end_time': processing_end_time,
            'processing_time': processing_time,
            'scheduler_name': scheduler_topic.replace("SCHEDULER_", ""),
            'correlation_id': correlation_id,
            'status': response.get('status', 'unknown'),
            'processed_count': response.get('processed', 0),
            'ilp_solve_time': response.get('ilp_solve_time'),  # If scheduler includes it
            'results': response.get('results', [])
        }
        
        # Add to historical batches
        processed_batches.append(batch_info)
        logger.info(f"Recorded batch {batch_id} processing: {processing_time:.3f}s")
        
        # Handle successful response
        scheduler_name = scheduler_topic.replace("SCHEDULER_", "")
        handle_scheduler_success(scheduler_name)
        
        # Reset ILP state to "done" after processing response
        ilp_state = "done"
        logger.info("Batch processing complete, resetting ILP state to 'done'")
        
    except Exception as e:
        logger.error(f"Error sending batch to {scheduler_topic} via MQTT: {e}")
        logger.warning(f"Scheduler {scheduler_topic} encountered error")
        
        # Handle scheduler failure with failure counting
        scheduler_name = scheduler_topic.replace("SCHEDULER_", "")
        handle_scheduler_failure(scheduler_name, f"exception: {str(e)}")
            
        # Reset ILP state
        ilp_state = "done"
        
        # Clean up pending response if exists
        if correlation_id in pending_responses:
            del pending_responses[correlation_id]
        
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
            logger.info(f"Timeout reached ({elapsed:.2f}s), processing current batch")
            await process_batch()
        elif has_items and ilp_state == "progress":
            logger.debug(f"Batch ready but waiting for ILP to complete. Elapsed time: {elapsed:.2f}s")
        elif has_items:
            # Additional debug for other cases
            logger.debug(f"Batch has {len(batch_state.current_batch)} items, elapsed: {elapsed:.2f}s, ILP state: {ilp_state}, timeout: {settings.BATCH_TIMEOUT_SECONDS}s")
        
        # Check every 0.1 seconds
        await asyncio.sleep(0.1)

@app.on_event("startup")
async def startup_event():
    """Start the background task to check for batch timeouts and initialize MQTT"""
    # Check if experiment mode is enabled
    global experiment_logger
    experiment_mode = check_experiment_mode()
    experiment_logger = None
    
    if experiment_mode:
        logs_dir = setup_logging_paths()
        experiment_logger = LoadBalancerLogger(logs_dir)
        experiment_logger.start_logging()
    
    # Start the batch timeout checker
    asyncio.create_task(check_timeout_task())
    
    # Connect to MQTT broker (same env as scheduler/providers/views.py)
    if not BROKER_ID:
        logger.error(
            "MQTT_BROKER is not set. Set it to the same broker host as the scheduler (see views.py)."
        )
        return
    client = get_mclient()
    if client is None:
        logger.warning("Starting without MQTT connectivity. Batch forwarding will wait for broker availability.")
    else:
        logger.info("MQTT client started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup when shutting down"""
    # Stop MQTT client
    if mclient not in (None, "DISCONNECTED"):
        mclient.loop_stop()
        mclient.disconnect()
        logger.info("MQTT client stopped")
    
    # Stop logging if experiment mode was enabled
    global experiment_logger
    if experiment_logger:
        experiment_logger.stop_logging()

@app.post("/submit")
async def submit_request(request: Request, background_tasks: BackgroundTasks):
    """Endpoint to submit a request to be batched"""
    # Parse the request body
    body = await request.json()
    logger.debug(f"Received request on /submit endpoint: {body}")
    
    # Add timestamp when request is received at load balancer
    from datetime import datetime
    import pytz
    # Use UTC for consistency across distributed system
    body['_lb_received_time'] = datetime.now(pytz.UTC).isoformat()
    
    async with batch_state.lock:
        # Add the request to the current batch
        batch_state.current_batch.append(body)
        logger.debug(f"Added request to batch. Current batch size: {len(batch_state.current_batch)}")
        
        # Check if batch is full AND ILP state is "done"
        if len(batch_state.current_batch) >= settings.BATCH_SIZE and ilp_state == "done":
            logger.info(f"Batch is full ({len(batch_state.current_batch)}/{settings.BATCH_SIZE}) and ILP is done. Processing batch.")
            # Process batch in the background to keep this request handler fast
            background_tasks.add_task(process_batch)
        else:
            logger.debug(f"Batch not ready. Size: {len(batch_state.current_batch)}/{settings.BATCH_SIZE}, ILP state: {ilp_state}")
            
    return {"status": "request queued for processing"}

@app.post("/loadbalancer/run_service/")
async def run_service(request: Request, background_tasks: BackgroundTasks):
    """Endpoint to submit a service request to be batched - matches the sample curl format"""
    # Parse the request body
    body = await request.json()
    logger.debug(f"Received request on /loadbalancer/run_service/ endpoint: {body}")
    
    # Add timestamp when request is received at load balancer
    from datetime import datetime
    from pytz import timezone
    import pytz
    # Use UTC for consistency across distributed system
    body['_lb_received_time'] = datetime.now(pytz.UTC).isoformat()
    
    async with batch_state.lock:
        # Add the request to the current batch
        batch_state.current_batch.append(body)
        logger.debug(f"Added request to batch. Current batch size: {len(batch_state.current_batch)}")
        
        # Check if batch is full AND ILP state is "done"
        if len(batch_state.current_batch) >= settings.BATCH_SIZE and ilp_state == "done":
            logger.info(f"Batch is full ({len(batch_state.current_batch)}/{settings.BATCH_SIZE}) and ILP is done. Processing batch.")
            # Process batch in the background to keep this request handler fast
            background_tasks.add_task(process_batch)
        else:
            logger.debug(f"Batch not ready. Size: {len(batch_state.current_batch)}/{settings.BATCH_SIZE}, ILP state: {ilp_state}")
            
    return {"status": "request queued for processing"}

@app.get("/status")
async def get_status():
    """Get current status of the load balancer"""
    current_time = time.time()
    
    # Get online schedulers
    online_schedulers = []
    for scheduler_name in scheduler_order:
        if scheduler_name in discovered_schedulers:
            scheduler_info = discovered_schedulers[scheduler_name]
            if (scheduler_info['status'] == 'online' and 
                (current_time - scheduler_info['last_seen']) < 60.0):
                online_schedulers.append({
                    'name': scheduler_name,
                    'topic': scheduler_info['topic'],
                    'last_seen': scheduler_info['last_seen'],
                    'order_index': scheduler_info['order_index']
                })
    
    async with batch_state.lock:
        current_batch_id = batch_state.current_batch_id
        batch_formation_time = batch_state.current_batch_formation_time
        batch_age = current_time - batch_formation_time if batch_formation_time else 0
        
        # Convert deque to list for JSON serialization
        recent_batches = list(processed_batches)
        
        return {
            "current_batch_size": len(batch_state.current_batch),
            "current_batch_id": current_batch_id,
            "batch_age_seconds": batch_age,
            "discovered_schedulers": len(discovered_schedulers),
            "online_schedulers": len(online_schedulers),
            "next_scheduler_index": next_scheduler_index,
            "scheduler_order": scheduler_order,
            "online_scheduler_details": online_schedulers,
            "ilp_state": ilp_state,
            "config": {
                "batch_size": settings.BATCH_SIZE,
                "batch_timeout": settings.BATCH_TIMEOUT_SECONDS
            },
            "recent_batches": recent_batches[-10:]  # Last 10 batches
        }

@app.get("/batch/{batch_id}")
async def get_batch_info(batch_id: str):
    """Get information about a specific processed batch"""
    # Search in recent batches
    for batch in processed_batches:
        if batch.get('batch_id') == batch_id:
            return batch
    
    return {"error": "Batch not found", "batch_id": batch_id}

@app.get("/batches/recent")
async def get_recent_batches(limit: int = 20):
    """Get recent processed batches with ILP metrics"""
    recent = list(processed_batches)[-limit:]
    return {
        "total_batches": len(processed_batches),
        "returned_batches": len(recent),
        "batches": recent
    }

# Run with: uvicorn loadbalancer_with_logging:app --host 0.0.0.0 --port 9001 --reload 