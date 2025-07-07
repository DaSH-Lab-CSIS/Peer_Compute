#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
import atexit
import signal

def cleanup_pid_file(pid_file):
    """Remove the PID file if it exists."""
    if os.path.exists(pid_file):
        os.remove(pid_file)
        print(f"Deleted PID file: {pid_file}")


def handle_signals(pid_file):
    """Register signal handlers for cleanup."""
    def signal_handler(signum, frame):
        cleanup_pid_file(pid_file)
        sys.exit(0)

    # Register cleanup for common termination signals
    signal.signal(signal.SIGINT, signal_handler)   # Handle Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Handle kill command

def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scheduler.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    
    # Setup experiment logging for runserver command
    if len(sys.argv) > 1 and sys.argv[1] == 'runserver':
        from django.conf import settings
        if settings.EXPERIMENT_MODE and settings.EXPERIMENT_STDOUT_LOGGING:
            from providers.experiment_logging import setup_scheduler_logging
            setup_scheduler_logging()
    
    # Get the current process ID
    pid = os.getpid()
    #Adding this code to write pid to a file

    pid_file = "djpid.txt"

    if not os.path.exists(pid_file):
        with open(pid_file, "w") as file:
            file.write(str(pid))
    # Print the PID
    print(f"PID: {pid}")
    execute_from_command_line(sys.argv)

    atexit.register(cleanup_pid_file, pid_file)
    handle_signals(pid_file)

if __name__ == '__main__':
    main()
