from django.db import models
from pytz import timezone
import pytz
from datetime import datetime, timedelta
import uuid
from scheduler.settings import TIME_ZONE
# from developers.models import Services


class User(models.Model):
    user_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_provider = models.BooleanField(default=False)
    is_developer = models.BooleanField(default=False)
    active = models.BooleanField(default=False)
    ready = models.BooleanField(default=False)
    last_ready_signal = models.DateTimeField(default=datetime.now)
    location = models.CharField(max_length=30, blank=True)
    ram = models.IntegerField(default=0)
    cpu = models.IntegerField(default=0)
    cpu_efficiency_score = models.DecimalField(null=True, max_digits=30, decimal_places=15)
    memory_efficiency_score = models.DecimalField(null=True, max_digits=30, decimal_places=15)
    # gpu_available = models.BooleanField(default=False)

    function_invocations = models.JSONField(default=dict, blank=True)

    """
    resolves a case that may occur even with other checks:
     -> non - provider has function_invocations populated
    """

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(is_provider=True) | models.Q(function_invocations__len=0),
                name="function_invocation_only_if_provider"
            )
        ]

    def __str__(self):
        return f"User : {self.user_id}\n  \tprovider : {self.is_provider} \tdeveloper : {self.is_developer}"

