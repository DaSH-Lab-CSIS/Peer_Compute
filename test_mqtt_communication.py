#!/usr/bin/env python3
"""
Test script to diagnose MQTT communication between scheduler and load balancer
"""

import paho.mqtt.client as mqtt
import json
import time
import threading
from datetime import datetime

# Global variables to track messages
received_messages = []
scheduler_announcements = []
heartbeats = []

def on_connect(client, userdata, flags, rc):
    print(f"[TEST] Connected to MQTT broker with result code {rc}")
    if rc == 0:
        # Subscribe to all relevant topics
        client.subscribe("SCHEDULER_ANNOUNCEMENTS")
        client.subscribe("EVERYONE")
        client.subscribe("LOADBALANCER_*")
        client.subscribe("SCHEDULER_*")
        print("[TEST] Subscribed to all relevant topics")
    else:
        print(f"[TEST] Failed to connect to MQTT broker")

def on_message(client, userdata, msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    topic = msg.topic
    payload = msg.payload.decode('utf-8')
    
    print(f"[TEST] {timestamp} - Topic: {topic}")
    print(f"[TEST] Payload: {payload}")
    print("-" * 50)
    
    # Store message for analysis
    message_info = {
        'timestamp': timestamp,
        'topic': topic,
        'payload': payload
    }
    received_messages.append(message_info)
    
    # Categorize messages
    if topic == "SCHEDULER_ANNOUNCEMENTS":
        try:
            announcement = json.loads(payload)
            scheduler_announcements.append(announcement)
            print(f"[TEST] SCHEDULER ANNOUNCEMENT: {announcement}")
        except:
            print(f"[TEST] Invalid JSON in scheduler announcement")
    
    elif payload.startswith("SCHEDULER_PONG:"):
        try:
            heartbeat_data = json.loads(payload[15:])
            heartbeats.append(heartbeat_data)
            print(f"[TEST] HEARTBEAT: {heartbeat_data}")
        except:
            print(f"[TEST] Invalid JSON in heartbeat")

def on_subscribe(client, userdata, mid, granted_qos):
    print(f"[TEST] Subscribed to topic with QoS {granted_qos}")

def analyze_results():
    print("\n" + "="*60)
    print("MQTT COMMUNICATION ANALYSIS")
    print("="*60)
    
    print(f"\nTotal messages received: {len(received_messages)}")
    print(f"Scheduler announcements: {len(scheduler_announcements)}")
    print(f"Heartbeats: {len(heartbeats)}")
    
    if scheduler_announcements:
        print(f"\nScheduler Announcements:")
        for i, announcement in enumerate(scheduler_announcements):
            print(f"  {i+1}. UUID: {announcement.get('scheduler_uuid', 'N/A')}")
            print(f"     Topic: {announcement.get('scheduler_topic', 'N/A')}")
            print(f"     Status: {announcement.get('status', 'N/A')}")
    else:
        print(f"\n❌ NO SCHEDULER ANNOUNCEMENTS RECEIVED!")
        print("   This means the scheduler is not announcing itself to the load balancer")
    
    if heartbeats:
        print(f"\nRecent Heartbeats:")
        for i, heartbeat in enumerate(heartbeats[-5:]):  # Show last 5
            print(f"  {i+1}. UUID: {heartbeat.get('scheduler_uuid', 'N/A')}")
            print(f"     Timestamp: {heartbeat.get('timestamp', 'N/A')}")
            print(f"     Status: {heartbeat.get('status', 'N/A')}")
    else:
        print(f"\n❌ NO HEARTBEATS RECEIVED!")
        print("   This means the scheduler is not sending heartbeats")
    
    # Check for specific topics
    topics_seen = set(msg['topic'] for msg in received_messages)
    print(f"\nTopics seen: {sorted(topics_seen)}")
    
    # Check for load balancer topics
    lb_topics = [topic for topic in topics_seen if topic.startswith('LOADBALANCER_')]
    if lb_topics:
        print(f"Load balancer topics: {lb_topics}")
    else:
        print("❌ No load balancer topics seen")
    
    # Check for scheduler topics
    scheduler_topics = [topic for topic in topics_seen if topic.startswith('SCHEDULER_')]
    if scheduler_topics:
        print(f"Scheduler topics: {scheduler_topics}")
    else:
        print("❌ No scheduler topics seen")

def main():
    print("MQTT Communication Test Script")
    print("="*40)
    print("This script will monitor MQTT messages for 30 seconds")
    print("to diagnose communication issues between scheduler and load balancer")
    print()
    
    # Create MQTT client
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe = on_subscribe
    
    try:
        # Connect to MQTT broker
        print("[TEST] Connecting to MQTT broker...")
        client.connect("broker.hivemq.com", 1883, 60)
        
        # Start the loop in a separate thread
        client.loop_start()
        
        print("[TEST] Monitoring MQTT messages for 30 seconds...")
        print("[TEST] Press Ctrl+C to stop early")
        
        # Monitor for 30 seconds
        time.sleep(30)
        
    except KeyboardInterrupt:
        print("\n[TEST] Stopped by user")
    except Exception as e:
        print(f"[TEST] Error: {e}")
    finally:
        client.loop_stop()
        client.disconnect()
        print("[TEST] Disconnected from MQTT broker")
    
    # Analyze results
    analyze_results()

if __name__ == "__main__":
    main()

