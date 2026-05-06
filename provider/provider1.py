from threading import Thread, Event, Lock
import threading

import concurrent
import zmq
import sys
import requests
import json
import time
import asyncio
import docker
import HFRequests
import math
import traceback
import csv
import paho.mqtt.client as mqtt
from time import sleep
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error
import joblib  # Used for model persistence
import pickle
import matplotlib.pyplot as plt
import numpy as np
from hybridcaching import HybridImageManager
import os
import signal
import logging
import sys
import tempfile
import socket
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PROVIDER_HTTP_PORT = int(os.environ.get("PROVIDER_HTTP_PORT", "9002"))

user_id = sys.argv[1]
# Add the project root directory to Python's path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# Load repo-root .env so MQTT_BROKER / MQTT_* match Django when you run without `source .env`
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(project_root, ".env"))
except ImportError:
    pass

# --- Experiment Logging Setup ---
try:
    from loadbalancer.loadbalancer_with_logging import get_experiment_log_dir, ExperimentLogger
    
    # Provider acts as a follower
    logs_dir = get_experiment_log_dir(is_leader=False)
    log_filename = f"prov_{user_id}_stdout.log"
    
    # Start the logger
    logger = ExperimentLogger(logs_dir, log_filename)
    logger.start_logging()
    
    # Ensure logger is stopped on exit
    import atexit
    atexit.register(logger.stop_logging)

except (ImportError, FileNotFoundError) as e:
    print(f"Warning: Could not set up experiment logging: {e}")
# --- End Logging Setup ---

# Change from relative to absolute import
from invocations.invoker import get_payload

from scheduler.scheduler.settings import HOST
controller_ip = HOST
controller_port = "8000"

_mqtt_log = logging.getLogger(__name__)


