from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('providers', '0012_job_cache_state'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='job',
            index=models.Index(
                fields=['provider_id', 'service_id', '-start_time'],
                name='job_prov_svc_start_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(
                fields=['provider_id', 'service_id', '-pull_time'],
                name='job_prov_svc_pull_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(
                fields=['provider_id', '-start_time'],
                name='job_prov_start_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='job',
            index=models.Index(
                fields=['finished', 'provider_id', 'service_id'],
                name='job_finished_prov_svc_idx',
            ),
        ),
    ]
