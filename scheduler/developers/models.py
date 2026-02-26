from django.db import models
from profiles.models import User

# Create your models here.
class Services(models.Model):
    developer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={'is_developer': True},
        related_name='services_as_developer'
    )
    # provider = models.ForeignKey(
    #     User,
    #     on_delete=models.CASCADE,
    #     limit_choices_to={'is_provider': True},
    #     related_name='services_as_provider'
    # )
    name = models.CharField(max_length=30)
    docker_container = models.URLField()
    active = models.BooleanField(default=False)

    # JSON field to represent service requirements
    requirements = models.JSONField(default=dict, blank=True)

    # Reference provider stats for runtime prediction: { "memory_usage", "cpu_usage", "actual_runtime" }
    # Populated when a reference run is done (ref_run_service_id/ MQTT). Null if not yet benchmarked.
    reference_stats = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        # Each developer can only have one service with a specific name
        unique_together = ['name', 'developer']

    # def predict_runtime(self):
    #     pred_rt = 0.0
    #     """
    #     implement logic for calculating predicted runtime 
    #     """
    #     return pred_rt
