from django.core.management.base import BaseCommand
from tabulate import tabulate
from termcolor import colored

from developers.models import Services
from profiles.models import User
from providers.models import Job


class Command(BaseCommand):
    help = "Prints the PostgreSQL tables, specifically provider and developer IDs in table format."

    def add_arguments(self, parser):
        parser.add_argument(
            'jobs',
            nargs='*',
            type=str,
            help= 'Keyword "jobs" followed by a list of job IDs or ranges to print, e.g., "jobs 1", "jobs 1-3", "jobs 5,7-9". !! Do not enclose the job IDs in []'
        )
        parser.add_argument(
            '--services',
            action='store_true',
            help='Print services table'
        )

    def parse_job_ids(self, job_args):
        job_ids = set()
        for arg in job_args:
            parts = arg.split(',')
            for part in parts:
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    job_ids.update(range(start, end + 1))
                else:
                    try:
                        job_ids.add(int(part))
                    except ValueError:
                        print(f"Invalid job ID: {part}")
        return job_ids

    def handle(self, *args, **options):
        job_args = options.get('jobs', [])
        if not job_args or not job_args[0] == 'jobs':
            job_ids = None  # No specific job IDs provided; fetch all jobs
        else:
            job_ids = self.parse_job_ids(job_args)

        if options.get('services'):
            self.print_services()
        else:
            self.print_providers()
            self.print_developers()
            self.print_services()
            self.print_jobs(job_ids)

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
                    [["Function ID", "Invocation Count"]]
                    + [
                        [func_id, count]
                        for func_id, count in provider.function_invocations.items()
                    ],
                    headers=[],  # Headers are included in the first row
                    tablefmt="simple",
                    stralign="left",
                )
                # Indent the sub-table for better readability
                func_invocations = "\n" + "\n".join(
                    ["    " + line for line in func_invocations_table.split("\n")]
                )
            else:
                func_invocations = "    No invocations"

            if provider.delay:
                # Create a mini-table string for function invocations
                delay_table = tabulate(
                    [["Active Time", "Predicted Runtimes"]]
                    + [
                        [active_t, pred_rt]
                        for active_t, pred_rt in provider.delay.items()
                    ],
                    headers=[],  # Headers are included in the first row
                    tablefmt="simple",
                    stralign="left",
                )
                # Indent the sub-table for better readability
                delay = "\n" + "\n".join(
                    ["    " + line for line in delay.split("\n")]
                )
            else:
                delay = "    No Delay"

            provider_data.append(
                [
                    str(provider.user_id),
                    provider.active,
                    provider.ready,
                    provider.ram,
                    provider.cpu,
                    provider.reputation_score,
                    func_invocations,
                    delay,
                ]
            )

        # Define table headers
        headers = [
            "Provider ID",
            "Active",
            "Ready",
            "RAM",
            "CPU",
            "Reputation Score",
            "Function Invocations",
            "Delay",
        ]

        # Define table format with appropriate column alignment
        print("\nProviders:")
        print(
            tabulate(
                provider_data,
                headers=headers,
                tablefmt="fancy_grid",
                stralign="left",
                showindex=False,
            )
        )
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
            developer_data.append([str(developer.user_id), developer.active])


        headers = ["Developer ID", "Active"]

        print("\nDevelopers:")
        print(
            tabulate(
                developer_data,
                headers=headers,
                tablefmt="fancy_grid",
                stralign="left",
                showindex=False,
            )
        )
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
            service_data.append(
                [
                    service.id,
                    service.name,
                    service.docker_container,
                    service.developer.user_id if service.developer else "None",
                    service.active,
                    service.requirements,
                ]
            )

        # Define table headers
        headers = [
            "Service ID",
            "Service Name",
            "Docker Container",
            "Developer ID",
            "Active",
            "Requirements",
        ]

        print("\nServices:")
        print(
            tabulate(
                service_data,
                headers=headers,
                tablefmt="fancy_grid",
                stralign="left",
                showindex=False,
            )
        )
        print("---")

    def print_jobs(self, job_ids = None):
        if job_ids is None:
            jobs = Job.objects.all()
        else:
            jobs = Job.objects.filter(id__in=job_ids)

        if not jobs.exists():
            print("\nJobs:")
            print("No jobs found.")
            print("---")
            return

        unfinished_jobs = jobs.filter(finished=False).order_by('start_time')
        finished_jobs = jobs.filter(finished=True).order_by('start_time')

        ordered_jobs = list(unfinished_jobs) + list(finished_jobs)

        # Prepare data for unfinished jobs
        unfinished_job_data = []
        for job in unfinished_jobs:
            unfinished_job_data.append(
                [
                    str(job.id),
                    job.provider.user_id if job.provider else "None",
                    job.service.name if job.service else "None",
                    job.developer.user_id if job.developer else "None",
                    job.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    f"\033[91mFalse\033[0m",  # Red for False
                ]
            )

        # Prepare data for finished jobs
        finished_job_data = []
        for job in finished_jobs:
            finished_job_data.append(
                [
                    str(job.id),
                    job.provider.user_id if job.provider else "None",
                    job.service.name if job.service else "None",
                    job.developer.user_id if job.developer else "None",
                    job.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    f"\033[92mTrue\033[0m",  # Green for True
                ]
            )

        # Define table headers
        headers = [
            "Job ID",
            "Provider ID",
            "Service Name",
            "Developer ID",
            "Start Time",
            "Finished",
        ]

        # Display unfinished jobs table
        print("\nUnfinished Jobs:")
        if unfinished_job_data:
            print(
                tabulate(
                    unfinished_job_data,
                    headers=headers,
                    tablefmt="fancy_grid",
                    stralign="left",
                    showindex=False,
                    colalign=("left", "left", "left", "left", "left", "center"),
                )
            )
        else:
            print("No unfinished jobs found. [ Pertaining to the provided job IDs if entered ]")

        print("---")

        # Display finished jobs table
        print("\nFinished Jobs:")
        if finished_job_data:
            print(
                tabulate(
                    finished_job_data,
                    headers=headers,
                    tablefmt="fancy_grid",
                    stralign="left",
                    showindex=False,
                    colalign=("left", "left", "left", "left", "left", "center"),
                )
            )
        else:
            print("No finished jobs found. [ Pertaining to the provided job IDs if entered ]")

        print("---")
