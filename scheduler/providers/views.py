from collections import defaultdict
import time
import pulp
from django.apps import apps
from django.db import transaction
from django.shortcuts import render,get_object_or_404, redirect
import pika 
import json
import socket
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from providers.forms import ProviderForm
from profiles.models import User
from datetime import datetime, timedelta, tzinfo
import uuid
from providers.models import Job
from django.http import JsonResponse
from django.core.exceptions import ObjectDoesNotExist
from scheduler.settings import TIME_ZONE
from pytz import timezone
from django.contrib import messages
import paho.mqtt.client as mqtt
import queue
from profiles.models import *
from providers.models import *
from random import randint 
from scheduler.settings import USE_FABRIC
import fabric.views as fabric
import csv
import random
from providers.mincost import minimize_total_cost
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

global procedural_shutdown_penalty
procedural_shutdown_penalty = 0
global non_procedural_shutdown_penalty
non_procedural_shutdown_penalty = 0
global non_procedural_shutdown_multiplier
non_procedural_shutdown_multiplier = 0.67
global prediction_deviation_points
global prediction_deviation_points_multiplier
import scheduler.settings as settings
import os
import logging

_mqtt_log = logging.getLogger(__name__)

# Create your views here.
data_dict = None
# BROKER_ID = "broker.hivemq.com"
BROKER_ID = os.environ.get('MQTT_BROKER')
print("BROKER_ID: ", BROKER_ID)
BROKER_PORT = int(os.environ.get('MQTT_PORT', '1884'))
print("BROKER_PORT: ", BROKER_PORT)


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
    _mqtt_log.info(
        "[MQTT] connect context: host=%s port=%s client_id=%r auth_username_env_set=%s auth_password_env_set=%s",
        BROKER_ID,
        BROKER_PORT,
        cid,
        user_set,
        pw_set,
    )

def get_scheduler_id():
    """Get scheduler identifier from database User record"""
    try:
        # Try to find existing scheduler user record
        scheduler_name = os.environ.get('SCHEDULER_NAME', socket.gethostname())
        print("scheduler_name: ", scheduler_name)
        
        # Look for a User record that represents this scheduler
        # Sort by -last_ready_signal and choose the latest
        scheduler_user = User.objects.filter(
            location=scheduler_name,  # Use location field to identify scheduler
            active=True,
            ready=True,
        ).order_by('-last_ready_signal').first()
        
        if scheduler_user:
            return str(scheduler_user.user_136)
        else:
            return None
    except User.DoesNotExist:
        print("No scheduler user record found")
        return None # No scheduler user record found, return None
# BROKER_ID = "10.8.1.18"
reference_provider_id = 'ff898965-5c47-41af-b447-5b538a0c7847'
file_path = "/home/user/Documents/Serverless_Scheduler/SchedInfo.csv"

mclient = None
# MQTT predicted runtimes: correlation_id -> { 'results': { provider_user_id: { service_id: runtime } }, 'expected_providers': set, 'event': Event }
pending_predictions = {}
pending_predictions_lock = threading.Lock()

global service_id_array 
global service_queue
service_id_array = {}
service_queue = queue.Queue()
global requested_services


def _get_predict_response_topic():
    """Topic where scheduler receives PREDICT_RESPONSE from providers."""
    return f"SCHEDULER_{os.environ.get('SCHEDULER_NAME', socket.gethostname())}/predict_response"

# Helpers
def load_data_as_dict(file_path):
    all_data = {}
    with open(file_path, 'r') as file:
        for line in file:
            data_dict = json.loads(line.strip())
            all_data.update(data_dict)
    return all_data

def update_efficiency_score_in_models(user_id, provider_cpu_usage, provider_memory_usage, reference_cpu_usage, reference_memory_usage):
    print("updating models... with r_cpu= ", reference_cpu_usage, " r_mem= ", reference_memory_usage, " p_cpu= ", provider_cpu_usage, " p_mem= ", provider_memory_usage)
    # uncomment after adding column to database tables
    provider= User.objects.get(user_id=user_id)
    provider.cpu_efficiency_score = provider_cpu_usage/reference_cpu_usage
    provider.memory_efficiency_score = provider_memory_usage/reference_memory_usage
    provider.save()

def get_benchmarks_for(user_id, benchmark):
    benchmarks = load_data_as_dict("benchmark_results.txt")
    reference_stats=benchmarks[benchmarks['Reference']]
    reference_cpu_usage= reference_stats['cpu_usage']
    reference_memory_usage= reference_stats['memory_usage']
    provider_cpu_usage = benchmark[user_id]['cpu_usage']
    provider_memory_usage = benchmark[user_id]['memory_usage']
    print(reference_stats)
    update_efficiency_score_in_models(user_id,provider_cpu_usage, provider_memory_usage, reference_cpu_usage, reference_memory_usage)

def penalise(user_id, penalty_type):
    provider = User.objects.get(user_id=user_id)
    if penalty_type == 1:
        provider.reputation_score -= service_queue.qsize()*non_procedural_shutdown_multiplier + non_procedural_shutdown_penalty #queuesize + fix penalty
        print("Penalised provider ", user_id, " for quitting non-procedurally")
        #TODO reallocation of jobs not done yet.
    elif penalty_type == 0:
        provider.reputation_score -= procedural_shutdown_penalty
        print("Did not penalise provider ", user_id, " for quitting procedurally")
    provider.save()

# mqtt client callbacks:
def send_heartbeat(mqtt_client, scheduler_name):
    """Send periodic heartbeat to load balancers"""
    while True:
        try:
            heartbeat_payload = {
                'scheduler_name': scheduler_name,
                'timestamp': time.time(),
                'status': 'active'
            }
            mqtt_client.publish(
                topic="EVERYONE",  # All load balancers listen to this
                payload="SCHEDULER_PONG:" + json.dumps(heartbeat_payload),
                qos=1
            )
            time.sleep(30)  # Send heartbeat every 10 seconds
        except Exception as e:
            print(f"Error sending heartbeat: {e}")
            time.sleep(5)

def on_connect(mqtt_client, userdata, flags, reason_code, properties):
    # paho CallbackAPIVersion.VERSION2: (client, userdata, flags, reason_code, properties)
    if reason_code == 0:
        _mqtt_log.info(
            "[MQTT] on_connect OK: flags=%r properties=%r",
            flags,
            properties,
        )
        print("=== SCHEDULER MQTT CONNECTION ESTABLISHED ===")
        
        # Subscribe to core topics
        mqtt_client.subscribe(topic="EVERYONE")
        mqtt_client.subscribe("ROTATION")
        print("Subscribed to core topics: EVERYONE, ROTATION")
        
        # Get scheduler name from environment or hostname
        scheduler_name = os.environ.get('SCHEDULER_NAME', socket.gethostname())
        print(f"Scheduler name: {scheduler_name}")
        scheduler_topic = f"SCHEDULER_{scheduler_name}"
        
        # Subscribe to scheduler-specific topic
        mqtt_client.subscribe(scheduler_topic)
        print(f"Subscribed to scheduler-specific topic: {scheduler_topic}")
        
        # Subscribe to predict_response topic for MQTT-based predicted runtimes
        predict_response_topic = f"{scheduler_topic}/predict_response"
        mqtt_client.subscribe(predict_response_topic)
        print(f"Subscribed to predict_response topic: {predict_response_topic}")
        
        # Subscribe to SCHEDULER_ANNOUNCEMENTS to receive other scheduler announcements
        mqtt_client.subscribe("SCHEDULER_ANNOUNCEMENTS")
        print("Subscribed to SCHEDULER_ANNOUNCEMENTS topic")
        
        print(f"=== SCHEDULER SUBSCRIPTION SUMMARY ===")
        print(f"Scheduler Name: {scheduler_name}")
        print(f"Scheduler Topic: {scheduler_topic}")
        print(f"Subscribed Topics:")
        print(f"  - EVERYONE (provider signals, heartbeats)")
        print(f"  - ROTATION (ILP coordination)")
        print(f"  - {scheduler_topic} (load balancer requests)")
        print(f"  - SCHEDULER_ANNOUNCEMENTS (scheduler discovery)")
        print(f"  - Individual provider topics (dynamically added)")
        print("=============================================")
        
        # Announce scheduler identity to load balancers
        announcement = {
            'scheduler_name': scheduler_name,
            'scheduler_topic': scheduler_topic,
            'status': 'online',
            'timestamp': time.time()
        }
        mqtt_client.publish(
            topic="SCHEDULER_ANNOUNCEMENTS",
            payload=json.dumps(announcement),
            qos=1
        )
        print(f"Announced scheduler identity: {scheduler_name}")
        
        # Start heartbeat thread
        heartbeat_thread = threading.Thread(target=send_heartbeat, args=(mqtt_client, scheduler_name))
        heartbeat_thread.daemon = True
        heartbeat_thread.start()
        print("Started heartbeat thread")
    else:
        detail = _mqtt_format_connack(reason_code, properties)
        _mqtt_log.warning("[MQTT] on_connect refused: %s", detail)
        print(f"Bad connection to mqtt from views.py/providers. {detail}")


