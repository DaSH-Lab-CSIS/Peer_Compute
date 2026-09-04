from collections import defaultdict
import time
import pulp
from django.apps import apps
from django.db import transaction
from django.db.models import Max
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
from django.conf import settings as django_settings
import fabric.views as fabric
import csv
import random
from providers.mincost import minimize_total_cost
from providers.prediction import (
    PredictionInput,
    ServicePredInput,
    predict as predict_runtimes,
)
from providers.prediction.cpi_strategy import CPIStrategy as _CPIStrategy
from providers.prediction.scaling_strategy import ScalingFactorStrategy as _ScalingFactorStrategy

# Module-level shadow strategy instances (stateless, thread-safe)
_SHADOW_STRATEGIES = {
    "cpi": _CPIStrategy(),
    "scaling": _ScalingFactorStrategy(),
}
from providers import profiling as scheduler_profiling
from developers.models import Services
import threading
import itertools as _itertools
import requests
import queue as _queue_mod
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Persistent in-process request queue + batch scheduler
# ---------------------------------------------------------------------------
# Each item: {'service': <Services obj>, 'req_data': dict,
#             'correlation_id': str, 'loadbalancer_id': str,
#             'received_time_iso': str}
_request_queue: _queue_mod.Queue = _queue_mod.Queue()

ILP_BATCH_SIZE = 50           # max services per ILP solve
ILP_QUEUE_POLL_INTERVAL = 0.5  # seconds between drain checks

# Round-robin placement state — persists across batches for true RR distribution.
_rr_lock = threading.Lock()
_rr_counter = _itertools.count(0)


def _prof(label: str, t0: float, **extra) -> float:
    """Print a structured PROFILE line, append JSONL when enabled; return current time."""
    elapsed = time.time() - t0
    extra_str = "  ".join(f"{k}={v}" for k, v in extra.items())
    print(f"[PROFILE] {label}  elapsed={elapsed:.4f}s  {extra_str}".rstrip())
    try:
        scheduler_profiling.persist_profile_row(label, elapsed_s=elapsed, **extra)
    except Exception:
        pass
    return time.time()


def _profile_note(label: str, **extra) -> None:
    """Structured PROFILE line without elapsed timing (persist + stderr)."""
    extra_str = "  ".join(f"{k}={v}" for k, v in extra.items())
    print(f"[PROFILE] {label}  {extra_str}".rstrip())
    try:
        scheduler_profiling.persist_profile_row(label, **extra)
    except Exception:
        pass


def _batch_scheduler_worker():
    """Background daemon that drains _request_queue in batches of ILP_BATCH_SIZE."""
    print("[batch-scheduler] worker started")
    while True:
        # Collect up to ILP_BATCH_SIZE pending items
        batch = []
        try:
            item = _request_queue.get(timeout=ILP_QUEUE_POLL_INTERVAL)
            batch.append(item)
        except _queue_mod.Empty:
            continue

        t_drain_start = time.time()
        while len(batch) < ILP_BATCH_SIZE:
            try:
                batch.append(_request_queue.get_nowait())
            except _queue_mod.Empty:
                break
        t_drain_end = time.time()

        queue_depth_after = _request_queue.qsize()
        _profile_note(
            "batch-drain",
            batch_size=len(batch),
            drain_time=round(t_drain_end - t_drain_start, 6),
            queue_depth_after=queue_depth_after,
        )

        by_correlation: dict = {}
        for it in batch:
            cid = it['correlation_id']
            by_correlation.setdefault(cid, {
                'services': [], 'requests_data': [],
                'loadbalancer_id': it['loadbalancer_id'],
                'received_time_iso': it['received_time_iso'],
            })
            by_correlation[cid]['services'].append(it['service'])
            by_correlation[cid]['requests_data'].append(it['req_data'])

        for cid, grp in by_correlation.items():
            svc_list = grp['services']
            req_list = grp['requests_data']
            lb_id = grp['loadbalancer_id']

            t_batch_start = time.time()
            scheduler_profiling.set_profile_correlation_id(cid)
            try:
                _profile_note(
                    "batch-start",
                    correlation_id=str(cid),
                    n_services=len(svc_list),
                    lb=lb_id,
                    queue_depth=_request_queue.qsize(),
                )

                try:
                    temp_time = datetime.now(tz=timezone(TIME_ZONE))
                    batch_results = request_handler(req_list, svc_list, temp_time, False)
                    t_batch_end = time.time()
                    processed_count = (
                        len([r for r in batch_results if 'error' not in r])
                        if batch_results else 0
                    )
                    results = batch_results or []
                    error_count = len(svc_list) - processed_count
                    _profile_note(
                        "batch-done",
                        correlation_id=str(cid),
                        n_services=len(svc_list),
                        processed=processed_count,
                        errors=error_count,
                        total_batch_time=round(t_batch_end - t_batch_start, 6),
                    )
                except Exception as exc:
                    t_batch_end = time.time()
                    _profile_note(
                        "batch-error",
                        correlation_id=str(cid),
                        error=str(exc),
                        total_batch_time=round(t_batch_end - t_batch_start, 6),
                    )
                    results = [{'error': f'ILP processing failed: {exc}'} for _ in svc_list]
                    processed_count = 0

                try:
                    mc = get_mclient()
                    if mc:
                        response_payload = {
                            'correlation_id': cid,
                            'status': 'success',
                            'batch_size': len(svc_list),
                            'processed': processed_count,
                            'ilp_solve_time': time.time() - t_batch_start,
                            'results': results,
                        }
                        mc.publish(
                            topic=lb_id,
                            payload="BATCH_RESPONSE:" + json.dumps(response_payload),
                            qos=2,
                        )
                except Exception as pub_exc:
                    print(f"[batch-scheduler] failed to publish response: {pub_exc}")
            finally:
                scheduler_profiling.clear_profile_correlation_id()

        for _ in batch:
            _request_queue.task_done()


# Start the batch-scheduler daemon thread once at module load
_batch_scheduler_thread = threading.Thread(
    target=_batch_scheduler_worker, daemon=True, name="batch-scheduler"
)
_batch_scheduler_thread.start()
# ---------------------------------------------------------------------------

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
# DEPRECATED - see providers/prediction/. Runtime prediction no longer uses MQTT;
# these structures are only kept so legacy PREDICT_RESPONSE messages don't crash
# the subscriber while the provider-side code is still around.
# MQTT predicted runtimes: correlation_id -> { 'results': { provider_user_id: { service_id: runtime } }, 'expected_providers': set, 'event': Event }
pending_predictions = {}
pending_predictions_lock = threading.Lock()

global service_id_array 
global service_queue
service_id_array = {}
service_queue = queue.Queue()
global requested_services


