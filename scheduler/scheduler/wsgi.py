"""
WSGI config for scheduler project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scheduler.settings')

application = get_wsgi_application()

# Setup experiment logging if enabled
from django.conf import settings
if settings.EXPERIMENT_MODE and settings.EXPERIMENT_STDOUT_LOGGING:
    from providers.experiment_logging import setup_scheduler_logging
    setup_scheduler_logging()
