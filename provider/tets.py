import docker
import requests
import time

def run_and_invoke_docker(body, container_name, payload) -> dict:
    print("Starting container run...")
    
    # Initialize Docker client
    client = docker.from_env()
    
    # Pull and run container
    try:
        cont = client.containers.run("interfacetestingimage2",
                                   detach=True,
                                   ports={'8080/tcp': None}
                                   )
        
        # Wait for container to start
        print(cont.stats)
        time.sleep(1)
        cont.reload()  # Refresh container data
        port_info = cont.ports.get('8080/tcp')
        host_port = port_info[0]['HostPort']
        print(host_port)
        
        # Make POST request to container
        payload = {"message": "helloworld"}
        response = requests.post(f'http://localhost:{host_port}',
                               json=payload,
                               headers={'Content-Type': 'application/json'})
        
        print("HTTP Response:")
        print(response.json())
        
        # Clean up container
        cont.stop()
        cont.remove()
        
        return response.json()
        
    except Exception as e:
        print(f"Error running container: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    result = run_and_invoke_docker(None, None, None)
    print(f"Final result: {result}")