def _get_predict_response_topic():
    """DEPRECATED - see providers/prediction/.

    Topic where scheduler receives PREDICT_RESPONSE from providers. No longer
    used by the prediction path; kept for the MQTT subscriber fallback.
    """
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
            time.sleep(10)  # Heartbeat every 10s: keeps LB last_seen well under its 60s TTL even if the worker briefly stalls
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
            # Parse on the paho thread (fast) then hand off to batch-scheduler.
            # This keeps on_message() non-blocking so ACK/READY/stats are processed
            # without waiting for ILP to finish.
            try:
                batch_json = payload_str[14:]
                request_data = json.loads(batch_json)
                correlation_id = request_data.get('correlation_id')
                batch_data = request_data.get('batch_data')
                loadbalancer_id = request_data.get('loadbalancer_id', 'LOADBALANCER')

                print(f"Received BATCH_REQUEST with correlation_id: {correlation_id} "
                      f"({len(batch_data.get('requests', []))} requests) — enqueueing")

                scheduler_received_time_iso = datetime.now(tz=timezone(TIME_ZONE)).isoformat()
                enqueued = 0
                skipped_results = []

                for req_data in batch_data.get('requests', []):
                    try:
                        service_id = req_data.get('serviceID')
                        if not service_id:
                            skipped_results.append({'error': 'Missing serviceID'})
                            continue
                        service = Services.objects.get(id=service_id)
                        if not service.active:
                            skipped_results.append({'error': f'Service {service_id} is disabled'})
                            continue
                        req_data['_scheduler_received_time'] = scheduler_received_time_iso
                        _request_queue.put({
                            'service': service,
                            'req_data': req_data,
                            'correlation_id': correlation_id,
                            'loadbalancer_id': loadbalancer_id,
                            'received_time_iso': scheduler_received_time_iso,
                        })
                        enqueued += 1
                    except ObjectDoesNotExist:
                        skipped_results.append({'error': f'Service {service_id} not found'})
                    except Exception as e:
                        skipped_results.append({'error': f'Failed to enqueue request: {str(e)}'})

                print(f"[BATCH_REQUEST] enqueued {enqueued} requests "
                      f"(skipped {len(skipped_results)}), queue depth={_request_queue.qsize()}")

                # If every request was skipped (all invalid), reply immediately so
                # the LB is not left waiting indefinitely.
                if enqueued == 0 and skipped_results:
                    try:
                        error_response = {
                            'correlation_id': correlation_id,
                            'status': 'success',
                            'batch_size': len(batch_data.get('requests', [])),
                            'processed': 0,
                            'ilp_solve_time': None,
                            'results': skipped_results,
                        }
                        mqtt_client.publish(
                            topic=loadbalancer_id,
                            payload="BATCH_RESPONSE:" + json.dumps(error_response),
                            qos=2,
                        )
                    except Exception:
                        pass

            except Exception as e:
                print(f"Error parsing BATCH_REQUEST: {e}")
                try:
                    mqtt_client.publish(
                        topic=loadbalancer_id if 'loadbalancer_id' in locals() else 'LOADBALANCER',
                        payload="BATCH_RESPONSE:" + json.dumps({
                            'correlation_id': correlation_id if 'correlation_id' in locals() else 'unknown',
                            'status': 'error',
                            'error': str(e),
                        }),
                        qos=2,
                    )
                except Exception:
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


def _coerce_service_ids(raw_service_ids):
    """Normalize service ids from request payload into unique integer ids preserving order."""
    if not isinstance(raw_service_ids, list):
        raise ValueError("service_ids must be a list")
    normalized = []
    seen = set()
    for raw_id in raw_service_ids:
        try:
            service_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid service id: {raw_id}")
        if service_id not in seen:
            seen.add(service_id)
            normalized.append(service_id)
    if not normalized:
        raise ValueError("service_ids cannot be empty")
    return normalized


@csrf_exempt
def direct_invoke(request):
    """
    Internal endpoint to invoke services directly on one provider (bypasses LB/ILP).
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST is supported'}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON payload'}, status=400)

    provider_user_id = str(body.get('provider_user_id', '')).strip()
    if not provider_user_id:
        return JsonResponse({'status': 'error', 'message': 'provider_user_id is required'}, status=400)

    try:
        service_ids = _coerce_service_ids(body.get('service_ids'))
    except ValueError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    try:
        provider = User.objects.get(
            user_id=provider_user_id,
            is_provider=True,
            active=True,
        )
    except User.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': f'Provider not found or inactive: {provider_user_id}'},
            status=404,
        )

    if not provider.ready:
        return JsonResponse(
            {'status': 'error', 'message': f'Provider is not ready: {provider_user_id}'},
            status=409,
        )

    services = list(Services.objects.filter(id__in=service_ids, active=True))
    found_ids = {svc.id for svc in services}
    missing_or_inactive = [sid for sid in service_ids if sid not in found_ids]
    if missing_or_inactive:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Some services are missing or inactive',
                'service_ids': missing_or_inactive,
            },
            status=404,
        )

    service_by_id = {svc.id: svc for svc in services}
    ordered_services = [service_by_id[sid] for sid in service_ids]

    run_multiple = bool(body.get('runMultipleInvocations', False))
    number_of_invocations = int(body.get('numberOfInvocations', 1))
    is_chained = bool(body.get('chained', False))
    input_data = body.get('input', 'None')
    assigned_time = datetime.now(tz=timezone(TIME_ZONE))

    created_jobs = []
    errors = []

    for service in ordered_services:
        try:
            job = Job.objects.create(
                provider=provider,
                service=service,
                developer=service.developer,
                finished=False,
                scheduler_received_time=assigned_time,
                assigned_to_provider_time=assigned_time,
            )

            service_key = str(service.id)
            provider.function_invocations = provider.function_invocations or {}
            provider.function_invocations[service_key] = provider.function_invocations.get(service_key, 0) + 1
            provider.save(update_fields=['function_invocations'])

            publish_to_topic_mqtt(
                run_multiple,
                number_of_invocations,
                is_chained,
                input_data,
                provider,
                service.docker_container,
                service.developer,
                job.id,
            )

            created_jobs.append({
                'job_id': job.id,
                'service_id': service.id,
                'provider_user_id': str(provider.user_id),
                'status': 'sent',
            })
        except Exception as e:
            errors.append({'service_id': service.id, 'error': str(e)})

    http_status = 202 if created_jobs else 500
    return JsonResponse(
        {
            'status': 'accepted' if created_jobs else 'error',
            'provider_user_id': str(provider.user_id),
            'jobs': created_jobs,
            'errors': errors,
        },
        status=http_status,
    )


@csrf_exempt
def direct_invocation_status(request):
    """Return current status for previously created direct invocation job ids."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST is supported'}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON payload'}, status=400)

    raw_job_ids = body.get('job_ids')
    if not isinstance(raw_job_ids, list) or not raw_job_ids:
        return JsonResponse({'status': 'error', 'message': 'job_ids must be a non-empty list'}, status=400)

    job_ids = []
    for raw_id in raw_job_ids:
        try:
            job_ids.append(int(raw_id))
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': f'Invalid job id: {raw_id}'}, status=400)

    jobs = Job.objects.filter(id__in=job_ids).select_related('provider', 'service').order_by('id')
    job_by_id = {job.id: job for job in jobs}
    not_found = [job_id for job_id in job_ids if job_id not in job_by_id]

    results = []
    for job_id in job_ids:
        job = job_by_id.get(job_id)
        if not job:
            continue
        results.append(
            {
                'job_id': job.id,
                'provider_user_id': str(job.provider.user_id),
                'service_id': job.service.id if job.service else None,
                'finished': job.finished,
                'start_time': job.start_time.isoformat() if job.start_time else None,
                'ack_time': job.ack_time.isoformat() if job.ack_time else None,
                'lb_received_time': job.lb_received_time.isoformat() if job.lb_received_time else None,
                'scheduler_received_time': job.scheduler_received_time.isoformat() if job.scheduler_received_time else None,
                'assigned_to_provider_time': job.assigned_to_provider_time.isoformat() if job.assigned_to_provider_time else None,
                'pull_time': job.pull_time,
                'run_time': job.run_time,
                'total_time': job.total_time,
                'response': job.response,
                'corr_id': str(job.corr_id) if job.corr_id else None,
                'cost': job.cost,
                'finish_time': job.finish_time.isoformat() if job.finish_time else None,
                'memory_usage': job.memory_usage,
                'cpu_usage': job.cpu_usage,
                'cpu_efficiency_score': float(job.cpu_efficiency_score) if job.cpu_efficiency_score else None,
                'memory_efficiency_score': float(job.memory_efficiency_score) if job.memory_efficiency_score else None,
                'predicted_runtime_ms': job.predicted_runtime_ms,
                'prediction_strategy': job.prediction_strategy,
                'prediction_source': job.prediction_source,
            }
        )

    finished_count = len([j for j in results if j['finished']])
    return JsonResponse(
        {
            'status': 'ok',
            'job_count': len(job_ids),
            'finished_count': finished_count,
            'all_finished': finished_count == len(job_ids),
            'not_found_job_ids': not_found,
            'jobs': results,
        },
        status=200,
    )

