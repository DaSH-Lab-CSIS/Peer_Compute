from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from profiles.models import User
import fabric.views as fabric
import json
import time
from developers.models import Services
from threading import Thread 
from scheduler.settings import USE_FABRIC
# Create your views here.

@csrf_exempt
def register_user(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        user = User(
            is_provider=data.get('is_provider', data['is_provider']),
            is_developer=data.get('is_developer', data['is_developer']),
            active=data.get('active', data['active']),
            ready=data.get('ready', data['ready']),
            location=data.get('location', data['location']),
            ram=data.get('ram', data['ram']),
            cpu=data.get('cpu', data['cpu'])
        )
        user.save()
        user_id = user.user_id
        if USE_FABRIC :
            r = fabric.invoke_new_monetary_account(str(user.user_id), '700')
            if 'jwt expired' in r.text or 'jwt malformed' in r.text or 'User was not found' in r.text:
                token = fabric.register_user()
                r = fabric.invoke_new_monetary_account(str(user.user_id), '700', token = token)
        
        if user.is_provider:
            user.active = True
            # username,password =  make_rmq_user(user)
            # create_thread_and_subscribe(request,user.user_id)

            return JsonResponse({'message':'User added successfully', 'user_id' : user_id})
        if user.is_developer:
            user.active = True
            add_default_service(user)
            ##add default service
            return JsonResponse({'message':'User added successfully', 'user_id' : user_id})
        
    else:
        return JsonResponse({'error': 'Invalid request method'})
    
def add_default_service(user):
    default_service = Services(
        developer = user,
        provider = get_object_or_404(User, pk=3),
        docker_container = "hello-world", 
        active=True
    )
    default_service.save()

def list_users(request):
    if request.method == 'GET':
        users = User.objects.all()
        user_ids = list(users.values_list('id', flat=True))
        return JsonResponse({'user_ids': user_ids})

# @csrf_exempt
def delete_user(request, user_id):
    if request.method == 'DELETE':
        try:
            user = User.objects.get(pk=user_id)
            user.delete()
            return JsonResponse({'message': 'User deleted successfully'})
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)

# def create_thread_and_subscribe(request,user_id):
#     client_ip = request.META.get('REMOTE_ADDR')
#     client_port = request.META.get('REMOTE_PORT')
#     provider_thread = Thread(target= thread_target, args= (client_ip,client_port,user_id))
#     provider_thread.start()
#     provider_thread.join()
    
# def thread_target(client_ip,client_port,user_id):
#     while True:
#         try:
#             ctx = zmq.Context()
#             socket = ctx.socket(zmq.SUB)
#             socket.connect(f"tcp://{client_ip}:{client_port}")
#             socket.setsockopt_string(zmq.SUBSCRIBE, str(user_id))
#             print("Connected to socket.")
#             break  # Exit the loop if connection is successful

#         except zmq.error.ZMQError as e:
#             print(f"Connection attempt failed: {e}")
#             time.sleep(5)  # Wait for 5 seconds before retrying
