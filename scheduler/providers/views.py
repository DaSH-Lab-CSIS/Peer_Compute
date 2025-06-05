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
global procedural_shutdown_penalty
procedural_shutdown_penalty = 0
global non_procedural_shutdown_penalty
non_procedural_shutdown_penalty = 0
global non_procedural_shutdown_multiplier
non_procedural_shutdown_multiplier = 0.67
global prediction_deviation_points
global prediction_deviation_points_multiplier
import scheduler.settings as settings
# Create your views here.
data_dict = None
BROKER_ID = "broker.hivemq.com"
# BROKER_ID = "10.8.1.18"
reference_provider_id = '34933555-5cca-41fb-aded-4ab7900c48d5'
file_path = "/home/user/Documents/Serverless_Scheduler/SchedInfo.csv"

mclient = None
global service_id_array 
global service_queue
service_id_array = {}
service_queue = queue.Queue()
global requested_services

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
def on_connect(mqtt_client, userdata, flags, rc, callback_api_version):
    mqtt_client.subscribe(topic="EVERYONE")
    print("Connected to mqtt from views.py/providers")

def on_message(mqtt_client, userdata, msg):
    print('from views.py/providers ')
    print(f'Received message on topic: {msg.topic} with payload: {msg.payload}')
    try:
        data = json.loads(msg.payload.decode("utf-8"))
        if(data['stage'] == 'dockernotrun'): print("pulled but docker not run")
        if(data['stage'] == 'dockerrun'):
            print(f"data[stage]==dockerrun works")
            print(data)
            finish_job(data)
            # mqtt_client.loop_stop()
            # mqtt_client.disconnect()
            # receive_job_data(data_dic t)
    except:
        print(msg.topic,msg.payload.decode("utf-8"))
        if(msg.payload.decode("utf-8").startswith("Benchmark:")):
            # this is in topic user_id not EVERYONE
            print("In except, will print benchmark...")
            benchmark = json.loads(msg.payload.decode("utf-8")[10:])
            user_id = list(benchmark.keys())[0]
            get_benchmarks_for(user_id=user_id, benchmark=benchmark) #this will also update models.
        elif(msg.payload.decode("utf-8").startswith("Stats for Reference Provider: ")):
            print("Stats added to TrainingData/Reference_Provider_Data.txt")
        elif(msg.payload.decode("utf-8").startswith("offline_non-procedurally")):    
            penalise(msg.topic, 1)
            print(msg.topic + "was disconnected non-procedurally")
        elif(msg.payload.decode("utf-8").startswith("offline_procedurally")):    
            penalise(msg.topic, 0)
            print(msg.topic + "was disconnected procedurally")  
        if(msg.topic=="EVERYONE"):
            if(msg.payload.decode("utf-8").startswith("start_connect")):
                print("connecting to ", msg.payload.decode("utf-8")[13:])
                mqtt_client.subscribe(topic=msg.payload.decode("utf-8")[13:])
            if(msg.payload.decode("utf-8").startswith("get_efficiency_score")):
                
                user_id=msg.payload.decode("utf-8")[20:]
                provider = User.objects.get(user_id=user_id)
                # Fix: Handle None values with default of 1.0
                cpu_score = 1.0 if provider.cpu_efficiency_score is None else float(provider.cpu_efficiency_score)
                memory_score = 1.0 if provider.memory_efficiency_score is None else float(provider.memory_efficiency_score)
                scoreset = {'cpu': cpu_score, 'memory': memory_score}
                mqtt_client.publish(topic=user_id, payload="EfficiencyScoreSet:"+json.dumps(scoreset),qos=2)


def on_subscribe(mqtt_client, userdata, mid, qos, properties=None):
    print("on_subscribe userdata is "+ str(mqtt_client))

