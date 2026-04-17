from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0009_merge_20251201_1300'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='cpi',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='memory_bandwidth',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=20, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='clock_hz',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
