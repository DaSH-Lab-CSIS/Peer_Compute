from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from developers.forms import ServiceForm
from django.contrib import messages
from django.http import JsonResponse
from django.db import IntegrityError
from profiles.models import User
from developers.models import Services
from providers.models import Job
from django.core.exceptions import ObjectDoesNotExist
from controller.views import request_handler, find_provider
from datetime import datetime
from pytz import timezone
from scheduler.settings import TIME_ZONE
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt
import json
import threading

def index(request):
    return render(request, 'developers_app/index.html')


# @login_required()
@csrf_exempt
def new_service(request):
    """
    Creates a new service in the network.
    """
    if request.method == 'POST':
        data = json.loads(request.body) 
        service = Services()
        try:
            service.save(
                developer = data.get('developer'), 
                provider = get_default_provider(), 
                name = data.get('name'),
                docker_container = data.get('docker_url'),
                active = data.get('is_active',True),
            )
            messages.success(request, "New service created")
        except IntegrityError:
                messages.error(request, "You already have a service with this name")
    else:
       return JsonResponse({'error': 'Invalid request method'})
    return JsonResponse({"message" : "Service added Successfully."})

# @login_required()
def get_default_provider():
    provider = User.objects.get(user_id = 3)
    return provider

def user_services(request):
    """
    Shows all services owned by a user.
    """
    all_services = Services.objects.filter(developer=request.user.developer)

    return render(request, 'developers_app/user_services.html',
                  {'all_services': all_services,
                   'developer_id': request.user.developer.id})


# @login_required()
def stop_service(request, service_id):
    all_services = Services.objects.filter(developer=request.user.developer)
    service = Services.objects.get(id=service_id)
    service.active = False
    service.save()
    return render(request, 'developers_app/services_table.html',
                  {'all_services': all_services,
                   'developer_id': request.user.developer.id})

# @login_required()
def start_service(request, service_id):
    service = Services.objects.get(id=service_id)
    all_services = Services.objects.filter(developer=request.user.developer)
    service.active = True
    service.save()
    return render(request, 'developers_app/services_table.html',
                  {'all_services': all_services,
                   'developer_id': request.user.developer.id})

# @login_required()
def delete_service(request, service_id):
    all_services = Services.objects.filter(developer=request.user.developer)
    service = Services.objects.get(id=service_id)
    service.delete()
    return render(request, 'developers_app/services_table.html',
                  {'all_services': all_services,
                   'developer_id': request.user.developer.id})

def run_service(request, service_id):
    response = ''
    try:
        service = Services.objects.get(id=service_id)
        if service.active:
            temp_time = datetime.now(tz=timezone(TIME_ZONE))
            response, provider, providing_time, job_id = request_handler(request, service, temp_time)
            if response is None:
                messages.error(request, "There are no available providers in the network")
                return redirect('index')
            else:
                messages.success(request, "Successfully sent a request to '{}' service of '{}'".format(service.name,
                                                                                                   service.developer))
        else:
            messages.error(request, "This service is disabled")

    except ObjectDoesNotExist:
        messages.error(request, "Incorrect service id")

    return JsonResponse(
                  {'result': response['Result'],
                   'providing_time': providing_time,
                   'pull_time': response['pull_time'],
                   'run_time': response['run_time'],
                   'total_time': response['total_time'],
                   'provider': provider, 
                   'job_id': job_id})

def run_service_async(request, service_id):
    response = ''
    try:
        service = Services.objects.get(id=service_id)
        if service.active:
            temp_time = datetime.now(tz=timezone(TIME_ZONE))
            # request_handler(request, service, temp_time, run_async=True)
            x = threading.Thread(target=request_handler, args=(request, service, temp_time, True))
            x.start()
            if find_provider() is None:
                messages.error(request, "There are no available providers in the network")
                return redirect('index')
            else:
                messages.success(request, "Successfully sent an async request to '{}' service of '{}'".format(service.name,
                                                                                                   service.developer))
        else:
            messages.error(request, "This service is disabled")

    except ObjectDoesNotExist:
        messages.error(request, "Incorrect service id")

    return redirect('index')


# @login_required()
def user_jobs(request):
    """
    Shows all jobs that belong to a user.
    """
    services = Services.objects.filter(developer=request.user.developer)
    all_jobs = Job.objects.filter(service__in=services).order_by('pk').reverse()
    return render(request, 'developers_app/user_jobs.html',
                  {'all_jobs': all_jobs,
                   'developer_id': request.user.developer.id})

# @login_required()
def job_info(request, job_id):
    """
    Shows all jobs that belong to a user.
    """
    job = Job.objects.get(pk=job_id)
    providing_time = int(((job.ack_time - job.start_time)/timedelta(microseconds=1))/1000)
    if job.response == '':
        result = "Result is not ready yet."
    else:
        result = json.loads(job.response)['Result']
    return render(request, 'final_response.html',
                  {'result': result,
                   'providing_time': providing_time,
                   'pull_time': job.pull_time,
                   'run_time': job.run_time,
                   'total_time': job.total_time,
                   'provider': job.provider.user.username, 
                   'job_id': job.pk})
