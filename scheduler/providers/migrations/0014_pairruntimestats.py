import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('developers', '0009_services_image_size_mb_services_ref_runtime_ms_and_more'),
        ('profiles', '0011_user_r_cpu_user_r_disk_user_r_mem_user_r_net_and_more'),
        ('providers', '0013_job_bulk_query_indexes'),
    ]

    operations = [
        migrations.CreateModel(
            name='PairRuntimeStats',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ema_runtime_ms', models.FloatField()),
                ('observation_count', models.PositiveIntegerField(default=0)),
                ('last_runtime_ms', models.IntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('provider', models.ForeignKey(limit_choices_to={'is_provider': True}, on_delete=django.db.models.deletion.CASCADE, related_name='pair_runtime_stats', to='profiles.user')),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pair_runtime_stats', to='developers.services')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('provider', 'service'), name='pair_runtime_stats_unique_pair')],
            },
        ),
    ]