@csrf_exempt
def reset_provider_state(request):
    """Reset delay and function_invocations for all active providers.

    Call this before starting a new experiment to ensure the scheduler's
    per-provider delay estimates and invocation counters don't carry over
    stale state from a previous run, which would skew ILP assignment decisions.

    POST (no body required).

    Returns:
        { "reset": <int n_providers>, "providers": [ user_id, ... ] }
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST is supported"}, status=405)

    providers = User.objects.filter(is_provider=True, active=True)
    reset_ids = []
    with transaction.atomic():
        for p in providers.select_for_update():
            p.reset_delay()
            p.function_invocations = {}
            p.save(update_fields=["delay", "function_invocations"])
            reset_ids.append(str(p.user_id))

    return JsonResponse({"reset": len(reset_ids), "providers": reset_ids})


def pending_jobs_count(request):
    """Return the count of dispatched-but-unfinished jobs created since a given timestamp.

    Query parameters:
        since (required): ISO-8601 UTC timestamp marking experiment start, e.g. 2026-05-15T13:00:00+00:00

    Only counts jobs that were actually dispatched to a provider
    (assigned_to_provider_time IS NOT NULL) so permanently-failed jobs that
    never left the scheduler queue are excluded.
    """
    from datetime import datetime, timezone as dt_tz

    since_str = request.GET.get("since")
    if not since_str:
        return JsonResponse({"error": "since param is required"}, status=400)

    try:
        since = datetime.fromisoformat(since_str)
        if since.tzinfo is None:
            since = since.replace(tzinfo=dt_tz.utc)
    except ValueError as exc:
        return JsonResponse({"error": f"Invalid since value: {exc}"}, status=400)

    active = Job.objects.filter(
        finished=False,
        assigned_to_provider_time__isnull=False,
        start_time__gte=since,
    ).count()

    return JsonResponse({"pending": active})


def jobs_in_window(request):
    """Return all jobs whose start_time falls within [since, until].

    Query parameters:
        since  (required): ISO-8601 UTC start of window, e.g. 2026-05-27T14:20:00Z
        until  (optional): ISO-8601 UTC end of window; defaults to now
        limit  (optional): max rows to return (default 10000, max 50000)
        offset (optional): pagination offset (default 0)

    Returns a JSON object:
        {
          "job_count": <int>,
          "since": <str>,
          "until": <str>,
          "jobs": [ { job fields ... }, ... ]
        }
    """
    from datetime import datetime, timezone as dt_tz

    since_str = request.GET.get("since")
    if not since_str:
        return JsonResponse({"error": "since param is required"}, status=400)

    try:
        since = datetime.fromisoformat(since_str)
        if since.tzinfo is None:
            since = since.replace(tzinfo=dt_tz.utc)
    except ValueError as exc:
        return JsonResponse({"error": f"Invalid since value: {exc}"}, status=400)

    until_str = request.GET.get("until")
    if until_str:
        try:
            until = datetime.fromisoformat(until_str)
            if until.tzinfo is None:
                until = until.replace(tzinfo=dt_tz.utc)
        except ValueError as exc:
            return JsonResponse({"error": f"Invalid until value: {exc}"}, status=400)
    else:
        until = datetime.now(tz=dt_tz.utc)

    try:
        limit = min(int(request.GET.get("limit", 10000)), 50000)
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        return JsonResponse({"error": "limit and offset must be integers"}, status=400)

    qs = (
        Job.objects.filter(start_time__gte=since, start_time__lte=until)
        .select_related("provider", "service")
        .order_by("start_time")[offset: offset + limit]
    )

    jobs_out = []
    for job in qs:
        jobs_out.append({
            "job_id": job.id,
            "provider_user_id": str(job.provider.user_id) if job.provider else None,
            "service_id": job.service.id if job.service else None,
            "finished": job.finished,
            "start_time": job.start_time.isoformat() if job.start_time else None,
            "ack_time": job.ack_time.isoformat() if job.ack_time else None,
            "lb_received_time": job.lb_received_time.isoformat() if job.lb_received_time else None,
            "scheduler_received_time": job.scheduler_received_time.isoformat() if job.scheduler_received_time else None,
            "assigned_to_provider_time": job.assigned_to_provider_time.isoformat() if job.assigned_to_provider_time else None,
            "pull_time": job.pull_time,
            "run_time": job.run_time,
            "total_time": job.total_time,
            "response": job.response,
            "corr_id": str(job.corr_id) if job.corr_id else None,
            "cost": job.cost,
            "finish_time": job.finish_time.isoformat() if job.finish_time else None,
            "memory_usage": job.memory_usage,
            "cpu_usage": job.cpu_usage,
            "cpu_efficiency_score": float(job.cpu_efficiency_score) if job.cpu_efficiency_score else None,
            "memory_efficiency_score": float(job.memory_efficiency_score) if job.memory_efficiency_score else None,
            "predicted_runtime_ms": job.predicted_runtime_ms,
            "prediction_strategy": job.prediction_strategy,
            "prediction_source": job.prediction_source,
        })

    return JsonResponse({
        "job_count": len(jobs_out),
        "since": since.isoformat(),
        "until": until.isoformat(),
        "jobs": jobs_out,
    })


@csrf_exempt
def timeout_stale_jobs(request):
    """Mark stale dispatched jobs as finished with timeout sentinel response.

    Expects POST body JSON:
      {
        "since": "<iso8601>",
        "no_result_threshold_seconds": 300,
        "no_ack_threshold_seconds": 120
      }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST is supported'}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload'}, status=400)

    since_str = body.get("since")
    if not since_str:
        return JsonResponse({"error": "since field is required"}, status=400)

    try:
        no_result_threshold = int(body.get("no_result_threshold_seconds", 300))
        no_ack_threshold = int(body.get("no_ack_threshold_seconds", 120))
    except (TypeError, ValueError):
        return JsonResponse(
            {"error": "Thresholds must be integers (seconds)"},
            status=400,
        )

    if no_result_threshold < 0 or no_ack_threshold < 0:
        return JsonResponse(
            {"error": "Thresholds must be non-negative"},
            status=400,
        )

    from datetime import datetime, timezone as dt_tz
    try:
        since = datetime.fromisoformat(since_str)
        if since.tzinfo is None:
            since = since.replace(tzinfo=dt_tz.utc)
    except ValueError as exc:
        return JsonResponse({"error": f"Invalid since value: {exc}"}, status=400)

    now = datetime.now(tz=dt_tz.utc)

    from django.db import OperationalError

    base_qs = Job.objects.filter(
        finished=False,
        assigned_to_provider_time__isnull=False,
        start_time__gte=since,
    )

    # Read candidates WITHOUT locking and decide timeouts in Python. This keeps each
    # write transaction tiny and short-lived, so it does not collide with the many
    # concurrent job-completion writes on these same rows — the collision is what made
    # the old single-transaction select_for_update sweep abort with a CockroachDB
    # RETRY_SERIALIZABLE error.
    candidates = base_qs.values("id", "ack_time", "assigned_to_provider_time")

    no_ack_ids = []
    no_result_ids = []
    for row in candidates:
        if row["ack_time"] is None:
            elapsed = (now - row["assigned_to_provider_time"]).total_seconds()
            if elapsed > no_ack_threshold:
                no_ack_ids.append(row["id"])
        else:
            elapsed = (now - row["ack_time"]).total_seconds()
            if elapsed > no_result_threshold:
                no_result_ids.append(row["id"])

    def _bulk_timeout(ids, kind, batch_size=500, max_retries=5):
        """Mark jobs finished in small batches, retrying CockroachDB serializable conflicts."""
        response_value = json.dumps(
            {"sweep": "timeout", "kind": kind, "swept_at": now.isoformat()}
        )
        updated = 0
        for start in range(0, len(ids), batch_size):
            chunk = ids[start:start + batch_size]
            for attempt in range(max_retries):
                try:
                    with transaction.atomic():
                        # Re-check finished=False so a job that completed for real
                        # between the read above and now is never clobbered.
                        n = (
                            Job.objects
                            .filter(id__in=chunk, finished=False)
                            .update(finished=True, response=response_value)
                        )
                    updated += n
                    break
                except OperationalError:
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(0.1 * (2 ** attempt))
        return updated

    timed_out_no_ack = _bulk_timeout(no_ack_ids, "no_ack")
    timed_out_no_result = _bulk_timeout(no_result_ids, "no_result")

    remaining_pending = Job.objects.filter(
        finished=False,
        assigned_to_provider_time__isnull=False,
        start_time__gte=since,
    ).count()

    return JsonResponse(
        {
            "timed_out": {
                "no_ack": timed_out_no_ack,
                "no_result": timed_out_no_result,
            },
            "remaining_pending": remaining_pending,
        },
        status=200,
    )


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
            
            # Jobs were already created and dispatched in find_providers → process_assignments.
            # Build results from the assignment dict — no DB round-trips needed here.
            assignment_by_svc_id = {}
            for key, assigned_provider in assignment.items():
                if isinstance(key, tuple) and len(key) == 2:
                    _, assigned_svc = key
                    assignment_by_svc_id[assigned_svc.id] = assigned_provider

            results = []
            for svc in services:
                provider = assignment_by_svc_id.get(svc.id)
                if provider:
                    print(f"Job dispatched to provider {provider.user_id} for service {svc.id}")
                    results.append((
                        {"Result": "Request sent to provider", "pull_time": 0, "run_time": 0, "total_time": 0},
                        provider.user_id,
                        0,
                        None,
                    ))
                else:
                    print(f"Warning: No provider assigned for service {svc.id}")
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
        job.finish_time = datetime.now(tz=timezone(TIME_ZONE))
        
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
                cache_location = data.get('cache_state', 'memory')

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


