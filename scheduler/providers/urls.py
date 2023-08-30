from django.urls import path
from .views import publish_to_topic, ready, not_ready,  job_ack

urlpatterns = [
    # path('make_rmq_user/', make_rmq_user, name='make_rmq_user'),
    path('publish_to_topic/', publish_to_topic, name='publish_to_topic'),
    # path('index/', index, name='index'),
    # path('stop_providing/', stop_providing, name='stop_providing'),
    path('ready/<string:user_id>', ready, name='ready'),
    path('not_ready/<string:user_id>', not_ready, name='not_ready'),
    path('job_ack/<int:job_id>', job_ack, name='job_ack')
]