def get_mclient():
    global mclient
    if(mclient == None):
        mclient = mqtt.Client(callback_api_version= mqtt.CallbackAPIVersion.VERSION2)
        mclient.on_connect = on_connect
        mclient.on_message = on_message
        mclient.on_subscribe= on_subscribe
        mclient.connect(host=BROKER_ID,port=1883)
        mclient.subscribe("ROTATION")  # Subscribe to ROTATION topic
        mclient.loop_start()
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
    mclient.subscribe(topic=router_name)
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

@csrf_exempt
def set_reference_stats(request):
    # send msg to reference provider with service id. on_msg of provider will call a function to execute this service.
    # It will also add cpu_usage and memory_usage to a txt file.
    print("in set rstats (views/provider)")
    client=get_mclient()
    #subscribe to EVERYONE in on_connect
    client.subscribe(topic=reference_provider_id)
    service_id = json.loads(request.body.decode("utf-8"))['service_id']
    print(type(service_id))
    print(service_id)
    # convert this service_id to task link before publishing. # Rn, we are actually directly passing in task link only.
    client.publish(topic=reference_provider_id, payload="ref_run_service_id/"+service_id)
    return JsonResponse({'State':'Running service on the reference provider, stats will be printed on django server and added to files also'})
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
    
    while attempt < max_attempts:
        try:
            # Find providers for all services at once
            assignment = find_providers(services)
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
                    
                    # Publish to MQTT - handle potential failures
                    try:
                        mqtt_params = {
                            'runMultipleInvocations': req_data.get('runMultipleInvocations', False),
                            'numberOfInvocations': req_data.get('numberOfInvocations', 1),
                            'chained': req_data.get('chained', False),
                            'input': input_val
                        }
                        
                        publish_to_topic_mqtt(
                            mqtt_params['runMultipleInvocations'],
                            mqtt_params['numberOfInvocations'],
                            mqtt_params['chained'],
                            input_val, 
                            provider, 
                            task_link, 
                            task_developer, 
                            job.id
                        )
                        
                        job.refresh_from_db()
                        job.save()
                        print(f"Job {job.id} successfully sent to provider {provider.user_id}")
                    except Exception as mqtt_error:
                        print(f"Error publishing to MQTT: {str(mqtt_error)}")
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
    print("Inside finish job")
    # Import here to avoid circular imports
    from providers.experiment_framework import experiment_runner
    
    #here unpack the data load job from job id and update and save it.
    id = data['job_id']
    job = Job.objects.get(pk=id)
    response_decoded = json.loads(data.decode("utf-8"))
    # response_decoded = json.loads(response)
    print("response from provider: ", response_decoded)
    job.refresh_from_db()
    job.pull_time = response_decoded['pull_time']
    job.run_time = response_decoded['run_time']
    job.total_time = response_decoded['total_time']
    job.cost = (response_decoded['total_time'])
    job.response = response_decoded['Result']
    job.finished = True
    job.save()
    
    # Record experiment metrics if experiment is active
    if experiment_runner.experiment_active:
        current_algorithm = settings.SCHEDULING_ALGORITHM
        experiment_runner.metrics.record_job_completion(current_algorithm, job)
    
    # Update cache state after job completion
    try:
        # Assume the image is stored in memory after execution
        # In a real implementation, this would come from the provider's report
        provider = job.provider
        service_id = job.service.id
        cache_location = 'memory'  # Default assumption - provider would report actual location
        
        # Update the cache state in the provider's model
        provider.update_cache_state(service_id, cache_location)
        print(f"Updated cache state for provider {provider.user_id} and service {service_id}")
    except Exception as e:
        print(f"Error updating cache state: {str(e)}")
    
    providing_time = int(((job.ack_time - job.start_time)/timedelta(microseconds=1))/1000) # Providing time in milliseconds
    if USE_FABRIC:
        r = fabric.invoke_received_result(str(job.id))
        if 'jwt expired' in r.text or 'jwt malformed' in r.text or 'User was not found' in r.text:
            token = fabric.register_user()
            r = fabric.invoke_received_result(str(job.id), token=token)
    return

