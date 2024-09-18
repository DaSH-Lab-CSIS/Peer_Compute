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
from profiles.models import User
from providers.models import Job
from random import randint 
from scheduler.settings import USE_FABRIC
import fabric.views as fabric
import csv
import random
from providers.mincost import minimize_total_cost
# Create your views here.
data_dict = None
BROKER_ID = "broker.hivemq.com"
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

# mqtt client callbacks:
def on_connect(mqtt_client, userdata, flags, rc, callback_api_version):
    mqtt_client.subscribe(topic="EVERYONE")
    print("Connected from views.py/providers")

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
        if(msg.topic=="EVERYONE"):
            if(msg.payload.decode("utf-8").startswith("start_connect")):
                print("connecting to ", msg.payload.decode("utf-8")[13:])
                mqtt_client.subscribe(topic=msg.payload.decode("utf-8")[13:])
            if(msg.payload.decode("utf-8").startswith("get_efficiency_score")):
                
                user_id=msg.payload.decode("utf-8")[20:]
                provider = User.objects.get(user_id=user_id)
                scoreset = {'cpu':float(provider.cpu_efficiency_score), 'memory':float(provider.memory_efficiency_score)}
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
    return



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
#(request, 'Stop', request.user.username)
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
    #TODO
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


def request_handler(data,service,start_time,run_async = False):
    print("In request handler.")
    provider = None
    while(provider == None):
        provider = find_provider(service)
    print(provider)
    
    job = Job.objects.create(provider = provider, start_time = start_time)
    job.save()

    if USE_FABRIC:
        r = fabric.invoke_new_job(str(job.id), str(service.id), str(service.developer_id),
                                        str(provider.id), provider_org="Org1")
        if 'jwt expired' in r.text or 'jwt malformed' in r.text or 'User was not found' in r.text:
            token = fabric.register_user()
            r = fabric.invoke_new_job(str(job.id), str(service.id), str(service.developer_id),
                                        str(provider.id), provider_org="Org1",token=token)

    task_link = service.docker_container 
    task_developer = service.developer
    input_val = data['input']
    response_decoded = None
    # if(data['chained'] == True): 
    #     for i in range(data['numberOfInvocations']):
    #         response = publish_to_topic(data['runMultipleInvocations'], data['numberOfInvocations'], data['chained'], input_val, provider,task_link,task_developer, job.id)
    #     # total_time = response['pull_time'] + response['run_time']
    #         response_decoded = json.loads(response.decode("utf-8"))
    #         input_val = int(response_decoded['Result'])
    # for i in range(data['numberOfInvocations']):
    #response = publish_to_topic(data['runMultipleInvocations'], data['numberOfInvocations'], data['chained'], input_val, provider,task_link,task_developer, job.id)
    #print("abt to pub to mqtt")
     # add the below code in on_message.
    publish_to_topic_mqtt(data['runMultipleInvocations'], data['numberOfInvocations'], data['chained'], input_val, provider,task_link,task_developer, job.id)
    # response_decoded = json.loads(response.decode("utf-8"))
    # # response_decoded = json.loads(response)
    # print("response from provider: ", response_decoded)
    # job.refresh_from_db()
    # job.pull_time = response_decoded['pull_time']
    # job.run_time = response_decoded['run_time']
    # job.total_time = response_decoded['total_time']
    # job.cost = (response_decoded['total_time'])
    # job.response = response_decoded['Result']
    # job.finished = True
    # job.save()
    # providing_time = int(((job.ack_time - job.start_time)/timedelta(microseconds=1))/1000) # Providing time in milliseconds
    # if USE_FABRIC:
    #     r = fabric.invoke_received_result(str(job.id))
    #     if 'jwt expired' in r.text or 'jwt malformed' in r.text or 'User was not found' in r.text:
    #         token = fabric.register_user()
    #         r = fabric.invoke_received_result(str(job.id), token=token)
    # return response_decoded, provider.id, providing_time, str(job.id)


def finish_job(data):
    print("Inside finish job")
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
    providing_time = int(((job.ack_time - job.start_time)/timedelta(microseconds=1))/1000) # Providing time in milliseconds
    if USE_FABRIC:
        r = fabric.invoke_received_result(str(job.id))
        if 'jwt expired' in r.text or 'jwt malformed' in r.text or 'User was not found' in r.text:
            token = fabric.register_user()
            r = fabric.invoke_received_result(str(job.id), token=token)
    return

def queue_jobs(service):
    requested_services.append(service)
    

def find_provider(service):

    ready_providers = User.objects.filter(
        active = True , ready = True , 
        # last_ready_signal__gte = datetime.now(tz=timezone(TIME_ZONE)) - timedelta(minutes=10000)
    )

    print("Ready Providers: \n", ready_providers)
    
    if len(ready_providers) == 0: 
        return

    max_provider = None
    max_invocations = -1
    provider_choices= []

    for provider_to_search in ready_providers:
        with open(file_path, mode='r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            for row in csv_reader:
                provider = row['Provider']
                function = int(row['Function'])
                invocations = int(row['Invocations'])

                # Check if the row matches the criteria
                if provider == str(provider_to_search.user_id) and function == (service.id - 7):
                    provider_choices.append({'invocations': invocations, 'provider': provider_to_search.id})
                    # max_provider = provider
                    # max_invocations = invocations

    # sort
    if (len(provider_choices)< 1) :
        max_provider = random.choice(ready_providers)

    elif (len(provider_choices)==1):
        max_provider = get_object_or_404(User, pk=provider_choices[0]['provider'])
    else:
        provider_choices.sort(key=lambda x: x['invocations'], reverse=True)
        max_provider = get_object_or_404(User, pk = random.choice(provider_choices[0:2])['provider'])

    print("Scheduler is chosing this provider -> ", max_provider)
    updated_data = []
    flag = False
    if(max_provider != None):
        # Read the CSV file and update the values
        with open(file_path, mode='r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            for row in csv_reader:
                provider = row['Provider']
                function = int(row['Function'])
                invocations = int(row['Invocations'])

                # Check if the row matches the criteria for update
                if provider == str(max_provider.user_id) and function == (service.id - 7):
                    flag = True
                    row['Invocations'] = str(int(invocations)+1)

                updated_data.append(row)

    if(flag == False):
        updated_data.append({'Provider': max_provider.user_id, 'Function': (service.id - 7), 'Invocations': 1})

    print(updated_data)

    with open(file_path, mode='w', newline='') as csv_file:
        fieldnames = ['Provider', 'Function', 'Invocations']
        csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

        # Write the header
        csv_writer.writeheader()

        # Write the updated rows
        csv_writer.writerows(updated_data)

    return max_provider

# MAIN CODE:

get_mclient()