# DEPRECATED - see providers/prediction/. The HTTP and MQTT prediction helpers
# below are no longer called from get_predicted_runtimes / build_cost_matrix.
# They are kept in place so existing provider-side endpoints keep working while
# the new path is validated; remove them in a follow-up PR.
def _get_provider_http_base_url(provider):
    """DEPRECATED - see providers/prediction/. Get HTTP base URL for provider's predicted_runtime endpoint."""
    from django.conf import settings
    url_by_loc = getattr(settings, "PROVIDER_HTTP_URL_BY_LOCATION", {})
    if provider.location and url_by_loc:
        return url_by_loc.get(provider.location)
    return getattr(settings, "PROVIDER_HTTP_BASE_URL", "http://localhost:9002")


def _fetch_predicted_runtime_http(base_url, service_docker, timeout=5):
    """DEPRECATED - see providers/prediction/. Fetch predicted runtime from provider via HTTP. Returns value or None."""
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
    """DEPRECATED - see providers/prediction/.

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
    """DEPRECATED - see providers/prediction/. Scheduler now runs predictions locally.

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


def get_predicted_runtimes_db_pass(provider, services, run_time_map=None):
    """
    First pass: fill predicted_runtimes from Job history; collect services needing prediction.

    run_time_map: optional pre-fetched {(provider_id, service_id): run_time} built by
                  Job.bulk_latest_run_time().  When supplied, no per-row ORM calls are made
                  (fast path — one round-trip for the entire batch instead of N×M).

    Returns: (predicted_runtimes dict, services_needing_prediction list, timing dict).
    """
    predicted_runtimes = {}
    services_needing_prediction = []
    job_latest_run_query_s = 0.0
    job_latest_run_calls = 0
    for service in services:
        try:
            service_id = None
            if hasattr(service, "id"):
                service_id = service.id
            elif isinstance(service, tuple) and len(service) == 2 and hasattr(service[1], "id"):
                service_id = service[1].id
            if service_id is None:
                continue

            if run_time_map is not None:
                val = run_time_map.get((provider.id, service_id))
                if val is not None:
                    predicted_runtimes[service_id] = val
                else:
                    services_needing_prediction.append((service_id, service))
            else:
                try:
                    tq = time.time()
                    latest_run_time = Job.get_latest_run_time(provider.id, service_id)
                    job_latest_run_query_s += time.time() - tq
                    job_latest_run_calls += 1
                    predicted_runtimes[service_id] = latest_run_time
                except Job.DoesNotExist:
                    services_needing_prediction.append((service_id, service))
        except Exception:
            pass
    timings = {
        "job_latest_run_query_s": job_latest_run_query_s,
        "job_latest_run_calls": job_latest_run_calls,
    }
    return predicted_runtimes, services_needing_prediction, timings


