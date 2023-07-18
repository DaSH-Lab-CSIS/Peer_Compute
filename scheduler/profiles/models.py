from django.db import models
from pytz import timezone
import pytz
from datetime import datetime, timedelta
import uuid
from scheduler.settings import TIME_ZONE

# Create your models here.
class User(models.Model):
    user_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_provider = models.BooleanField(default=False)
    is_developer = models.BooleanField(default=False)
    active = models.BooleanField(default=False)
    ready = models.BooleanField(default=False)
    last_ready_signal = models.DateTimeField(default=datetime(2018, 7, 1, tzinfo=timezone(TIME_ZONE)))
    location = models.CharField(max_length=30, blank=True)
    ram = models.IntegerField(default=0)
    cpu = models.IntegerField(default=0)
    