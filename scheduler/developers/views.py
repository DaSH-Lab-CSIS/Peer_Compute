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
# from controller.views import request_handler, find_provider
from providers.views import request_handler, find_provider
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
            developer_id = data.get('developer', 11) # default developer id
            developer_instance = User.objects.get(id = developer_id)
            service.developer = developer_instance
            # NEW change, remove after migration is successfuly.
            # service.provider = get_default_provider()
            service.name = data.get('name')
            service.docker_container = data.get('docker_url')
            service.active = data.get('is_active', True)
            service.save()
            messages.success(request, "New service created")
        except IntegrityError:
                # name and developer are unique together in the Service model def.
                messages.error(request, "You already have a service with this name")
    else:
       return JsonResponse({'error': 'Invalid request method'})
    return JsonResponse({"message" : "Service added Successfully."})

# @login_required()
def get_default_provider():
    provider = User.objects.get(id = 16)
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

# @csrf_exempt
# def run_service(request, service_id):
#     print("in run service")
#     student_list = User.objects.all()
#     print(student_list.count())
#     for student in student_list:
#         print(student.user_id)
#     response = ''
#     try:
#         service = Services.objects.get(id=(service_id+7))
#         if service.active:
#             temp_time = datetime.now(tz=timezone(TIME_ZONE))
#             data = json.loads(request.body)
#             if (data['chained'] == True) :
#                 for i in range(data['numberOfInvocations']):
#                     request_handler(data, service, temp_time)

#             else:
#                 for i in range(data['numberOfInvocations']):
#                 #     print("Invocation ", str(i), ": \n")
#                     request_handler(data, service, temp_time)

#         else:
#             messages.error(request, "This service is disabled")

#     except ObjectDoesNotExist:
#         messages.error(request, "Incorrect service id")
#         print("incorrect service id")
#     # print("Response", response)
#     return JsonResponse({'response': 'There is no return or response for now.'})

@csrf_exempt
def run_service(request, service_id):
    response = ''
    try:
        service = Services.objects.get(id=(service_id)) # legacy +7 bug was here.
        if service.active:
            temp_time = datetime.now(tz=timezone(TIME_ZONE))
            data = json.loads(request.body)
            if (data['chained'] == True) :
                for i in range(data['numberOfInvocations']):
                    response, provider, providing_time, job_id = request_handler(data, service, temp_time)
                    data['input'] = int(response['Result'])
            else:
                for i in range(data['numberOfInvocations']):
                    #     print("Invocation ", str(i), ": \n")
                    response, provider, providing_time, job_id = request_handler(
                        data, service, temp_time
                    )
            if response is None:
                messages.error(request, "There are no available providers in the network")
                return redirect('index')
            else:
                messages.success(request, "Successfully sent a request to '{}' service of '{}'".format(service.name,
                                                                                                   service.developer))
        else:
            messages.error(request, "This service is disabled")

    except ObjectDoesNotExist as e:
        print(f"ObjectDoesNotExist: {e}")
        messages.error(request, "Incorrect service id")
    # print("Response", response)
    return JsonResponse(
                  {'result': response['Result'],
                   'providing_time': providing_time,
                   'pull_time': response['pull_time'],
                   'run_time': response['run_time'],
                   'total_time': response['total_time'],
                   'provider': provider, 
                   'job_id': job_id})

@csrf_exempt
def run_service_async(request, service_id):
    response = ''
    try:
        service = Services.objects.get(id=service_id)
        if service.active:
            data = json.loads(request.body)
            temp_time = datetime.now(tz=timezone(TIME_ZONE))
            # request_handler(data, service, temp_time, run_async=True)
            x = threading.Thread(target=request_handler, args=(data, service, temp_time, True))
            x.start()
            
            # Check if there are available providers without waiting for the result
            # Use direct DB query to avoid calling find_provider which might cause errors
            available_providers = User.objects.filter(
                active=True,
                is_provider=True,
                ready=True
            ).exists()
            
            if not available_providers:
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


@csrf_exempt
def run_service_async_api(request, service_id):
    """API-first async trigger endpoint: returns JSON with HTTP 202 on accept."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        service = Services.objects.get(id=service_id)
    except ObjectDoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Incorrect service id', 'service_id': service_id},
            status=404,
        )

    if not service.active:
        return JsonResponse(
            {'status': 'error', 'message': 'This service is disabled', 'service_id': service_id},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON payload'}, status=400)

    available_providers = User.objects.filter(
        active=True,
        is_provider=True,
        ready=True
    ).exists()
    if not available_providers:
        return JsonResponse(
            {'status': 'error', 'message': 'There are no available providers in the network'},
            status=503,
        )

    temp_time = datetime.now(tz=timezone(TIME_ZONE))
    worker = threading.Thread(target=request_handler, args=(data, service, temp_time, True), daemon=True)
    worker.start()

    return JsonResponse(
        {
            'status': 'accepted',
            'message': 'Async request queued',
            'service_id': service_id,
            'service_name': service.name,
        },
        status=202,
    )

@csrf_exempt
def run_service_async_batch(request):
    """
    Processes a batch of requests from the load balancer.
    Sends the entire batch to request_handler to process at once.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)
    
    try:
        # Parse the batch of requests
        batch_data = json.loads(request.body)
        if 'requests' not in batch_data:
            return JsonResponse({'error': 'Invalid batch format'}, status=400)
        
        # Collect all services and request data
        services = []
        requests_data = []
        results = []
        temp_time = datetime.now(tz=timezone(TIME_ZONE))
        
        # First pass - collect valid services and data
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
                
                # Add to our processing lists
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
        
        # Process all collected services in a single thread
        if services:
            x = threading.Thread(
                target=request_handler, 
                args=(requests_data, services, temp_time, True)
            )
            x.start()
        
        return JsonResponse({
            'status': 'success', 
            'batch_size': len(batch_data['requests']),
            'processed': len(services),
            'results': results
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Batch processing failed: {str(e)}'}, status=500)

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