def get_predicted_runtimes_cache_pass(provider, services, predicted_runtimes,
                                      default_runtime=1000, pull_time_map=None):
    """
    Second pass: adjust predicted_runtimes for cache state (pull time).
    Mutates predicted_runtimes in place.

    pull_time_map: optional pre-fetched {(provider_id, service_id): pull_time} built by
                   Job.bulk_latest_pull_time().  When supplied, no per-row ORM calls are made.

    Returns a timing breakdown dict with cache_probe_s, pull_time_query_s, pull_time_calls.
    """
    cache_probe_s = 0.0
    pull_time_query_s = 0.0
    pull_time_calls = 0

    for service in services:
        try:
            service_id = None
            if hasattr(service, "id"):
                service_id = service.id
            elif isinstance(service, tuple) and len(service) == 2 and hasattr(service[1], "id"):
                service_id = service[1].id
            if service_id is None or service_id not in predicted_runtimes:
                continue
            tp = time.time()
            cached = provider.is_service_cached(service_id)
            cache_location = None
            if cached:
                cache_location = provider.get_cache_location(service_id)
            cache_probe_s += time.time() - tp
            if cached:
                if cache_location == "memory":
                    continue
                if cache_location == "disk":
                    try:
                        if pull_time_map is not None:
                            pull_time = pull_time_map.get((provider.id, service_id))
                            pull_time_calls += 1
                        else:
                            t_pull = time.time()
                            pull_time = Job.get_latest_pull_time(provider.id, service_id)
                            pull_time_query_s += time.time() - t_pull
                            pull_time_calls += 1
                        if pull_time:
                            predicted_runtimes[service_id] += int(pull_time * 0.2)
                    except Exception:
                        pass
            else:
                try:
                    if pull_time_map is not None:
                        pull_time = pull_time_map.get((provider.id, service_id))
                        pull_time_calls += 1
                    else:
                        t_pull = time.time()
                        pull_time = Job.get_latest_pull_time(provider.id, service_id)
                        pull_time_query_s += time.time() - t_pull
                        pull_time_calls += 1
                    if pull_time:
                        predicted_runtimes[service_id] += pull_time
                except Exception:
                    pass
        except Exception:
            pass
    return {
        "cache_probe_s": cache_probe_s,
        "pull_time_query_s": pull_time_query_s,
        "pull_time_calls": pull_time_calls,
    }


def _build_prediction_input(provider, services_needing_prediction, service_rows_by_id=None):
    """Build a PredictionInput for one provider from already-loaded DB rows.

    ``services_needing_prediction`` is a list of ``(service_id, service)`` tuples
    as produced by :func:`get_predicted_runtimes_db_pass`. If ``service_rows_by_id``
    is not supplied the rows are fetched in one query by id.
    """
    service_ids = [sid for sid, _ in services_needing_prediction if sid is not None]
    if service_rows_by_id is None:
        service_rows_by_id = {
            s.id: s
            for s in Services.objects.filter(id__in=service_ids).only(
                "id",
                "cpu_cycles_required",
                "memory_footprint",
                "memory_bytes_per_second",
                "reference_stats",
                "ref_runtime_ms",
                "w_cpu",
                "w_mem",
                "w_disk",
                "w_net",
                "image_size_mb",
            )
        }
    svc_inputs = []
    for sid in service_ids:
        row = service_rows_by_id.get(sid)
        if row is None:
            svc_inputs.append(ServicePredInput(service_id=sid))
            continue
        svc_inputs.append(
            ServicePredInput(
                service_id=sid,
                cpu_cycles_required=row.cpu_cycles_required,
                memory_footprint=row.memory_footprint,
                memory_bytes_per_second=row.memory_bytes_per_second,
                reference_stats=row.reference_stats,
                ref_runtime_ms=getattr(row, "ref_runtime_ms", None),
                w_cpu=getattr(row, "w_cpu", None),
                w_mem=getattr(row, "w_mem", None),
                w_disk=getattr(row, "w_disk", None),
                w_net=getattr(row, "w_net", None),
                image_size_mb=getattr(row, "image_size_mb", None),
            )
        )
    return PredictionInput(
        provider_id=provider.id,
        cpi=getattr(provider, "cpi", None),
        memory_bandwidth=getattr(provider, "memory_bandwidth", None),
        clock_hz=getattr(provider, "clock_hz", None),
        cpu_efficiency_score=getattr(provider, "cpu_efficiency_score", None),
        memory_efficiency_score=getattr(provider, "memory_efficiency_score", None),
        r_cpu=getattr(provider, "r_cpu", None),
        r_mem=getattr(provider, "r_mem", None),
        r_disk=getattr(provider, "r_disk", None),
        r_net=getattr(provider, "r_net", None),
        s_disk_mbps=getattr(provider, "s_disk_mbps", None),
        s_net_mbps=getattr(provider, "s_net_mbps", None),
        services=svc_inputs,
    )


