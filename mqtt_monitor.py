#!/usr/bin/env python3
"""
MQTT Message Monitor

A comprehensive tool to monitor all MQTT messages in the serverless scheduler system.
Subscribes to all topics and displays messages in real-time.

Usage:
    python mqtt_monitor.py                    # Monitor for 60 seconds
    python mqtt_monitor.py --duration 300     # Monitor for 5 minutes
    python mqtt_monitor.py --topics EVERYONE SCHEDULER_ANNOUNCEMENTS  # Specific topics
    python mqtt_monitor.py --all              # Monitor all topics (use # wildcard)
"""

import paho.mqtt.client as mqtt
import json
import time
import argparse
import sys
from datetime import datetime
from collections import defaultdict

# Global variables
received_messages = []
message_counts = defaultdict(int)
topic_messages = defaultdict(list)

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def colorize(text, color):
    """Add color to text if terminal supports it"""
    if sys.stdout.isatty():
        return f"{color}{text}{Colors.ENDC}"
    return text

def on_connect(client, userdata, flags, rc, properties=None):
    """Callback when MQTT client connects"""
    if rc == 0:
        print(colorize("✓ Connected to MQTT broker successfully", Colors.GREEN))
        print(f"  Broker: broker.hivemq.com:1883")
    else:
        print(colorize(f"✗ Failed to connect to MQTT broker. Code: {rc}", Colors.RED))
        sys.exit(1)

