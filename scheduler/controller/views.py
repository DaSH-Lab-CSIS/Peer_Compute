from django.shortcuts import render
from profiles.models import User
from providers.models import Job
from providers.views import publish_to_topic
from datetime import datetime, timedelta
from pytz import timezone
from scheduler.settings import TIME_ZONE
from random import randint 
from scheduler.settings import USE_FABRIC
import fabric.views as fabric
import json
# import zmq

# # Create your views here.
# zmq_context = zmq.Context()

def request_handler(data,service,start_time,run_async = False):
    
    provider = None
    while(provider == None):
        provider = find_provider()
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
    if(data['chained'] == True): 
        for i in range(data['numberOfInvocations']):
            response = publish_to_topic(data['runMultipleInvocations'], data['numberOfInvocations'], data['chained'], input_val, provider,task_link,task_developer, job.id)
        # total_time = response['pull_time'] + response['run_time']
            response_decoded = json.loads(response.decode("utf-8"))
            input_val = int(response_decoded['Result'])
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
    return response_decoded, provider.id, providing_time, str(job.id)
    #handle response
    
def calculate_cost(total_time):
    return total_time*0.01

def find_provider():

    ready_providers = User.objects.filter(
        active = True , ready = True , 
        last_ready_signal__gte = datetime.now(tz=timezone(TIME_ZONE)) - timedelta(minutes=10000)
    )

    print("Ready Providers: \n", ready_providers)
    
    if len(ready_providers) == 0: 
        return

    return ready_providers[randint(0,len(ready_providers)-1)]

#have to add job_status get method 