def queue_jobs(service):
    requested_services.append(service)


def get_ready_providers():
    # Remove the transaction.atomic() as it will be handled by find_providers
    return User.objects.select_for_update(nowait=True).filter(
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
def get_predicted_runtimes(provider, services):
    print("Entering get_predicted_runtimes")
    predicted_runtimes = {}
    DEFAULT_RUNTIME = 1000  # milliseconds, adjust this based on your typical service runtime
    
    for service in services:
        try:
            # Get service ID safely, handling potential tuples or objects without ID
            service_id = None
            if hasattr(service, 'id'):
                service_id = service.id
            elif isinstance(service, tuple) and len(service) == 2 and hasattr(service[1], 'id'):
                service_id = service[1].id
            
            if service_id is None:
                print(f"Warning: Could not determine service ID from: {service}")
                continue
                
            latest_run_time = Job.get_latest_run_time(provider.id, service_id)
            if latest_run_time is None:
                # Use a default value instead of infinity
                predicted_runtimes[service_id] = DEFAULT_RUNTIME
                print(f"No previous runtime found for provider {provider.id} and service {service_id}. Using default: {DEFAULT_RUNTIME}")
            else:
                predicted_runtimes[service_id] = latest_run_time
            
            # Check cache state to adjust predicted runtime
            if provider.is_service_cached(service_id):
                cache_location = provider.get_cache_location(service_id)
                print(f"Service {service_id} is cached on provider {provider.id} in {cache_location}")
                
                # If cached in memory, we can skip the pull time completely
                if cache_location == 'memory':
                    # In memory cache means fastest access, no pull time needed
                    print(f"Service {service_id} is in memory cache, skipping pull time")
                    continue
                    
                # If cached on disk, add a reduced pull time (faster than full pull)
                elif cache_location == 'disk':
                    # Disk cache is faster than pulling from remote, but slower than memory
                    # Add a reduced pull time (e.g., 20% of normal pull time)
                    try:
                        pull_time = Job.get_latest_pull_time(provider.id, service_id)
                        if pull_time:
                            disk_pull_time = int(pull_time * 0.2)  # 20% of normal pull time
                            predicted_runtimes[service_id] += disk_pull_time
                            print(f"Service {service_id} is in disk cache, adding reduced pull time: {disk_pull_time}")
                    except Exception as e:
                        print(f"Error calculating disk pull time: {str(e)}")
            else:
                # Not cached, add full pull time
                try:
                    pull_time = Job.get_latest_pull_time(provider.id, service_id)
                    if pull_time:
                        predicted_runtimes[service_id] += pull_time
                        print(f"Service {service_id} is not cached, adding full pull time: {pull_time}")
                except Exception as e:
                    print(f"Error adding pull time: {str(e)}")
        except Job.DoesNotExist:
            print(f"Warning: No job found for provider {provider.id} and service {service_id if 'service_id' in locals() else 'unknown'}")
            if 'service_id' in locals() and service_id is not None:
                predicted_runtimes[service_id] = DEFAULT_RUNTIME
        except Exception as e:
            print(f"Error in get_predicted_runtimes: {str(e)}")
            # Continue processing other services
    
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
    provider_width = max(len(str(provider.user_id)) for provider in cost_matrix.keys())
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
    header = f"{'Provider':>{provider_width}} |"
    header += "".join(f" {'Service '+str(getattr(service, 'id', i)):^{width}}" 
                     for i, (service, width) in enumerate(zip(extracted_services, service_widths)))
    print("\n" + "="*(len(header)))
    print(header)
    print("="*(len(header)))
    
    # Print each row
    for provider, costs in cost_matrix.items():
        # Convert UUID to string for formatting
        row = f"{str(provider.user_id):>{provider_width}} |"
        row += "".join(f" {costs[service]:^{width}.2f}" for service, width in zip(services, service_widths))
        print(row)
    
    print("="*(len(header)) + "\n")
    print("Exiting print_cost_matrix")

def build_cost_matrix(providers, services):
    print("Entering build_cost_matrix")
    cost_matrix = {}

    # Create list of enumerated services
    indexed_services = list(enumerate(services))
    
    for provider in providers:
        # Filter services compatible with the provider
        # NOTE This is only for testing. Actual implementation would require a service to have requirements 
        compatible_services = services

        # Fetch predicted runtimes in a batch
        predicted_runtimes = get_predicted_runtimes(provider, compatible_services)

        # Create the cost subdict for this provider
        subdict = {}
        for i, svc in indexed_services:
            # Ensure we're accessing the service ID correctly
            service_id = getattr(svc, 'id', None)
            if service_id is not None:
                runtime = predicted_runtimes.get(service_id, float('inf'))
                subdict[(i, svc)] = runtime
            else:
                print(f"Warning: Could not get ID from service object: {svc}")
                subdict[(i, svc)] = float('inf')

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

def process_assignments(assignment, cost_matrix):
    print("\nEntering process_assignments")
    jobs_to_send = []  # Store jobs to send after transaction
    
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
            
            # Lock the provider record
            provider_locked = User.objects.select_for_update().get(pk=provider.pk)
            print(f"Provider locked: {provider_locked.user_id}")
            
            # Create a Job instance with CREATED status
            job = Job.objects.create(
                provider=provider_locked,
                service=service,
                developer=service.developer,
                finished=False
            )
            print(f"Created job with ID: {job.id}")
            
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
            print(f"Current provider delay state: {provider_locked.delay}")
            
            try:
                provider_locked.add_delay(predicted_runtime)
                print("Successfully added delay")
            except Exception as e:
                print(f"Error adding delay: {str(e)}")
                print(f"Type of predicted_runtime: {type(predicted_runtime)}")
                print(f"Value of predicted_runtime: {predicted_runtime}")
                # Don't raise, just continue with default delay
                provider_locked.delay = provider_locked.delay or 0

            print(f"Updated provider delay state: {provider_locked.delay}")
            
            # Update function invocations
            service_key = str(service.id)
            current_invocations = provider_locked.function_invocations.get(service_key, 0)
            provider_locked.function_invocations[service_key] = current_invocations + 1
            
            try:
                provider_locked.save()
                print("Successfully saved provider")
            except Exception as e:
                print(f"Error saving provider: {str(e)}")
                print(f"Provider state at save: {provider_locked.__dict__}")
                raise

            # Store job information for sending after transaction commits
            jobs_to_send.append({
                'job': job,
                'provider': provider_locked,
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

def find_providers(services, jobs=None):
    print("Debug: Entering find_providers")
    
    # Import here to avoid circular imports
    from providers.scheduling_algorithms import get_scheduler
    from providers.experiment_framework import experiment_runner
    
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

        # 4. Get assignment using the configured scheduling algorithm
        try:
            # Get the scheduler based on current configuration
            scheduler = get_scheduler()
            print(f"Using scheduling algorithm: {scheduler.name}")
            
            # Get assignment from the selected algorithm
            assignment, total_cost = scheduler.assign_providers(
                suitable_providers, services, cost_matrix, delay
            )
            
            # Record metrics if experiment is active
            if experiment_runner.experiment_active and assignment:
                experiment_runner.metrics.record_assignment(
                    scheduler.name, assignment, cost_matrix, delay, 
                    scheduler.metrics.get('assignment_time', 0), services
                )
            
            if assignment is None:
                print("Warning: No optimal solution found")
                return None
                
            # 5. Process assignments - Invoke providers and update job status
            process_assignments(assignment, cost_matrix)
            
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
            
        except Exception as e:
            print(f"Error in find_providers: {str(e)}")
            # Attempt fallback solution for single service
            if len(services) == 1:
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
                    process_assignments(assignment, cost_matrix)
                    
                    # Handle job mapping if needed
                    if jobs is not None and len(jobs) == 1:
                        job = jobs[0]
                        return {job.id: (provider, delay.get(provider, 0))}
                    
                    return assignment
            
            # If fallback also fails or multiple services
            print("Could not find providers after trying fallback solutions")
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

get_mclient()

# Experiment and Algorithm Control Endpoints

@csrf_exempt
def start_algorithm_experiment(request):
    """Start a scheduling algorithm comparison experiment"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            algorithms = data.get('algorithms', ['ILP', 'MRU', 'BELADY', 'ROUND_ROBIN'])
            iterations = data.get('iterations', 10)
            services_per_iteration = data.get('services_per_iteration', 5)
            
            from providers.experiment_framework import start_experiment
            result = start_experiment(algorithms, iterations, services_per_iteration)
            
            return JsonResponse({
                'status': 'success',
                'message': result,
                'algorithms': algorithms,
                'iterations': iterations,
                'services_per_iteration': services_per_iteration
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)

@csrf_exempt
def get_experiment_status(request):
    """Get current experiment status"""
    from scheduler.settings import SCHEDULING_ALGORITHM
    if request.method == 'GET':
        try:
            from providers.experiment_framework import get_experiment_status
            status = get_experiment_status()
            return JsonResponse({
                'status': 'success',
                'experiment': status,
                'current_algorithm': SCHEDULING_ALGORITHM,
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'GET method required'}, status=405)

@csrf_exempt
def switch_scheduling_algorithm(request):
    """Switch the current scheduling algorithm"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            algorithm = data.get('algorithm')
            
            valid_algorithms = ['ILP', 'MRU', 'BELADY', 'ROUND_ROBIN']
            if algorithm not in valid_algorithms:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Invalid algorithm. Valid options: {valid_algorithms}'
                }, status=400)
            
            # Update Django settings (note: this only affects current instance)
            settings.SCHEDULING_ALGORITHM = algorithm
            
            return JsonResponse({
                'status': 'success',
                'message': f'Switched to {algorithm} algorithm',
                'algorithm': algorithm
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)

@csrf_exempt
def generate_experiment_report(request):
    """Generate and return experiment report"""
    if request.method == 'GET':
        try:
            from providers.experiment_framework import experiment_runner
            experiment_name = request.GET.get('name', f'Manual_Report_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
            
            report = experiment_runner.metrics.generate_report(experiment_name)
            report_file = experiment_runner.metrics.save_report(report)
            
            return JsonResponse({
                'status': 'success',
                'report': report,
                'report_file': report_file
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'GET method required'}, status=405)

@csrf_exempt 
def get_algorithm_metrics(request):
    """Get current algorithm performance metrics"""
    if request.method == 'GET':
        try:
            from providers.scheduling_algorithms import get_scheduler
            scheduler = get_scheduler()
            
            return JsonResponse({
                'status': 'success',
                'algorithm': scheduler.name,
                'metrics': scheduler.get_metrics()
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'GET method required'}, status=405)

@csrf_exempt
def reset_algorithm_metrics(request):
    """Reset algorithm performance metrics"""
    if request.method == 'POST':
        try:
            from providers.scheduling_algorithms import get_scheduler
            scheduler = get_scheduler()
            scheduler.reset_metrics()
            
            return JsonResponse({
                'status': 'success',
                'message': f'Metrics reset for {scheduler.name} algorithm'
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)

@csrf_exempt
def toggle_experiment_mode(request):
    """Toggle experiment mode on/off"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            enable = data.get('enable', not settings.EXPERIMENT_MODE)
            
            settings.EXPERIMENT_MODE = enable
            
            return JsonResponse({
                'status': 'success',
                'message': f'Experiment mode {"enabled" if enable else "disabled"}',
                'experiment_mode': enable
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    else:
        return JsonResponse({'status': 'error', 'message': 'POST method required'}, status=405)
