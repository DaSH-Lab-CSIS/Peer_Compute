from django.shortcuts import render,get_object_or_404
import pika 
import json
from profiles.models import User
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

def add_task_to_queue(request,task,username):

    client = RpcClient()
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


class RpcClient(object):
    """
    This is the rabbitmq RpcClient class.
    """

    def __init__(self):
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
        if not RABBITMQ_PORT:
            self.connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=RABBITMQ_HOST, credentials=credentials))
        else:
            self.connection = pika.BlockingConnection(
                pika.ConnectionParameters(RABBITMQ_HOST, RABBITMQ_PORT, credentials=credentials))

        self.channel = self.connection.channel()

        result = self.channel.queue_declare(queue='', exclusive=True)
        self.callback_queue = result.method.queue

        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response,
            auto_ack=True)
        self.response = None

    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            self.response = body

    def call(self, queue_name, request):
        self.response = None
        self.corr_id = str(uuid.uuid4())
        self.channel.basic_publish(
            exchange='',
            routing_key=queue_name,
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
