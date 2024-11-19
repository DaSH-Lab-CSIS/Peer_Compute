from django.db import models
from datetime import datetime
from pytz import timezone
from scheduler.settings import TIME_ZONE
from profiles.models import User
from developers.models import Services
from django.apps import apps
from django.core.exceptions import ValidationError

# Create your models here.


class Job(models.Model):
    id = models.AutoField(primary_key=True)
    provider = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"is_provider": True},
        null=False,
        blank=False,
        related_name="jobs_as_provider",
        # it's not possible for a Job instance to not have a provider.
    )
    service = models.ForeignKey(
        Services,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        # REVIEW if this comment is present this needs to be done.
        # allowing null values till pushing to postgres. THIS WILL BE REMOVED POST THAT. [ Job is an instance of a Service it can't be null ]
    )
    developer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"is_developer": True},
        related_name="jobs_as_developer",
        null=True,
        blank=True,
        # allowing null values till pushing to postgres. THIS WILL BE REMOVED POST THAT.
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

    # override the save and clean method for enforcing constraints at model level processes
    def save(self, *args, **kwargs):
        if self.service:
            self.developer = self.service.developer
        super().save(*args, **kwargs)