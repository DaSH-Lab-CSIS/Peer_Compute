# Generated migration for request timing tracking

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('providers', '0006_job_last_recovery_attempt_job_recovery_attempts_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='lb_received_time',
            field=models.DateTimeField(null=True, blank=True, help_text='Timestamp when request was received at load balancer'),
        ),
        migrations.AddField(
            model_name='job',
            name='scheduler_received_time',
            field=models.DateTimeField(null=True, blank=True, help_text='Timestamp when request was received at scheduler'),
        ),
        migrations.AddField(
            model_name='job',
            name='assigned_to_provider_time',
            field=models.DateTimeField(null=True, blank=True, help_text='Timestamp when job was assigned to provider'),
        ),
    ]


