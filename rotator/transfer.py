from fabric import Connection, transfer
import time 
from multiprocessing import Process

def start_server(ip):
    c = Connection (host=ip, port=222, user="user", connect_kwargs={'password': 'user123'})
    try:
        local_path = "/home/user/Documents/Serverless_Scheduler/test.txt"
        remote_path = "/home/user/Documents/Serverless_Scheduler/test.txt"

        # Create an SCP transfer object
        transfer = transfer(c)

        # Use the SCP transfer object to upload the file to the remote server
        transfer.put(local=local_path, remote=remote_path)
    except Exception as e:
        print(f"Error in copying the file from {ip}: {str(e)}")
    try:
        print("Starting ",ip)
        c.run("/home/user/Documents/Serverless_Scheduler/script.sh")
    except Exception as e:
        print(f"Error starting server on {ip}: {str(e)}")
    
def stop_server(ip):
    c = Connection (host=ip, port=222, user="user", connect_kwargs={'password': 'user123'})
    try:
        c.run('fuser -k 8000/tcp')
    except Exception as e:
        print(f"Error stopping server on {ip}: {str(e)}")

def round_robin():
    ips = ['10.8.1.46', '10.8.1.48', '10.8.1.45', '10.8.1.44']
  
    while True:
        for ip in ips:            
            p = Process(target=start_server, args=(ip,))
            p.start()
            print("Going to sleep")
            time.sleep(10) 
            print("Stoping ",ip)
            stop_server(ip)
                        

round_robin()
