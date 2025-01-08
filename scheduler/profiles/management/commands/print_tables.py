from django.core.management.base import BaseCommand
from tabulate import tabulate

from developers.models import Services
from profiles.models import User
from providers.models import Job


class Command(BaseCommand):
    help = 'Prints the PostgreSQL tables, specifically provider and developer IDs in table format.'

    def handle(self, *args, **options):
        self.print_providers()
        self.print_developers()
        self.print_services()
        self.print_jobs()

    def print_providers(self):
        providers = User.objects.filter(is_provider=True)
        if not providers.exists():
            print("\nProviders:")
            print("No providers found.")
            print("---")
            return

        provider_data = []
        for provider in providers:
            function_invocations = getattr(provider,'function_invocations', {})
            if function_invocations:
                func_invocations_table = tabulate(
                    [["Function ID", "Invocation Count"]] +
                    [[func_id, count] for func_id, count in function_invocations.items()],
                    headers=[],
                    tablefmt="simple",
                    stralign="left"
                )

                func_invocations = "\n" + "\n".join(["    " + line for line in func_invocations_table.split("\n")])
            else:
                func_invocations = "    No invocations"

            provider_data.append([
                str(provider.user_id),
                provider.active,
                provider.ready,
                provider.ram,
                provider.cpu,
                func_invocations
            ])

        # Define table headers
        headers = ["Provider ID", "Active", "Ready", "RAM", "CPU", "Function Invocations"]

        # Define table format with appropriate column alignment
        print("\nProviders:")
        print(tabulate(provider_data, headers=headers, tablefmt="fancy_grid", stralign="left", showindex=False))
        print("---")

    def print_developers(self):
        developers = User.objects.filter(is_developer=True)
        if not developers.exists():
            print("\nDevelopers:")
            print("No developers found.")
            print("---")
            return

        developer_data = []
        for developer in developers:
            developer_data.append([
                str(developer.user_id),
                developer.active
            ])


        headers = ["Developer ID", "Active"]

        print("\nDevelopers:")
        print(tabulate(developer_data, headers=headers, tablefmt="fancy_grid", stralign="left", showindex=False))
        print("---")

    def print_services(self):
        services = Services.objects.all()
        if not services.exists():
            print("\nServices:")
            print("No services found.")
            print("---")
            return

        # Prepare data for tabulation
        service_data = []
        for service in services:
            service_data.append([
                service.id,
                service.name,
                service.docker_container,
                service.developer.user_id if service.developer else "None",
                service.provider.user_id if service.provider else "None",
                service.active,

                service.requirements
            ])

        # Define table headers
        headers = ["Service ID", "Service Name","Service URL", "Developer ID", "Provider ID", "Active", "Requirements"]

        print("\nServices:")
        print(tabulate(service_data, headers=headers, tablefmt="fancy_grid", stralign="left", showindex=False))
        print("---")

    def print_jobs(self):
        jobs = Job.objects.all()
        if not jobs.exists():
            print("\nJobs:")
            print("No jobs found.")
            print("---")
            return

        # Prepare data for tabulation
        job_data = []
        for job in jobs:
            job_data.append([
                str(job.id),
                job.provider.user_id if job.provider else "None",
                job.service.name if job.service else "None",
                job.developer.user_id if job.developer else "None",
                job.start_time,
                job.finished
            ])

        # Define table headers
        headers = ["Job ID", "Provider ID", "Service Name", "Developer ID", "Start Time", "Finished"]

        print("\nJobs:")
        print(tabulate(job_data, headers=headers, tablefmt="fancy_grid", stralign="left", showindex=False))
        print("---")
