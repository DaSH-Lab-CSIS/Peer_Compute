from django.shortcuts import render
from profiles.models import User
from providers.models import Job
from providers.views import publish_to_topic
from datetime import datetime, timedelta
from pytz import timezone
from scheduler.settings import TIME_ZONE
from random import randint 
import zmq 
import json

# Create your views here.


def request_handler(request,service,start_time,run_async = False):
    provider = find_provider()

    if provider is None : 
        return None,None,None,None
    
    job = Job.objects.create(provider = provider, start_time = start_time)
    job.save()
    task_link = service.docker_container 
    task_developer = service.developer
    response = publish_to_topic(provider,task_link,task_developer, job.id)
    # total_time = response['pull_time'] + response['run_time']
    response = json.loads(response.decode("utf-8"))
    print("response from provider: ", response)
    job.refresh_from_db()
    job.pull_time = response['pull_time']
    job.run_time = response['run_time']
    job.total_time = response['total_time']
    job.cost = calculate_cost(response['total_time'])
    job.response = response['Result']
    job.finished = True
    job.save()
    providing_time = int(((job.ack_time - job.start_time)/timedelta(microseconds=1))/1000) # Providing time in milliseconds
    # if USE_FABRIC:
    #     r = fabric.invoke_received_result(str(job.id))
    #     if 'jwt expired' in r.text or 'jwt malformed' in r.text or 'User was not found' in r.text:
    #         token = fabric.register_user()
    #         r = fabric.invoke_received_result(str(job.id))
    return response, provider.id, providing_time, str(job.id)
    #handle response
    
def calculate_cost(total_time):
    return total_time*0.01

def find_provider():

    ready_providers = User.objects.filter(
        active = True , ready = True , 
        last_ready_signal__gte = datetime.now(tz=timezone(TIME_ZONE)) - timedelta(minutes=10000)
    )
    
    if len(ready_providers) == 0: 
        return

    return ready_providers[randint(0,len(ready_providers)-1)]

#have to add job_status get method 

