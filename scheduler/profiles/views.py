from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import User
import json
from providers.views import make_rmq_user

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
            make_rmq_user(user)
        return JsonResponse({'message':'User added successfully'})
    else:
        return JsonResponse({'error': 'Invalid request method'})