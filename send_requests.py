import requests
import json
import time

# The list of requests from your curl command
requests_data = [
    {"serviceID": 13, "numberOfInvocations": 5, "chained": False, "input": "None", "runMultipleInvocations": True},
    {"serviceID": 17, "numberOfInvocations": 3, "chained": False, "input": "None", "runMultipleInvocations": True},
    {"serviceID": 18, "numberOfInvocations": 1, "chained": False, "input": "None", "runMultipleInvocations": False},
    {"serviceID": 19, "numberOfInvocations": 4, "chained": False, "input": "None", "runMultipleInvocations": True},
    {"serviceID": 20, "numberOfInvocations": 3, "chained": False, "input": "None", "runMultipleInvocations": True},
    {"serviceID": 21, "numberOfInvocations": 1, "chained": False, "input": "None", "runMultipleInvocations": False},
    {"serviceID": 22, "numberOfInvocations": 1, "chained": False, "input": "None", "runMultipleInvocations": False},
    {"serviceID": 23, "numberOfInvocations": 2, "chained": False, "input": "None", "runMultipleInvocations": True},
    {"serviceID": 24, "numberOfInvocations": 3, "chained": False, "input": "None", "runMultipleInvocations": True},
    {"serviceID": 13, "numberOfInvocations": 2, "chained": False, "input": "None", "runMultipleInvocations": True},
    {"serviceID": 17, "numberOfInvocations": 1, "chained": False, "input": "None", "runMultipleInvocations": False},
    {"serviceID": 18, "numberOfInvocations": 2, "chained": False, "input": "None", "runMultipleInvocations": True},
    {"serviceID": 19, "numberOfInvocations": 1, "chained": False, "input": "None", "runMultipleInvocations": False},
    {"serviceID": 20, "numberOfInvocations": 1, "chained": False, "input": "None", "runMultipleInvocations": False}
]

# Loadbalancer endpoint
url = "http://localhost:9002/loadbalancer/run_service/"

# Headers
headers = {
    "Accept": "*/*",
    "User-Agent": "Thunder Client",
    "Content-Type": "application/json"
}

def send_request(request_data):
    """Send a single request to the loadbalancer"""
    try:
        response = requests.post(url, json=request_data, headers=headers)
        print(f"Service ID {request_data['serviceID']}: Status Code {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending request for Service ID {request_data['serviceID']}: {str(e)}")
        return False

def main():
    print("Starting to send requests...")
    successful = 0
    failed = 0
    
    for i, request_data in enumerate(requests_data, 1):
        print(f"\nSending request {i}/{len(requests_data)}")
        if send_request(request_data):
            successful += 1
        else:
            failed += 1
        
        # Add a small delay between requests to avoid overwhelming the server
        time.sleep(0.5)
    
    print(f"\nSummary:")
    print(f"Total requests: {len(requests_data)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")

if __name__ == "__main__":
    main() 