def on_connect_fail(mqtt_client, userdata):
    """Fired when TCP/TLS fails before a CONNACK (no broker MQTT response)."""
    sock_err = None
    try:
        sock = getattr(mqtt_client, "socket", None)
        if sock is not None:
            sock_err = getattr(sock, "error", None)
    except Exception:
        sock_err = "unavailable"
    _mqtt_log.warning(
        "[MQTT] on_connect_fail: could not complete connect to %s:%s (socket_error=%r). "
        "Check host/port, firewall, TLS vs plain, and that the broker is listening.",
        BROKER_ID,
        BROKER_PORT,
        sock_err,
    )
    print(
        f"[MQTT] connect_fail before CONNACK to {BROKER_ID}:{BROKER_PORT} "
        f"(see Django logs for details; set MQTT_DEBUG=1 for paho wire logs)"
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
    _mqtt_log.warning("[MQTT] on_disconnect: %s", detail)

def on_message(mqtt_client, userdata, msg):
    print('from views.py/providers ')
    print(f'Received message on topic: {msg.topic} with payload: {msg.payload}')
    # Try to parse as JSON first (for job completion messages)
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        
        # Only process messages with 'stage' field (job completion messages)
        if 'stage' in data:
            if(data['stage'] == 'dockernotrun'): 
                print("pulled but docker not run")
            if(data['stage'] == 'dockerrun'):
                print(f"data[stage]==dockerrun works")
                print(data)
                try:
                    finish_job(data)
                except Exception as finish_error:
                    print(f"ERROR: Exception in finish_job: {str(finish_error)}")
                    import traceback
                    traceback.print_exc()
            # Job completion message processed, return early
            return
        # If JSON message doesn't have 'stage', it's not a job completion message
        # Continue below to handle as a string message (signals, etc.)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # JSON parsing failed - continue to handle as string message below
        pass
    except Exception as e:
        # Other errors during JSON processing
        print(f"Error processing JSON message: {str(e)}")
        import traceback
        traceback.print_exc()
        # Continue to handle as string message
    
    # Handle non-JSON messages (signals, etc.) or JSON messages without 'stage'
    try:
        print(msg.topic, msg.payload.decode("utf-8"))
        payload_str = msg.payload.decode("utf-8")
        
        # Handle PREDICT_RESPONSE (MQTT predicted runtimes from providers)
        if msg.topic == _get_predict_response_topic() and payload_str.startswith("PREDICT_RESPONSE:"):
            try:
                rest = payload_str[len("PREDICT_RESPONSE:"):]
                parts = rest.split("|", 2)
                if len(parts) >= 3:
                    correlation_id, provider_user_id, runtimes_json = parts[0], parts[1], parts[2]
                    runtimes = json.loads(runtimes_json)
                    with pending_predictions_lock:
                        if correlation_id in pending_predictions:
                            pending_predictions[correlation_id]["results"][provider_user_id] = runtimes
                            pending_predictions[correlation_id]["expected_providers"].discard(provider_user_id)
                            if not pending_predictions[correlation_id]["expected_providers"]:
                                pending_predictions[correlation_id]["event"].set()
                    print(f"PREDICT_RESPONSE received from {provider_user_id} for correlation_id {correlation_id}")
            except Exception as e:
                print(f"Error processing PREDICT_RESPONSE: {e}")
            return
        
        # Handle new MQTT-based provider signals
        if payload_str == "STARTUP":
            print(f"Provider {msg.topic} sent STARTUP signal via MQTT")
            # Call the same logic as providerStartup HTTP endpoint
            try:
                providerStartup_mqtt(msg.topic)
                # Provider is already connected via MQTT, just acknowledge
            except Exception as e:
                print(f"Error handling STARTUP signal from {msg.topic}: {str(e)}")
                
        elif payload_str == "READY":
            print(f"=== PROVIDER READY SIGNAL RECEIVED ===")
            print(f"Provider {msg.topic} sent READY signal via MQTT")
            print(f"Topic: {msg.topic}")
            print(f"Payload: {payload_str}")
            print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("=========================================")
            # Call the same logic as ready HTTP endpoint
            try:
               ready_mqtt(msg.topic)
               print(f"Successfully processed READY signal from provider {msg.topic}")
            except User.DoesNotExist:
                print(f"ERROR: Provider {msg.topic} not found in database")
            except Exception as e:
                print(f"ERROR: Error handling READY signal from {msg.topic}: {str(e)}")
                import traceback
                traceback.print_exc()
                
        elif payload_str == "NOT_READY":
            print(f"Provider {msg.topic} sent NOT_READY signal via MQTT")
            # Call the same logic as not_ready HTTP endpoint
            try:
                not_ready_mqtt(msg.topic)
            except User.DoesNotExist:
                print(f"Provider {msg.topic} not found in database")
            except Exception as e:
                print(f"Error handling NOT_READY signal from {msg.topic}: {str(e)}")
                
        elif payload_str.startswith("ACK:"):
            job_id = payload_str[4:]  # Extract job_id after "ACK:"
            print(f"Provider {msg.topic} sent ACK signal for job {job_id} via MQTT")
            # Call the same logic as job_ack HTTP endpoint
            try:
                job_ack_mqtt(job_id)
            except Job.DoesNotExist:
                print(f"Job {job_id} not found in database")
            except Exception as e:
                print(f"Error handling ACK signal for job {job_id}: {str(e)}")
        
        elif payload_str.startswith("BATCH_REQUEST:"):
            try:
                # Extract correlation ID and batch data
                batch_json = payload_str[14:]  # Remove "BATCH_REQUEST:" prefix
                request_data = json.loads(batch_json)
                correlation_id = request_data.get('correlation_id')
                batch_data = request_data.get('batch_data')
                loadbalancer_id = request_data.get('loadbalancer_id', 'LOADBALANCER')
                
                print(f"Received BATCH_REQUEST with correlation_id: {correlation_id}")
                
                # Record timestamp when scheduler receives the batch
                scheduler_received_time = datetime.now(tz=timezone(TIME_ZONE))
                scheduler_received_time_iso = scheduler_received_time.isoformat()
                
                # Process batch (reuse run_service_async_batch logic)
                services = []
                requests_data = []
                results = []
                temp_time = datetime.now(tz=timezone(TIME_ZONE))
                
                for req_data in batch_data['requests']:
                    try:
                        service_id = req_data.get('serviceID')
                        if not service_id:
                            results.append({'error': 'Missing serviceID'})
                            continue
                            
                        service = Services.objects.get(id=service_id)
                        
                        if not service.active:
                            results.append({'error': f'Service {service_id} is disabled'})
                            continue
                        
                        # Add scheduler received time to request data (preserve lb_received_time if present)
                        req_data['_scheduler_received_time'] = scheduler_received_time_iso
                        # lb_received_time should already be in req_data from load balancer
                        
                        services.append(service)
                        requests_data.append(req_data)
                        
                        results.append({
                            'status': 'pending',
                            'message': f'Service {service_id} queued for processing',
                            'service_name': service.name
                        })
                        
                    except ObjectDoesNotExist:
                        results.append({'error': f'Service {service_id} not found'})
                    except Exception as e:
                        results.append({'error': f'Failed to process request: {str(e)}'})
                
                # Process the batch synchronously to get actual results
                ilp_solve_time = None
                if services:
                    print(f"Starting ILP processing for {len(services)} services...")
                    try:
                        # Measure ILP solve time
                        import time as time_module
                        ilp_start_time = time_module.time()
                        
                        # Call request_handler directly (not in a thread) to get results
                        batch_results = request_handler(requests_data, services, temp_time, False)
                        
                        ilp_end_time = time_module.time()
                        ilp_solve_time = ilp_end_time - ilp_start_time
                        
                        print(f"ILP processing completed in {ilp_solve_time:.3f}s. Results: {batch_results}")
                        
                        # Update results with actual processing results
                        if batch_results and len(batch_results) > 0:
                            results = batch_results
                            processed_count = len([r for r in results if 'error' not in r])
                        else:
                            processed_count = 0
                    except Exception as e:
                        print(f"Error in ILP processing: {e}")
                        results = [{'error': f'ILP processing failed: {str(e)}'} for _ in services]
                        processed_count = 0
                else:
                    processed_count = 0
                
                # Send response back to load balancer on its specific topic
                response_payload = {
                    'correlation_id': correlation_id,
                    'status': 'success',
                    'batch_size': len(batch_data['requests']),
                    'processed': processed_count,
                    'ilp_solve_time': ilp_solve_time,  # Include ILP solve time
                    'results': results
                }
                mqtt_client.publish(
                    topic=loadbalancer_id,
                    payload="BATCH_RESPONSE:" + json.dumps(response_payload),
                    qos=2
                )
                print(f"Published BATCH_RESPONSE to {loadbalancer_id}")
                
            except Exception as e:
                print(f"Error processing BATCH_REQUEST: {e}")
                # Try to send error response if we have correlation_id
                try:
                    error_response = {
                        'correlation_id': correlation_id if 'correlation_id' in locals() else 'unknown',
                        'status': 'error',
                        'error': str(e)
                    }
                    mqtt_client.publish(
                        topic=loadbalancer_id if 'loadbalancer_id' in locals() else 'LOADBALANCER',
                        payload="BATCH_RESPONSE:" + json.dumps(error_response),
                        qos=2
                    )
                except:
                    pass
        
        # Existing message handlers
        elif(payload_str.startswith("Benchmark:")):
            # this is in topic user_id not EVERYONE
            print("In except, will print benchmark...")
            benchmark = json.loads(payload_str[10:])
            user_id = list(benchmark.keys())[0]
            get_benchmarks_for(user_id=user_id, benchmark=benchmark) #this will also update models.
        elif(payload_str.startswith("Stats for Reference Provider: ")):
            try:
                ref_stats_json = payload_str[len("Stats for Reference Provider: "):]
                run_vars = json.loads(ref_stats_json)
                service_id_str = run_vars.get("service")
                if service_id_str:
                    from developers.models import Services
                    reference_stats = {
                        "memory_usage": run_vars.get("memory_usage"),
                        "cpu_usage": run_vars.get("cpu_usage"),
                        "actual_runtime": run_vars.get("actual_runtime"),
                    }
                    updated = Services.objects.filter(docker_container=service_id_str).update(reference_stats=reference_stats)
                    print(f"Reference stats saved to DB for service {service_id_str}: {updated} row(s) updated")
                else:
                    print("Stats for Reference Provider: missing 'service' in payload")
            except Exception as e:
                print(f"Error saving reference stats to DB: {e}")
                import traceback
                traceback.print_exc()
        elif(payload_str.startswith("offline_non-procedurally")):    
            penalise(msg.topic, 1)
            print(msg.topic + "was disconnected non-procedurally")
        elif(payload_str.startswith("offline_procedurally")):    
            penalise(msg.topic, 0)
            print(msg.topic + "was disconnected procedurally")  
        if(msg.topic=="EVERYONE"):
            if(payload_str.startswith("start_connect")):
                user_id = payload_str[13:]
                print(f"=== PROVIDER CONNECTION REQUEST ===")
                print(f"Provider {user_id} requesting connection")
                print(f"Topic: {msg.topic}")
                print(f"Payload: {payload_str}")
                print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                
                mqtt_client.subscribe(topic=user_id)
                print(f"Subscribed to provider topic: {user_id}")
                
                # Send confirmation back to provider
                mqtt_client.publish(topic=user_id, payload="SUBSCRIPTION_CONFIRMED", qos=2)
                print(f"Sent subscription confirmation to {user_id}")
                print("=====================================")
            if(payload_str.startswith("get_efficiency_score")):

                user_id=payload_str[20:]
                provider = User.objects.get(user_id=user_id)
                # Fix: Handle None values with default of 1.0
                cpu_score = 1.0 if provider.cpu_efficiency_score is None else float(provider.cpu_efficiency_score)
                memory_score = 1.0 if provider.memory_efficiency_score is None else float(provider.memory_efficiency_score)
                scoreset = {'cpu': cpu_score, 'memory': memory_score}
                mqtt_client.publish(topic=user_id, payload="EfficiencyScoreSet:"+json.dumps(scoreset),qos=2)
                
    except Exception as e:
        # Handle any errors during string message processing
        print(f"Error processing string message from {msg.topic}: {str(e)}")
        import traceback
        traceback.print_exc()


def on_subscribe(mqtt_client, userdata, mid, qos, properties=None):
    print("on_subscribe userdata is "+ str(mqtt_client))

# Connect timeout (seconds) so startup does not block when broker is unreachable
MQTT_CONNECT_TIMEOUT = 5

def _do_mqtt_connect(timed_out_flag):
    """Run MQTT connect in a thread; set global mclient on success or DISCONNECTED on failure."""
    global mclient
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

        # Configure optional authentication if provided via environment
        mqtt_username = os.environ.get("MQTT_USERNAME")
        mqtt_password = os.environ.get("MQTT_PASSWORD")
        if mqtt_username:
            client.username_pw_set(mqtt_username, mqtt_password)

        if _mqtt_env_truthy("MQTT_DEBUG"):
            ph_logger = logging.getLogger("paho.mqtt.client")
            ph_logger.setLevel(logging.DEBUG)
            client.enable_logger(ph_logger)

        _mqtt_log_connect_context(client)

        client.on_connect = on_connect
        client.on_connect_fail = on_connect_fail
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        client.on_subscribe = on_subscribe
        # client.connect(host=BROKER_ID, port=1883)
        client.connect(host=BROKER_ID, port=BROKER_PORT)
        if timed_out_flag[0]:
            return
        client.subscribe("ROTATION")
        client.loop_start()
        mclient = client
        _mqtt_log.info(
            "[MQTT] connect() returned and loop_start() running; broker CONNACK is asynchronous "
            "(success prints in on_connect when reason_code==0)."
        )
        print(
            f"[MQTT] client started toward {BROKER_ID}:{BROKER_PORT} "
            f"(wait for on_connect / check logs; not yet authenticated)"
        )
    except Exception as e:
        if not timed_out_flag[0]:
            _mqtt_log.exception(
                "[MQTT] connect exception host=%s port=%s: %s",
                BROKER_ID,
                BROKER_PORT,
                e,
            )
            print(f"⚠️  Warning: Failed to connect to MQTT broker {BROKER_ID}:{BROKER_PORT} - {e}")
            print("   MQTT functionality will be unavailable. Server will continue running.")
            print("   This may be due to network connectivity issues.")
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
            print(f"⚠️  Warning: MQTT connection to {BROKER_ID}:{BROKER_PORT} timed out after {MQTT_CONNECT_TIMEOUT}s.")
            print("   MQTT functionality will be unavailable. Server will continue running.")
            return None
    if mclient == "DISCONNECTED":
        return None
    return mclient

# mqtt global communications, all providers are subbed to this topic and the schedule is too
# TODO This stuff is not called by any url pattern.

############################################################################################

# def publish_to_topic(runMultipleInvocations, numberOfInvocations, isChained, inputData, provider , task_link , task_developer, job_id):
#     router_name = str(provider.user_id)
#     print("publish_to_topic used NOT MQTT")
#     zmq_data = {
#         'provider_id' : router_name,
#         'task_link' : task_link,
#         'task_developer' : str(task_developer.user_id),
#         'job_id' : job_id,
#         'numberOfInvocations': numberOfInvocations,
#         'isChained': isChained,
#         'inputData': inputData,
#         'runMultipleInvocations': runMultipleInvocations
#     }
#     zmq_socket = zmq_context.socket(zmq.DEALER)
#     dealer_id = b"dealer1"
#     zmq_socket.setsockopt(zmq.IDENTITY, dealer_id)
#     zmq_socket.bind("tcp://*:5555")
#     # print("Sending zmq data.")
#     zmq_socket.send_multipart([router_name.encode("utf-8"), json.dumps(zmq_data).encode("utf-8")])
#     # print("Waiting for zmq response.")
#     response = zmq_socket.recv()
#     # print("Received response from zmq: ", response)
#     zmq_socket.close()
#     return response


def findfreq_service(service):
    while(service_queue.qsize()>=30):
        service_id_array[service_queue.get()] -=1
    service_queue.put(service.id)
    service_id_array[service.id] = service_id_array[service.id]+1
    return

# pub to topic mqtt actually just forwards it to provider1.py where it adds pull times and stuff and then it publishes.
def publish_to_topic_mqtt(runMultipleInvocations, numberOfInvocations, isChained, inputData, provider , task_link , task_developer, job_id):
    router_name = str(provider.user_id)
    userdata = {
        'provider_id' : router_name,
        'task_link' : task_link,
        'task_developer' : str(task_developer.user_id),
        'job_id' : job_id,
        'numberOfInvocations': numberOfInvocations,
        'isChained': isChained,
        'inputData': inputData,
        'runMultipleInvocations': runMultipleInvocations,
        'stage': "dockernotrun"
    }  
    #makes a new client everytime it pubtotopic is called.
    mclient = get_mclient()
    if mclient is None:
        print(f'⚠️  Warning: MQTT client unavailable. Cannot publish to {router_name}')
        raise Exception("MQTT broker is unreachable. Cannot send job to provider.")
    mclient.subscribe(topic=router_name)
    
    print(f'=== PUBLISHING MQTT MESSAGE ===')
    print(f'Topic: {router_name}')
    print(f'Payload: {json.dumps(userdata, indent=2)}')
    print(f'Timestamp: {time.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'================================')
    
    mclient.publish(topic=router_name, payload=json.dumps(userdata).encode("utf-8"), qos=2)
    print("in pub to topic mqtt")
    # mclient.loop_forever() #get rid of this
    # dont return this return the data which is sent by on_message {data} which is stored in global var called data_dict
    
    # IMP # 
    #return json.dumps(data_dict)


# def make_rmq_user(user):
#     username = 'username' + str(user.user_id)
#     password = 'username' + str(user.user_id) + '_mqtt'
#     api = AdminAPI(url='http://' + RABBITMQ_HOST + ':' + RABBITMQ_MANAGEMENT_PORT, auth=(RABBITMQ_USER, RABBITMQ_PASS))

#     #create user and set permissions
#     api.create_user(username, password)
#     permission = "^(" + username + ".*|amq.default)$"
#     api.create_user_permission(username, '/', permission, permission, permission)

#     return username,password

# # @login_required
# # csrf_exempt is used so that a code can login on behalf of the provider
# # @csrf_exempt
# def index(request):
#     if request.user.provider.active:
#         if request.method == 'POST':
#             provider_form = ProviderForm(data=request.POST)
#             if provider_form.is_valid():
#                 provider = request.user.provider
#                 provider.cpu = provider_form.cleaned_data['cpu']
#                 provider.ram = provider_form.cleaned_data['ram']
#                 provider.ready = True
#                 provider.save()
#             else:
#                 print(provider_form.errors)
#         else:
#             provider_form = ProviderForm()

#         # is_contributing shows if a provider is active, ready and has send a ready signal in the past minute
#         is_contributing = request.user.provider.is_contributing()
#         return render(request, 'providers_app/index.html',
#                       {'provider_form': provider_form,
#                        'is_contributing': is_contributing})
#     else:
#         messages.error(request, "You are not an active provider.")
#         return redirect('profiles:change_info')


# # @login_required
# def stop_providing(request):
#     """
#     The provider can stop contributing through the web application. This send a Stop message to provider's queue.
#     """
#     if request.user.provider.is_contributing():
#         provider = request.user.provider
#         provider.ready = False
#         provider.save()
#         publish_to_topic
# (request, 'Stop', request.user.username)
#         return redirect('providers_app:index')
#     else:
#         return redirect('providers_app:index')


# @login_required
@csrf_exempt
def ready(request,user_id):
    """
    Shows that the provider is still ready.
    """
    if request.method == 'GET':
        provider = User.objects.get(user_id=user_id)
        provider.ready = True
        provider.last_ready_signal = datetime.now(tz=timezone(TIME_ZONE))
        provider.save()
    else:
        messages.error(request, "Wrong request method.")
    return JsonResponse({'message' : 'Not ready ran successfully.'})

def ready_mqtt(user_id):
    print(f"=== PROCESSING READY SIGNAL ===")
    print(f"Provider ID: {user_id}")
    
    try:
        provider = User.objects.get(user_id=user_id)
        print(f"Found provider in database: {provider.user_id}")
        print(f"Provider state before update - ready: {provider.ready}, last_ready_signal: {provider.last_ready_signal}")
        
        provider.ready = True
        provider.last_ready_signal = datetime.now(tz=timezone(TIME_ZONE))
        
        print(f"Provider state after update - ready: {provider.ready}, last_ready_signal: {provider.last_ready_signal}")
        
        provider.save()
        print(f"Provider {user_id} marked as READY and saved to database")
        print("=====================================")
        
    except User.DoesNotExist:
        print(f"ERROR: Provider {user_id} not found in database")
        raise
    except Exception as e:
        print(f"ERROR: Failed to process READY signal for provider {user_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    


# @login_required
@csrf_exempt
def not_ready(request, user_id):
    """
    Shows that the provider is not ready to receive tasks.
    """
    if request.method == 'GET':
            provider = User.objects.get(user_id=user_id)
            provider.ready = False
            provider.save()
    else:
        messages.error(request, "Wrong request method.")
    return JsonResponse({'message' : 'Not ready ran successfully.'})

def not_ready_mqtt(user_id):
    provider = User.objects.get(user_id=user_id)
    provider.ready = False
    provider.save()

# # @login_required
@csrf_exempt
def job_ack(request, job_id):
    if request.method == 'GET':
        job = get_object_or_404(Job, pk=job_id)
        job.ack_time = datetime.now(tz=timezone(TIME_ZONE))
        job.save(update_fields=['ack_time'])
    else:
        messages.error(request, "Wrong request method.")
    return JsonResponse({'message' : 'Job acknowledge time updated successfully.'})


def job_ack_mqtt(job_id):
    job = get_object_or_404(Job, pk=job_id)
    job.ack_time = datetime.now(tz=timezone(TIME_ZONE))
    job.save(update_fields=['ack_time'])

def calculate_efficiency(request, user_id):
    # TODO
    # send this to provider1.py requesting a docker container value, update it to the provider model.
    client = get_mclient()
    client.subscribe(topic=user_id)
    client.publish(topic=user_id, payload="calculate_efficiency", qos=2)
    print("in calculate_efficiency")
    print("views.py/provider loop_forever exited")
    return JsonResponse({'State':'Updated new efficiency scores in database'})

def providerStartup(request, user_id):
    print("Provider ", user_id, " started...")
    client = get_mclient()
    #subscribe to EVERYONE in on_connect
    client.subscribe(topic=user_id)
    return JsonResponse({'State':'scheduler connected to provider user_id'})

def providerStartup_mqtt(user_id):
    print("Provider ", user_id, " started...")
    client = get_mclient()
    #subscribe to EVERYONE in on_connect
    client.subscribe(topic=user_id)


@csrf_exempt
def set_reference_stats(request):
    # send msg to reference provider with service id. on_msg of provider will call a function to execute this service.
    # It will also add cpu_usage and memory_usage to a txt file.
    # service_id can be numeric (DB Service id) or string (task link / docker_container); if numeric we resolve to docker_container.
    print("in set rstats (views/provider)")
    client=get_mclient()
    client.subscribe(topic=reference_provider_id)
    body = json.loads(request.body.decode("utf-8"))
    service_id = body['service_id']
    task_link = service_id
    if isinstance(service_id, int) or (isinstance(service_id, str) and service_id.isdigit()):
        try:
            service = Services.objects.get(id=int(service_id))
            task_link = service.docker_container
            print(f"Resolved service id {service_id} -> {task_link}")
        except (Services.DoesNotExist, ValueError) as e:
            return JsonResponse({'State': f'Service not found: {service_id}', 'error': str(e)}, status=404)
    client.publish(topic=reference_provider_id, payload="ref_run_service_id/"+str(task_link))
    return JsonResponse({'State':'Running service on the reference provider, stats will be printed on django server and added to files also'})

@csrf_exempt
def get_user_id(request):
    """
    Get the latest user_id for a provider at a given location.
    
    Query parameters:
        location: Location string (e.g., 'colva2', 'colva3')
    
    Returns:
        JSON with user_id if found, error message otherwise
    """
    if request.method == 'GET':
        location = request.GET.get('location')
        if not location:
            return JsonResponse({'error': 'location parameter is required'}, status=400)
        
        try:
            # Get the latest active provider at this location
            provider = User.objects.filter(
                is_provider=True,
                active=True,
                location=location
            ).order_by('-last_ready_signal', '-id').first()
            
            if provider:
                return JsonResponse({
                    'user_id': str(provider.user_id),
                    'location': provider.location,
                    'ready': provider.ready,
                    'last_ready_signal': provider.last_ready_signal.isoformat() if provider.last_ready_signal else None
                })
            else:
                return JsonResponse({
                    'error': f'No active provider found for location: {location}'
                }, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    else:
        return JsonResponse({'error': 'Only GET method is supported'}, status=405)
# class RpcClient(object):
#     """
#     This is the rabbitmq RpcClient class.
#     """
#     username = None

#     def __init__(self,username):
#         RpcClient.username = username

#         credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
#         self.connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST, RABBITMQ_PORT, credentials=credentials))
#         self.channel = self.connection.channel()

#         result = self.channel.queue_declare(queue=username, exclusive=True)
#         self.callback_queue = result.method.queue

#         self.channel.basic_consume(
#             queue=self.callback_queue,
#             on_message_callback=self.on_response,
#             auto_ack=True)
#         self.response = None

#     def on_response(self, ch, method, props, body):
#         if self.corr_id == props.correlation_id:
#             self.response = body

#     def call(self, request):
#         self.response = None
#         self.corr_id = str(uuid.uuid4())
#         self.channel.basic_publish(
#             exchange='',
#             routing_key=RpcClient.username, #using the class variable here
#             properties=pika.BasicProperties(
#                 reply_to=self.callback_queue,
#                 correlation_id=self.corr_id,
#             ),
#             body=request)
#         if request == '"Stop"':
#             return
#         while self.response is None:
#             self.connection.process_data_events()
#         return self.response


def request_handler(data, service, start_time, run_async=False):
    """
    Handles a service request by finding suitable providers and sending jobs.
    
    Args:
        data: Request data (single request or list of requests)
        service: Service object (single service or list of services)
        start_time: Start time
        run_async: Whether to run asynchronously
        
    Returns:
        If single request: Tuple of (response, provider_id, providing_time, job_id)
        If batch request: List of results for each service
        
    Raises:
        Exception: If provider selection fails after multiple attempts
    """
    print("Entering request_handler")
    max_attempts = 3
    attempt = 0
    
    # Check if we're handling a batch of services
    is_batch = isinstance(service, list) and isinstance(data, list)
    
    # Convert single request to list format for unified processing
    if not is_batch:
        services = [service]
        data_items = [data]
    else:
        services = service
        data_items = data
    
    # Create request_data_map: service.id -> request data (for timestamps)
    request_data_map = {}
    if is_batch:
        for svc, req_data in zip(services, data_items):
            request_data_map[svc.id] = req_data
    else:
        request_data_map[services[0].id] = data_items[0]
    
    while attempt < max_attempts:
        try:
            # Find providers for all services at once
            assignment = find_providers(services, request_data_map=request_data_map)
            if not assignment:
                print("No providers available for services")
                attempt += 1
                if attempt < max_attempts:
                    print(f"Retrying provider selection (attempt {attempt+1}/{max_attempts})")
                    time.sleep(1)  # Brief delay before retry
                    continue
                else:
                    raise Exception("Could not find suitable providers after multiple attempts")
            
            # Process each service-provider assignment
            results = []
            for i, svc in enumerate(services):
                try:
                    # Find the provider for this service
                    provider = None
                    for assignment_key, assigned_provider in assignment.items():
                        # Handle both direct service objects and (index, service) tuples
                        if isinstance(assignment_key, tuple) and len(assignment_key) == 2:
                            idx, assigned_svc = assignment_key
                            if assigned_svc.id == svc.id:
                                provider = assigned_provider
                                break
                    
                    if not provider:
                        print(f"Warning: No provider assigned for service {svc.id}")
                        results.append((None, None, 0, None))
                        continue
                    
                    # Get the job created during assignment
                    job = Job.objects.filter(
                        provider=provider,
                        service=svc,
                        finished=False
                    ).order_by('-start_time').first()
    
                    if not job:
                        print(f"Warning: No job found for service {svc.id} and provider {provider.id}")
                        results.append((None, None, 0, None))
                        continue
    
                    if USE_FABRIC:
                        r = fabric.invoke_new_job(str(job.id), str(svc.id), str(svc.developer_id),
                                                str(provider.id), provider_org="Org1")
                        if 'jwt expired' in r.text or 'jwt malformed' in r.text or 'User was not found' in r.text:
                            token = fabric.register_user()
                            r = fabric.invoke_new_job(str(job.id), str(svc.id), str(svc.developer_id),
                                                    str(provider.id), provider_org="Org1",token=token)
    
                    req_data = data_items[i]
                    task_link = svc.docker_container 
                    task_developer = svc.developer
                    input_val = req_data.get('input', 'None')
                    
                    # Job already sent by find_providers -> process_assignments
                    # Just refresh and save the job
                    try:
                        job.refresh_from_db()
                        job.save()
                        print(f"Job {job.id} already sent to provider {provider.user_id} by process_assignments")
                    except Exception as mqtt_error:
                        print(f"Error refreshing job: {str(mqtt_error)}")
                        # This will be handled by the recovery process - job stays in CREATED status
                    
                    # Calculate providing time for response
                    providing_time = 0
                    if job.ack_time:
                        providing_time = int(((job.ack_time - job.start_time)/timedelta(microseconds=1))/1000)
                    
                    response_decoded = {"Result": "Request sent to provider", "pull_time": 0, "run_time": 0, "total_time": 0}
                
                except Exception as service_error:
                    print(f"Error processing service {svc.id}: {str(service_error)}")
                    results.append((None, None, 0, None))
            
            # If this was a single request, return just that result
            if not is_batch:
                try:
                    return results[0]
                except Exception as e:
                    print(f"Error in request_handler (attempt {attempt+1}): {str(e)}")
            return results
            
        except Exception as e:
            print(f"Error in request_handler (attempt {attempt+1}): {str(e)}")
            attempt += 1
            if attempt < max_attempts:
                print(f"Retrying (attempt {attempt+1}/{max_attempts})")
                time.sleep(1)  # Brief delay before retry
            else:
                print("Max retry attempts reached")
                raise
    
    raise Exception("Request handler failed after multiple attempts")



def finish_job(data):
    print("=== JOB COMPLETION PROCESSING ===")
    print(f"Inside finish_job with data: {data}")
    
    # Import here to avoid circular imports (optional - may not exist)
    try:
        from providers.experiment_framework import experiment_runner
    except ImportError:
        # experiment_framework is optional - continue without it
        experiment_runner = None
    
    #here unpack the data load job from job id and update and save it.
    id = data['job_id']
    print(f"Processing job completion for job_id: {id}")
    
    try:
        job = Job.objects.get(pk=id)
        print(f"Found job {id} in database")
        service_info = f"Service: {job.service.id}" if job.service else "Service: None"
        print(f"Job details - Provider: {job.provider.user_id}, {service_info}, Status: {job.finished}")
        
        # Handle both dict and string data formats
        if isinstance(data, dict):
            response_decoded = data
        else:
            response_decoded = json.loads(data.decode("utf-8"))
        
        print(f"Job completion data: {response_decoded}")
        
        # Update job with completion data
        job.refresh_from_db()
        print(f"Job state before update - pull_time: {job.pull_time}, run_time: {job.run_time}, total_time: {job.total_time}, finished: {job.finished}")
        
        job.pull_time = response_decoded['pull_time']
        job.run_time = response_decoded['run_time']
        job.total_time = response_decoded['total_time']
        job.cost = (response_decoded['total_time'])

        # Optional: efficiency/training stats (eff_score_data shape) when provider sends them
        if 'memory_usage' in response_decoded:
            job.memory_usage = response_decoded['memory_usage']
        if 'cpu_usage' in response_decoded:
            job.cpu_usage = response_decoded['cpu_usage']
        if 'cpu_efficiency_score' in response_decoded:
            job.cpu_efficiency_score = response_decoded['cpu_efficiency_score']
        if 'memory_efficiency_score' in response_decoded:
            job.memory_efficiency_score = response_decoded['memory_efficiency_score']
        
        # Convert Result to JSON string if it's a dict/list, otherwise convert to string
        result = response_decoded.get('Result', {})
        if isinstance(result, (dict, list)):
            job.response = json.dumps(result)
        else:
            job.response = str(result)
        
        job.finished = True
        
        print(f"Job state after update - pull_time: {job.pull_time}, run_time: {job.run_time}, total_time: {job.total_time}, finished: {job.finished}")
        
        job.save()
        print(f"Job {id} successfully updated and saved to database")
        
        # Update cache state after job completion (inside try block to ensure job is saved first)
        try:
            if job.service:
                # Assume the image is stored in memory after execution
                # In a real implementation, this would come from the provider's report
                provider = job.provider
                service_id = job.service.id
                cache_location = 'memory'  # Default assumption - provider would report actual location
                
                # Update the cache state in the provider's model
                if hasattr(provider, 'update_cache_state'):
                    provider.update_cache_state(service_id, cache_location)
                    print(f"Updated cache state for provider {provider.user_id} and service {service_id}")
        except Exception as e:
            print(f"Error updating cache state: {str(e)}")
        
        # Calculate providing time safely (handle None ack_time)
        try:
            if job.ack_time is not None and job.start_time is not None:
                providing_time = int(((job.ack_time - job.start_time)/timedelta(microseconds=1))/1000)  # Providing time in milliseconds
                print(f"Providing time: {providing_time}ms")
            else:
                print(f"Warning: Cannot calculate providing time - ack_time: {job.ack_time}, start_time: {job.start_time}")
        except Exception as e:
            print(f"Error calculating providing time: {str(e)}")
        
        # Handle Fabric integration if enabled
        if USE_FABRIC:
            try:
                r = fabric.invoke_received_result(str(job.id))
                if 'jwt expired' in r.text or 'jwt malformed' in r.text or 'User was not found' in r.text:
                    token = fabric.register_user()
                    r = fabric.invoke_received_result(str(job.id), token=token)
            except Exception as e:
                print(f"Error invoking Fabric result: {str(e)}")
        
        # Record experiment metrics if experiment is active
        # if experiment_runner.experiment_active:
        #     current_algorithm = settings.SCHEDULING_ALGORITHM
        #     experiment_runner.metrics.record_job_completion(current_algorithm, job)
        
    except Job.DoesNotExist:
        print(f"ERROR: Job {id} not found in database!")
        import traceback
        traceback.print_exc()
        return
    except Exception as e:
        print(f"ERROR: Failed to update job {id}: {str(e)}")
        import traceback
        traceback.print_exc()
        return
    
    return

def queue_jobs(service):
    requested_services.append(service)


def get_ready_providers():
    """
    Get ready providers with proper locking for concurrency control.
    Uses select_for_update with timeout to handle lock contention gracefully.
    """
    return User.objects.select_for_update(nowait=False).filter(
        active=True,
        is_provider=True,
        ready=True,
    )

def is_cached(provider_id, service_id):
    """
    Check if a service is cached on a provider.
    
    Args:
        provider_id: The ID of the provider
        service_id: The ID of the service
        
    Returns:
        bool: True if the service is cached on the provider, False otherwise
        
    # NOTE: Circumstances where cache hit does not take place:
    1. Service's first encounter with provider.
    2. Service was cached but evicted by the LFU policy.
    3. Service not present in cache as of now
    """
    try:
        provider = User.objects.get(user_id=provider_id)
        return provider.is_service_cached(service_id)
    except User.DoesNotExist:
        return False

# FIXME for now the predicited_runtimes fetch the last runtime of a service - provider combination. If the service has not run with a provider, when the service is registered, it will be benchmarked with all the providers and that runtime will be added to db as predicted_runtime.
"""
Args:
    provider: Provider object
    services: [List] of compatible services objects
Returns:
    A dictionary mapping each service to its predicted runtime. ( for ONE specific provider )
"""


def _get_provider_http_base_url(provider):
    """Get HTTP base URL for provider's predicted_runtime endpoint."""
    from django.conf import settings
    url_by_loc = getattr(settings, "PROVIDER_HTTP_URL_BY_LOCATION", {})
    if provider.location and url_by_loc:
        return url_by_loc.get(provider.location)
    return getattr(settings, "PROVIDER_HTTP_BASE_URL", "http://localhost:9002")


def _fetch_predicted_runtime_http(base_url, service_docker, timeout=5):
    """Fetch predicted runtime from provider via HTTP. Returns value or None."""
    try:
        from urllib.parse import quote
        url = f"{base_url.rstrip('/')}/predicted_runtime?service={quote(service_docker, safe='')}"
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            return data.get("value")
    except Exception as e:
        print(f"HTTP predicted_runtime fetch failed: {e}")
    return None


def _fetch_predicted_runtimes_parallel(provider, services_to_fetch, timeout=5):
    """
    [Legacy] Fetch predicted runtimes from provider via HTTP in parallel.
    Replaced by MQTT-based _fetch_predicted_runtimes_mqtt_batch for build_cost_matrix.
    """
    base_url = _get_provider_http_base_url(provider)
    results = {}

    def _fetch_one(item):
        service_id, service = item
        svc_obj = service[1] if isinstance(service, tuple) and len(service) == 2 else service
        docker_container = getattr(svc_obj, "docker_container", None)
        if not docker_container:
            return (service_id, None)
        val = _fetch_predicted_runtime_http(base_url, docker_container, timeout)
        return (service_id, val)

    with ThreadPoolExecutor(max_workers=min(len(services_to_fetch), 8)) as executor:
        futures = {executor.submit(_fetch_one, item): item[0] for item in services_to_fetch}
        for future in as_completed(futures, timeout=timeout + 2):
            try:
                service_id, val = future.result()
                results[service_id] = val
            except Exception as e:
                print(f"Parallel fetch error: {e}")

    return results


def _service_docker_container(service):
    """Extract docker_container string from service (tuple (i, svc) or plain svc)."""
    svc = service[1] if isinstance(service, tuple) and len(service) == 2 else service
    return getattr(svc, "docker_container", None)


def _fetch_predicted_runtimes_mqtt_batch(provider_services_map, timeout=7):
    """
    Fetch predicted runtimes from multiple providers via MQTT in parallel.
    provider_services_map: dict provider -> list of (service_id, service) needing prediction.
    Returns: dict provider_user_id -> dict service_id -> runtime_ms (int or None).
    Fires all requests at once, then waits once for all PREDICT_RESPONSE messages.
    """
    if not provider_services_map:
        return {}
    correlation_id = str(uuid.uuid4())
    reply_topic = _get_predict_response_topic()
    client = get_mclient()
    if client is None:
        print("MQTT client unavailable for predicted runtimes batch")
        return {}
    expected = set()
    for provider, services_to_fetch in provider_services_map.items():
        services_payload = []
        for service_id, service in services_to_fetch:
            dc = _service_docker_container(service)
            if dc:
                services_payload.append({"service_id": service_id, "docker_container": dc})
        if not services_payload:
            continue
        expected.add(str(provider.user_id))
        payload = f"PREDICT_REQUEST:{correlation_id}|{reply_topic}|{json.dumps(services_payload)}"
        client.publish(topic=str(provider.user_id), payload=payload.encode("utf-8"), qos=1)
        print(f"Published PREDICT_REQUEST to {provider.user_id} for {len(services_payload)} services")
    if not expected:
        return {}
    with pending_predictions_lock:
        pending_predictions[correlation_id] = {
            "results": {},
            "expected_providers": expected,
            "event": threading.Event(),
        }
    got_all = pending_predictions[correlation_id]["event"].wait(timeout=timeout)
    with pending_predictions_lock:
        entry = pending_predictions.pop(correlation_id, None)
        results = dict(entry["results"]) if entry else {}
    if not got_all:
        print(f"PREDICT_RESPONSE timeout for correlation_id {correlation_id}; got {len(results)}/{len(expected)}")
    return results


def get_predicted_runtimes_db_pass(provider, services):
    """
    First pass: fill predicted_runtimes from Job history; collect services needing provider prediction.
    Returns: (predicted_runtimes dict, services_needing_prediction list of (service_id, service)).
    """
    predicted_runtimes = {}
    services_needing_prediction = []
    for service in services:
        try:
            service_id = None
            if hasattr(service, "id"):
                service_id = service.id
            elif isinstance(service, tuple) and len(service) == 2 and hasattr(service[1], "id"):
                service_id = service[1].id
            if service_id is None:
                continue
            try:
                latest_run_time = Job.get_latest_run_time(provider.id, service_id)
                predicted_runtimes[service_id] = latest_run_time
            except Job.DoesNotExist:
                services_needing_prediction.append((service_id, service))
        except Exception:
            pass
    return predicted_runtimes, services_needing_prediction


def get_predicted_runtimes_cache_pass(provider, services, predicted_runtimes, default_runtime=1000):
    """
    Second pass: adjust predicted_runtimes for cache state (pull time).
    Mutates predicted_runtimes in place.
    """
    for service in services:
        try:
            service_id = None
            if hasattr(service, "id"):
                service_id = service.id
            elif isinstance(service, tuple) and len(service) == 2 and hasattr(service[1], "id"):
                service_id = service[1].id
            if service_id is None or service_id not in predicted_runtimes:
                continue
            if provider.is_service_cached(service_id):
                cache_location = provider.get_cache_location(service_id)
                if cache_location == "memory":
                    continue
                if cache_location == "disk":
                    try:
                        pull_time = Job.get_latest_pull_time(provider.id, service_id)
                        if pull_time:
                            predicted_runtimes[service_id] += int(pull_time * 0.2)
                    except Exception:
                        pass
            else:
                try:
                    pull_time = Job.get_latest_pull_time(provider.id, service_id)
                    if pull_time:
                        predicted_runtimes[service_id] += pull_time
                except Exception:
                    pass
        except Exception:
            pass
    return predicted_runtimes


def get_predicted_runtimes(provider, services):
    """Get predicted runtimes for one provider via DB + MQTT batch + cache pass."""
    DEFAULT_RUNTIME = 1000
    print("Entering get_predicted_runtimes")
    predicted_runtimes, services_needing_prediction = get_predicted_runtimes_db_pass(provider, services)
    if services_needing_prediction:
        mqtt_results = _fetch_predicted_runtimes_mqtt_batch({provider: services_needing_prediction})
        provider_runtimes = mqtt_results.get(str(provider.user_id), {})
        for service_id, _ in services_needing_prediction:
            val = provider_runtimes.get(service_id) or provider_runtimes.get(str(service_id))
            if val is not None and val > 0:
                predicted_runtimes[service_id] = int(val)
            else:
                predicted_runtimes[service_id] = DEFAULT_RUNTIME
    get_predicted_runtimes_cache_pass(provider, services, predicted_runtimes, DEFAULT_RUNTIME)
    print(f"Predicted runtimes: {predicted_runtimes}")
    print("Exiting get_predicted_runtimes")
    return predicted_runtimes

def print_cost_matrix(cost_matrix):
    """Pretty prints the cost matrix in a tabular format."""
    print("Entering print_cost_matrix")
    if not cost_matrix:
        print("Empty cost matrix")
        return

    # Get all services (columns) from the first provider's dictionary
    services = list(next(iter(cost_matrix.values())).keys())
    
    # Extract service objects from any tuples
    extracted_services = []
    for service_item in services:
        if isinstance(service_item, tuple) and len(service_item) == 2:
            # Extract the service from tuple (index, service)
            _, service_obj = service_item
            extracted_services.append(service_obj)
        else:
            extracted_services.append(service_item)
    
    # Calculate column widths - handle both direct service objects and tuples
    # Include provider name/id info in width calculation
    provider_width = max(len(f"{provider.user_id} ({provider.location or 'No Location'})") for provider in cost_matrix.keys())
    service_widths = []
    for service_item in extracted_services:
        try:
            # Handle service object directly
            width = max(len(str(service_item.id)), 8)
        except AttributeError:
            # Fallback for unexpected types
            width = 8
        service_widths.append(width)
    
    # Print header
    header = f"{'Provider (ID + Location)':>{provider_width}} |"
    header += "".join(f" {'Service '+str(getattr(service, 'id', i)):^{width}}" 
                     for i, (service, width) in enumerate(zip(extracted_services, service_widths)))
    print("\n" + "="*(len(header)))
    print(header)
    print("="*(len(header)))
    
    # Print each row
    for provider, costs in cost_matrix.items():
        # Include provider ID and location for better identification
        provider_info = f"{provider.user_id} ({provider.location or 'No Location'})"
        row = f"{provider_info:>{provider_width}} |"
        row += "".join(f" {costs[service]:^{width}.2f}" for service, width in zip(services, service_widths))
        print(row)
    
    print("="*(len(header)) + "\n")
    print("Exiting print_cost_matrix")

def build_cost_matrix(providers, services):
    """Build cost matrix: one DB pass per provider, one MQTT batch for all providers, then merge + cache pass."""
    DEFAULT_RUNTIME = 1000
    print("Entering build_cost_matrix")
    cost_matrix = {}
    indexed_services = list(enumerate(services))
    compatible_services = services

    # First pass: DB per provider and collect providers that need MQTT prediction
    per_provider_runtimes = {}
    provider_services_map = {}
    for provider in providers:
        predicted_runtimes, services_needing_prediction = get_predicted_runtimes_db_pass(provider, compatible_services)
        per_provider_runtimes[provider] = predicted_runtimes
        if services_needing_prediction:
            provider_services_map[provider] = services_needing_prediction

    # One MQTT batch: fire all provider requests at once, wait once for all PREDICT_RESPONSE
    mqtt_results = _fetch_predicted_runtimes_mqtt_batch(provider_services_map) if provider_services_map else {}

    # Merge MQTT results and run cache pass per provider
    for provider in providers:
        predicted_runtimes = per_provider_runtimes[provider]
        if provider in provider_services_map:
            provider_runtimes = mqtt_results.get(str(provider.user_id), {})
            for service_id, _ in provider_services_map[provider]:
                val = provider_runtimes.get(service_id) or provider_runtimes.get(str(service_id))
                if val is not None and val > 0:
                    predicted_runtimes[service_id] = int(val)
                else:
                    predicted_runtimes[service_id] = DEFAULT_RUNTIME
        get_predicted_runtimes_cache_pass(provider, compatible_services, predicted_runtimes, DEFAULT_RUNTIME)

        subdict = {}
        for i, svc in indexed_services:
            service_id = getattr(svc, "id", None)
            if service_id is not None:
                runtime = predicted_runtimes.get(service_id, float("inf"))
                subdict[(i, svc)] = runtime
            else:
                print(f"Warning: Could not get ID from service object: {svc}")
                subdict[(i, svc)] = float("inf")
        cost_matrix[provider] = subdict

    print_cost_matrix(cost_matrix)
    print("Exiting build_cost_matrix")
    return cost_matrix

# NOTE This is for when services would have requirements. Function unused for now.
def get_suitable_providers(services):
    suitable_providers = set()
    all_ready_providers = get_ready_providers()
    for service in services:
        for provider in all_ready_providers:
            if provider.satisfies(service.requirements):
                suitable_providers.add(provider)
    return list(suitable_providers)

# FIX figure out the right way to calculate delays
def build_delay_dict(providers):
    print("Entering build_delay_dict")
    delay = {}
    for provider in providers:
        try:
            time_of_last_startjob = provider.get_last_start_time()
            print(f"Time of last start job for {provider.user_id}: {str(time_of_last_startjob)}")
            
            # Ensure proper type for datetime calculation
            if time_of_last_startjob is None:
                print(f"No previous jobs for provider {provider.user_id}")
                delay[provider] = 0
            elif isinstance(time_of_last_startjob, datetime):
                try:
                    delay[provider] = provider.calculate_current_delay(time_of_last_startjob)
                    print(f"Delay for {provider.user_id}: {delay[provider]}")
                except Exception as e:
                    print(f"Error calculating delay: {str(e)}")
                    delay[provider] = 0
            elif isinstance(time_of_last_startjob, str):
                print(f"Converting string timestamp to datetime: {time_of_last_startjob}")
                try:
                    # Try different datetime formats
                    if 'T' in time_of_last_startjob:
                        # ISO format
                        dt = datetime.fromisoformat(time_of_last_startjob.replace('Z', '+00:00'))
                    else:
                        # Django format with timezone
                        dt = datetime.strptime(time_of_last_startjob, "%Y-%m-%d %H:%M:%S.%f%z")
                    
                    delay[provider] = provider.calculate_current_delay(dt)
                    print(f"Delay for {provider.user_id} after conversion: {delay[provider]}")
                except Exception as e:
                    print(f"Error converting datetime string: {str(e)}")
                    delay[provider] = 0
            else:
                print(f"Invalid last start time type for provider {provider.user_id}: {type(time_of_last_startjob)}")
                delay[provider] = 0
                
        except Exception as e:
            print(f"Error calculating delay for provider {provider.user_id} - {str(e)}")
            try:
                provider.reset_delay()  # Reset the delay
                print(f"No inflight jobs for {provider.user_id}")
                delay[provider] = 0
                print(f"After reset - Delay for {provider.user_id}: {delay[provider]}")
            except Exception as retry_error:
                print(f"Error after reset for provider {provider.user_id} - {str(retry_error)}")
                delay[provider] = 0  # Ensure we always have a delay value
    
    print(f"Delay dictionary: {delay}")
    print("Exiting build_delay_dict")
    return delay

def process_assignments(assignment, cost_matrix, request_data_map=None):
    """
    Process job assignments and create Job objects.
    
    Args:
        assignment: Dictionary mapping (index, service) to provider
        cost_matrix: Cost matrix for ILP
        request_data_map: Optional dict mapping service.id to request data (for timestamps)
    """
    print("\nEntering process_assignments")
    jobs_to_send = []  # Store jobs to send after transaction
    assigned_time = datetime.now(tz=timezone(TIME_ZONE))  # Time when jobs are assigned to providers
    
    # Database operations inside transaction
    with transaction.atomic():
        for key, provider in assignment.items():
            # Extract service from the assignment key
            if isinstance(key, tuple) and len(key) == 2:
                i, service = key
            else:
                # Fallback if key is not a tuple (shouldn't normally happen)
                service = key
                i = 0
                
            print(f"\nProcessing assignment - Service: {service.id}, Provider: {provider.user_id}")
            
            # Provider is already locked by get_ready_providers(), so we can use it directly
            # No need to lock again - this was causing self-deadlock
            print(f"Using provider: {provider.user_id} (already locked)")
            
            # Extract timestamps from request data if available
            lb_received_time = None
            scheduler_received_time = None
            
            if request_data_map and service.id in request_data_map:
                req_data = request_data_map[service.id]
                # Parse timestamps from ISO format strings
                if '_lb_received_time' in req_data:
                    try:
                        # Handle ISO format with timezone (replace Z with +00:00 for Python <3.11)
                        time_str = req_data['_lb_received_time'].replace('Z', '+00:00')
                        lb_received_time = datetime.fromisoformat(time_str)
                        # Convert to local timezone if needed
                        if lb_received_time.tzinfo:
                            lb_received_time = lb_received_time.astimezone(timezone(TIME_ZONE))
                    except Exception as e:
                        print(f"Error parsing lb_received_time: {e}")
                        pass
                if '_scheduler_received_time' in req_data:
                    try:
                        # Handle ISO format with timezone
                        time_str = req_data['_scheduler_received_time'].replace('Z', '+00:00')
                        scheduler_received_time = datetime.fromisoformat(time_str)
                        # Convert to local timezone if needed
                        if scheduler_received_time.tzinfo:
                            scheduler_received_time = scheduler_received_time.astimezone(timezone(TIME_ZONE))
                    except Exception as e:
                        print(f"Error parsing scheduler_received_time: {e}")
                        pass
            
            # Create a Job instance with CREATED status and timestamps
            job = Job.objects.create(
                provider=provider,
                service=service,
                developer=service.developer,
                finished=False,
                lb_received_time=lb_received_time,
                scheduler_received_time=scheduler_received_time,
                assigned_to_provider_time=assigned_time
            )
            print(f"Created job with ID: {job.id}")
            if lb_received_time:
                print(f"  LB received: {lb_received_time}")
            if scheduler_received_time:
                print(f"  Scheduler received: {scheduler_received_time}")
            print(f"  Assigned to provider: {assigned_time}")
            
            # Get predicted runtime from cost_matrix if available
            try:
                # First try to get it from the cost matrix with the tuple key
                if isinstance(key, tuple) and (i, service) in cost_matrix.get(provider, {}):
                    predicted_runtime = cost_matrix[provider][(i, service)]
                # Then try with just the service
                elif service in cost_matrix.get(provider, {}):
                    predicted_runtime = cost_matrix[provider][service]
                # If service.id works as a key
                elif service.id in cost_matrix.get(provider, {}):
                    predicted_runtime = cost_matrix[provider][service.id]
                else:
                    # Use a default value if not found
                    print(f"Warning: Could not find runtime prediction for service {service.id} in cost matrix")
                    predicted_runtime = 1000  # Default value in milliseconds
            except Exception as e:
                print(f"Error accessing cost matrix: {str(e)}")
                predicted_runtime = 1000  # Default value
                
            print(f"Predicted runtime: {predicted_runtime}")
            print(f"Current provider delay state: {provider.delay}")
            
            try:
                provider.add_delay(predicted_runtime)
                print("Successfully added delay")
            except Exception as e:
                print(f"Error adding delay: {str(e)}")
                print(f"Type of predicted_runtime: {type(predicted_runtime)}")
                print(f"Value of predicted_runtime: {predicted_runtime}")
                # Don't raise, just continue with default delay
                provider.delay = provider.delay or 0

            print(f"Updated provider delay state: {provider.delay}")
            
            # Update function invocations
            service_key = str(service.id)
            current_invocations = provider.function_invocations.get(service_key, 0)
            provider.function_invocations[service_key] = current_invocations + 1
            
            try:
                provider.save()
                print("Successfully saved provider")
            except Exception as e:
                print(f"Error saving provider: {str(e)}")
                print(f"Provider state at save: {provider.__dict__}")
                raise

            # Store job information for sending after transaction commits
            jobs_to_send.append({
                'job': job,
                'provider': provider,
                'service': service
            })

    # Send jobs to providers after the transaction has committed
    for job_info in jobs_to_send:
        job = job_info['job']
        provider = job_info['provider']
        service = job_info['service']
        
        try:
            # Create a dummy data structure similar to what request_handler expects
            job_data = {
                'runMultipleInvocations': False,  # Default values
                'numberOfInvocations': 1,
                'chained': False,
                'input': 'None'
            }
            
            # Send the job to the provider
            print(f"Sending job {job.id} to provider {provider.user_id}")
            publish_to_topic_mqtt(
                job_data['runMultipleInvocations'],
                job_data['numberOfInvocations'],
                job_data['chained'],
                job_data['input'],
                provider,
                service.docker_container,
                service.developer,
                job.id
            )
            
            # Refresh and save job
            job.refresh_from_db()
            job.save()
            print(f"Job {job.id} successfully sent to provider {provider.user_id}")
        except Exception as e:
            print(f"Failed to send job {job.id} to provider {provider.user_id}: {str(e)}")
            # Don't raise exception - this job will be recovered by the recovery process

    print("Exiting process_assignments\n")

    # Publish ILP_DONE to ROTATION topic after processing assignments
    mqtt_client = get_mclient()
    mqtt_client.publish(topic="ROTATION", payload="ILP_DONE", qos=2)
    print("Published ILP_DONE to ROTATION topic")

def find_providers(services, jobs=None, request_data_map=None):
    """
    Find providers for services using ILP.
    
    Args:
        services: List of Service objects
        jobs: Optional jobs parameter (legacy)
        request_data_map: Optional dict mapping service.id to request data (for timestamps)
    """
    print("Debug: Entering find_providers")
    
    # Import here to avoid circular imports
    # from providers.scheduling_algorithms import get_scheduler
    # from providers.experiment_framework import experiment_runner
    
    # Retry logic for database lock contention
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Wrap the entire process in a transaction to keep providers locked
            with transaction.atomic():
                if not isinstance(services, list):
                    services = [services]

                # 1. Get Suitable Providers (now locks are kept until this transaction ends)
                suitable_providers = get_ready_providers()
                for provider in suitable_providers:
                    print(provider)
                if not suitable_providers:
                    print("No ready providers available.")
                    return None

                # 2. Build Cost Matrix
                cost_matrix = build_cost_matrix(suitable_providers, services)

                # 3. Build Delay Dict
                delay = build_delay_dict(suitable_providers)

                # 4. Get min cost provider by calling the ILP solver
                # Extract the list of (index, service) tuples as jobs for the minimize function
                indexed_services = [(i, svc) for i, svc in enumerate(services)]
                workers = list(cost_matrix.keys())
                
                try:
                    # Call minimize_total_cost with proper arguments
                    assignment, total_cost = minimize_total_cost(suitable_providers, indexed_services, cost_matrix, delay)
                    main_processing_succeeded = False  # Initialize flag
                    
                    if assignment is None:
                        print("Warning: No optimal solution found")
                        return None
                        
                    # 5. Process assignments - Invoke providers and update job status
                    process_assignments(assignment, cost_matrix, request_data_map)
                    main_processing_succeeded = True  # Flag to prevent fallback from running
                    print(f"DEBUG: Main processing succeeded, flag set to: {main_processing_succeeded}")
                    
                    # If jobs were provided, map job IDs to provider assignments
                    if jobs is not None:
                        # Create mappings from index and service to job
                        job_mapping = {}
                        for i, (service, job) in enumerate(zip(services, jobs)):
                            job_mapping[(i, service)] = job
                        
                        # Create provider assignments
                        provider_assignments = {}
                        for (i, service), provider in assignment.items():
                            if (i, service) in job_mapping:
                                job = job_mapping[(i, service)]
                                provider_assignments[job.id] = (provider, delay.get(provider, 0))
                        return provider_assignments
                    
                    # Return the original assignment format if no jobs provided
                    return assignment
                    
                except Exception as ilp_error:
                    print(f"Error in ILP solver: {str(ilp_error)}")
                    # This will be caught by the outer exception handler
                    raise
                    
        except Exception as e:
            # Check if this is a database lock contention error
            error_str = str(e).lower()
            if 'could not obtain lock' in error_str or 'lock timeout' in error_str or 'deadlock' in error_str:
                retry_count += 1
                print(f"Database lock contention detected (attempt {retry_count}/{max_retries}): {str(e)}")
                if retry_count < max_retries:
                    # Exponential backoff with jitter
                    import random
                    sleep_time = (0.1 * (2 ** retry_count)) + random.uniform(0, 0.1)
                    print(f"Retrying in {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
                    continue
                else:
                    print(f"Max retries reached for lock contention, giving up")
                    raise Exception(f"Could not obtain database locks after {max_retries} attempts: {str(e)}")
            else:
                # For non-lock errors, don't retry
                print(f"Non-lock error in find_providers: {str(e)}")
                print(f"DEBUG: main_processing_succeeded flag is: {main_processing_succeeded}")
                # Only attempt fallback if main processing didn't succeed
                if not main_processing_succeeded and len(services) == 1:
                    print("DEBUG: Running fallback logic")
                    service = services[0]
                    # Find a suitable provider with minimal delay
                    if suitable_providers:
                        provider = min(suitable_providers, key=lambda p: delay.get(p, 0))
                        print(f"Fallback provider selection: {provider}")
                        
                        # Create a simple assignment dictionary with the expected tuple key
                        assignment = {(0, service): provider}
                        
                        # Ensure cost_matrix has the necessary entries
                        # If the cost_matrix doesn't have this provider or service, create it
                        if provider not in cost_matrix:
                            cost_matrix[provider] = {}
                        
                        # Use a default runtime value if not available
                        if (0, service) not in cost_matrix[provider]:
                            # Try to get a default runtime from the Job model or use a fixed value
                            try:
                                default_runtime = Job.get_latest_run_time(provider.id, service.id) or 1000
                            except:
                                default_runtime = 1000
                            cost_matrix[provider][(0, service)] = default_runtime
                    
                        # Process the assignment with the updated cost_matrix
                        print(f"Using fallback cost matrix entry: {cost_matrix[provider][(0, service)]}")
                        process_assignments(assignment, cost_matrix, request_data_map)
                        
                        # Handle job mapping if needed
                        if jobs is not None and len(jobs) == 1:
                            job = jobs[0]
                            return {job.id: (provider, delay.get(provider, 0))}
                        
                        return assignment
                    else:
                        print("Could not find providers after trying fallback solutions")
                        return None
                else:
                    print("DEBUG: Skipping fallback logic - main processing succeeded or multiple services")
                    print("Could not find providers after trying fallback solutions")
                    return None
    
    # If we get here, all retries failed
    print(f"Failed to find providers after {max_retries} attempts")
    return None

def find_provider(service):
    # NOTE - Logic for this function can be defined later if a different provider selection algorithm is needed for one service.
    """
    Find the max provider for the given service.
    """
    # Ensure we're passing a single service object, not a tuple
    if not isinstance(service, list):
        services = [service]
    else:
        services = service
    
    return find_providers(services)


# @csrf_exempt
# def recover_pending_jobs(request=None):
#     """
#     Recover jobs that were created but not sent to providers.
#     This function can be called periodically to recover from scheduler failures.
    
#     Can be triggered via HTTP endpoint or called directly.
#     """
#     print("Checking for jobs that need recovery...")
    
#     # Find jobs in CREATED state older than 2 minutes
#     cutoff_time = datetime.now(tz=timezone(TIME_ZONE)) - timedelta(minutes=2)
#     pending_jobs = Job.objects.filter(
#         status='CREATED',
#         start_time__lt=cutoff_time,
#         finished=False,
#         recovery_attempts__lt=3  # Limit recovery attempts
#     )
    
#     recovered_count = 0
#     failed_count = 0
#     for job in pending_jobs:
#         try:
#             # Get job details
#             service = job.service
#             provider = job.provider
            
#             # Create job_data
#             job_data = {
#                 'runMultipleInvocations': False,
#                 'numberOfInvocations': 1,
#                 'chained': False,
#                 'input': 'None'  # Default
#             }
            
#             # Attempt to send to provider
#             publish_to_topic_mqtt(
#                 job_data['runMultipleInvocations'],
#                 job_data['numberOfInvocations'],
#                 job_data['chained'],
#                 job_data['input'],
#                 provider,
#                 service.docker_container,
#                 service.developer,
#                 job.id
#             )
            
#             # Update job status
#             job.status = 'SENT'
#             job.recovery_attempts += 1
#             job.last_recovery_attempt = datetime.now(tz=timezone(TIME_ZONE))
#             job.save()
            
#             print(f"Recovered job {job.id} (attempt {job.recovery_attempts})")
#             recovered_count += 1
            
#         except Exception as e:
#             print(f"Failed to recover job {job.id}: {str(e)}")
#             failed_count += 1
            
#             # Update recovery attempt count
#             job.recovery_attempts += 1
#             job.last_recovery_attempt = datetime.now(tz=timezone(TIME_ZONE))
            
#             # Mark as failed if too many attempts
#             if job.recovery_attempts >= 3:
#                 job.status = 'FAILED'
#                 print(f"Job {job.id} marked as FAILED after {job.recovery_attempts} recovery attempts")
            
#             job.save()
    
#     result_message = f"Recovery process completed. Recovered {recovered_count} jobs, failed {failed_count} jobs."
#     print(result_message)
    
#     # If called via HTTP request, return a JSON response
#     if request is not None:
#         return JsonResponse({
#             'status': 'success',
#             'message': result_message,
#             'recovered_count': recovered_count,
#             'failed_count': failed_count,
#             'total_pending': len(pending_jobs)
#         })
    
#     # Otherwise return the count for programmatic use
#     return recovered_count

# MAIN CODE:

# Initialize MQTT client lazily - don't fail if broker is unreachable
# This allows the server to start even if MQTT is unavailable
try:
    get_mclient()
except Exception as e:
    print(f"⚠️  Warning: Could not initialize MQTT client at startup: {e}")
    print("   Server will continue, but MQTT functionality may be unavailable.")

# Experiment and Algorithm Control Endpoints

# @csrf_exempt
# def start_algorithm_experiment(request):
#     """Start a scheduling algorithm comparison experiment"""
#     # Commented out - experiment framework not implemented
#     return JsonResponse({'status': 'error', 'message': 'Experiment framework not implemented'}, status=501)

# @csrf_exempt
# def get_experiment_status(request):
#     """Get current experiment status"""
#     # Commented out - experiment framework not implemented
#     return JsonResponse({'status': 'error', 'message': 'Experiment framework not implemented'}, status=501)

# @csrf_exempt
# def switch_scheduling_algorithm(request):
#     """Switch the current scheduling algorithm"""
#     # Commented out - only ILP algorithm is currently implemented
#     return JsonResponse({'status': 'error', 'message': 'Only ILP algorithm is currently implemented'}, status=501)

# @csrf_exempt
# def generate_experiment_report(request):
#     """Generate and return experiment report"""
#     # Commented out - experiment framework not implemented
#     return JsonResponse({'status': 'error', 'message': 'Experiment framework not implemented'}, status=501)

# @csrf_exempt 
# def get_algorithm_metrics(request):
#     """Get current algorithm performance metrics"""
#     # Commented out - only ILP algorithm is currently implemented
#     return JsonResponse({'status': 'error', 'message': 'Only ILP algorithm is currently implemented'}, status=501)

# @csrf_exempt
# def reset_algorithm_metrics(request):
#     """Reset algorithm performance metrics"""
#     # Commented out - only ILP algorithm is currently implemented
#     return JsonResponse({'status': 'error', 'message': 'Only ILP algorithm is currently implemented'}, status=501)

# @csrf_exempt
# def toggle_experiment_mode(request):
#     """Toggle experiment mode on/off"""
#     # Commented out - experiment framework not implemented
#     return JsonResponse({'status': 'error', 'message': 'Experiment framework not implemented'}, status=501)