def get_predicted_runtimes(provider, services):
    """Get predicted runtimes for one provider via DB fast-path + pluggable predictor + cache pass.

    Replaces the legacy MQTT round-trip: we now pull all features the strategy
    needs from Postgres and call :func:`providers.prediction.predict` locally.
    """
    DEFAULT_RUNTIME = 1000
    print("Entering get_predicted_runtimes")
    force_model = getattr(settings, 'PREDICTION_FORCE_MODEL', False)
    predicted_runtimes, services_needing_prediction, _db_timings = get_predicted_runtimes_db_pass(
        provider, services, run_time_map={} if force_model else None
    )
    if services_needing_prediction:
        pred_input = _build_prediction_input(provider, services_needing_prediction)
        try:
            output = predict_runtimes(pred_input)
            runtimes = output.runtimes_ms
        except Exception as e:
            print(f"[predict] strategy raised {e}; falling back to default")
            runtimes = {}
        for service_id, _ in services_needing_prediction:
            val = runtimes.get(service_id)
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
    """Build cost matrix: DB fast-path per provider, then one local predict() per provider, then cache pass.

    The MQTT batch round-trip has been removed; all prediction features live in
    Postgres and are consumed by the currently-configured strategy in
    :mod:`providers.prediction`.
    """
    DEFAULT_RUNTIME = 1000
    t0 = time.time()
    n_providers = len(providers)
    n_services = len(services)
    _profile_note(
        "build_cost_matrix-start",
        n_providers=n_providers,
        n_services=n_services,
        matrix_entries=n_providers * n_services,
    )
    cost_matrix = {}
    indexed_services = list(enumerate(services))
    compatible_services = services

    # Bulk-fetch run_time and pull_time for ALL (provider, service) pairs in two queries
    # instead of N_providers × N_services individual round-trips.
    t_bulk = time.time()
    provider_ids = [p.id for p in providers]
    service_ids = list({
        getattr(s, "id", None) or (s[1].id if isinstance(s, tuple) and len(s) == 2 else None)
        for s in services
    } - {None})
    run_time_map  = Job.bulk_latest_run_time(provider_ids, service_ids)
    pull_time_map = Job.bulk_latest_pull_time(provider_ids, service_ids)
    force_model = getattr(settings, 'PREDICTION_FORCE_MODEL', False)
    effective_run_time_map = {} if force_model else run_time_map
    _prof(
        "build_cost_matrix-bulk_prefetch",
        t_bulk,
        n_run_time_rows=len(run_time_map),
        n_pull_time_rows=len(pull_time_map),
        n_provider_ids=len(provider_ids),
        n_service_ids=len(service_ids),
    )

    # First pass: distribute pre-fetched run_times per provider — pure dict lookups.
    t_db_outer = time.time()
    per_provider_runtimes = {}
    provider_services_map = {}
    for provider in providers:
        predicted_runtimes, services_needing_prediction, t_db_inner = (
            get_predicted_runtimes_db_pass(provider, compatible_services,
                                           run_time_map=effective_run_time_map)
        )
        per_provider_runtimes[provider] = predicted_runtimes
        if services_needing_prediction:
            provider_services_map[provider] = services_needing_prediction
    t_db_elapsed = time.time() - t_db_outer
    # Source tracking: DB-history runtimes start as 'history'; forced-model start as 'model'
    _initial_source = 'model' if force_model else 'history'
    prediction_source_map = {
        prov.id: {sid: _initial_source for sid in runtimes}
        for prov, runtimes in per_provider_runtimes.items()
    }
    _prof(
        "build_cost_matrix-db_pass",
        t_db_outer,
        n_providers=n_providers,
        providers_needing_prediction=len(provider_services_map),
        job_latest_run_query_s=0.0,
        job_latest_run_calls=0,
        db_pass_non_orm_s=t_db_elapsed,
    )

    # Pre-fetch all Services rows once for the union of ids needing prediction
    t_prefetch = time.time()
    service_rows_by_id = {}
    if provider_services_map:
        all_ids = {
            sid
            for pairs in provider_services_map.values()
            for sid, _ in pairs
            if sid is not None
        }
        if all_ids:
            service_rows_by_id = {
                s.id: s
                for s in Services.objects.filter(id__in=all_ids).only(
                    "id",
                    "cpu_cycles_required",
                    "memory_footprint",
                    "memory_bytes_per_second",
                    "reference_stats",
                    "ref_runtime_ms",
                    "w_cpu",
                    "w_mem",
                    "w_disk",
                    "w_net",
                    "image_size_mb",
                )
            }
    _prof("build_cost_matrix-prefetch_service_rows", t_prefetch,
          ids_fetched=len(service_rows_by_id))

    # Run the strategy once per provider using the pre-fetched rows
    t_predict_total = time.time()
    sum_predict_strategy_s = 0.0
    sum_predict_merge_defaults_s = 0.0
    sum_cache_probe_s = 0.0
    sum_pull_query_s = 0.0
    sum_pull_calls = 0
    sum_subdict_s = 0.0

    for provider in providers:
        predicted_runtimes = per_provider_runtimes[provider]
        if provider in provider_services_map:
            pred_input = _build_prediction_input(
                provider, provider_services_map[provider], service_rows_by_id
            )
            t_strat = time.time()
            try:
                output = predict_runtimes(pred_input)
                runtimes = output.runtimes_ms
            except Exception as e:
                print(f"[predict] strategy raised {e}; falling back to default")
                runtimes = {}
            strat_elapsed = time.time() - t_strat
            sum_predict_strategy_s += strat_elapsed
            _prof(
                "build_cost_matrix-predict_strategy_provider",
                t_strat,
                provider=provider.user_id,
                strategy_segment_s=strat_elapsed,
            )

            t_merge = time.time()
            n_predicted = 0
            n_defaulted = 0
            provider_src = prediction_source_map.setdefault(provider.id, {})
            for service_id, _ in provider_services_map[provider]:
                val = runtimes.get(service_id)
                if val is not None and val > 0:
                    predicted_runtimes[service_id] = int(val)
                    n_predicted += 1
                    provider_src[service_id] = 'model'
                else:
                    predicted_runtimes[service_id] = DEFAULT_RUNTIME
                    n_defaulted += 1
                    provider_src[service_id] = 'fallback'
            sum_predict_merge_defaults_s += time.time() - t_merge
            _profile_note(
                "build_cost_matrix-merge_defaults_provider",
                provider=provider.user_id,
                predicted=n_predicted,
                defaulted=n_defaulted,
            )

            # Shadow evaluation: run all static strategies against the same pred_input
            # and emit one prediction_audit record per (provider, service).
            # This is the Axis-P dataset for offline accuracy scoring.
            try:
                _active_name = django_settings.RUNTIME_PREDICTION_STRATEGY
                _shadow_outputs: dict[str, dict] = {}
                for _s_name, _s_inst in _SHADOW_STRATEGIES.items():
                    try:
                        _shadow_outputs[_s_name] = _s_inst.predict(pred_input).runtimes_ms
                    except Exception:
                        _shadow_outputs[_s_name] = {}
                for _sid, _svc_obj in provider_services_map[provider]:
                    _audit_rec: dict = {
                        "provider_id": provider.id,
                        "service_id": _sid,
                        "active_strategy": _active_name,
                        "active_output_ms": runtimes.get(_sid),
                        "prediction_source": provider_src.get(_sid),
                        "cpi_output_ms": _shadow_outputs.get("cpi", {}).get(_sid),
                        "scaling_output_ms": _shadow_outputs.get("scaling", {}).get(_sid),
                        # Provider CPI features
                        "f_cpi": float(pred_input.cpi) if pred_input.cpi is not None else None,
                        "f_clock_hz": pred_input.clock_hz,
                        "f_memory_bandwidth": float(pred_input.memory_bandwidth) if pred_input.memory_bandwidth is not None else None,
                        "f_r_cpu": pred_input.r_cpu,
                        "f_r_mem": pred_input.r_mem,
                        "f_r_disk": pred_input.r_disk,
                        "f_r_net": pred_input.r_net,
                    }
                    # Append per-service features
                    _svc_feats = next((s for s in pred_input.services if s.service_id == _sid), None)
                    if _svc_feats is not None:
                        _audit_rec.update({
                            "f_cpu_cycles_required": _svc_feats.cpu_cycles_required,
                            "f_memory_footprint": _svc_feats.memory_footprint,
                            "f_ref_runtime_ms": _svc_feats.ref_runtime_ms,
                            "f_w_cpu": _svc_feats.w_cpu,
                            "f_w_mem": _svc_feats.w_mem,
                            "f_w_disk": _svc_feats.w_disk,
                            "f_w_net": _svc_feats.w_net,
                            "f_image_size_mb": _svc_feats.image_size_mb,
                            "f_ema_runtime_ms": _svc_feats.ema_runtime_ms,
                            "f_observation_count": _svc_feats.observation_count,
                            "f_cache_state": _svc_feats.cache_state,
                        })
                    try:
                        scheduler_profiling.persist_prediction_audit_row(**_audit_rec)
                    except Exception:
                        pass
            except Exception:
                pass

        ctim = get_predicted_runtimes_cache_pass(
            provider, compatible_services, predicted_runtimes, DEFAULT_RUNTIME,
            pull_time_map=pull_time_map,
        )
        sum_cache_probe_s += ctim["cache_probe_s"]
        sum_pull_query_s += ctim["pull_time_query_s"]
        sum_pull_calls += int(ctim["pull_time_calls"])

        t_sub = time.time()
        subdict = {}
        for i, svc in indexed_services:
            service_id = getattr(svc, "id", None)
            if service_id is not None:
                runtime = predicted_runtimes.get(service_id, float("inf"))
                subdict[(i, svc)] = runtime
            else:
                print(f"Warning: Could not get ID from service object: {svc}")
                subdict[(i, svc)] = float("inf")
        sum_subdict_s += time.time() - t_sub
        cost_matrix[provider] = subdict

    _prof(
        "build_cost_matrix-predict_all_providers",
        t_predict_total,
        n_providers=n_providers,
        predict_strategy_s=sum_predict_strategy_s,
        predict_merge_defaults_s=sum_predict_merge_defaults_s,
        cache_probe_s=sum_cache_probe_s,
        pull_time_query_s=sum_pull_query_s,
        pull_time_calls=sum_pull_calls,
        subdict_build_s=sum_subdict_s,
        cache_python_overhead_s=max(
            0.0,
            (time.time() - t_predict_total)
            - sum_predict_strategy_s
            - sum_predict_merge_defaults_s
            - sum_cache_probe_s
            - sum_pull_query_s
            - sum_subdict_s,
        ),
    )

    # Only print cost matrix for small batches to avoid log flood (time this explicitly).
    if n_services <= 20:
        t_print_m = time.time()
        print_cost_matrix(cost_matrix)
        _prof("build_cost_matrix-print_matrix", t_print_m, n_services=n_services)
    else:
        _profile_note(
            "build_cost_matrix-skipping_print_matrix",
            reason=f"n_services={n_services}>20",
        )

    _prof("build_cost_matrix-total", t0,
          n_providers=n_providers, n_services=n_services,
          matrix_entries=n_providers * n_services)
    return cost_matrix, prediction_source_map

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
    t0 = time.time()
    _profile_note("build_delay_dict-start", n_providers=len(providers))
    delay = {}
    sum_get_last_start_s = 0.0
    sum_calculate_delay_s = 0.0

    # Bulk-fetch the latest start_time for all providers in ONE query instead of
    # one round-trip per provider (~60ms × N_providers saved).
    t_bulk = time.time()
    provider_id_list = [p.id for p in providers]
    from datetime import timedelta
    cutoff = datetime.now(tz=timezone(TIME_ZONE)) - timedelta(days=90)
    bulk_rows = (
        Job.objects
        .filter(provider_id__in=provider_id_list, start_time__gte=cutoff)
        .values('provider_id')
        .annotate(last_start=Max('start_time'))
    )
    last_start_map = {r['provider_id']: r['last_start'] for r in bulk_rows}
    _prof("build_delay_dict-bulk_prefetch", t_bulk,
          n_providers=len(providers), n_rows=len(last_start_map))

    t_loop = time.time()
    for provider in providers:
        try:
            t_gl = time.time()
            time_of_last_startjob = last_start_map.get(provider.id)
            sum_get_last_start_s += time.time() - t_gl
            print(f"Time of last start job for {provider.user_id}: {str(time_of_last_startjob)}")
            
            # Ensure proper type for datetime calculation
            if time_of_last_startjob is None:
                print(f"No previous jobs for provider {provider.user_id}")
                delay[provider] = 0
            elif isinstance(time_of_last_startjob, datetime):
                try:
                    t_cd = time.time()
                    delay[provider] = provider.calculate_current_delay(time_of_last_startjob)
                    sum_calculate_delay_s += time.time() - t_cd
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
                    
                    t_cd = time.time()
                    delay[provider] = provider.calculate_current_delay(dt)
                    sum_calculate_delay_s += time.time() - t_cd
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

    _prof(
        "build_delay_dict-provider_loop",
        t_loop,
        n_providers=len(providers),
        get_last_start_time_s=sum_get_last_start_s,
        calculate_current_delay_s=sum_calculate_delay_s,
        loop_remainder_s=max(
            0.0,
            time.time() - t_loop - sum_get_last_start_s - sum_calculate_delay_s,
        ),
    )

    t_print_final = time.time()
    print(f"Delay dictionary: {delay}")
    _prof("build_delay_dict-print_final_dict_summary", t_print_final)
    _prof("build_delay_dict-total", t0, n_providers=len(providers))
    return delay

