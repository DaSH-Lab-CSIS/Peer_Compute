#!/usr/bin/env python3
"""
Quick check to see if scheduler is running and what's happening
"""

import requests
import subprocess
import time

def check_scheduler_process():
    """Check if scheduler process is running"""
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        lines = result.stdout.split('\n')
        scheduler_processes = [line for line in lines if 'python manage.py runserver' in line]
        
        if scheduler_processes:
            print("✅ Scheduler process is running:")
            for proc in scheduler_processes:
                print(f"   {proc}")
            return True
        else:
            print("❌ No scheduler process found")
            return False
    except Exception as e:
        print(f"Error checking processes: {e}")
        return False

def check_scheduler_port():
    """Check if scheduler is listening on port 8000"""
    try:
        response = requests.get("http://localhost:8000", timeout=5)
        print(f"✅ Scheduler responding on port 8000 (status: {response.status_code})")
        return True
    except requests.exceptions.ConnectionError:
        print("❌ Scheduler not responding on port 8000")
        return False
    except Exception as e:
        print(f"Error checking scheduler port: {e}")
        return False

def check_loadbalancer_status():
    """Check load balancer status"""
    try:
        response = requests.get("http://localhost:9001/status", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print("✅ Load balancer status:")
            print(f"   Discovered schedulers: {data.get('discovered_schedulers', 0)}")
            print(f"   Online schedulers: {data.get('online_schedulers', 0)}")
            print(f"   Scheduler order: {data.get('scheduler_order', [])}")
            return data
        else:
            print(f"❌ Load balancer returned status {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error checking load balancer: {e}")
        return None

def main():
    print("SCHEDULER STATUS CHECK")
    print("=" * 30)
    
    # Check if scheduler process is running
    print("\n1. Checking scheduler process...")
    process_running = check_scheduler_process()
    
    # Check if scheduler is responding on port
    print("\n2. Checking scheduler port...")
    port_responding = check_scheduler_port()
    
    # Check load balancer status
    print("\n3. Checking load balancer status...")
    lb_status = check_loadbalancer_status()
    
    # Summary
    print("\n" + "=" * 30)
    print("SUMMARY:")
    print(f"Scheduler process running: {'✅' if process_running else '❌'}")
    print(f"Scheduler port responding: {'✅' if port_responding else '❌'}")
    print(f"Load balancer responding: {'✅' if lb_status else '❌'}")
    
    if lb_status:
        discovered = lb_status.get('discovered_schedulers', 0)
        online = lb_status.get('online_schedulers', 0)
        print(f"Schedulers discovered: {discovered}")
        print(f"Schedulers online: {online}")
        
        if discovered == 0:
            print("\n🔍 DIAGNOSIS: Scheduler is not announcing itself via MQTT")
            print("   - Scheduler process is running")
            print("   - Scheduler HTTP port is responding") 
            print("   - But scheduler is not sending MQTT announcements")
            print("   - This means the scheduler's MQTT connection or announcement code has an issue")
        elif discovered > 0 and online == 0:
            print("\n🔍 DIAGNOSIS: Scheduler announced but not sending heartbeats")
            print("   - Scheduler announced itself initially")
            print("   - But scheduler stopped sending heartbeats")
            print("   - This could be a heartbeat timeout or MQTT connection issue")

if __name__ == "__main__":
    main()

