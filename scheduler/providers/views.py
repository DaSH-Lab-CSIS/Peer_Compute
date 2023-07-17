from django.shortcuts import render
import pika 
from profiles.models import User
from scheduler.settings import RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_MANAGEMENT_PORT, RABBITMQ_USER, RABBITMQ_PASS
from rabbitmq_admin import AdminAPI
# Create your views here.

def make_rmq_user(user):
    username = 'username' + str(user.user_id)
    password = 'username' + str(user.user_id) + '_mqtt'
    api = AdminAPI(url='http://' + RABBITMQ_HOST + ':' + RABBITMQ_MANAGEMENT_PORT, auth=(RABBITMQ_USER, RABBITMQ_PASS))
    api.create_user(username, password)
    permission = "^(" + username + ".*|amq.default)$"
    api.create_user_permission(username, '/', permission, permission, permission)
