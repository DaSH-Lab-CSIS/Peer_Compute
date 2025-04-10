from django.core.management.base import BaseCommand
from django.db.models import Count
from scheduler.providers.models import Job, ServiceInvocationLog
from scheduler.profiles.models import User
from scheduler.developers.models import Services


class Command(BaseCommand):
    help = "Populate the ServiceInvocationLog table from existing Job data"

    def handle(self, *args, **kwargs):
        # Aggregate the number of times each service has been invoked by each provider
        job_aggregates = Job.objects.values("provider_id", "service_id").annotate(
            frequency=Count("id")
        )

        for entry in job_aggregates:
            provider_id = entry["provider_id"]
            service_id = entry["service_id"]
            frequency = entry["frequency"]

            # Ensure the provider and service exist
            try:
                provider = User.objects.get(id=provider_id)
                service = Services.objects.get(id=service_id)
            except (User.DoesNotExist, Services.DoesNotExist):
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping non-existent provider or service: Provider {provider_id}, Service {service_id}"
                    )
                )
                continue

            # Create or update the ServiceInvocationLog entry
            log_entry, created = ServiceInvocationLog.objects.get_or_create(
                provider=provider, service=service, defaults={"frequency": frequency}
            )

            if not created:
                log_entry.frequency = frequency
                log_entry.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Processed Provider {provider_id}, Service {service_id}, Frequency {frequency}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS("ServiceInvocationLog table populated successfully.")
        )
