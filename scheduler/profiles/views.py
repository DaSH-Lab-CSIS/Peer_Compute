from django.shortcuts import render, get_object_or_404
from django.core import serializers
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from profiles.models import User
import json
from providers.views import make_rmq_user
from developers.models import Services


# Create your views here.

@csrf_exempt
def register_user(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        user = User(
            is_provider=data.get('is_provider', False),
            is_developer=data.get('is_developer', False),
            active=data.get('active', False),
            ready=data.get('ready', False),
            location=data.get('location', 'DASH_LAB'),
            ram=data.get('ram', 0),
            cpu=data.get('cpu', 0)
        )
        user.save()
        if user.is_provider:
            user.active = True
            username,password =  make_rmq_user(user)
            return JsonResponse({'message':'User added successfully','rmq_username': username, 'rmq_password': password})
        if user.is_developer:
            user.active = True
            add_default_service(user)
            ##add default service
            return JsonResponse({'message':'User added successfully','rmq_username': username, 'rmq_password': password})
        else:
            return JsonResponse({'message':'User added successfully'})
    else:
        return JsonResponse({'error': 'Invalid request method'})
    
def add_default_service(user):
    default_service = Services(
        developer = user,
        provider = get_object_or_404(User, pk=3),
        docker_container = "https://cloud.docker.com/u/ghaemisr/repository/docker/ghaemisr/node-info", 
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

