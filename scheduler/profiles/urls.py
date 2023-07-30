from django.urls import path
from .views import register_user,list_users,delete_user

urlpatterns = [
    path('register_user/', register_user, name='register_user'),
    path('list_users/', list_users, name='list_users'),
    path('delete_user/<int:user_id>/', delete_user, name='delete_user'),
]