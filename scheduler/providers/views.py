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
import zmq
import paho.mqtt.client as mqtt

# Create your views here.
zmq_context = zmq.Context()
data_dict = None
BROKER_ID = "broker.hivemq.com"
# zmq_socket = zmq_context.socket(zmq.DEALER)
# dealer_id = b"dealer1"
# zmq_socket.setsockopt(zmq.IDENTITY, dealer_id)
# zmq_socket.bind("tcp://*:5555")


# mqtt client callbacks:
def on_connect(mqtt_client, userdata, flags, rc, callback_api_version):
    if rc == 0:
        print('Connected successfully')
    else:
        print('Bad connection. Code:', rc)

def on_message(mqtt_client, userdata, msg):
    print('from views.py/providers ')
    print(f'Received message on topic: {msg.topic} with payload: {msg.payload}')
    data = json.loads(msg.payload.decode("utf-8"))
    try:
        if(data['stage'] == 'dockernotrun'): print("pulled but docker not run")
        if(data['stage'] == 'dockerrun'):
            print(f"data[stage]==dockerrun works")
            global data_dict
            data_dict = data
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
    except:
        print("docker success messgae")
def on_subscribe(mqtt_client, userdata, mid, qos, properties=None):
    print("on_subscribe userdata is "+ str(mqtt_client))

############################################################################################
    
def publish_to_topic(runMultipleInvocations, numberOfInvocations, isChained, inputData, provider , task_link , task_developer, job_id):
    router_name = str(provider.user_id)
    zmq_data = {
        'provider_id' : router_name,
        'task_link' : task_link,
        'task_developer' : str(task_developer.user_id),
        'job_id' : job_id,
        'numberOfInvocations': numberOfInvocations,
        'isChained': isChained,
        'inputData': inputData,
        'runMultipleInvocations': runMultipleInvocations
    }
    zmq_socket = zmq_context.socket(zmq.DEALER)
    dealer_id = b"dealer1"
    zmq_socket.setsockopt(zmq.IDENTITY, dealer_id)
    zmq_socket.bind("tcp://*:5555")
    # print("Sending zmq data.")
    zmq_socket.send_multipart([router_name.encode("utf-8"), json.dumps(zmq_data).encode("utf-8")])
    # print("Waiting for zmq response.")
    response = zmq_socket.recv()
    # print("Received response from zmq: ", response)
    zmq_socket.close()
    return response

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
    client = mqtt.Client(callback_api_version= mqtt.CallbackAPIVersion.VERSION2)
    # make a socket bind to tcp and make a dealer
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe= on_subscribe

    client.connect(host=BROKER_ID,port=1883)
    client.subscribe(topic=router_name)
    client.publish(topic=router_name, payload=json.dumps(userdata).encode("utf-8"), qos=2)
    print("in pub to topic mqtt")
    client.loop_forever()
    print("views.py/provider loop_forever exited")
    # dont return this return the data which is sent by on_message {data}
    
    return json.dumps(data_dict)

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