def _mqtt_env_truthy(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


# uncomment requests.get ACK READY NOT READY
channelName = "mychannel"
chaincodeName = "monitoring"
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE2OTQxMjk2MzcsInVzZXJuYW1lIjoiY29udHJvbGxlciIsIm9yZ05hbWUiOiJPcmcxIiwiaWF0IjoxNjk0MDkzNjM3fQ.DNJZ4kB11PbDB4UO2HaMjwlqxgTbJ8b7JK3WsRzaePY"


# Get the current process ID
pid = os.getpid()

# Print the PID
print(f"PID: {pid}")

try:
    client = docker.from_env()
except docker.errors.DockerException as e:
    chain = " ".join(
        str(x) for x in (e, e.__cause__, getattr(e.__cause__, "__cause__", None)) if x
    )
    if "Permission denied" in chain or "Errno 13" in chain:
        print(
            "Docker socket permission denied: add this user to the docker group, then "
            "log out and back in (or run: newgrp docker). Example: sudo usermod -aG docker $USER",
            file=sys.stderr,
        )
    raise
procedural_shutdown_event = Event()
pending_jobs = 0  #despite the name, this is flag indicating whether something is running or not. 
pending_jobs_lock = Lock()
last_message_time = time.time()


# REGISTER_URL = 'https://' + controller_ip + ":" + controller_port + "/profiles/register_user/"
# Removed HTTP URL definitions - switching to MQTT-based signaling
# ACK_URL = "http://" + controller_ip + ":" + controller_port + "/providers/job_ack/"
# NOT_READY_URL = "http://" + controller_ip + ":" + controller_port + "/providers/not_ready/"
# READY_URL = "http://" + controller_ip + ":" + controller_port + "/providers/ready/"

# Remove early READY signal - will be sent after MQTT connection
# requests.get(url=READY_URL+user_id)
# TODO make a request to ready url as soon as this script has run, ie j write a line here.
runs_list = [] #this stores all data in all runs for a specific job.
# def create_thread_and_subscribe(user_id):
#     provider_thread = Thread(target= thread_target, args= (controller_ip,controller_port,user_id))
#     provider_thread.start()
#     provider_thread.join()
curl_count = 0

cpu_efficiency_score = "DID NOT RECIEVE"
memory_efficiency_score = "DID NOT RECIEVE"

MEMORY_LIMIT = 1200 * 1024 * 1024
DISK_LIMIT = 2000 * 1024 * 1024

imagePuller = HybridImageManager(memory_limit=MEMORY_LIMIT, disk_limit=DISK_LIMIT)
# MQTT

# Add a flag to track subscription confirmation
subscription_confirmed = False

def on_connect(mqtt_client, userdata, flags, reason_code, properties):
    # paho CallbackAPIVersion.VERSION2: (client, userdata, flags, reason_code, properties)
    if reason_code == 0:
        print("Connected successfully")
        mqtt_client.subscribe(user_id)
        mqtt_client.subscribe("EVERYONE")
    else:
        print("Bad connection. reason_code:", reason_code)


def on_connect_fail(mqtt_client, userdata):
    sock_err = None
    try:
        sock = getattr(mqtt_client, "socket", None)
        if sock is not None:
            sock_err = getattr(sock, "error", None)
    except Exception:
        sock_err = "unavailable"
    _mqtt_log.warning(
        "[MQTT] on_connect_fail: could not complete connect to %s:%s (socket_error=%r).",
        BROKER_ID,
        BROKER_PORT,
        sock_err,
    )
    print(
        f"[MQTT] connect_fail before CONNACK to {BROKER_ID}:{BROKER_PORT} "
        f"(set MQTT_DEBUG=1 for paho wire logs)"
    )

def process_dockernotrun_request(data):
    global pending_jobs
    print(f"[DEBUG] process_dockernotrun_request started for job_id: {data.get('job_id', 'unknown')}")
    
    with pending_jobs_lock:
        pending_jobs += 1
        print(f"Pending jobs incremented: {pending_jobs}")
    
    try: 
        print(f"[DEBUG] Processing job with runMultipleInvocations: {data.get('runMultipleInvocations', False)}")
        if(data['runMultipleInvocations'] == True):
            if(data['numberOfInvocations'] == 1) :
                print(f"[DEBUG] Single invocation, calling on_request")
                on_request(data)
            elif(data['isChained'] == False):
                print(f"[DEBUG] Multiple invocations (not chained), calling on_request {data['numberOfInvocations']} times")
                for i in range(data['numberOfInvocations']):
                    container_name = str(data['job_id']) + "_container_" + str(i)
                    on_request(data)
            else: 
                print(f"[DEBUG] Chained invocations, calling on_chained_request")
                on_chained_request(data)
        else:
            print(f"[DEBUG] Single job, calling on_request")
            on_request(data)
            
        print(f"[DEBUG] Job processing completed successfully for job_id: {data.get('job_id', 'unknown')}")
    except Exception as e:
        print(f"[DEBUG] Exception in process_dockernotrun_request: {str(e)}")
        print(str(e))
    finally: 
        with pending_jobs_lock:
            pending_jobs -= 1
            print(f"Pending jobs decremented: {pending_jobs}")
            print(f"[DEBUG] process_dockernotrun_request finished for job_id: {data.get('job_id', 'unknown')}")

def on_message(mqtt_client, userdata, msg):
    print(f'=== MQTT MESSAGE RECEIVED ===')
    print(f'Topic: {msg.topic}')
    print(f'Payload: {msg.payload}')
    print(f'Timestamp: {time.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'================================')
    
    global last_message_time, subscription_confirmed
    last_message_time = time.time()

    try: 
        data = json.loads(msg.payload.decode("utf-8"))
        print(f'Parsed JSON data: {data}')
        if(data["stage"] == "dockernotrun"):
            print(f'Processing dockernotrun request for job_id: {data.get("job_id", "unknown")}')
            data["stage"] = "dockerrunning"
            # Offload heavy processing to a separate thread
            Thread(target=process_dockernotrun_request, args=(data,)).start()
        
    except:
        payload_str = msg.payload.decode("utf-8")
        
        # Handle subscription confirmation from scheduler
        if payload_str == "SUBSCRIPTION_CONFIRMED":
            subscription_confirmed = True
            print("Scheduler confirmed subscription, sending startup signals...")
            # Now it's safe to send startup signals
            mclient.publish(topic=user_id, payload="STARTUP", qos=2)
            print("STARTUP signal sent to scheduler")
            mclient.publish(topic=user_id, payload="READY", qos=2)
            print("READY signal sent to scheduler")
            
        elif(payload_str == "calculate_efficiency"):
            Thread(target=calc_benchmark_stats).start()
        elif(payload_str.startswith("EfficiencyScoreSet:")):
            scoreset = json.loads(payload_str[19:])
            global cpu_efficiency_score
            cpu_efficiency_score = scoreset['cpu']
            global memory_efficiency_score
            memory_efficiency_score = scoreset['memory']
            print("Fetched this provider's efficiency score set")
            print(cpu_efficiency_score)
            print(memory_efficiency_score)
        elif(payload_str.startswith("ref_run_service_id/")):
            service_id = payload_str[19:]
            # Offload reference stats collection to a separate thread
            Thread(target=set_reference_stats_for_service, args=(service_id,)).start()
        elif payload_str.startswith("PREDICT_REQUEST:"):
            try:
                rest = payload_str[len("PREDICT_REQUEST:"):]
                parts = rest.split("|", 2)
                if len(parts) >= 3:
                    correlation_id, reply_topic, services_json = parts[0], parts[1], parts[2]
                    services_payload = json.loads(services_json)
                    Thread(target=handle_predict_request, args=(correlation_id, reply_topic, services_payload)).start()
            except Exception as e:
                print(f"[DEBUG] PREDICT_REQUEST parse error: {e}")

def handle_predict_request(correlation_id, reply_topic, services_payload):
    """Compute predicted runtimes for requested services and publish PREDICT_RESPONSE to scheduler."""
    runtimes = {}
    for item in services_payload:
        service_id = item.get("service_id")
        docker_container = item.get("docker_container")
        if service_id is None or not docker_container:
            continue
        try:
            pred_ms = trainAndPredict({"service": docker_container})
            runtimes[str(service_id)] = int(pred_ms) if pred_ms and pred_ms > 0 else 1000
        except Exception as e:
            print(f"[DEBUG] trainAndPredict error for service_id {service_id}: {e}")
            runtimes[str(service_id)] = 1000
    payload = f"PREDICT_RESPONSE:{correlation_id}|{user_id}|{json.dumps(runtimes)}"
    mclient.publish(topic=reply_topic, payload=payload.encode("utf-8"), qos=1)
    print(f"[DEBUG] Published PREDICT_RESPONSE to {reply_topic} for correlation_id {correlation_id}")

def on_subscribe(mqtt_client, userdata, mid, qos, properties=None):
    pass

# tell scheduler that this provider has started. waits for the request to get then proceeds.
# requests.get("http://"+controller_ip+":"+controller_port+"/providers/startup/"+user_id)

# Match scheduler/providers/views.py; define next to MQTT client so edits to this block stay consistent.
BROKER_ID = os.environ.get("MQTT_BROKER")
try:
    BROKER_PORT = int(os.environ.get("MQTT_PORT", "1884"))
except ValueError:
    BROKER_PORT = 1884
print("BROKER_ID: ", BROKER_ID)
print("BROKER_PORT: ", BROKER_PORT)

if not BROKER_ID:
    print("Error: MQTT_BROKER is not set. Set it to the same broker host as the scheduler (see views.py).")
    sys.exit(1)

mclient = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
# sets up LWT for non-procedural disconnections
LWT_TOPIC = f"{user_id}"
LWT_MESSAGE = "offline_non-procedurally"
mclient.will_set(topic=LWT_TOPIC, payload=LWT_MESSAGE, qos=2, retain=False)

mqtt_username = os.environ.get("MQTT_USERNAME")
mqtt_password = os.environ.get("MQTT_PASSWORD")
if mqtt_username:
    mclient.username_pw_set(mqtt_username, mqtt_password)

if _mqtt_env_truthy("MQTT_DEBUG"):
    ph_logger = logging.getLogger("paho.mqtt.client")
    ph_logger.setLevel(logging.DEBUG)
    mclient.enable_logger(ph_logger)

print(
    f"[MQTT] connecting to {BROKER_ID}:{BROKER_PORT} "
    f"(auth_username_env_set={bool(mqtt_username)}; CONNACK is async, see on_connect)"
)

mclient.on_connect = on_connect
mclient.on_connect_fail = on_connect_fail
mclient.on_message = on_message
mclient.on_subscribe = on_subscribe

try:
    mclient.connect(host=BROKER_ID, port=BROKER_PORT, keepalive=100)
except Exception as e:
    hint = ""
    if isinstance(e, OSError) and e.errno == 101:
        hint = (
            " No route to broker: confirm MQTT_BROKER in .env, ping that host from this machine, "
            "and check ip route / WiFi or VLAN."
        )
    print(
        f"Error: Failed to connect to MQTT broker {BROKER_ID}:{BROKER_PORT} - {e}.{hint}"
    )
    sys.exit(1)

# client subscribe is in on_connect
mclient.loop_start()

mclient.publish(topic="EVERYONE", payload="start_connect"+user_id, qos=2)
mclient.publish(topic="EVERYONE", payload="get_efficiency_score"+user_id, qos=2)

# Wait for subscription confirmation before sending user-specific messages
print("Waiting for scheduler subscription confirmation...")
timeout_counter = 0
while not subscription_confirmed and timeout_counter < 30:  # 30 second timeout
    time.sleep(1)
    timeout_counter += 1

if not subscription_confirmed:
    print("Warning: No subscription confirmation received, sending signals anyway...")
    mclient.publish(topic=user_id, payload="STARTUP", qos=2)
    mclient.publish(topic=user_id, payload="READY", qos=2)

def procedural_shutdown(sig, frame):
    print("Commencing procedural shutdown...")
    procedural_shutdown_event.set()
    # Replace HTTP NOT_READY signal with MQTT
    global mclient
    mclient.publish(topic=user_id, payload="NOT_READY", qos=2)

#This will call the shutdown_handler function when the SIGINT or SIGTERM signal is received from system
signal.signal(signal.SIGINT, procedural_shutdown)   # Ctrl+C induced signal
signal.signal(signal.SIGTERM, procedural_shutdown)  # we may not need to handle this signal    

#LINEAR REGRESSION LOGIC


#making all data into a list...
# Function to append data returned by run_docker() to a file
def append_data_to_file(data, filename):
    os.makedirs(os.path.dirname(filename), exist_ok=True) if os.path.dirname(filename) else None
    with open(filename, 'a') as file:
        file.write(json.dumps(data) + '\n')

def load_data_from_file(filename):
    data = []
    decoder = json.JSONDecoder()
    with open(filename, 'r') as file:
        for line in file:
            line = line.strip()
            while line:
                try:
                    obj, idx = decoder.raw_decode(line)
                    data.append(obj)
                    line = line[idx:].strip()
                except json.JSONDecodeError:
                    break
    # Clean the data by removing entries with 'DID NOT RECIEVE' values
    cleaned_data = []
    for item in data:
        # Check if any value contains 'DID NOT RECIEVE'
        has_invalid_data = any('DID NOT RECIEVE' in str(value) for value in item.values())
        if not has_invalid_data:
            cleaned_data.append(item)
        else:
            print(f"[DEBUG] Skipping corrupted training data entry: {item}")
    
    print(f"[DEBUG] Loaded {len(data)} entries, cleaned to {len(cleaned_data)} valid entries")
    return cleaned_data #returns a list

# Function to save the trained model to disk
def save_model(model, filename):
    with open(filename, 'wb') as file:
        pickle.dump(model, file)

# Function to load the trained model from disk
def load_model(filename):
    with open(filename, 'rb') as file:
        model = pickle.load(file)
    return model


def train_regression_model(training_data):
    print(f"[DEBUG] Training data length: {len(training_data)}")
    if len(training_data) > 0:
        print(f"[DEBUG] First training data sample: {training_data[0]}")
        print(f"[DEBUG] Data types in first sample:")
        for key, value in training_data[0].items():
            print(f"  {key}: {type(value)} = {value}")
    
    X = []
    y = []
    for i, data in enumerate(training_data):
        try:
            # Convert to float to ensure numeric values
            cpu_usage = float(data["cpu_usage"])
            memory_usage = float(data["memory_usage"])
            cpu_eff = float(data["cpu_efficiency_score"])
            memory_eff = float(data["memory_efficiency_score"])
            runtime = float(data["actual_runtime"])
            
            X.append([cpu_usage * cpu_eff, memory_usage * memory_eff])
            y.append(runtime)
            print(f"[DEBUG] Sample {i}: cpu={cpu_usage}, mem={memory_usage}, runtime={runtime}")
        except (ValueError, TypeError, KeyError) as e:
            print(f"[DEBUG] Error processing training sample {i}: {e}")
            print(f"[DEBUG] Problematic data: {data}")
            # Skip samples with 'DID NOT RECIEVE' or other invalid data
            if 'DID NOT RECIEVE' in str(data.values()):
                print(f"[DEBUG] Skipping sample with 'DID NOT RECIEVE' data")
            continue
    
    if len(X) == 0:
        print("[DEBUG] No valid training data found, returning dummy model")
        # Return a dummy model that predicts 1000ms for any input
        class DummyModel:
            def predict(self, X):
                return np.array([1000.0] * len(X))
        return DummyModel()
    
    print(f"[DEBUG] Training model with {len(X)} samples")
    model = LinearRegression()
    model.fit(X, y)
    return model

def predict_runtime(service, provider, model):
    print(f"[DEBUG] predict_runtime called with service: {service}")
    
    try:
        ref_service_list = load_data_from_file("TrainingData/Reference_Provider_Data.txt")
        print(f"[DEBUG] Reference service list length: {len(ref_service_list)}")
        
        reference_cpu_usage = None
        reference_memory_usage = None
        
        for item in ref_service_list:
            if(item['service']==service):
                reference_cpu_usage = float(item['cpu_usage'])
                reference_memory_usage = float(item['memory_usage'])
                print(f"[DEBUG] Found reference data: cpu={reference_cpu_usage}, mem={reference_memory_usage}")
                break
        
        if reference_cpu_usage is None:
            print(f"[DEBUG] No reference data found for service {service}, using defaults")
            reference_cpu_usage = 1000.0  # Default CPU usage
            reference_memory_usage = 1000.0  # Default memory usage
            
        global cpu_efficiency_score, memory_efficiency_score
        print(f"[DEBUG] Efficiency scores: cpu={cpu_efficiency_score}, mem={memory_efficiency_score}")

        # For training in scheduler, instead of globals use provider.cpu_efficiency_score and provider.memory_efficiency_score
        X = np.array([[reference_cpu_usage * float(cpu_efficiency_score), reference_memory_usage * float(memory_efficiency_score)]])
        print(f"[DEBUG] Input features X: {X}")
        
        prediction = model.predict(X)
        print(f"[DEBUG] Model prediction: {prediction}")
        return prediction
        
    except Exception as e:
        print(f"[DEBUG] Error in predict_runtime: {e}")
        import traceback
        traceback.print_exc()
        # Return a default prediction
        return np.array([1000.0])


def trainAndPredict(run_vars):
    #run_vars has  cpu_usage, memory_usage, actual_runtime (of providers required for training not prediction) they will be loaded from file
    #It also has service (task link) (to get corresponding reference stats), eff_scores for training+prediction the ones which we use in this function
    #TRAINING
    print("running predictions inside trainAndPredict")
    print(f"[DEBUG] run_vars: {run_vars}")
    
    try:
        training_data=load_data_from_file("TrainingData/eff_score_data.txt")
        print(f"[DEBUG] Loaded training data from file")
        model = train_regression_model(training_data)
        print(f"[DEBUG] Model trained successfully")
        
        #PREDICTION
        provider_id = 0 # this provider would be used if this training and prediction were to run in the scheduler. Here it is useless as we use globals.
        predicted_runtime = predict_runtime(run_vars['service'], provider_id, model)
        print(f"[DEBUG] Prediction completed: {predicted_runtime}")
        return predicted_runtime[0]
        
    except Exception as e:
        print(f"[DEBUG] Error in trainAndPredict: {e}")
        import traceback
        traceback.print_exc()
        # Return a default prediction
        return 1000.0


def run_docker(body, container_name, inputData=None):
    start_pull_time = time.time()
    #image = client.images.pull(body)
    print("inside run_docker with body : " + body)
    image = imagePuller.request_image(body)
    print("Out of Hybrid Caching manager and inside run_docker again")
    print(image)
    pull_time = int((time.time() - start_pull_time) *1000)
    
    start_run_time = 0
    cont = None
    if inputData == None:
        # result = client.containers.run(body, name=container_name)
        try:
            cont = client.containers.run(image, name=container_name, detach=True)
        except Exception as e:
            print(e)
            container_name += "t"
            cont = client.containers.run(image, name=container_name, detach=True)
        # cont = client.containers.get(container_name)
        # cont.start()
        
    else:    
        try:
            cont = client.containers.run(image, command=str(inputData), name=container_name, detach=True)
        except Exception as e:
            print(e)
            container_name += "n"
            cont = client.containers.run(image, command=str(inputData), name=container_name, detach=True)
        # cont = client.containers.get(container_name)
        # cont.start()

    start_run_time = time.time()
    result = "this is result" #remove this line uncomment below line
    #result = result.decode("utf-8") #this gives the Hello from Docker msg.
    print("Run Started!")
    print(body)
    timeout = 3000
    stack = []
    run_vars = {}
    #cont = client.containers.get(container_name)
    count = 0
    if(cont==None):print("cont is None")
    while ((cont != None) and ((str(cont.status) == 'running') or (str(cont.status) == 'created'))):
        if(time.time()-start_run_time > timeout):
            print("timeout exceeded (cont not killed)")
            break
        #elapsed_time += stop_time
        s = cont.stats(decode=False, stream=False)
        if(s['memory_stats'] != {}):
            #stack.clear() #to get stats streamed throughout the process remove this line
            stack.clear() #only to save time
            stack.append(s)
        else: break
        count+=1

    #print(stack) #uncomment this to get full stats
    run_time = int((time.time() - start_run_time)*1000)
    #print(count)
    # run_vars['time_indexed_stats'] = time_indexed_stats
    run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
    run_vars['cpu_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
    #adding new lines for io_usage
    # blkio_read=0
    # blkio_write=0
    # for entry in stack[0]['blkio_stats']['io_service_bytes_recursive']:
    #     if entry['op'] == 'Read':
    #         blkio_read += entry['value']
    #     elif entry['op'] == 'Write':
    #         blkio_write += entry['value']
    # run_vars['io_read_stats'] = blkio_read
    # run_vars['io_write_stats'] = blkio_write
    #updated code till here
    run_vars['actual_runtime'] = run_time
    global cpu_efficiency_score
    run_vars['cpu_efficiency_score'] = cpu_efficiency_score
    global memory_efficiency_score
    run_vars['memory_efficiency_score'] = memory_efficiency_score
    # the below is service specific and has to be made for each service.
    append_data_to_file(run_vars, 'TrainingData/eff_score_data.txt')
    run_vars['service']=body # this is the task link

    print("Predicted Runtime:")
    print(trainAndPredict(run_vars))
    #print(predict_runtime(model, run_vars['time_indexed_stats'])) #a list of stats with timestamps
    print("Actual Runtime " + str(run_time))
    # Plot real-time predictions
    #plot_predictions(predictions)
    return result, pull_time, run_time, container_name

def monitor_container(cont, start_run_time, timeout):
    stack = []
    count = 0
    print(f"[DEBUG] monitor_container started for container: {cont.name if cont else 'None'}")
    
    while(str(cont.status)=='created'):
        cont.reload()
        print(f"[DEBUG] Container status: {cont.status}")
        time.sleep(0.5)  # Wait for container to start
    
    while ((cont != None) and ((str(cont.status) == 'running') )):
        if(time.time()-start_run_time > timeout):
            print("timeout exceeded (cont not killed)")
            # Force kill the container if it's been running too long
            try:
                cont.kill()
                print(f"[DEBUG] Container killed due to timeout")
            except Exception as e:
                print(f"[DEBUG] Error killing container: {e}")
            break
        s = cont.stats(decode=False, stream=False)
        print(f"[DEBUG] Container stats - memory_stats empty: {s['memory_stats'] == {}}")
        if(s['memory_stats'] != {}):
            stack.clear()
            stack.append(s)
            print(f"[DEBUG] Added stats to stack, stack length: {len(stack)}")
        else: 
            print(f"[DEBUG] Memory stats empty, but continuing monitoring (container may still be starting)")
            # Don't break immediately - container might still be starting up
            # Only break if we've been monitoring for a while and still no stats
            if count > 5:  # After 10+ seconds of no stats, then break
                print(f"[DEBUG] No memory stats after {count} checks, breaking monitoring loop")
                break
        
        # Always try to get stats, even if memory_stats is empty
        # This ensures we capture stats when the container exits
        if not stack:  # Only add if stack is empty
            stack.append(s)
            print(f"[DEBUG] Added stats to stack (even with empty memory_stats), stack length: {len(stack)}")
        count+=1
        
        # Add a delay to prevent excessive CPU usage and allow container to finish
        time.sleep(2)  # Check every 2 seconds instead of continuously
        
        # Reload container status to check if it's still running
        try:
            cont.reload()
            print(f"[DEBUG] Container status check: {cont.status}")
        except Exception as e:
            print(f"[DEBUG] Error reloading container: {e}")
            break
    
    print(f"[DEBUG] monitor_container finished, returning stack with length: {len(stack)}")
    return stack

def get_docker_host_ip():
    """Get the IP address to reach the host from inside a container"""
    try:
        # First try to get the default gateway (works when provider runs in container)
        result = subprocess.run(['ip', 'route', 'show', 'default'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            gateway_ip = result.stdout.split()[2]
            return gateway_ip
    except:
        pass
    
    try:
        # Fallback: try to get Docker bridge IP
        result = subprocess.run(['docker', 'network', 'inspect', 'bridge'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            import json
            bridge_info = json.loads(result.stdout)
            gateway = bridge_info[0]['IPAM']['Config'][0]['Gateway']
            return gateway
    except:
        pass
    
    # Last resort fallbacks
    try:
        # Try host.docker.internal (works on Docker Desktop)
        socket.gethostbyname('host.docker.internal')
        return 'host.docker.internal'
    except:
        pass
    
    # If all else fails, return localhost (might work in some setups)
    return '10.1.19.76'

def run_and_invoke_docker(body, container_name) -> dict:
    try:
        print(f"[DEBUG] run_and_invoke_docker started with body: {body}, container_name: {container_name}")
        #open a file and write the payload to it
        #with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        #    json.dump(payload, f)
        #    f.flush()
        #    input_file = f.name

        # Create output file
        #output_file = tempfile.NamedTemporaryFile(delete=False).name
                
        # Mount configurations for both input and output files
        #mounts = {
        #    input_file: {'bind': '/tmp/input.json', 'mode': 'ro'},
        #    output_file: {'bind': '/tmp/output.json', 'mode': 'rw'}
        #}

        start_pull_time = time.time()
        #image = client.images.pull(body)
        print("inside run_and_invoke_docker with body : " + body)
        print(f"[DEBUG] Requesting image: {body}")
        image = imagePuller.request_image(body)
        print("Out of Hybrid Caching manager and inside run_and_invoke_docker again")
        print(f"[DEBUG] Image obtained: {image}")
        pull_time = int((time.time() - start_pull_time) *1000)
        print(f"[DEBUG] Image pull time: {pull_time}ms")
        
        start_run_time = time.time()
        cont = None
        # Safely parse benchmark number from task_link
        try:
            benchmark_no=body.split("/")[1].split(".")[1] # get number from peercompute/benchmark.010....
            payload=get_payload(benchmark_no, "large")
        except (IndexError, AttributeError):
            # Fallback for simple task names like "hello-world"
            print(f"[DEBUG] Could not parse benchmark number from '{body}', using simple payload")
            payload = {"message": "Hello from simple task", "input": "test"}  # Simple payload for basic containers
        except ImportError as import_err:
            # Handle import errors with detailed information about the source
            import traceback
            error_trace = traceback.format_exc()
            print(f"[DEBUG] ImportError in get_payload for benchmark {benchmark_no}:")
            print(f"[DEBUG] Error: {str(import_err)}")
            print(f"[DEBUG] Full traceback:")
            for line in error_trace.split('\n'):
                print(f"[DEBUG]   {line}")
            # Extract the source file from the traceback
            for line in error_trace.split('\n'):
                if 'File "' in line and 'invocations' in line:
                    print(f"[DEBUG] SOURCE OF ERROR: {line.strip()}")
            raise  # Re-raise to be caught by outer exception handler
        # Temporarily override payload with a fixed value
        
        print(payload)
        response = None
        future=None
        host_port = None  # Initialize host_port before try block
        try:
            print("container started running")
            print(f"[DEBUG] Creating container with name: {container_name}")
            cont = client.containers.run(image,
                                         name=container_name,
                                         detach=True,
                                         ports={'8080/tcp': None}, #None dynamically allocates a port
                                         environment={
                                             'AWS_ACCESS_KEY_ID': 'AKIA3KAG6W36BSXOEHWD',
                                             'AWS_SECRET_ACCESS_KEY': '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', 
                                             'AWS_REGION': 'ap-south-1'
                                         }
                                         )
            print(f"[DEBUG] Container created successfully: {cont.id}")
            
            # Wait a bit for container to start
            time.sleep(2)  # Increased wait time
            cont.reload()  # Refresh container data
            print(f"[DEBUG] Container reloaded, status: {cont.status}")
            
            # Check if container is actually running
            if cont.status != 'running':
                print(f"[DEBUG] ERROR: Container is not running! Status: {cont.status}")
                # Try to get container logs to see what happened
                try:
                    logs = cont.logs().decode('utf-8')
                    print(f"[DEBUG] Container logs: {logs}")
                except Exception as e:
                    print(f"[DEBUG] Could not get container logs: {e}")
                raise Exception(f"Container failed to start properly. Status: {cont.status}")
            
            port_info = cont.ports.get('8080/tcp')
            print(f"[DEBUG] Port info: {port_info}")
            if port_info and len(port_info) > 0:
                host_port = port_info[0]['HostPort'] #get the port
                print(f"[DEBUG] Host port: {host_port}")
            else:
                print(f"[DEBUG] No port 8080 exposed, using default port 8080")
                host_port = "8080"  # Default port for containers without exposed ports
            
            # Additional container health check
            print(f"[DEBUG] Container ID: {cont.id}")
            print(f"[DEBUG] Container name: {cont.name}")
            print(f"[DEBUG] Container image: {cont.image}")
            print(f"[DEBUG] Container created: {cont.attrs.get('Created', 'Unknown')}")
            print(f"[DEBUG] Container state: {cont.attrs.get('State', 'Unknown')}")
            print("container name ID: ", cont.id)
            print("container name: ", cont.name)
            # Make POST request to container # blocking
            
        except Exception as e:
            print(e)

        finally:
            print(body)
            timeout = 3000
            print("monitoring container")
            print(f"[DEBUG] Starting container monitoring with timeout: {timeout}s")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor_for_cont_monitoring:
                # Submit the monitoring task to the executor
                future = executor_for_cont_monitoring.submit(monitor_container, cont, start_run_time, timeout)
                print("container monitored")
                
                # Only attempt HTTP request if container started successfully and host_port was assigned
                if host_port is not None and cont is not None:
                    # Get the appropriate host IP for container communication
                    host_ip = get_docker_host_ip()
                    print(f"Using host IP: {host_ip}")
                    
                    # Try localhost as fallback if the detected IP doesn't work
                    import socket
                    test_ips = [host_ip, "127.0.0.1", "localhost"]
                    working_ip = None
                    
                    for test_ip in test_ips:
                        try:
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(2)
                            result = sock.connect_ex((test_ip, int(host_port)))
                            sock.close()
                            if result == 0:
                                working_ip = test_ip
                                print(f"[DEBUG] Found working IP: {test_ip}")
                                break
                            else:
                                print(f"[DEBUG] IP {test_ip} not accessible")
                        except Exception as e:
                            print(f"[DEBUG] IP {test_ip} test failed: {e}")
                    
                    if working_ip:
                        host_ip = working_ip
                        print(f"[DEBUG] Using working IP: {host_ip}")
                    else:
                        print(f"[DEBUG] No working IP found, using original: {host_ip}")
                    
                    # Check container logs before making request
                    try:
                        logs = cont.logs(tail=10).decode('utf-8')
                        print(f"[DEBUG] Container logs (last 10 lines): {logs}")
                    except Exception as e:
                        print(f"[DEBUG] Could not get container logs: {e}")
                    
                    # Test if port is accessible (using the working IP we found)
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(5)
                        result = sock.connect_ex((host_ip, int(host_port)))
                        sock.close()
                        if result == 0:
                            print(f"[DEBUG] Port {host_port} is accessible on {host_ip}")
                        else:
                            print(f"[DEBUG] Port {host_port} is NOT accessible on {host_ip} (connection failed)")
                    except Exception as e:
                        print(f"[DEBUG] Port accessibility test failed: {e}")
                    
                    print(f"[DEBUG] Making POST request to http://{host_ip}:{host_port}")
                    print(f"[DEBUG] Request payload: {payload}")
                    try:
                        response = requests.post(f'http://{host_ip}:{host_port}', 
                                            json=payload,
                                            headers={'Content-Type': 'application/json'},
                                            timeout=30)  # Increased timeout to 5 minutes (300 seconds)
                        print(f"[DEBUG] POST request completed with status: {response.status_code}")
                        print("post request sent")
                    except requests.exceptions.RequestException as e:
                        print(f"[DEBUG] POST request failed: {e}")
                        # Try GET request as fallback
                        try:
                            print(f"[DEBUG] Trying GET request as fallback...")
                            response = requests.get(f'http://{host_ip}:{host_port}', timeout=10)
                            print(f"[DEBUG] GET request completed with status: {response.status_code}")
                        except requests.exceptions.RequestException as e2:
                            print(f"[DEBUG] GET request also failed: {e2}")
                            response = None
                else:
                    print(f"[DEBUG] Skipping HTTP request - container failed to start or host_port not assigned (host_port={host_port}, cont={cont})")
                    response = None

            #result = "this is result" #remove this line uncomment below line
            #result = result.decode("utf-8") #this gives the Hello from Docker msg.

            print(f"[DEBUG] Getting monitoring results from future")
            try:
                stack=future.result()
                print(f"[DEBUG] Monitoring results - stack length: {len(stack) if stack else 'None'}")
                print(f"[DEBUG] Stack content: {stack}")
            except Exception as e:
                print(f"[DEBUG] Exception getting monitoring results: {e}")
                stack = []
            
            run_vars={}
            # Read result from output file
            #with open(output_file, 'r') as f:
            #    result = f.read()
            #print("Result from container:", result)
            #print(response.json())
            try:
                if response is not None:
                    result = response.json()
                    print(f"[DEBUG] Response result: {result}")
                else:
                    result = {"error": "No response received from container"}
                    print(f"[DEBUG] No response received, using default result: {result}")
            except Exception as e:
                print(f"[DEBUG] Exception parsing response JSON: {e}")
                result = {"error": f"Failed to parse response: {str(e)}"}
            
            print(stack) #uncomment this to get full stats
            run_time = int((time.time() - start_run_time)*1000) # get in ms
            print(f"[DEBUG] Run time: {run_time}ms")
            #print(count)
            # run_vars['time_indexed_stats'] = time_indexed_stats
    
            print(f"[DEBUG] About to access stack[0] - stack length: {len(stack) if stack else 'None'}")
            if stack and len(stack) > 0:
                print(f"[DEBUG] Accessing stack[0] - memory_stats: {stack[0].get('memory_stats', 'NOT_FOUND')}")
                print(f"[DEBUG] Accessing stack[0] - cpu_stats: {stack[0].get('cpu_stats', 'NOT_FOUND')}")
                
                # Safely extract memory usage
                memory_stats = stack[0].get('memory_stats', {})
                if 'usage' in memory_stats:
                    run_vars['memory_usage'] = memory_stats['usage']
                    print(f"[DEBUG] Successfully extracted memory_usage: {run_vars['memory_usage']}")
                else:
                    run_vars['memory_usage'] = 100000000  # 100MB default
                    print(f"[DEBUG] No memory usage in stats, using default: {run_vars['memory_usage']}")
                
                # Safely extract CPU usage
                cpu_stats = stack[0].get('cpu_stats', {})
                cpu_usage = cpu_stats.get('cpu_usage', {})
                if 'total_usage' in cpu_usage:
                    run_vars['cpu_usage'] = cpu_usage['total_usage']
                    print(f"[DEBUG] Successfully extracted cpu_usage: {run_vars['cpu_usage']}")
                else:
                    run_vars['cpu_usage'] = 1000000000  # 1 second of CPU time default
                    print(f"[DEBUG] No CPU usage in stats, using default: {run_vars['cpu_usage']}")
            else:
                print(f"[DEBUG] ERROR: Stack is empty or None! Cannot access stack[0]")
                print(f"[DEBUG] Setting default values for memory_usage and cpu_usage")
                # Use more realistic default values instead of 0
                run_vars['memory_usage'] = 100000000  # 100MB default
                run_vars['cpu_usage'] = 1000000000    # 1 second of CPU time default
            #adding new lines for io_usage
            # blkio_read=0
            # blkio_write=0
            # for entry in stack[0]['blkio_stats']['io_service_bytes_recursive']:
            #     if entry['op'] == 'Read':
            #         blkio_read += entry['value']
            #     elif entry['op'] == 'Write':
            #         blkio_write += entry['value']
            # run_vars['io_read_stats'] = blkio_read
            # run_vars['io_write_stats'] = blkio_write
            #updated code till here
            run_vars['actual_runtime'] = run_time
            global cpu_efficiency_score
            run_vars['cpu_efficiency_score'] = cpu_efficiency_score
            global memory_efficiency_score
            run_vars['memory_efficiency_score'] = memory_efficiency_score
            # the below is service specific and has to be made for each service.
            print(f"[DEBUG] Appending runtime data to file")
            append_data_to_file(run_vars, 'TrainingData/eff_score_data.txt')
            run_vars['service']=body # this is the task link
            print("runtime data: ")
            print(run_vars)
            print("Predicted Runtime:")
            print(trainAndPredict(run_vars))
            #print(predict_runtime(model, run_vars['time_indexed_stats'])) #a list of stats with timestamps
            print("Actual Runtime " + str(run_time))
            # Plot real-time predictions
            #plot_predictions(predictions)

            # Cleanup temporary files
            #os.unlink(input_file)
            #os.unlink(output_file)
            print(f"[DEBUG] Stopping and removing container: {container_name}")
            try:
                cont.stop()  #remove this line to keep container running
                cont.remove()
                print(f"[DEBUG] Container stopped and removed successfully")
            except Exception as e:
                print(f"[DEBUG] Exception stopping/removing container: {e}")
            
            print(f"[DEBUG] run_and_invoke_docker completed successfully for container: {container_name}")
            return result, pull_time, run_time, container_name, run_vars
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[DEBUG] Exception in run_and_invoke_docker: {e}")
        print(f"[DEBUG] Full traceback:")
        for line in error_trace.split('\n'):
            print(f"[DEBUG]   {line}")
        
        # Extract source information for import errors
        if isinstance(e, ImportError) or "ModuleNotFoundError" in str(type(e)) or "No module named" in str(e):
            print(f"[DEBUG] === IMPORT ERROR SOURCE ANALYSIS ===")
            for line in error_trace.split('\n'):
                if 'File "' in line and ('invocations' in line or 'import' in line.lower()):
                    print(f"[DEBUG] SOURCE FILE: {line.strip()}")
                if 'from ' in line or 'import ' in line:
                    print(f"[DEBUG] FAILED IMPORT: {line.strip()}")
            print(f"[DEBUG] =====================================")
        
        traceback.print_exc()
        # Return default values to prevent the function from crashing
        return {"error": str(e)}, 0, 0, container_name, None

def delete_container_and_image(body, container_name):
    print(f"[DEBUG] delete_container_and_image called with body: {body}, container_name: {container_name}")
    try:
        filters = {'name': container_name}
        containers = client.containers.list(all=True, filters=filters)
        print(f"[DEBUG] Found {len(containers)} containers with name {container_name}")
        if containers:
            container_id = containers[0]
            container_id.remove()
            print(f"[DEBUG] Container {container_name} removed successfully")
        else:
            print(f"[DEBUG] Container {container_name} not found, already removed")
    except Exception as e:
        print(f"[DEBUG] Exception in delete_container_and_image: {e}")
        # Don't let this prevent MQTT sending

    # client.images.remove(body)

def HF_set_time(job_code, t_time):
    global token
    response = HFRequests.invoke_set_time(token, channelName, chaincodeName, 'org2', job_code, t_time)
    if 'jwt expired' in response.text or 'jwt malformed' in response.text or 'User was not found' in response.text or 'UnauthorizedError' in response.text:
        token = HFRequests.register_user(user_id, 'Org2')
        response = HFRequests.invoke_set_time(token, channelName, chaincodeName, 'org2', job_code, t_time)
    return response

def HF_invoke_balance_transfer(receiver, sender):
    global token
    response = HFRequests.invoke_balance_transfer(receiver, sender, token, channelName, chaincodeName, 'org2')
    if 'jwt expired' in response.text or 'jwt malformed' in response.text or 'User was not found' in response.text or 'UnauthorizedError' in response.text:
        token = HFRequests.register_user(user_id, 'Org2')
        response = HFRequests.invoke_balance_transfer(receiver, sender, token, channelName, chaincodeName, 'org2')
    return response

def on_request(json_data) :
    # Replace HTTP ACK signal with MQTT
    global mclient
    print(f"[DEBUG] Starting job processing for job_id: {json_data['job_id']}")
    
    print(f"[DEBUG] About to send ACK signal for job_id: {json_data['job_id']}")
    mclient.publish(topic=user_id, payload="ACK:"+str(json_data['job_id']), qos=2)
    print(f"[DEBUG] ACK signal sent successfully for job_id: {json_data['job_id']}")
    
    # Replace HTTP NOT_READY signal with MQTT (set provider as busy during job execution)
    print(f"[DEBUG] About to send NOT_READY signal for provider: {user_id}")
    mclient.publish(topic=user_id, payload="NOT_READY", qos=2)
    print(f"[DEBUG] NOT_READY signal sent successfully for provider: {user_id}")
    
    if json_data['inputData'] == "None":
        json_data['inputData'] = None

    print("[on_request] in provider1.py")
    try:
        r, pull_time, run_time, container_name, run_vars = run_and_invoke_docker(json_data['task_link'], str(str(json_data['job_id'])+"_container_")) #TODO
        total_time = math.ceil(((pull_time + run_time)/100.0))*100 
        print(f"[DEBUG] pull_time: {pull_time}, run_time: {run_time}, total_time: {total_time}")
    except Exception as e:
        print(f"[DEBUG] Exception in run_and_invoke_docker: {e}")
        # Set default values to ensure MQTT sending still happens
        r = {"error": f"Container execution failed: {str(e)}"}
        pull_time = 0
        run_time = 0
        container_name = f"{json_data['job_id']}_container_"
        total_time = 0
        run_vars = None
    # HF_set_time(str(json_data['job_id']), total_time)
    # HF_invoke_balance_transfer(str(json_data['provider_id']), str(json_data['task_developer']))

    with open("results.csv", mode='a', newline='') as file:
    # Create a CSV writer object
        writer = csv.DictWriter(file, fieldnames=['PT', 'RT', 'TT'])        
        # Check if the file is empty, and if so, write the header
        if file.tell() == 0:
            writer.writeheader()
        data = {
            'PT':pull_time, 'RT': run_time, 'TT': total_time
        }
        # Write the data as a new row
        writer.writerow(data)


    print(f"[DEBUG] About to call delete_container_and_image for container: {container_name}")
    delete_container_and_image(json_data['task_link'], container_name)
    print(f"[DEBUG] delete_container_and_image completed for container: {container_name}")
    
    print(f"[DEBUG] Creating response object for job_id: {json_data['job_id']}")
    response = {'stage': "dockerrun", 'Result': r, 'pull_time': pull_time, 'run_time': run_time, 'total_time': total_time, 'job_id': json_data['job_id']}
    if run_vars:
        for key in ('memory_usage', 'cpu_usage', 'cpu_efficiency_score', 'memory_efficiency_score'):
            if key in run_vars:
                response[key] = run_vars[key]
    print(f"[DEBUG] Response object created: {response}")
    
    print(f"[DEBUG] About to send job result for job_id: {json_data['job_id']}")
    mclient.publish(user_id, json.dumps(response).encode("utf-8"),qos=2)
    print(f"[DEBUG] Job result sent successfully for job_id: {json_data['job_id']}")
    
    # Set provider as ready again after job completion
    print(f"[DEBUG] About to send READY signal for provider: {user_id}")
    mclient.publish(topic=user_id, payload="READY", qos=2)
    print(f"[DEBUG] READY signal sent successfully for provider: {user_id}")
    print("published response to scheduler")

def on_chained_request(json_data) :
    # Replace HTTP ACK signal with MQTT
    global mclient
    mclient.publish(topic=user_id, payload="ACK:"+str(json_data['job_id']), qos=2)
    # Replace HTTP NOT_READY signal with MQTT (set provider as busy during job execution)
    mclient.publish(topic=user_id, payload="NOT_READY", qos=2)
    
    responses = []
    pull_times = []
    run_times = []
    total_times = []
    if json_data['inputData'] == "None":
        json_data['inputData'] = None
    for i in range(json_data['numberOfInvocations']):
        container_name = str(json_data['job_id']) + "_container_" + str(i)
        r, pull_time, run_time = run_docker(json_data['task_link'], container_name, json_data['inputData'] if i == 0 else responses[-1])
        responses.append(r)
        pull_times.append(pull_time)
        run_times.append(run_time)
        total_time = math.ceil(((pull_time + run_time)/100.0))*100
        total_times.append(total_time)
        print(pull_time,run_time,total_time)
        delete_container_and_image(json_data['task_link'])
        with open("results.csv", mode='a', newline='') as file:
        # Create a CSV writer object
            writer = csv.DictWriter(file, fieldnames=['PT', 'RT', 'TT'])        
            # Check if the file is empty, and if so, write the header
            if file.tell() == 0:
                writer.writeheader()
            data = {
                'PT':pull_time, 'RT': run_time, 'TT': total_time
            }
            # Write the data as a new row
            writer.writerow(data)
    # print(responses, pull_times, run_times)
    # HF_set_time(str(json_data['job_id']), total_time)
    # HF_invoke_balance_transfer(str(json_data['provider_id']), str(json_data['task_developer']))
    # delete_container_and_image(json_data['task_link'])
    
    # Set provider as ready again after chained job completion
    mclient.publish(topic=user_id, payload="READY", qos=2)
    return {'Result': responses, 'pull_time': pull_times, 'run_time': run_times, 'total_time': total_times}

# data = {
#     "is_provider": True,
#     "is_developer": False,
#     "active": True,
#     "ready": True,
#     "location": "TEST_PROV_1",
#     "ram": 8,
#     "cpu": 4
# }

def calc_benchmark_stats():
    #TODO
    print("calculating bench mark stats")
    bench_container_name = "benchTest"
    bench_image = "satyam098/testimage_largeruntime"
    image = imagePuller.request_image(bench_image)
    try:
        cont = client.containers.run(image, name=bench_container_name)
    except Exception as e:
        print(e)
        container_name+='b'
        cont = client.containers.run(image, name=bench_container_name)
    print(cont)
    print(str(cont.status))
    start_run_time=time.time()
    timeout = 40 # how long will this benchmark test run in seconds
    stack=[]
    run_vars={}
    runtime=timeout
    while ((cont != None) and ((str(cont.status) == 'running') or (str(cont.status) == 'created'))):
        if(time.time()-start_run_time > timeout):
            print("timeout reached")
            cont.kill()
            break
        #elapsed_time += stop_time
        s = cont.stats(decode=False, stream=False)
        if(s['memory_stats'] != {}):
            #stack.clear() #to get stats streamed throughout the process remove this line
            stack.clear() #only to save time
            stack.append(s)
        else: break
        #if(cont.status=='running'):print("running")
        #else: print("Not running")
        #sleep(stop_time)
    delete_container_and_image(bench_image, bench_container_name)
    run_time = int((time.time() - start_run_time)*1000)
    run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
    run_vars['cpu_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
    run_vars['actual_runtime'] = run_time
    run_vars['timeout']=timeout*1000
    #adding new lines for io_usage
    blkio_read=0
    blkio_write=0
    for entry in stack[0]['blkio_stats']['io_service_bytes_recursive']:
        if entry['op'] == 'Read':
            blkio_read += entry['value']
        elif entry['op'] == 'Write':
            blkio_write += entry['value']
    run_vars['io_read_stats'] = blkio_read
    run_vars['io_write_stats'] = blkio_write
    #updated code till here
    print(user_id)
    benchmark = {user_id: run_vars}
    append_data_to_file(benchmark, "benchmark_results.txt")
    #store one run as the reference benchmark.
    #calc efficiency score from this benchmark.
    #update_model()
    #send mqtt topic a msg request to calculate eff score and update the model.
    global mclient
    mclient.publish(topic=user_id, payload="Benchmark:"+json.dumps(benchmark), qos=2)
    print(benchmark)
    return benchmark


def set_reference_stats_for_service(service_id):
    # Docker container names only allow [a-zA-Z0-9][a-zA-Z0-9_.-]; sanitize / and :
    safe_name = service_id.replace("/", "_").replace(":", "_")
    container_name = safe_name + "_reference_stats_"
    print(container_name)
    img = imagePuller.request_image(service_id)
    global client
    # Remove any existing container with this name (e.g. from a previous run or crash) to avoid 409 Conflict
    try:
        old = client.containers.get(container_name)
        old.remove(force=True)
    except Exception:
        pass
    # detach=True so we get a container object to monitor; without it run() returns bytes (log output)
    cont = client.containers.run(img, name=container_name, detach=True)
    start_run_time = time.time()
    timeout = 500  # how long will this service run on reference in seconds
    stack = []
    run_vars = {}
    try:
        while cont is not None:
            cont.reload()  # refresh status so we see 'exited' when container finishes
            if str(cont.status) not in ('running', 'created'):
                break
            if time.time() - start_run_time > timeout:
                print("timeout of 500 seconds reached in running service on the reference provider.")
                cont.kill()
                break
            try:
                s = cont.stats(decode=False, stream=False)
                if s.get('memory_stats'):
                    stack.clear()
                    stack.append(s)
            except Exception as e:
                print(f"[DEBUG] stats error: {e}")
                break
            time.sleep(0.5)  # avoid hammering Docker API; one stats sample every 0.5s is enough
        run_time = int((time.time() - start_run_time) * 1000)
        run_vars['service'] = service_id
        run_vars['actual_runtime'] = run_time
        if stack:
            run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
            run_vars['cpu_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
        else:
            # Short-lived container (e.g. hello-world) may exit before we get stats
            try:
                c = client.containers.get(container_name)
                s = c.stats(decode=False, stream=False)
                if s.get('memory_stats'):
                    run_vars['memory_usage'] = s['memory_stats']['usage']
                    run_vars['cpu_usage'] = s['cpu_stats']['cpu_usage']['total_usage']
                else:
                    run_vars['memory_usage'] = 0
                    run_vars['cpu_usage'] = 0
            except Exception as e:
                print(f"[DEBUG] no stats for short-lived container: {e}")
                run_vars['memory_usage'] = 0
                run_vars['cpu_usage'] = 0
    finally:
        try:
            cont.reload()
            if str(cont.status) != 'exited':
                cont.stop()
            cont.remove()
        except Exception as e:
            print(f"[DEBUG] cleanup: {e}")
    append_data_to_file(run_vars, 'TrainingData/Reference_Provider_Data.txt')
    global mclient
    # !IMPORTANT here user_id should actually be reference_user_id 
    mclient.publish(topic=user_id, payload="Stats for Reference Provider: "+json.dumps(run_vars), qos=2)
    return

# response = requests.POST(url=REGISTER_URL, data=data)
# user_id = response['user_id']

## mqtt implementation


def _run_predicted_runtime_http_server():
    """HTTP server for predicted_runtime requests (scheduler -> provider)."""

    class PredictedRuntimeHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/predicted_runtime":
                    qs = parse_qs(parsed.query)
                    service = (qs.get("service") or [None])[0]
                    if service:
                        pred_ms = trainAndPredict({"service": service})
                        body = json.dumps({"value": pred_ms}).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(body)
                    else:
                        self.send_response(400)
                        self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception as e:
                print(f"[DEBUG] PredictedRuntimeHandler error: {e}")
                self.send_response(500)
                self.end_headers()

        def log_message(self, format, *args):
            pass  # Suppress default logging

    try:
        httpd = HTTPServer(("0.0.0.0", PROVIDER_HTTP_PORT), PredictedRuntimeHandler)
        t = Thread(target=httpd.serve_forever)
        t.daemon = True
        t.start()
        print(f"Provider HTTP server listening on port {PROVIDER_HTTP_PORT} for /predicted_runtime")
    except Exception as e:
        print(f"Warning: Could not start provider HTTP server: {e}")


_run_predicted_runtime_http_server()

while True:
    if procedural_shutdown_event.is_set():
        time_since_last_message = time.time() - last_message_time 
        with pending_jobs_lock:
            if pending_jobs == 0 and time_since_last_message >= 2: #if no job is actively running and no queued messages have been recieved in the past two seconds it will break out of the while loop
                print("No pending jobs. Exiting main loop.")
                break
    else:        
        time.sleep(1) #or you can just do a=1

# After the loop, perform cleanup
# Stop the MQTT client
print("performing procedural shutdown")
mclient.publish(topic=LWT_TOPIC, payload="offline_procedurally", qos=2)
mclient.loop_stop()
mclient.disconnect()


print("All jobs completed. Exiting procedurally.")



def job_queue():
    q = None
    # take arguments of on_request function out them in a dict array.
    # execute it one after other.
    # communicate services in the 