def process_assignments(assignment, cost_matrix, request_data_map=None, prediction_source_map=None):
    """
    Process job assignments and create Job objects.

    Args:
        assignment: Dictionary mapping (index, service) to provider
        cost_matrix: Cost matrix for ILP
        request_data_map: Optional dict mapping service.id to request data (for timestamps)
    """
    t0 = time.time()
    n_assignments = len(assignment)
    _profile_note("process_assignments-start", n_assignments=n_assignments)
    assigned_time = datetime.now(tz=timezone(TIME_ZONE))

    # Pre-compute all data before touching the DB so the transaction is as short as possible.
    pending = []          # list of (Job instance, provider, service)
    providers_seen = {}   # provider.id -> provider instance (accumulates delay/invocation changes)

    for key, provider in assignment.items():
        i, service = key if isinstance(key, tuple) and len(key) == 2 else (0, key)

        lb_received_time = None
        scheduler_received_time = None
        if request_data_map and service.id in request_data_map:
            req_data = request_data_map[service.id]
            if '_lb_received_time' in req_data:
                try:
                    lb_received_time = datetime.fromisoformat(
                        req_data['_lb_received_time'].replace('Z', '+00:00')
                    ).astimezone(timezone(TIME_ZONE))
                except Exception as e:
                    print(f"Error parsing lb_received_time: {e}")
            if '_scheduler_received_time' in req_data:
                try:
                    scheduler_received_time = datetime.fromisoformat(
                        req_data['_scheduler_received_time'].replace('Z', '+00:00')
                    ).astimezone(timezone(TIME_ZONE))
                except Exception as e:
                    print(f"Error parsing scheduler_received_time: {e}")

        try:
            if isinstance(key, tuple) and (i, service) in cost_matrix.get(provider, {}):
                predicted_runtime = cost_matrix[provider][(i, service)]
            elif service in cost_matrix.get(provider, {}):
                predicted_runtime = cost_matrix[provider][service]
            elif service.id in cost_matrix.get(provider, {}):
                predicted_runtime = cost_matrix[provider][service.id]
            else:
                print(f"Warning: Could not find runtime prediction for service {service.id} in cost matrix")
                predicted_runtime = 1000
        except Exception as e:
            print(f"Error accessing cost matrix: {str(e)}")
            predicted_runtime = 1000

        _pred_source = (prediction_source_map or {}).get(provider.id, {}).get(service.id, 'fallback')

        job = Job(
            provider=provider,
            service=service,
            developer=service.developer,
            finished=False,
            lb_received_time=lb_received_time,
            scheduler_received_time=scheduler_received_time,
            assigned_to_provider_time=assigned_time,
            predicted_runtime_ms=int(predicted_runtime) if predicted_runtime is not None else None,
            prediction_strategy=django_settings.RUNTIME_PREDICTION_STRATEGY,
            prediction_source=_pred_source,
        )
        pending.append((job, provider, service))

        # Accumulate provider state changes (one provider may serve multiple services)
        if provider.id not in providers_seen:
            providers_seen[provider.id] = provider
        try:
            provider.add_delay(predicted_runtime)
        except Exception as e:
            print(f"Error adding delay: {e}")
            provider.delay = provider.delay or 0
        service_key = str(service.id)
        provider.function_invocations[service_key] = provider.function_invocations.get(service_key, 0) + 1

    # Single bulk INSERT for all jobs + single bulk UPDATE for all providers.
    t_tx1 = time.time()
    with transaction.atomic():
        created_jobs = Job.objects.bulk_create([p[0] for p in pending])
        User.objects.bulk_update(
            list(providers_seen.values()), ['delay', 'function_invocations']
        )
    _prof("process_assignments-tx1_job_create", t_tx1, n_jobs=n_assignments)

    # MQTT dispatch after the transaction has committed
    t_send = time.time()
    n_sent = 0
    n_send_errors = 0
    for created_job, (_, provider, service) in zip(created_jobs, pending):
        try:
            print(f"Sending job {created_job.id} to provider {provider.user_id}")
            publish_to_topic_mqtt(
                False, 1, False, 'None',
                provider,
                service.docker_container,
                service.developer,
                created_job.id
            )
            print(f"Job {created_job.id} successfully sent to provider {provider.user_id}")
            n_sent += 1
        except Exception as e:
            print(f"Failed to send job {created_job.id} to provider {provider.user_id}: {str(e)}")
            n_send_errors += 1

    _prof("process_assignments-mqtt_publish_jobs", t_send,
          n_sent=n_sent, n_send_errors=n_send_errors)
    _prof("process_assignments-total", t0,
          n_assignments=n_assignments, n_sent=n_sent, n_send_errors=n_send_errors)

    mc = get_mclient()
    if mc:
        mc.publish(topic="ROTATION", payload="ILP_DONE", qos=2)
        _profile_note("process_assignments", mqtt_note="published ILP_DONE to ROTATION")


