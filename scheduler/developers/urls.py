from django.urls import path
from .views import new_service, stop_service, index, user_services, start_service, delete_service, run_service, run_service_async, user_jobs, job_info

urlpatterns = [
    path('new_service/', new_service, name='new_service'),
    path('stop_service/', stop_service, name='stop_service'),
    path('index/', index, name='index'),
    path('user_services/', user_services, name='user_services'),
    path('start_service/', start_service, name='start_service'),
    path('delete_service/', delete_service, name='delete_service'),
    path('run_service/<int:service_id>', run_service, name='run_service'),
    path('run_service_async/', run_service_async, name='run_service_async'),
    path('user_jobs/', user_jobs, name='user_jobs'),
    path('job_info/', job_info, name='job_info'),
]