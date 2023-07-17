from django.shortcuts import render
from profiles.models import User
from providers.models import Job
from datetime import datetime, timedelta
from pytz import timezone
from scheduler.settings import TIME_ZONE
from random import randint 

# Create your views here.
def request_handler(request,service,start_time,run_async = False):
    provider = find_provider()
    if provider is None : 
        return None,None,None,None
    
    job = Job.objects.create(provider = provider,service = service , start_time = start_time)
    job.save()
    

def find_provider():

    ready_providers = User.objects.filter(
        active = True , ready = True , 
        last_ready_signal__gte = datetime.now(tz=timezone(TIME_ZONE)) - timedelta(minutes=1)
    )
    
    if len(ready_providers) == 0: 
        return

    return ready_providers[randint(0,len(ready_providers)-1)]
