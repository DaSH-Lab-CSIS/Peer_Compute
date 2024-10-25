"""
The provider_data in this script will be added based on the django models as of sn34kyp3t3/dev commit -> 636d003.
Use this as a template for any csv additions in the future. ( Be sure to alter the script if the models change )
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from profiles.models import User


class Command(BaseCommand):
    help = 'Import function invocations for providers.'

    def handle(self, *args, **options):
        provider_data = [
            {
                'user_id': '34933555-5cca-41fb-aded-4ab7900c48d5',
                'function_invocations': {"3": 224, "4": 209, "5": 217, "6": 4},
            },
            {
                'user_id': '02b96209-bbe3-4e30-b628-3d95afba3e27',
                'function_invocations': {"4": 197},
            },
        ]

        with transaction.atomic():
            for provider in provider_data:
                user, created = User.objects.update_or_create(
                    user_id=provider['user_id'],
                    defaults={
                        'is_provider': True,
                        'is_developer': False,
                        'active': False,  # since False is default [ADJUST AS NECESSARY]
                        'ready': False,  # since False is default [ADJUST AS NECESSARY]
                        'location': '',
                        'ram': 0,
                        'cpu': 0,
                        'function_invocations': provider['function_invocations'],
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created provider {user.user_id}"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"Updated provider {user.user_id}"))

        self.stdout.write(self.style.SUCCESS("Function invocations imported successfully."))