def find_providers(services, jobs=None, request_data_map=None):
    """
    Find providers for services using ILP.
    
    Args:
        services: List of Service objects
        jobs: Optional jobs parameter (legacy)
        request_data_map: Optional dict mapping service.id to request data (for timestamps)
    """
    t_fp_start = time.time()
    n_services = len(services) if isinstance(services, list) else 1
    _profile_note("find_providers-start", n_services=n_services)

    # Retry logic for database lock contention
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            if not isinstance(services, list):
                services = [services]

            # ------------------------------------------------------------------
            # Transaction 1 (short): read provider state, build cost/delay data.
            # Locks are released before ILP solve so MQTT callbacks can write DB.
            # ------------------------------------------------------------------
            t_tx1_start = time.time()
            with transaction.atomic():
                # Time from entering transaction to query execution start
                t_lock_wait_start = time.time()
                _prof("find_providers-pre_lock_overhead", t_tx1_start)

                suitable_providers = get_ready_providers()

                # Force QuerySet evaluation — this is where SELECT FOR UPDATE executes
                # and lock contention blocks if another scheduler holds the rows.
                t_eval_start = time.time()
                _prof("find_providers-qs_build_overhead", t_lock_wait_start)

                suitable_providers_list = list(suitable_providers)
                _prof("find_providers-select_for_update_eval", t_eval_start,
                      n_providers=len(suitable_providers_list))

                if not suitable_providers_list:
                    print("No ready providers available.")
                    return None

                suitable_providers = suitable_providers_list
                _prof("find_providers-get_ready_providers", t_tx1_start,
                      n_providers=len(suitable_providers))

                t_cm = time.time()
                cost_matrix, prediction_source_map = build_cost_matrix(suitable_providers, services)
                _prof("find_providers-build_cost_matrix", t_cm,
                      n_providers=len(suitable_providers), n_services=len(services))

                t_dd = time.time()
                delay = build_delay_dict(suitable_providers)
                _prof("find_providers-build_delay_dict", t_dd,
                      n_providers=len(suitable_providers))

            _prof("find_providers-tx1_total", t_tx1_start,
                  n_providers=len(suitable_providers), n_services=len(services))
            # provider row locks released here

            # ------------------------------------------------------------------
            # ILP solve — pure CPU, no DB, runs outside any transaction.
            # ACK/READY/stats from providers can now update the DB freely.
            # ------------------------------------------------------------------
            indexed_services = [(i, svc) for i, svc in enumerate(services)]
            n_vars = len(suitable_providers) * len(services)
            t_ilp = time.time()
            _profile_note(
                "find_providers-ilp_start",
                n_providers=len(suitable_providers),
                n_services=len(services),
                n_binary_vars=n_vars,
            )

            try:
                if django_settings.SCHEDULER_PLACEMENT_MODE == "rr":
                    # Round-robin: assign each (index, service) cyclically across
                    # suitable_providers.  The counter is module-level so RR
                    # distribution is maintained across the entire experiment,
                    # not just within a single batch.
                    with _rr_lock:
                        start = next(_rr_counter)
                    assignment = {}
                    for batch_idx, (i, service) in enumerate(indexed_services):
                        provider = suitable_providers[
                            (start + batch_idx) % len(suitable_providers)
                        ]
                        assignment[(i, service)] = provider
                    total_cost = 0
                    _prof("find_providers-rr_assign", t_ilp,
                          n_services=len(indexed_services), rr_start=start)
                else:
                    assignment, total_cost = minimize_total_cost(
                        suitable_providers, indexed_services, cost_matrix, delay
                    )
                    _prof("find_providers-ilp_solve", t_ilp,
                          n_vars=n_vars, total_cost=total_cost)
                main_processing_succeeded = False

                if assignment is None:
                    print("Warning: No optimal solution found")
                    return None

                # ------------------------------------------------------------------
                # Transaction 2 (short): write assignments, create Job rows.
                # ------------------------------------------------------------------
                t_tx2 = time.time()
                with transaction.atomic():
                    process_assignments(assignment, cost_matrix, request_data_map, prediction_source_map)
                _prof("find_providers-tx2_process_assignments", t_tx2,
                      n_assignments=len(assignment))
                main_processing_succeeded = True
                _prof("find_providers-total", t_fp_start,
                      n_services=len(services), n_providers=len(suitable_providers),
                      n_vars=n_vars)
                print(f"DEBUG: Main processing succeeded, flag set to: {main_processing_succeeded}")

                if jobs is not None:
                    job_mapping = {}
                    for i, (service, job) in enumerate(zip(services, jobs)):
                        job_mapping[(i, service)] = job
                    provider_assignments = {}
                    for (i, service), provider in assignment.items():
                        if (i, service) in job_mapping:
                            job = job_mapping[(i, service)]
                            provider_assignments[job.id] = (provider, delay.get(provider, 0))
                    return provider_assignments

                return assignment

            except Exception as ilp_error:
                print(f"Error in ILP solver: {str(ilp_error)}")
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
                        process_assignments(assignment, cost_matrix, request_data_map, prediction_source_map)
                        
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
