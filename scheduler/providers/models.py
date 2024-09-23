from django.db import models
from developers.models import Services
from datetime import datetime
from pytz import timezone
from scheduler.settings import TIME_ZONE
from profiles.models import User
from developers.models import Services

# Create your models here.


class Job(models.Model):
    id = models.AutoField(primary_key=True)
    provider = models.ForeignKey(
        User, on_delete=models.CASCADE, limit_choices_to={"is_provider": True}
    )
    service = models.ForeignKey(
        Services,
        on_delete=models.CASCADE,
    )
    developer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"is_developer": True},
    )
    start_time = models.DateTimeField(
        default=datetime(2023, 7, 1, tzinfo=timezone(TIME_ZONE))
    )
    ack_time = models.DateTimeField(
        default=datetime(2018, 7, 1, tzinfo=timezone(TIME_ZONE))
    )
    pull_time = models.IntegerField(default=0)
    run_time = models.IntegerField(default=0)
    total_time = models.IntegerField(default=0)
    cost = models.FloatField(default=0.0)
    finished = models.BooleanField(default=False)
    corr_id = models.UUIDField(default=0, db_index=True)
    response = models.TextField(default="")

    def save(self, *args, **kwargs):
        if self.service:
            self.developer = self.service.developer
        super().save(*args, **kwargs)
