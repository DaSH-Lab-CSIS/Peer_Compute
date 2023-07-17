from django.db import models
from datetime import datetime
from pytz import timezone
from scheduler.settings import TIME_ZONE
from profiles.models import User

# Create your models here.
class Job(models.Model):
    provider = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'is_provider': True}
    )
    start_time = models.DateTimeField(default=datetime(2023, 7, 1, tzinfo=timezone(TIME_ZONE)))
    ack_time = models.DateTimeField(default=datetime(2018, 7, 1, tzinfo=timezone(TIME_ZONE)))
    pull_time = models.IntegerField(default=0)
    run_time = models.IntegerField(default=0)
    total_time = models.IntegerField(default=0)
    cost = models.FloatField(default=0.0)
    finished = models.BooleanField(default=False)
    corr_id = models.UUIDField(default=0, db_index=True)
    response = models.TextField(default='')