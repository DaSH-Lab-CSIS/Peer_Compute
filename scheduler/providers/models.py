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
    # # New state field
    # STATUS_CHOICES = [
    #     ('CREATED', 'Created'),
    #     ('SENT', 'Sent to Provider'),
    #     ('ACKNOWLEDGED', 'Acknowledged by Provider'),
    #     ('COMPLETED', 'Completed'),
    #     ('FAILED', 'Failed'),
    # ]
    # status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CREATED')
    # recovery_attempts = models.IntegerField(default=0)
    # last_recovery_attempt = models.DateTimeField(null=True, blank=True)
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
        # allowing null values till production ready. THIS WILL BE REMOVED POST THAT. [ Job is an instance of a Service it can't have a null service reference ]
    )
    developer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"is_developer": True},
        related_name="jobs_as_developer",
        null=True,
        blank=True,
        # allowing null values till production ready. THIS WILL BE REMOVED POST THAT.
    )
    start_time = models.DateTimeField(auto_now_add=True)
    ack_time = models.DateTimeField(null=True, blank=True)  # Only set when job is acknowledged
    # Request timing fields for tracking delays
    lb_received_time = models.DateTimeField(null=True, blank=True, help_text='Timestamp when request was received at load balancer')
    scheduler_received_time = models.DateTimeField(null=True, blank=True, help_text='Timestamp when request was received at scheduler')
    assigned_to_provider_time = models.DateTimeField(null=True, blank=True, help_text='Timestamp when job was assigned to provider')
    pull_time = models.IntegerField(default=0)
    run_time = models.IntegerField(default=0)
    total_time = models.IntegerField(default=0)
    cost = models.FloatField(default=0.0)
    finished = models.BooleanField(default=False)
    corr_id = models.UUIDField(default=0, db_index=True)
    response = models.TextField(default="")

    # Efficiency/training stats from provider (same shape as eff_score_data.txt); null if not reported
    memory_usage = models.BigIntegerField(null=True, blank=True, help_text="Container memory usage in bytes")
    cpu_usage = models.BigIntegerField(null=True, blank=True, help_text="Container CPU usage (total_usage)")
    cpu_efficiency_score = models.DecimalField(null=True, blank=True, max_digits=30, decimal_places=15)
    memory_efficiency_score = models.DecimalField(null=True, blank=True, max_digits=30, decimal_places=15)

    # Return the run_time of the latest invocation of this service (job) for a certain provider
    def get_latest_run_time(provider_id, service_id):
        latest_job = Job.objects.filter(
            provider_id = provider_id,
            service_id = service_id
        ).latest('start_time')

        if latest_job:
            return latest_job.run_time
        else:
            return None

    def get_latest_pull_time(provider_id, service_id):
        latest_job = Job.objects.filter(
            provider_id = provider_id,
            service_id = service_id
        ).latest('pull_time')

        if latest_job:
            return latest_job.pull_time
        else:
            return None

    # override the save and clean method for enforcing constraints at model level processes
    def save(self, *args, **kwargs):
        if self.service:
            self.developer = self.service.developer
        if not self.start_time:
            self.start_time = datetime.now(timezone(TIME_ZONE))
        super().save(*args, **kwargs)
    # reputation_score = models.IntegerField(default=0)

    # delay = models.JSONField(default=dict, blank=True)
    # time_of_last_startjob = models.DateTimeField(null=True, blank=True)
    # predicted_runtimes = models.JSONField(default=dict, blank=True)

    # def increment_reputation(self, amount=1):
    #     self.reputation_score += amount

    # def decrement_reputation(self, amount=1):
    #     self.reputation_score -= amount

    # def reset_delay(self):
    #     self.delay["active_t"] = 0
    #     self.delay["predicted_runtimes"] = []
    #     self.save()

    # def add_delay(self, predicted_runtime):
    #     # self.delay['active_t'] += time
    #     self.delay["predicted_runtimes"].append(predicted_runtime)
    #     if len(self.delay["predicted_runtimes"]) == 1:
    #         self.delay["active_t"] = datetime.now()
    #     self.save()

    # def calculate_current_delay(self):
    #     """
    #     This calculation is only done when needed (i.e. scheduling)
    #     """
    #     if not self.delay["predicted_runtimes"]:
    #         return 0

    #     # elapsed time since the last job started
    #     current_time = datetime.now()
    #     elapsed_time = (current_time - self.time_of_last_startjob).total_seconds()

    #     remaining_time_for_current_job = max(0, self.delay["active_t"] - elapsed_time)

    #     total_delay = remaining_time_for_current_job + sum(
    #         self.delay["predicted_runtimes"][1:]
    #     )

    #     return total_delay

    # def update_delay_after_completion(self):
    #     """
    #     Updates delay after a job completion.
    #      -> Remove the oldest predicted runtime
    #      -> adjust active_t
    #     """
    #     if not self.delay["predicted_runtimes"]:
    #         return

    #     current_time = datetime.now().timestamp()
    #     elapsed_time = current_time - self.delay["active_t"]

    #     # Remove the predicted runtime of the completed job (the oldest one)
    #     self.delay["predicted_runtimes"].pop(0)

    #     if self.delay["predicted_runtimes"]:
    #         # Adjust active_t based on remaining predicted runtimes
    #         self.delay["active_t"] = max(
    #             0, sum(self.delay["predicted_runtimes"]) - elapsed_time
    #         )
    #     else:
    #         # If no jobs are remaining, reset active_t
    #         self.delay["active_t"] = 0

    #     self.save()

    # def satisfies(self, requirements):
    #     # requirements expected to be a dict with key - value pairs like ram, cpu, gpu, etc.

    #     # specs dict should be changed as and how the extent of requirements are
    #     specifications = {
    #         "memory_limit": self.provider.ram,
    #         "cpu_cores": self.provider.cpu,
    #         # "ram": self.provider.ram,
    #         # "cpu": self.provider.cpu,
    #         # 'gpu_required' : self.gpu_available,
    #     }

    #     # return True if specs are better than
    #     for key, value in requirements.items():
    #         if key not in specifications:
    #             return False
    #         if isinstance(value, bool):  # suppose a spec is "gpu_available" : True
    #             if specifications[key] != value:
    #                 return False
    #         if specifications[key] < value:
    #             return False
    #     return True

    # def get_compatible_services(self):
    #     """
    #     Retrieves services that the provider can handle based on their specifications.
    #     Returns a QuerySet compatible Services.
    #     """
    #     Services = apps.get_model("developers", "Services")
    #     # Services referenced this way to resolve circular import.
    #     # syntax = ModelClass = apps.get_model('app_label', 'ModelName')
    #     return Services.objects.filter(
    #         provider=self.provider,
    #         active=True,
    #         requirements__ram__lte=self.provider.ram,
    #         requirements__cpu__lte=self.provider.cpu,
    #         # requirements__gpu_required=self.gpu_available,
    #         # Add other requirements as needed
    #     )

    # # return a dict mapping each compatible service to its predicted runtime
    # def get_predicted_runtimes(self):
    #     pred_rt_matrix = {
    #         service.name: service.predict_runtime()
    #         for service in self.get_compatible_services()
    #     }
    #     return pred_rt_matrix