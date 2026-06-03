from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("providers", "0009_cockroach_fix_job_id_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="finish_time",
            field=models.DateTimeField(
                blank=True,
                help_text="Timestamp when the scheduler received the provider result and marked the job finished",
                null=True,
            ),
        ),
    ]