def on_message(client, userdata, msg):
    """Callback when MQTT message is received"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    topic = msg.topic
    
    try:
        payload = msg.payload.decode('utf-8')
    except UnicodeDecodeError:
        payload = f"<binary data: {len(msg.payload)} bytes>"
    
    # Store message
    message_info = {
        'timestamp': timestamp,
        'topic': topic,
        'payload': payload,
        'qos': msg.qos,
        'retain': msg.retain
    }
    received_messages.append(message_info)
    message_counts[topic] += 1
    topic_messages[topic].append(message_info)
    
    # Determine message type for color coding
    if topic == "SCHEDULER_ANNOUNCEMENTS":
        color = Colors.CYAN
        prefix = "[SCHEDULER DISCOVERY]"
    elif topic == "EVERYONE":
        color = Colors.YELLOW
        prefix = "[BROADCAST]"
    elif topic == "ROTATION":
        color = Colors.BLUE
        prefix = "[ILP ROTATION]"
    elif topic.startswith("SCHEDULER_"):
        color = Colors.GREEN
        prefix = "[SCHEDULER]"
    elif topic.startswith("LOADBALANCER_"):
        color = Colors.YELLOW
        prefix = "[LOAD BALANCER]"
    else:
        # Likely a provider topic (user_id)
        color = Colors.CYAN
        prefix = "[PROVIDER]"
    
    # Print message
    print(f"\n{colorize(prefix, color)} {colorize(timestamp, Colors.HEADER)}")
    print(f"  Topic: {colorize(topic, Colors.BOLD)}")
    
    # Try to pretty-print JSON payloads
    try:
        payload_json = json.loads(payload)
        print(f"  Payload (JSON):")
        print(f"    {json.dumps(payload_json, indent=4)}")
    except (json.JSONDecodeError, ValueError):
        # Not JSON, print as string
        if len(payload) > 200:
            print(f"  Payload: {payload[:200]}... ({len(payload)} chars)")
        else:
            print(f"  Payload: {payload}")
    
    print(f"  QoS: {msg.qos}, Retain: {msg.retain}")
    print("-" * 80)

def on_subscribe(client, userdata, mid, granted_qos, properties=None):
    """Callback when subscription is confirmed"""
    print(colorize(f"✓ Subscription confirmed (QoS: {granted_qos})", Colors.GREEN))

def print_summary():
    """Print summary of all messages received"""
    print("\n" + "=" * 80)
    print(colorize("MQTT MESSAGE SUMMARY", Colors.BOLD))
    print("=" * 80)
    
    print(f"\nTotal messages received: {colorize(str(len(received_messages)), Colors.BOLD)}")
    print(f"Unique topics: {len(message_counts)}")
    
    if message_counts:
        print(f"\n{colorize('Messages per topic:', Colors.BOLD)}")
        for topic, count in sorted(message_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {topic}: {count}")
    
    # Show recent messages by category
    print(f"\n{colorize('Recent Messages by Category:', Colors.BOLD)}")
    
    scheduler_msgs = [m for m in received_messages if m['topic'].startswith('SCHEDULER_')]
    if scheduler_msgs:
        print(f"\n  Scheduler Messages ({len(scheduler_msgs)}):")
        for msg in scheduler_msgs[-3:]:  # Last 3
            print(f"    [{msg['timestamp']}] {msg['topic']}: {msg['payload'][:50]}...")
    
    provider_msgs = [m for m in received_messages if not any(m['topic'].startswith(prefix) 
                     for prefix in ['SCHEDULER_', 'LOADBALANCER_', 'EVERYONE', 'ROTATION'])]
    if provider_msgs:
        print(f"\n  Provider Messages ({len(provider_msgs)}):")
        for msg in provider_msgs[-3:]:  # Last 3
            print(f"    [{msg['timestamp']}] {msg['topic']}: {msg['payload'][:50]}...")
    
    broadcast_msgs = [m for m in received_messages if m['topic'] == 'EVERYONE']
    if broadcast_msgs:
        print(f"\n  Broadcast Messages ({len(broadcast_msgs)}):")
        for msg in broadcast_msgs[-3:]:  # Last 3
            print(f"    [{msg['timestamp']}]: {msg['payload'][:50]}...")

def main():
    parser = argparse.ArgumentParser(description='Monitor MQTT messages in serverless scheduler system')
    parser.add_argument('--broker', default='broker.hivemq.com', help='MQTT broker hostname')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--duration', type=int, default=60, help='Monitoring duration in seconds (0 = infinite)')
    parser.add_argument('--topics', nargs='+', help='Specific topics to subscribe to')
    parser.add_argument('--all', action='store_true', help='Subscribe to all topics using # wildcard')
    parser.add_argument('--quiet', action='store_true', help='Only show summary, not individual messages')
    
    args = parser.parse_args()
    
    print(colorize("MQTT Message Monitor", Colors.BOLD))
    print("=" * 80)
    print(f"Broker: {args.broker}:{args.port}")
    
    if args.all:
        topics = ["#"]  # Subscribe to everything
        print("Subscribing to: ALL TOPICS (#)")
    elif args.topics:
        topics = args.topics
        print(f"Subscribing to: {', '.join(topics)}")
    else:
        # Default: subscribe to all system topics
        topics = [
            "EVERYONE",
            "ROTATION",
            "SCHEDULER_ANNOUNCEMENTS",
            "SCHEDULER_+",  # All scheduler topics
            "LOADBALANCER_+",  # All load balancer topics
            "+",  # All single-level topics (provider user_ids)
        ]
        print("Subscribing to: System topics (EVERYONE, ROTATION, SCHEDULER_*, etc.)")
        print("  (Use --all to subscribe to ALL topics including nested ones)")
    
    if args.duration > 0:
        print(f"Duration: {args.duration} seconds")
    else:
        print("Duration: Infinite (press Ctrl+C to stop)")
    
    print("=" * 80)
    print()
    
    # Create MQTT client
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe = on_subscribe
    
    try:
        # Connect to broker
        print(f"Connecting to {args.broker}:{args.port}...")
        client.connect(args.broker, args.port, 60)
        
        # Start the loop
        client.loop_start()
        
        # Wait a moment for connection
        time.sleep(1)
        
        # Subscribe to topics
        for topic in topics:
            client.subscribe(topic, qos=0)
            if not args.quiet:
                print(f"Subscribed to: {topic}")
        
        if args.quiet:
            print("Monitoring (quiet mode - summary will be shown at the end)...")
        else:
            print("\n" + colorize("Monitoring MQTT messages...", Colors.GREEN))
            print("Press Ctrl+C to stop\n")
        
        # Monitor for specified duration
        if args.duration > 0:
            time.sleep(args.duration)
        else:
            # Infinite monitoring
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n" + colorize("Stopped by user", Colors.YELLOW))
        
    except KeyboardInterrupt:
        print("\n" + colorize("Stopped by user", Colors.YELLOW))
    except Exception as e:
        print(colorize(f"Error: {e}", Colors.RED))
        import traceback
        traceback.print_exc()
    finally:
        client.loop_stop()
        client.disconnect()
        print(colorize("\nDisconnected from MQTT broker", Colors.YELLOW))
        
        # Print summary
        print_summary()

if __name__ == "__main__":
    main()

