#!/usr/bin/env python3
"""
Load Balancer with Experiment Logging

This script wraps the standard loadbalancer functionality with experiment logging
capabilities. It captures stdout/stderr to files when experiment mode is enabled.

Usage:
    python loadbalancer_with_logging.py
"""

import sys
import os
from datetime import datetime

def check_experiment_mode():
    """Check if experiment mode is enabled"""
    try:
        # Try to read scheduler settings
        scheduler_settings_path = os.path.join(os.path.dirname(__file__), '..', 'scheduler', 'scheduler', 'settings.py')
        
        if os.path.exists(scheduler_settings_path):
            with open(scheduler_settings_path, 'r') as f:
                content = f.read()
                return 'EXPERIMENT_MODE = True' in content and 'EXPERIMENT_STDOUT_LOGGING = True' in content
        
        # Fallback: check environment variable
        return os.environ.get('EXPERIMENT_MODE', 'False').lower() == 'true'
    except:
        return False

def setup_logging_paths():
    """Setup logging paths based on current algorithm"""
    # Check for algorithm-specific logging
    experiment_algorithm = os.environ.get('EXPERIMENT_ALGORITHM')
    experiment_log_dir = os.environ.get('EXPERIMENT_LOG_DIR')
    
    if experiment_log_dir:
        logs_dir = experiment_log_dir
    elif experiment_algorithm:
        # Create algorithm-specific directory
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        logs_dir = os.path.join(base_dir, 'experiment_logs', timestamp, experiment_algorithm)
    else:
        # Default behavior
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        logs_dir = os.path.join(base_dir, 'experiment_logs', timestamp)
    
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir

class LoadBalancerLogger:
    """Simple logger for loadbalancer stdout/stderr"""
    
    def __init__(self, logs_dir):
        self.log_file_path = os.path.join(logs_dir, "loadbalancer_stdout.log")
        self.log_file = None
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
    def start_logging(self):
        """Start capturing stdout/stderr"""
        self.log_file = open(self.log_file_path, 'a', encoding='utf-8')
        
        # Write session start marker
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        start_msg = f"[{timestamp}] [loadbalancer] [SYSTEM] === EXPERIMENT SESSION START ===\n"
        self.log_file.write(start_msg)
        self.log_file.flush()
        
        # Replace stdout/stderr
        sys.stdout = self._LogWriter(self, "stdout")
        sys.stderr = self._LogWriter(self, "stderr")
        
        print("Experiment logging started for loadbalancer")
    
    def stop_logging(self):
        """Stop logging and restore original streams"""
        if self.log_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            end_msg = f"[{timestamp}] [loadbalancer] [SYSTEM] === EXPERIMENT SESSION END ===\n"
            self.log_file.write(end_msg)
            self.log_file.flush()
            
            # Restore original streams
            sys.stdout = self.original_stdout
            sys.stderr = self.original_stderr
            
            self.log_file.close()
            self.log_file = None
            
            print("Experiment logging stopped for loadbalancer")
    
    def write_message(self, message, stream_type="stdout"):
        """Write message to log file"""
        if self.log_file and message.strip():
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            formatted_msg = f"[{timestamp}] [loadbalancer] [{stream_type.upper()}] {message}\n"
            self.log_file.write(formatted_msg)
            self.log_file.flush()
            
            # Also write to original stream
            original_stream = self.original_stdout if stream_type == "stdout" else self.original_stderr
            original_stream.write(message)
            original_stream.flush()
    
    class _LogWriter:
        """Custom writer that logs to file and original stream"""
        
        def __init__(self, logger, stream_type):
            self.logger = logger
            self.stream_type = stream_type
        
        def write(self, message):
            if message.strip():
                self.logger.write_message(message.rstrip('\n'), self.stream_type)
        
        def flush(self):
            if self.logger.log_file:
                self.logger.log_file.flush()


def main():
    """Main function with logging setup"""
    experiment_mode = check_experiment_mode()
    
    logger = None
    if experiment_mode:
        logs_dir = setup_logging_paths()
        logger = LoadBalancerLogger(logs_dir)
        logger.start_logging()
    
    try:
        print(f"Starting loadbalancer with experiment logging: {experiment_mode}")
        
        # Import and run the original loadbalancer
        import loadbalancer
        
    except KeyboardInterrupt:
        print("\nLoadbalancer shutting down...")
    except Exception as e:
        print(f"Error in loadbalancer: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        if logger:
            logger.stop_logging()


if __name__ == "__main__":
    main() 