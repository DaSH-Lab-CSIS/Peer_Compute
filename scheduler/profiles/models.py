from django.db import models
from pytz import timezone
import pytz
from django.apps import apps
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
    # network_bandwidth = models.DecimalField(null=True, max_digits=30, decimal_places=15)
    # gpu_available = models.BooleanField(default=False)

    # NOTE Provider - Only fields 
    function_invocations = models.JSONField(default=dict, blank=True)  # { function_id [str] : invocation_count [int] }
    reputation_score = models.IntegerField(default=0)
    delay = models.JSONField(default=dict, blank=True)  # { "active_t" : [int], "predicted_runtimes": [ [int],[int],...] }
    time_of_last_startjob = models.DateTimeField(null=True, blank=True)
    inflight_jobs = models.JSONField(default=dict, blank=True)

    """
    resolves a case that may occur even with other checks: -> non - provider has provider only fields populated
    """

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(is_provider=True)
                | models.Q(function_invocations__len=0),
                name="function_invocation_only_if_provider",
            ),
            models.CheckConstraint(
                check=models.Q(is_provider=True) | models.Q(delay={}),
                name="delay_only_if_provider",
            ),
            models.CheckConstraint(
                check=models.Q(is_provider=True)
                | models.Q(time_of_last_startjob__isnull=True),
                name="time_of_last_startjob_only_if_provider",
            ),
            models.CheckConstraint(
                check=models.Q(is_provider=True) | models.Q(inflight_jobs__len=0),
                name="inflight_jobs_only_if_provider",
            ),
        ]

    def add_inflight_job(self, service_id):
        # Add a service ID to the inflight jobs at the end
        if service_id not in self.inflight_jobs:
            self.inflight_jobs.append(service_id)
            self.save()

    # if no args are passed, it will remove the first element from the inflight jobs array
    def remove_inflight_job(self, service_id=None):
        # Remove a service ID from the inflight jobs.
        if service_id is not None:
            if self.inflight_jobs:
                if service_id in self.inflight_jobs:
                    self.inflight_jobs.remove(service_id)
                    self.save()
        else:
            if self.inflight_jobs:
                self.inflight_jobs.pop(0)
                self.save()

    def increment_reputation(self, amount=1):
        self.reputation_score += amount

    def decrement_reputation(self, amount=1):
        self.reputation_score -= amount

    def reset_delay(self):
        self.delay["active_t"] = 0
        self.delay["predicted_runtimes"] = []
        self.save()

    def add_delay(self, predicted_runtime):
        # self.delay['active_t'] += time
        self.delay["predicted_runtimes"].append(predicted_runtime)
        if len(self.delay["predicted_runtimes"]) == 1:
            self.delay["active_t"] = datetime.now()
        self.save()

    def calculate_current_delay(self):
        """
        This calculation is only done when needed (i.e. scheduling)
        """
        if not self.delay["predicted_runtimes"]:
            return 0

        # elapsed time since the last job started
        current_time = datetime.now()
        elapsed_time = (current_time - self.time_of_last_startjob).total_seconds()

        remaining_time_for_current_job = max(0, self.delay["active_t"] - elapsed_time)

        total_delay = remaining_time_for_current_job + sum(self.delay["predicted_runtimes"][1:])

        return total_delay

    def update_delay_after_completion(self):
        """
        Updates delay after a job completion.
         -> Remove the oldest predicted runtime
         -> adjust active_t
        """
        if not self.delay["predicted_runtimes"]:
            return

        current_time = datetime.now().timestamp()
        elapsed_time = current_time - self.delay["active_t"]

        # Remove the predicted runtime of the completed job (the oldest one)
        self.delay["predicted_runtimes"].pop(0)

        if self.delay["predicted_runtimes"]:
            # Adjust active_t based on remaining predicted runtimes
            self.delay["active_t"] = max(
                0, sum(self.delay["predicted_runtimes"]) - elapsed_time
            )
        else:
            # If no jobs are remaining, reset active_t
            self.delay["active_t"] = 0

        self.save()

    def satisfies(self, requirements):
        # requirements expected to be a dict with key - value pairs like ram, cpu, gpu, etc.

        # specs dict should be changed as and how the extent of requirements are
        specifications = {
            "memory_limit": self.ram,
            "cpu_cores": self.cpu,
            # "network_bandwidth": getattr(self, "network_bandwidth", 0),
            # "ram": self.ram,
            # "cpu": self.cpu,
            # 'gpu_required' : self.gpu_available,
        }

        # return True if specs are better than
        for key, value in requirements.items():
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
        Services = apps.get_model("developers", "Services")
        # Services referenced this way to resolve circular import.
        # syntax = ModelClass = apps.get_model('app_label', 'ModelName')
        return Services.objects.filter(
            provider=self,
            active=True,
            requirements__ram__lte=self.ram,
            requirements__cpu__lte=self.cpu,
            # requirements__gpu_required=self.gpu_available,
            # Add other requirements as needed
        )

    # return a dict mapping each compatible service to its predicted runtime
    def get_predicted_runtimes(self):
        pred_rt_matrix = {
            service.name: service.predict_runtime()
            for service in self.get_compatible_services()
        }
        return pred_rt_matrix

    def __str__(self):
        return f"User : {self.user_id}\n  \tprovider : {self.is_provider} \tdeveloper : {self.is_developer}"
