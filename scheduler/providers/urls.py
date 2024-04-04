from django.urls import path
from .views import publish_to_topic_mqtt, ready, not_ready,  job_ack, calculate_efficiency, providerStartup, set_reference_stats

urlpatterns = [
    # path('make_rmq_user/', make_rmq_user, name='make_rmq_user'),
    path('publish_to_topic/', publish_to_topic_mqtt, name='publish_to_topic'),
    # path('index/', index, name='index'),
    # path('stop_providing/', stop_providing, name='stop_providing'),
    path('ready/<str:user_id>', ready, name='ready'),
    path('not_ready/<str:user_id>', not_ready, name='not_ready'),
    path('job_ack/<int:job_id>', job_ack, name='job_ack'),
    path('calculate_efficiency/<str:user_id>', calculate_efficiency, name='calculate_efficiency'),
    path('startup/<str:user_id>', providerStartup, name='startup'),
    path('set_reference_stats_for_service/', set_reference_stats, name='set_reference_stats')
]