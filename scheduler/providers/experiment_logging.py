"""
Experiment Logging Utilities

This module provides utilities for capturing and logging stdout/stderr output
during scheduling algorithm experiments. It enables detailed logging of scheduler
and provider activities for post-experiment analysis.
"""

import os
import sys
import threading
from datetime import datetime
from contextlib import contextmanager
from django.conf import settings
import socket


class ExperimentLogger:
    """Handles stdout/stderr logging for experiment mode"""
    
    def __init__(self, log_file_path: str, node_type: str, node_id: str = None):
        """
        Initialize experiment logger
        
        Args:
            log_file_path: Path to the log file
            node_type: Type of node ('scheduler', 'provider', 'loadbalancer')
            node_id: Unique identifier for the node (user_id for providers, IP for scheduler)
        """
        self.log_file_path = log_file_path
        self.node_type = node_type
        self.node_id = node_id or self._get_default_node_id()
        self.original_stdout = None
        self.original_stderr = None
        self.log_file = None
        self.lock = threading.Lock()
        
        # Ensure log directory exists
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        
    def _get_default_node_id(self):
        """Get default node ID based on hostname/IP"""
        try:
            return socket.gethostname()
        except:
            return "unknown"
    
    def _get_timestamp(self):
        """Get formatted timestamp"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
    def _format_log_line(self, message: str, stream_type: str = "stdout"):
        """Format a log line with timestamp and node info"""
        timestamp = self._get_timestamp()
        return f"[{timestamp}] [{self.node_type}:{self.node_id}] [{stream_type.upper()}] {message}"
    
    def start_logging(self):
        """Start capturing stdout/stderr to file"""
        if not settings.EXPERIMENT_MODE or not settings.EXPERIMENT_STDOUT_LOGGING:
            return
        
        with self.lock:
            if self.log_file is not None:
                return  # Already logging
                
            # Store original streams
            self.original_stdout = sys.stdout
            self.original_stderr = sys.stderr
            
            # Open log file
            self.log_file = open(self.log_file_path, 'a', encoding='utf-8')
            
            # Write session start marker
            start_msg = self._format_log_line(f"=== EXPERIMENT SESSION START ===", "system")
            self.log_file.write(start_msg + '\n')
            self.log_file.flush()
            
            # Replace stdout/stderr with custom writers
            sys.stdout = self._LogWriter(self, "stdout")
            sys.stderr = self._LogWriter(self, "stderr")
            
            print(f"Experiment logging started for {self.node_type}:{self.node_id}")
    
    def stop_logging(self):
        """Stop capturing stdout/stderr and restore original streams"""
        with self.lock:
            if self.log_file is None:
                return  # Not logging
            
            # Write session end marker
            end_msg = self._format_log_line(f"=== EXPERIMENT SESSION END ===", "system")
            self.log_file.write(end_msg + '\n')
            self.log_file.flush()
            
            # Restore original streams
            sys.stdout = self.original_stdout
            sys.stderr = self.original_stderr
            
            # Close log file
            self.log_file.close()
            self.log_file = None
            
            print(f"Experiment logging stopped for {self.node_type}:{self.node_id}")
    
    def write_message(self, message: str, stream_type: str = "stdout"):
        """Write a message to the log file"""
        if self.log_file:
            formatted_msg = self._format_log_line(message, stream_type)
            self.log_file.write(formatted_msg + '\n')
            self.log_file.flush()
            
            # Also write to original stream
            original_stream = self.original_stdout if stream_type == "stdout" else self.original_stderr
            if original_stream:
                original_stream.write(message)
                original_stream.flush()
    
    class _LogWriter:
        """Custom writer that logs to file and original stream"""
        
        def __init__(self, logger, stream_type):
            self.logger = logger
            self.stream_type = stream_type
        
        def write(self, message):
            if message.strip():  # Only log non-empty messages
                self.logger.write_message(message.rstrip('\n'), self.stream_type)
        
        def flush(self):
            if self.logger.log_file:
                self.logger.log_file.flush()


class SchedulerLogger(ExperimentLogger):
    """Logger specifically for Django scheduler"""
    
    def __init__(self, node_id: str = None):
        log_file = settings.SCHEDULER_LOG_FILE
        super().__init__(log_file, "scheduler", node_id)


class ProviderLogger(ExperimentLogger):
    """Logger specifically for providers"""
    
    def __init__(self, provider_id: str):
        # Get current log directory (may be algorithm-specific)
        if hasattr(settings, 'get_experiment_logs_dir'):
            current_log_dir = settings.get_experiment_logs_dir()
        else:
            current_log_dir = '/tmp/experiment_logs'  # Fallback directory
        os.makedirs(current_log_dir, exist_ok=True)
        
        # Create provider-specific log file
        log_file = os.path.join(current_log_dir, f"provider_{provider_id}_stdout.log")
        super().__init__(log_file, "provider", provider_id)


class LoadBalancerLogger(ExperimentLogger):
    """Logger specifically for load balancer"""
    
    def __init__(self, node_id: str = None):
        # Get current log directory (may be algorithm-specific)
        if hasattr(settings, 'get_experiment_logs_dir'):
            current_log_dir = settings.get_experiment_logs_dir()
        else:
            current_log_dir = '/tmp/experiment_logs'  # Fallback directory
        os.makedirs(current_log_dir, exist_ok=True)
        
        log_file = os.path.join(current_log_dir, "loadbalancer_stdout.log")
        super().__init__(log_file, "loadbalancer", node_id)


@contextmanager
def experiment_logging(logger: ExperimentLogger):
    """Context manager for experiment logging"""
    logger.start_logging()
    try:
        yield logger
    finally:
        logger.stop_logging()


# Global scheduler logger instance
_scheduler_logger = None

def setup_scheduler_logging():
    """Setup logging for the Django scheduler"""
    global _scheduler_logger
    
    if not settings.EXPERIMENT_MODE or not settings.EXPERIMENT_STDOUT_LOGGING:
        return None
    
    try:
        # Get current log directory (may be algorithm-specific)
        if hasattr(settings, 'get_experiment_logs_dir'):
            current_log_dir = settings.get_experiment_logs_dir()
        else:
            print("ERROR: get_experiment_logs_dir function not available in settings")
            return None
        
        # Ensure log directory exists with proper permissions
        try:
            os.makedirs(current_log_dir, exist_ok=True)
            # Set permissions to allow read/write
            os.chmod(current_log_dir, 0o755)
        except PermissionError:
            print(f"WARNING: Unable to create log directory {current_log_dir}. Check permissions.")
            return None
        except Exception as e:
            print(f"ERROR creating log directory: {e}")
            return None
    
        # Create new logger if needed or if directory changed
        if _scheduler_logger is None or _scheduler_logger.log_file_path != os.path.join(current_log_dir, 'scheduler_stdout.log'):
            # Stop existing logger if any
            if _scheduler_logger:
                _scheduler_logger.stop_logging()
            
            # Create new logger with current directory
            _scheduler_logger = SchedulerLogger()
            _scheduler_logger.log_file_path = os.path.join(current_log_dir, 'scheduler_stdout.log')
        
        return _scheduler_logger
        
    except AttributeError as e:
        print(f"ERROR: Unable to access experiment logging settings. Details: {e}")
        print("Ensure that get_experiment_logs_dir() is correctly defined in settings.py")
        return None
    except Exception as e:
        print(f"Unexpected error in setup_scheduler_logging: {e}")
        return None

def cleanup_scheduler_logging():
    """Cleanup scheduler logging"""
    global _scheduler_logger
    
    if _scheduler_logger:
        _scheduler_logger.stop_logging()
        _scheduler_logger = None

def get_scheduler_logger():
    """Get the current scheduler logger"""
    return _scheduler_logger

# Provider logging helpers
def create_provider_logger(provider_id: str):
    """Create a provider logger"""
    return ProviderLogger(provider_id)

def create_loadbalancer_logger():
    """Create a load balancer logger"""
    return LoadBalancerLogger() 