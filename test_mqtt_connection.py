#!/usr/bin/env python3
"""
MQTT Connection Test Script
This script helps verify MQTT connectivity between scheduler and provider
"""

import paho.mqtt.client as mqtt
import json
import time
import sys

# Configuration
BROKER_ID = "broker.hivemq.com"
BROKER_PORT = 1883

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✅ Connected to MQTT broker successfully")
    else:
        print(f"❌ Failed to connect to MQTT broker. Code: {rc}")

def on_message(client, userdata, msg):
    print(f"📨 Message received:")
    print(f"   Topic: {msg.topic}")
    print(f"   Payload: {msg.payload.decode('utf-8')}")
    print(f"   Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 50)

def on_subscribe(client, userdata, mid, qos, properties=None):
    print(f"✅ Subscribed to topic successfully")

def test_mqtt_subscription(provider_id):
    """Test subscribing to a provider's topic"""
    print(f"🔍 Testing MQTT subscription for provider: {provider_id}")
    
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe = on_subscribe
    
    try:
        client.connect(BROKER_ID, BROKER_PORT, 60)
        client.subscribe(provider_id, qos=2)
        print(f"👂 Listening for messages on topic: {provider_id}")
        print("Press Ctrl+C to stop...")
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n🛑 Stopping MQTT test...")
        client.disconnect()
    except Exception as e:
        print(f"❌ Error: {e}")

def test_mqtt_publish(provider_id, test_message):
    """Test publishing a message to a provider's topic"""
    print(f"📤 Testing MQTT publish to provider: {provider_id}")
    
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    
    try:
        client.connect(BROKER_ID, BROKER_PORT, 60)
        client.loop_start()
        
        # Wait for connection
        time.sleep(1)
        
        # Publish test message
        client.publish(provider_id, test_message, qos=2)
        print(f"✅ Test message published to {provider_id}")
        print(f"   Message: {test_message}")
        
        time.sleep(2)  # Wait for message to be sent
        client.loop_stop()
        client.disconnect()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_mqtt_connection.py subscribe <provider_id>")
        print("  python test_mqtt_connection.py publish <provider_id> <message>")
        print("\nExample:")
        print("  python test_mqtt_connection.py subscribe provider123")
        print("  python test_mqtt_connection.py publish provider123 'Hello from test'")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "subscribe":
        if len(sys.argv) < 3:
            print("❌ Please provide provider_id for subscription test")
            sys.exit(1)
        provider_id = sys.argv[2]
        test_mqtt_subscription(provider_id)
        
    elif command == "publish":
        if len(sys.argv) < 4:
            print("❌ Please provide provider_id and message for publish test")
            sys.exit(1)
        provider_id = sys.argv[2]
        message = sys.argv[3]
        test_mqtt_publish(provider_id, message)
        
    else:
        print(f"❌ Unknown command: {command}")
        sys.exit(1)
