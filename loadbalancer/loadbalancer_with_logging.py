#!/usr/bin/env python3
"""
Experiment Logging Utility

This script provides centralized functionality for experiment logging.
It allows one component to act as a "leader" to establish a shared
logging directory for an experiment run, and other components to "follow".
Coordination is done via MQTT.
"""

import sys
import os
from datetime import datetime
import uuid
import time
import paho.mqtt.client as mqtt


# --- Configuration ---
BROKER_ID = "broker.hivemq.com"
CONTROL_TOPIC = "experiment/control"


# --- Core Functions ---

def get_experiment_log_dir(is_leader=False, timeout=5):
    """
    Gets the shared experiment log directory via MQTT.

    If is_leader, it creates a new directory and broadcasts its path.
    If not is_leader, it listens for the path from the leader.

    Args:
        is_leader (bool): Whether this component is the leader.
        timeout (int): Seconds to wait for a message if not a leader.

    Returns:
        str: The path to the experiment log directory.
    """
    # Environment variable override takes precedence
    if 'EXPERIMENT_LOG_DIR' in os.environ:
        log_dir = os.environ['EXPERIMENT_LOG_DIR']
        os.makedirs(log_dir, exist_ok=True)
        return log_dir

    # Determine base directory for experiment logs
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs_base_dir = os.path.join(base_dir, 'experiment_logs')
    os.makedirs(logs_base_dir, exist_ok=True)

    if is_leader:
        # Leader creates a new directory and broadcasts the path
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        unique_id = str(uuid.uuid4())[:8]  # Short UUID for uniqueness
        experiment_id = f"{timestamp}_{unique_id}"
        log_dir = os.path.join(logs_base_dir, experiment_id)
        os.makedirs(log_dir, exist_ok=True)
        
        print(f"Acting as experiment leader. Broadcasting log directory: {log_dir}")

        try:
            # Publish the directory path for followers
            client = mqtt.Client()
            client.connect(BROKER_ID, 1883, 60)
            # Retain the message so late-joining followers can receive it
            client.publish(CONTROL_TOPIC, payload=log_dir, qos=1, retain=True)
            client.disconnect()
        except Exception as e:
            print(f"Warning: Could not broadcast log directory via MQTT: {e}")
        
        return log_dir

    else:  # Follower logic
        log_dir_holder = {'path': None}
        
        def on_connect(client, userdata, flags, rc, props=None):
            if rc == 0:
                client.subscribe(CONTROL_TOPIC)
        
        def on_message(client, userdata, msg):
            # Store the received path and stop the client
            log_dir_holder['path'] = msg.payload.decode('utf-8')
            client.disconnect()

        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_message = on_message
        
        try:
            client.connect(BROKER_ID, 1883, 60)
            client.loop_start()
            
            print(f"Waiting for experiment log directory on '{CONTROL_TOPIC}'...")
            start_time = time.time()
            while time.time() - start_time < timeout:
                if log_dir_holder['path'] is not None:
                    break
                time.sleep(0.1)
            
            client.loop_stop()
        except Exception as e:
            print(f"Warning: Could not connect to MQTT to get log directory: {e}")

        if log_dir_holder['path']:
            print(f"Received log directory: {log_dir_holder['path']}")
            return log_dir_holder['path']
        else:
            # Fallback if no message is received
            print("Timeout: No experiment directory received. Creating a local one.")
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            log_dir = os.path.join(logs_base_dir, f"{timestamp}_no_leader")
            os.makedirs(log_dir, exist_ok=True)
            return log_dir


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

# This function is deprecated but kept for compatibility
def setup_logging_paths():
    """Setup logging paths (now handled by get_experiment_log_dir)"""
    return get_experiment_log_dir(is_leader=True)


class ExperimentLogger:
    """Simple logger for capturing component stdout/stderr to a file."""
    
    def __init__(self, logs_dir, log_filename):
        self.log_file_path = os.path.join(logs_dir, log_filename)
        self.log_file = None
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
    def start_logging(self):
        """Start capturing stdout/stderr"""
        self.log_file = open(self.log_file_path, 'a', encoding='utf-8')
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        start_msg = f"[{timestamp}] [SYSTEM] === LOGGING SESSION START ===\n"
        self.log_file.write(start_msg)
        self.log_file.flush()
        
        sys.stdout = self._LogWriter(self, "stdout")
        sys.stderr = self._LogWriter(self, "stderr")
        
        print(f"Experiment logging started. Outputting to: {self.log_file_path}")
    
    def stop_logging(self):
        """Stop logging and restore original streams"""
        if self.log_file:
            print("Experiment logging stopped.")
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            end_msg = f"[{timestamp}] [SYSTEM] === LOGGING SESSION END ===\n"
            
            # Temporarily restore original stdout to write final message
            original_stdout = self.original_stdout
            sys.stdout = original_stdout
            
            self.log_file.write(end_msg)
            self.log_file.flush()
            
            sys.stderr = self.original_stderr
            self.log_file.close()
            self.log_file = None
    
    def write_message(self, message, stream_type="stdout"):
        """Write message to the log file and the original stream."""
        if self.log_file and message.strip():
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            # Generic log format without component name
            formatted_msg = f"[{timestamp}] [{stream_type.upper()}] {message}\n"
            self.log_file.write(formatted_msg)
            self.log_file.flush()
            
            original_stream = self.original_stdout if stream_type == "stdout" else self.original_stderr
            original_stream.write(message + '\n')
            original_stream.flush()
    
    class _LogWriter:
        """Custom writer that logs to file and original stream."""
        
        def __init__(self, logger, stream_type):
            self.logger = logger
            self.stream_type = stream_type
        
        def write(self, message):
            if message.strip():
                self.logger.write_message(message.rstrip('\n'), self.stream_type)
        
        def flush(self):
            if self.logger.log_file:
                self.logger.log_file.flush()

        def isatty(self):
            # Uvicorn's logger checks for this. Returning False is safe.
            return False


def main():
    """Main function to run the load balancer with coordinated logging."""
    experiment_mode = check_experiment_mode()
    
    logger = None
    if experiment_mode:
        # The load balancer acts as the experiment leader to set the log directory
        logs_dir = get_experiment_log_dir(is_leader=True)
        logger = ExperimentLogger(logs_dir, "lb_stdout.log")
        logger.start_logging()
    
    try:
        print(f"Starting loadbalancer with experiment logging: {experiment_mode}")
        
        import loadbalancer
        import uvicorn
        
        uvicorn.run(
            loadbalancer.app,
            host="0.0.0.0",
            port=9001,
            log_level="info"
        )
        
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