from threading import Thread
import zmq
import sys
import requests
import json
import time
import docker
import math

user_id = sys.argv[1]
controller_ip = "10.8.1.46"
controller_port = "8000"

client = docker.from_env()
container_name = ""

# REGISTER_URL = 'https://' + controller_ip + ":" + controller_port + "/profiles/register_user/"
ACK_URL = "http://" + controller_ip + ":" + controller_port + "/providers/job_ack/"
NOT_READY_URL = "http://" + controller_ip + ":" + controller_port + "/providers/not_ready/"
READY_URL = "http://" + controller_ip + ":" + controller_port + "/providers/ready/"


# def create_thread_and_subscribe(user_id):
#     provider_thread = Thread(target= thread_target, args= (controller_ip,controller_port,user_id))
#     provider_thread.start()
#     provider_thread.join()
    
# def thread_target(client_ip,client_port,user_id):
#     while True:
#         try:
#             ctx = zmq.Context()
#             socket = ctx.socket(zmq.SUB)
#             socket.connect(f"tcp://{client_ip}:{client_port}")
#             socket.setsockopt_string(zmq.SUBSCRIBE, str(user_id))
#             print("Connected to socket.")
#             break  # Exit the loop if connection is successful

#         except zmq.error.ZMQError as e:
#             print(f"Connection attempt failed: {e}")
#             time.sleep(5)  # Wait for 5 seconds before retrying

def run_docker(body):
    start_pull_time = time.time()
    image = client.images.pull(body)
    print("Pull done!")
    pull_time = int((time.time() - start_pull_time) *1000)

    start_run_time = time.time()
    result = client.containers.run(body, name=container_name)
    result = result.decode("utf-8")
    print("Run done!")

    print(result)
    run_time = int((time.time() - start_run_time)*1000)
    return result, pull_time, run_time

def delete_container_and_image(body):

    filters = {'name': container_name}
    container_id = client.containers.list(all=True, filters=filters)[0]
    container_id.remove()

    client.images.remove(body)

def on_request(json_data) :
    requests.get(url=ACK_URL + str(json_data['job_id']))
    requests.get(url=NOT_READY_URL + user_id)
    container_name = str(json_data['job_id']) + "_container"
    r, pull_time, run_time = run_docker(json_data['task_link'])
    total_time = math.ceil(((pull_time + run_time)/100.0))*100
    print(pull_time, run_time, total_time)
    delete_container_and_image(json_data['task_link'])
    return {'Result': r, 'pull_time': pull_time, 'run_time': run_time, 'total_time': total_time}

data = {
    "is_provider": True,
    "is_developer": False,
    "active": True,
    "ready": True,
    "location": "TEST_PROV_1",
    "ram": 8,
    "cpu": 4
}

# response = requests.POST(url=REGISTER_URL, data=data)
# user_id = response['user_id']

# create_thread_and_subscribe(user_id)

context = zmq.Context()
socket = context.socket(zmq.ROUTER)
socket.setsockopt(zmq.IDENTITY, user_id.encode("utf-8"))
socket.connect("tcp://" + controller_ip + ":5555")
# socket.setsockopt_string(zmq.SUBSCRIBE, user_id)

while True:
        identity, _, json_data = socket.recv_multipart()
        data = json.loads(json_data.decode("utf-8"))
        
        print(f"Received identity: {identity.decode('utf-8')}")
        print(f"Received data: {data}")

        response = on_request(data)
        socket.send_multipart([identity, json.dumps(response).encode("utf-8")])

        requests.get(url=READY_URL+user_id)
