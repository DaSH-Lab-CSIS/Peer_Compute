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
        # allowing null values till pushing to postgres. THIS WILL BE REMOVED POST THAT.
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

    reputation_score = models.IntegerField(default=0)

    delay = models.JSONField(default=dict, blank=True)
    time_of_last_startjob = models.DateTimeField(null=True, blank=True)
    # predicted_runtimes = models.JSONField(default=dict, blank=True)

    def increment_reputation(self, amount=1):
        self.reputation_score += amount

    def decrement_reputation(self, amount=1):
        self.reputation_score -= amount

    def reset_delay(self):
        self.delay['active_t'] = 0
        self.delay['predicted_runtimes'] = []
        self.save()

    def add_delay(self, predicted_runtime):
        # self.delay['active_t'] += time
        self.delay['predicted_runtimes'].append(predicted_runtime)
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
            'ram': self.provider.ram,
            'cpu': self.provider.cpu,
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
        Services = apps.get_model('developers', 'Services')
        # Services referenced this way to resolve circular import.
        # syntax = ModelClass = apps.get_model('app_label', 'ModelName')
        return Services.objects.filter(
            provider=self.provider,
            active=True,
            requirements__memory_limit__lte=self.provider.ram,
            requirements__cpu_cores__lte=self.provider.cpu,
            # requirements__gpu_required=self.gpu_available,
            # Add other requirements as needed
        )

    # return a dict mapping each compatible service to its predicted runtime
    def get_predicted_runtimes(self):
        pred_rt_matrix = {service.name: service.predict_runtime() for service in self.get_compatible_services()}
        return pred_rt_matrix

    # override the save and clean method for enforcing constraints at model level processes
    def save(self, *args, **kwargs):
        if self.service:
            self.developer = self.service.developer
        super().save(*args, **kwargs)