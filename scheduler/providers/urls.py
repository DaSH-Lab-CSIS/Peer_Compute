from django.urls import path
from .views import (
    publish_to_topic_mqtt,
    ready,
    not_ready,
    job_ack,
    calculate_efficiency,
    providerStartup,
    set_reference_stats,
    get_user_id,
    direct_invoke,
    direct_invocation_status,
    pending_jobs_count,
    timeout_stale_jobs,
    jobs_in_window,
    reset_provider_state,
)
# from .views import recover_pending_jobs

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
    path('set_reference_stats_for_service/', set_reference_stats, name='set_reference_stats'),
    path('get_user_id/', get_user_id, name='get_user_id'),
    path('direct_invoke/', direct_invoke, name='direct_invoke'),
    path('direct_invocation_status/', direct_invocation_status, name='direct_invocation_status'),
    path('pending_jobs_count/', pending_jobs_count, name='pending_jobs_count'),
    path('timeout_stale_jobs/', timeout_stale_jobs, name='timeout_stale_jobs'),
    path('jobs_in_window/', jobs_in_window, name='jobs_in_window'),
    path('reset_provider_state/', reset_provider_state, name='reset_provider_state'),
    # path('recover_jobs/', recover_pending_jobs, name='recover_jobs')
]