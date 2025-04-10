#!/usr/bin/env python3
import docker
import requests
import time
import concurrent.futures
import json
import os
import sys



# Mock dependencies that might not be needed for basic debugging
class MockImagePuller:
    def request_image(self, image_name):
        print(f"Pulling image: {image_name}")
        return image_name

def get_payload(benchmark_no, size):
    # For benchmark 120, return the specific payload
    if benchmark_no == '120':
        return {
            'object': {
                'url': 'https://github.com/STEllAR-GROUP/hpx/archive/refs/tags/1.4.0.zip'
            },
            'bucket': {
                'bucket': 'peercomputebucket2',
                'output': 'output'
            }
        }
    # Default fallback for other benchmarks
    return {"test": f"benchmark-{benchmark_no}", "size": size}

def monitor_container(container, start_time, timeout):
    """Monitor container stats"""
    stats = []
    try:
        for stat in container.stats(stream=True, decode=True):
            stats.append(stat)
            elapsed = int((time.time() - start_time) * 1000)
            if elapsed > timeout:
                break
    except Exception as e:
        print(f"Error monitoring container: {e}")
    return stats

def append_data_to_file(data, filename):
    # For debugging, just print the data
    print(f"Would write to {filename}: {data}")

def debug_container_logs(container):
    """Print container logs to help debug connection issues"""
    try:
        logs = container.logs().decode('utf-8')
        print("\n---- CONTAINER LOGS ----")
        print(logs)
        print("------------------------\n")
    except Exception as e:
        print(f"Error getting logs: {e}")

def run_test(image_name, with_aws=True):
    """Run a test with the specified image"""
    client = docker.from_env()
    imagePuller = MockImagePuller()
    container_name = f"debug-container-{int(time.time())}"
    cpu_efficiency_score = 0.5  # Mock value
    memory_efficiency_score = 0.5  # Mock value
    
    print(f"\n[TEST] Running with image: {image_name}")
    
    # The actual function with more debugging
    print("[run_and_invoke_docker]")
    
    start_pull_time = time.time()
    print(f"Pulling image: {image_name}")
    image = imagePuller.request_image(image_name)
    pull_time = int((time.time() - start_pull_time) * 1000)
    
    start_run_time = time.time()
    cont = None
    benchmark_no = image_name.split("/")[1].split(".")[1] if '/' in image_name and '.' in image_name else "001"
    payload = get_payload(benchmark_no, "small")
    print(f"Using payload: {payload}")
    
    response = None
    future = None
    
    try:
        print("Starting container...")
        
        # Environment variables - use empty values for debugging if not testing AWS
        env_vars = {}
        if with_aws:
            env_vars = {
                'AWS_ACCESS_KEY_ID': 'AKIA3KAG6W36BSXOEHWD',
                'AWS_SECRET_ACCESS_KEY': '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',
                'AWS_REGION': 'ap-south-1'
            }
        
        cont = client.containers.run(
            image,
            name=container_name,
            detach=True,
            ports={'8080/tcp': None},
            environment=env_vars
        )
        
        print(f"Container started: {cont.id} ({cont.name})")
        print("Waiting for container to initialize...")
        time.sleep(5)  # Give more time for initialization
        
        cont.reload()
        port_info = cont.ports.get('8080/tcp')
        if not port_info:
            print("ERROR: Container did not expose port 8080!")
            debug_container_logs(cont)
            return
            
        host_port = port_info[0]['HostPort']
        print(f"Container exposed port: {host_port}")
        
        print("Monitoring container...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(monitor_container, cont, start_run_time, 10000)
            
            print(f"Sending POST request to http://localhost:{host_port}...")
            try:
                # Print the request payload
                print(f"POST request payload: {json.dumps(payload, indent=2)}")
                
                # Increase timeout and add verbose error handling
                response = requests.post(
                    f'http://localhost:{host_port}', 
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=60
                )
                
                print(f"Response status: {response.status_code}")
                print(f"Response content: {response.text[:500]}...")  # Show first 500 chars
                
                try:
                    result = response.json()
                    print(f"JSON result: {json.dumps(result, indent=2)}")
                except:
                    print("Response was not valid JSON")
                    
            except requests.exceptions.Timeout:
                print("ERROR: Request timed out")
                debug_container_logs(cont)
            except requests.exceptions.ConnectionError as ce:
                print(f"ERROR: Connection error: {ce}")
                debug_container_logs(cont)
            except Exception as e:
                print(f"ERROR: Request failed: {e}")
                debug_container_logs(cont)
        
    except Exception as e:
        print(f"ERROR during container execution: {e}")
    
    finally:
        # Get stats if available
        if future and future.done():
            try:
                stack = future.result()
                if stack and len(stack) > 0:
                    print("\n---- CONTAINER STATS SUMMARY ----")
                    print(f"Memory usage: {stack[0].get('memory_stats', {}).get('usage', 'N/A')}")
                    print(f"CPU usage: {stack[0].get('cpu_stats', {}).get('cpu_usage', {}).get('total_usage', 'N/A')}")
                    print("--------------------------------\n")
            except Exception as e:
                print(f"Error getting stats: {e}")
        
        run_time = int((time.time() - start_run_time) * 1000)
        print(f"Total runtime: {run_time}ms")
        
        # Clean up
        if cont:
            try:
                print("Stopping container...")
                cont.stop(timeout=5)
                cont.remove()
            except Exception as e:
                print(f"Error stopping container: {e}")
                
    return

if __name__ == "__main__":
    # Test with a container that uses AWS S3
    if len(sys.argv) > 1:
        image_name = sys.argv[1]
    else:
        image_name = "peercompute/benchmark.120.uploader.python-3.9"  # Replace with your AWS S3-dependent image
    
    run_test(image_name, with_aws=True)
    
    # You could also run a test without AWS credentials for comparison
    # run_test(image_name, with_aws=False)
