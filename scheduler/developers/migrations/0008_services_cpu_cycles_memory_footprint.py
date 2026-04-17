from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('developers', '0007_services_reference_stats'),
    ]

    operations = [
        migrations.AddField(
            model_name='services',
            name='cpu_cycles_required',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='services',
            name='memory_footprint',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='services',
            name='memory_bytes_per_second',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
