from django.core.exceptions import ValidationError
from django.db import models
from pytz import timezone
import pytz
from datetime import datetime, timedelta
import uuid
from scheduler.settings import TIME_ZONE
# from developers.models import Services
from django.apps import apps


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
    reputation_score = models.IntegerField(default=0)

    delay = models.JSONField(default=dict, blank=True)
    time_of_last_startjob = models.DateTimeField(null=True, blank=True)
    # predicted_runtimes = models.JSONField(default=dict, blank=True)

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

    def increment_reputation(self, amount=1):
        self.reputation_score += 1

    def decrement_reputation(self, amount=1):
        self.reputation_score -= 1

    def reset_delay(self):
        self.delay['active_t'] = 0
        self.delay['predicted_runtimes'] = []
        self.save()

    def add_delay(self, predicted_runtime ):
        # self.delay['active_t'] += time
        self.predicted_runtimes.append(predicted_runtime)
        if len(self.delay['predicted_runtimes']) == 1:
            self.delay['active_t'] = datetime.now()
        self.save()

    def calculate_current_delay(self):
        """
        This calculation is only done when needed (i.e. scheduling)
        """
        if not self.delay['predicted_runtimes']:
            return 0

        # elapsed time since the last job started
        current_time = datetime.now()
        elapsed_time = (current_time - self.time_of_last_startjob).total_seconds()

        remaining_time_for_current_job = max(0, self.delay['active_t'] - elapsed_time)

        total_delay = remaining_time_for_current_job + sum(self.delay['predicted_runtimes'][1:])

        return total_delay

    def update_delay_after_completion(self):
        """
        Updates delay after a job completion.
         -> Remove the oldest predicted runtime
         -> adjust active_t
        """
        if not self.delay['predicted_runtimes']:
            return

        current_time = datetime.now().timestamp()
        elapsed_time = current_time - self.delay['active_t']

        # Remove the predicted runtime of the completed job (the oldest one)
        self.delay['predicted_runtimes'].pop(0)

        if self.delay['predicted_runtimes']:
            # Adjust active_t based on remaining predicted runtimes
            self.delay['active_t'] = max(0, sum(self.delay['predicted_runtimes']) - elapsed_time)
        else:
            # If no jobs are remaining, reset active_t
            self.delay['active_t'] = 0

        self.save()

    def satisfies(self, requirements):
        # requirements expected to be a dict with key - value pairs like ram, cpu, gpu, etc.

        # specs dict should be changed as and how the extent of requirements are
        specifications = {
            'ram': self.ram,
            'cpu': self.cpu,
            # 'gpu_required' : self.gpu_available,
        }

        # return True if specs are better than
        for key, value in requirements.values():
            if key not in specifications:
                return False
            if isinstance(value, bool):  # suppose a spec is "gpu_available" : True
                if specifications[key] != value:
                    return False
            if specifications[key] < value:
                return False
        return True

    def get_compatible_services(self):
        """
        Retrieves services that the provider can handle based on their specifications.
        Returns a QuerySet compatible Services.
        """
        Services = apps.get_model('developers', 'Service')
        # Services referenced this way to resolve circular import.
        # syntax = ModelClass = apps.get_model('app_label', 'ModelName')
        return Services.objects.filter(
            provider=self,
            active=True,
            requirements__memory_limit__lte=self.ram,
            requirements__cpu_cores__lte=self.cpu,
            # requirements__gpu_required=self.gpu_available,
            # Add other requirements as needed
        )

    # return a dict mapping each compatible service to its predicted runtime
    def get_predicted_runtimes(self):
        pred_rt_matrix = {service.name: service.predict_runtime() for service in self.get_compatible_services()}
        return pred_rt_matrix

    # override the save and clean method for enforcing constraints at model level processes
    def save(self, *args, **kwargs):
        if not self.is_provider():
            if self.function_invocations or self.predicted_runtimes:
                self.function_invocations = {}
                self.predicted_runtimes = {}
                raise ValidationError("Cannot set function invocation data for a non - provider User object")
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.is_provider and self.function_invocations:
            raise ValidationError({
                'function_invocations': 'Only providers can have function invocations.'
            })
