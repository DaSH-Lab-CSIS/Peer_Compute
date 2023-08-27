from django.shortcuts import render,get_object_or_404, redirect
import pika 
import json
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from providers.forms import ProviderForm
from profiles.models import User
from datetime import datetime, timedelta, tzinfo
import uuid
from providers.models import Job
from scheduler.settings import TIME_ZONE
from pytz import timezone
from django.contrib import messages
from scheduler.settings import RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_MANAGEMENT_PORT, RABBITMQ_USER, RABBITMQ_PASS
from rabbitmq_admin import AdminAPI
# Create your views here.

def make_rmq_user(user):
    username = 'username' + str(user.user_id)
    password = 'username' + str(user.user_id) + '_mqtt'
    api = AdminAPI(url='http://' + RABBITMQ_HOST + ':' + RABBITMQ_MANAGEMENT_PORT, auth=(RABBITMQ_USER, RABBITMQ_PASS))

    #create user and set permissions 
    api.create_user(username, password)
    permission = "^(" + username + ".*|amq.default)$"
    api.create_user_permission(username, '/', permission, permission, permission)

    return username,password

# @login_required
# csrf_exempt is used so that a code can login on behalf of the provider
# @csrf_exempt
def index(request):
    if request.user.provider.active:
        if request.method == 'POST':
            provider_form = ProviderForm(data=request.POST)
            if provider_form.is_valid():
                provider = request.user.provider
                provider.cpu = provider_form.cleaned_data['cpu']
                provider.ram = provider_form.cleaned_data['ram']
                provider.ready = True
                provider.save()
            else:
                print(provider_form.errors)
        else:
            provider_form = ProviderForm()

        # is_contributing shows if a provider is active, ready and has send a ready signal in the past minute
        is_contributing = request.user.provider.is_contributing()
        return render(request, 'providers_app/index.html',
                      {'provider_form': provider_form,
                       'is_contributing': is_contributing})
    else:
        messages.error(request, "You are not an active provider.")
        return redirect('profiles:change_info')


def add_task_to_queue(request,task,username):

    client = RpcClient(username)
    task_dict = json.dumps(task)
    client.call(username,task_dict)
    response = client.response 
    job = get_object_or_404(Job, pk=task['job'])
    job.corr_id = client.corr_id
    job.response = response.decode("utf-8")
    job.save(update_fields=['corr_id', 'response'])
    if response is None:
        return
    return json.loads(response.decode("utf-8"))

# @login_required
def stop_providing(request):
    """
    The provider can stop contributing through the web application. This send a Stop message to provider's queue.
    """
    if request.user.provider.is_contributing():
        provider = request.user.provider
        provider.ready = False
        provider.save()
        add_task_to_queue(request, 'Stop', request.user.username)
        return redirect('providers_app:index')
    else:
        return redirect('providers_app:index')


# @login_required
def ready(request):
    """
    Shows that the provider is still ready.
    """
    provider = request.user.provider
    provider.ready = True
    provider.last_ready_signal = datetime.now(tz=timezone(TIME_ZONE))
    provider.save()
    return redirect('providers_app:index')


# @login_required
def not_ready(request):
    """
    Shows that the provider is not ready to receive tasks.
    """
    provider = request.user.provider
    provider.ready = False
    provider.save()
    return redirect('providers_app:index')

# @login_required
def job_ack(request):
    if request.method == 'GET':
        if 'job' in request.GET.keys():
            job = get_object_or_404(Job, pk=request.GET['job'])
            job.ack_time = datetime.now(tz=timezone(TIME_ZONE))
            job.save(update_fields=['ack_time'])
        else:
            messages.error(request, "You need to provide the job number.")
    else:
        messages.error(request, "Wrong request method.")
    return redirect('providers_app:index')


class RpcClient(object):
    """
    This is the rabbitmq RpcClient class.
    """
    username = None

    def __init__(self,username):
        RpcClient.username = username

        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST, RABBITMQ_PORT, credentials=credentials))
        self.channel = self.connection.channel()

        result = self.channel.queue_declare(queue=username, exclusive=True)
        self.callback_queue = result.method.queue

        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response,
            auto_ack=True)
        self.response = None

    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            self.response = body

    def call(self, request):
        self.response = None
        self.corr_id = str(uuid.uuid4())
        self.channel.basic_publish(
            exchange='',
            routing_key=RpcClient.username, #using the class variable here
            properties=pika.BasicProperties(
                reply_to=self.callback_queue,
                correlation_id=self.corr_id,
            ),
            body=request)
        if request == '"Stop"':
            return
        while self.response is None:
            self.connection.process_data_events()
        return self.response
