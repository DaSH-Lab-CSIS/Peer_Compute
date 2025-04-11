from threading import Thread, Event, Lock
import threading

import concurrent
import zmq
import sys
import requests
import json
import time
import asyncio
import docker
import HFRequests
import math
import traceback
import csv
import paho.mqtt.client as mqtt
from time import sleep
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error
import joblib  # Used for model persistence
import pickle
import matplotlib.pyplot as plt
import numpy as np
from hybridcaching import HybridImageManager
import os
import signal
import sys
import tempfile
import socket

user_id = sys.argv[1]
# Add the project root directory to Python's path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Change from relative to absolute import
from invocations.invoker import get_payload

controller_ip = "10.8.1.18" #change to whichever is running django
controller_port = "8000"
# BROKER_ID = "10.8.1.18"
BROKER_ID="broker.hivemq.com"
#uncomment requests.get ACK READY NOT READY
channelName = "mychannel"
chaincodeName = "monitoring"
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE2OTQxMjk2MzcsInVzZXJuYW1lIjoiY29udHJvbGxlciIsIm9yZ05hbWUiOiJPcmcxIiwiaWF0IjoxNjk0MDkzNjM3fQ.DNJZ4kB11PbDB4UO2HaMjwlqxgTbJ8b7JK3WsRzaePY"


# Get the current process ID
pid = os.getpid()

# Print the PID
print(f"PID: {pid}")

client = docker.from_env()
procedural_shutdown_event = Event()
pending_jobs = 0  #despite the name, this is flag indicating whether something is running or not. 
pending_jobs_lock = Lock()
last_message_time = time.time()


# REGISTER_URL = 'https://' + controller_ip + ":" + controller_port + "/profiles/register_user/"
ACK_URL = "http://" + controller_ip + ":" + controller_port + "/providers/job_ack/"
NOT_READY_URL = "http://" + controller_ip + ":" + controller_port + "/providers/not_ready/"
READY_URL = "http://" + controller_ip + ":" + controller_port + "/providers/ready/"

requests.get(url=READY_URL+user_id)
# TODO make a request to ready url as soon as this script has run, ie j write a line here.
runs_list = [] #this stores all data in all runs for a specific job.
# def create_thread_and_subscribe(user_id):
#     provider_thread = Thread(target= thread_target, args= (controller_ip,controller_port,user_id))
#     provider_thread.start()
#     provider_thread.join()
curl_count = 0

cpu_efficiency_score = "DID NOT RECIEVE"
memory_efficiency_score = "DID NOT RECIEVE"

MEMORY_LIMIT = 1200 * 1024 * 1024
DISK_LIMIT = 2000 * 1024 * 1024

imagePuller = HybridImageManager(memory_limit=MEMORY_LIMIT, disk_limit=DISK_LIMIT)
# MQTT

def on_connect(mqtt_client, userdata, flags, rc, callback_api_version):
    if rc == 0:
        print('Connected successfully')
        mqtt_client.subscribe(user_id)
        mqtt_client.subscribe("EVERYONE")
    else:
        print('Bad connection. Code:', rc)

def process_dockernotrun_request(data):
    global pending_jobs
    with pending_jobs_lock:
        pending_jobs += 1
        print(f"Pending jobs incremented: {pending_jobs}")
    
    try: 
        if(data['runMultipleInvocations'] == True):
            if(data['numberOfInvocations'] == 1) :
                on_request(data)
            elif(data['isChained'] == False):
                for i in range(data['numberOfInvocations']):
                    container_name = str(data['job_id']) + "_container_" + str(i)
                    on_request(data)
            else: 
                on_chained_request(data)
        else:
            on_request(data)
    except Exception as e:
        print(str(e))
    finally: 
        with pending_jobs_lock:
            pending_jobs -= 1
            print(f"Pending jobs decremented: {pending_jobs}")

def on_message(mqtt_client, userdata, msg):
    print(f'Received message on topic: {msg.topic} with payload: {msg.payload}')
    global last_message_time
    last_message_time = time.time()

    try: 
        data = json.loads(msg.payload.decode("utf-8"))
        if(data["stage"] == "dockernotrun"):
            data["stage"] = "dockerrunning"
            # Offload heavy processing to a separate thread
            Thread(target=process_dockernotrun_request, args=(data,)).start()
        
    except:
        payload_str = msg.payload.decode("utf-8")
        if(payload_str == "calculate_efficiency"):
            # Offload efficiency calculations to a separate thread
            Thread(target=calc_benchmark_stats).start()
        elif(payload_str.startswith("EfficiencyScoreSet:")):
            scoreset = json.loads(payload_str[19:])
            global cpu_efficiency_score
            cpu_efficiency_score = scoreset['cpu']
            global memory_efficiency_score
            memory_efficiency_score = scoreset['memory']
            print("Fetched this provider's efficiency score set")
            print(cpu_efficiency_score)
            print(memory_efficiency_score)
        elif(payload_str.startswith("ref_run_service_id/")):
            service_id = payload_str[19:]
            # Offload reference stats collection to a separate thread
            Thread(target=set_reference_stats_for_service, args=(service_id,)).start()


def on_subscribe(mqtt_client, userdata, mid, qos, properties=None):
    pass

# tell scheduler that this provider has started. waits for the request to get then proceeds.
requests.get("http://localhost:8000/providers/startup/"+user_id)


mclient = mqtt.Client(callback_api_version= mqtt.CallbackAPIVersion.VERSION2)
# sets up LWT for non-procedural disconnections
LWT_TOPIC = f"{user_id}"
LWT_MESSAGE = "offline_non-procedurally"
mclient.will_set(topic=LWT_TOPIC, payload=LWT_MESSAGE, qos=2, retain=False) 
# make a socket bind to tcp and make a dealer
mclient.on_connect = on_connect
mclient.on_message = on_message
mclient.on_subscribe= on_subscribe

mclient.connect(host=BROKER_ID,port=1883, keepalive=100)
#client subscribe is in on_connect
mclient.loop_start() #different thread

mclient.publish(topic="EVERYONE", payload="start_connect"+user_id, qos=2)
mclient.publish(topic="EVERYONE", payload="get_efficiency_score"+user_id, qos=2)

def procedural_shutdown(sig, frame):
    print("Commencing procedural shutdown...")
    procedural_shutdown_event.set()
    requests.get(url=NOT_READY_URL + user_id) #This should set provider to not ready on scheduler

#This will call the shutdown_handler function when the SIGINT or SIGTERM signal is received from system
signal.signal(signal.SIGINT, procedural_shutdown)   # Ctrl+C induced signal
signal.signal(signal.SIGTERM, procedural_shutdown)  # we may not need to handle this signal    

#LINEAR REGRESSION LOGIC


#making all data into a list...
# Function to append data returned by run_docker() to a file
def append_data_to_file(data, filename):
    with open(filename, 'a') as file:
        file.write(json.dumps(data) + '\n')

def load_data_from_file(filename):
    with open(filename, 'r') as file:
        data = [json.loads(line.strip()) for line in file]
    return data #returns a list

# Function to save the trained model to disk
def save_model(model, filename):
    with open(filename, 'wb') as file:
        pickle.dump(model, file)

# Function to load the trained model from disk
def load_model(filename):
    with open(filename, 'rb') as file:
        model = pickle.load(file)
    return model


def train_regression_model(training_data):
    X = []
    y = []
    for data in training_data:
        X.append([data["cpu_usage"] * data["cpu_efficiency_score"], 
                  data["memory_usage"] * data["memory_efficiency_score"]])
        y.append(data["actual_runtime"])

    model = LinearRegression()
    model.fit(X, y)
    return model

def predict_runtime(service, provider, model):

    ref_service_list = load_data_from_file("TrainingData/Reference_Provider_Data.txt")
    for item in ref_service_list:
        if(item['service']==service):
            reference_cpu_usage=item['cpu_usage']
            reference_memory_usage=item['memory_usage']
            break
    global cpu_efficiency_score, memory_efficiency_score

    # For training in scheduler, instead of globals use provider.cpu_efficiency_score and provider.memory_efficiency_score
    X = np.array([[reference_cpu_usage * cpu_efficiency_score, reference_memory_usage * memory_efficiency_score]])
    return model.predict(X)


def trainAndPredict(run_vars):
    #run_vars has  cpu_usage, memory_usage, actual_runtime (of providers required for training not prediction) they will be loaded from file
    #It also has service (task link) (to get corresponding reference stats), eff_scores for training+prediction the ones which we use in this function
    #TRAINING
    print("running predictions inside trainAndPredict")
    training_data=load_data_from_file("TrainingData/eff_score_data.txt")
    model = train_regression_model(training_data)
    #PREDICTION
    provider_id = 0 # this provider would be used if this training and prediction were to run in the scheduler. Here it is useless as we use globals.
    predicted_runtime = predict_runtime(run_vars['service'], provider_id, model)
    return predicted_runtime[0]


def run_docker(body, container_name, inputData=None):
    start_pull_time = time.time()
    #image = client.images.pull(body)
    print("inside run_docker with body : " + body)
    image = imagePuller.request_image(body)
    print("Out of Hybrid Caching manager and inside run_docker again")
    print(image)
    pull_time = int((time.time() - start_pull_time) *1000)
    
    start_run_time = 0
    cont = None
    if inputData == None:
        # result = client.containers.run(body, name=container_name)
        try:
            cont = client.containers.run(image, name=container_name, detach=True)
        except Exception as e:
            print(e)
            container_name += "t"
            cont = client.containers.run(image, name=container_name, detach=True)
        # cont = client.containers.get(container_name)
        # cont.start()
        
    else:    
        try:
            cont = client.containers.run(image, command=str(inputData), name=container_name, detach=True)
        except Exception as e:
            print(e)
            container_name += "n"
            cont = client.containers.run(image, command=str(inputData), name=container_name, detach=True)
        # cont = client.containers.get(container_name)
        # cont.start()

    start_run_time = time.time()
    result = "this is result" #remove this line uncomment below line
    #result = result.decode("utf-8") #this gives the Hello from Docker msg.
    print("Run Started!")
    print(body)
    timeout = 3000
    stack = []
    run_vars = {}
    #cont = client.containers.get(container_name)
    count = 0
    if(cont==None):print("cont is None")
    while ((cont != None) and ((str(cont.status) == 'running') or (str(cont.status) == 'created'))):
        if(time.time()-start_run_time > timeout):
            print("timeout exceeded (cont not killed)")
            break
        #elapsed_time += stop_time
        s = cont.stats(decode=False, stream=False)
        if(s['memory_stats'] != {}):
            #stack.clear() #to get stats streamed throughout the process remove this line
            stack.clear() #only to save time
            stack.append(s)
        else: break
        count+=1

    #print(stack) #uncomment this to get full stats
    run_time = int((time.time() - start_run_time)*1000)
    #print(count)
    # run_vars['time_indexed_stats'] = time_indexed_stats
    run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
    run_vars['cpu_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
    #adding new lines for io_usage
    # blkio_read=0
    # blkio_write=0
    # for entry in stack[0]['blkio_stats']['io_service_bytes_recursive']:
    #     if entry['op'] == 'Read':
    #         blkio_read += entry['value']
    #     elif entry['op'] == 'Write':
    #         blkio_write += entry['value']
    # run_vars['io_read_stats'] = blkio_read
    # run_vars['io_write_stats'] = blkio_write
    #updated code till here
    run_vars['actual_runtime'] = run_time
    global cpu_efficiency_score
    run_vars['cpu_efficiency_score'] = cpu_efficiency_score
    global memory_efficiency_score
    run_vars['memory_efficiency_score'] = memory_efficiency_score
    # the below is service specific and has to be made for each service.
    append_data_to_file(run_vars, 'TrainingData/eff_score_data.txt')
    run_vars['service']=body # this is the task link

    print("Predicted Runtime:")
    print(trainAndPredict(run_vars))
    #print(predict_runtime(model, run_vars['time_indexed_stats'])) #a list of stats with timestamps
    print("Actual Runtime " + str(run_time))
    # Plot real-time predictions
    #plot_predictions(predictions)
    return result, pull_time, run_time, container_name

def monitor_container(cont, start_run_time, timeout):
    stack = []
    count = 0
    while(str(cont.status)=='created'):
        cont.reload()
    while ((cont != None) and ((str(cont.status) == 'running') )):
        if(time.time()-start_run_time > timeout):
            print("timeout exceeded (cont not killed)")
            break
        s = cont.stats(decode=False, stream=False)
        if(s['memory_stats'] != {}):
            stack.clear()
            stack.append(s)
        else: break
        count+=1
    return stack


def run_and_invoke_docker(body, container_name) -> dict:

    print("[run_and_invoke_docker]")
    #open a file and write the payload to it
    #with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
    #    json.dump(payload, f)
    #    f.flush()
    #    input_file = f.name

    # Create output file
    #output_file = tempfile.NamedTemporaryFile(delete=False).name
            
    # Mount configurations for both input and output files
    #mounts = {
    #    input_file: {'bind': '/tmp/input.json', 'mode': 'ro'},
    #    output_file: {'bind': '/tmp/output.json', 'mode': 'rw'}
    #}

    start_pull_time = time.time()
    #image = client.images.pull(body)
    print("inside run_and_invoke_docker with body : " + body)
    image = imagePuller.request_image(body)
    print("Out of Hybrid Caching manager and inside run_and_invoke_docker again")
    print(image)
    pull_time = int((time.time() - start_pull_time) *1000)
    
    start_run_time = time.time()
    cont = None
    benchmark_no=body.split("/")[1].split(".")[1] # get number from peercompute/benchmark.010....
    payload=get_payload(benchmark_no, "small")
    # Temporarily override payload with a fixed value
    
    print(payload)
    response = None
    future=None
    try:
        print("container started running")
        cont = client.containers.run(image,
                                     name=container_name,
                                     detach=True,
                                     ports={'8080/tcp': None}, #None dynamically allocates a port
                                     environment={
                                         'AWS_ACCESS_KEY_ID': 'AKIA3KAG6W36BSXOEHWD',
                                         'AWS_SECRET_ACCESS_KEY': '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', 
                                         'AWS_REGION': 'ap-south-1'
                                     }
                                     )
        
        # Wait a bit for container to start
        time.sleep(1)
        cont.reload()  # Refresh container data
        port_info = cont.ports.get('8080/tcp')
        host_port = port_info[0]['HostPort'] #get the port
        print("container name ID: ", cont.id)
        print("container name: ", cont.name)
        # Make POST request to container # blocking
        
    except Exception as e:
        print(e)

    finally:
        print(body)
        timeout = 3000
        print("monitoring container")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor_for_cont_monitoring:
            # Submit the monitoring task to the executor
            future = executor_for_cont_monitoring.submit(monitor_container, cont, start_run_time, timeout)
            print("container monitored")
            response = requests.post(f'http://localhost:{host_port}', 
                                json=payload,
                                headers={'Content-Type': 'application/json'},
                                timeout=30)  # Increased timeout to 5 minutes (300 seconds)
            print("post request sent")

    #result = "this is result" #remove this line uncomment below line
    #result = result.decode("utf-8") #this gives the Hello from Docker msg.

    stack=future.result()
    run_vars={}
    # Read result from output file
    #with open(output_file, 'r') as f:
    #    result = f.read()
    #print("Result from container:", result)
    #print(response.json())
    result = response.json()
    print(result)
    print(stack) #uncomment this to get full stats
    run_time = int((time.time() - start_run_time)*1000) # get in ms
    #print(count)
    # run_vars['time_indexed_stats'] = time_indexed_stats
    run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
    run_vars['cpu_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
    #adding new lines for io_usage
    # blkio_read=0
    # blkio_write=0
    # for entry in stack[0]['blkio_stats']['io_service_bytes_recursive']:
    #     if entry['op'] == 'Read':
    #         blkio_read += entry['value']
    #     elif entry['op'] == 'Write':
    #         blkio_write += entry['value']
    # run_vars['io_read_stats'] = blkio_read
    # run_vars['io_write_stats'] = blkio_write
    #updated code till here
    run_vars['actual_runtime'] = run_time
    global cpu_efficiency_score
    run_vars['cpu_efficiency_score'] = cpu_efficiency_score
    global memory_efficiency_score
    run_vars['memory_efficiency_score'] = memory_efficiency_score
    # the below is service specific and has to be made for each service.
    append_data_to_file(run_vars, 'TrainingData/eff_score_data.txt')
    run_vars['service']=body # this is the task link
    print("runtime data: ")
    print(run_vars)
    print("Predicted Runtime:")
    print(trainAndPredict(run_vars))
    #print(predict_runtime(model, run_vars['time_indexed_stats'])) #a list of stats with timestamps
    print("Actual Runtime " + str(run_time))
    # Plot real-time predictions
    #plot_predictions(predictions)

    # Cleanup temporary files
    #os.unlink(input_file)
    #os.unlink(output_file)
    cont.stop()  #remove this line to keep container running
    cont.remove()
    return result, pull_time, run_time, container_name

def delete_container_and_image(body, container_name):
    filters = {'name': container_name}
    container_id = client.containers.list(all=True, filters=filters)[0]
    container_id.remove()

    # client.images.remove(body)

def HF_set_time(job_code, t_time):
    global token
    response = HFRequests.invoke_set_time(token, channelName, chaincodeName, 'org2', job_code, t_time)
    if 'jwt expired' in response.text or 'jwt malformed' in response.text or 'User was not found' in response.text or 'UnauthorizedError' in response.text:
        token = HFRequests.register_user(user_id, 'Org2')
        response = HFRequests.invoke_set_time(token, channelName, chaincodeName, 'org2', job_code, t_time)
    return response

def HF_invoke_balance_transfer(receiver, sender):
    global token
    response = HFRequests.invoke_balance_transfer(receiver, sender, token, channelName, chaincodeName, 'org2')
    if 'jwt expired' in response.text or 'jwt malformed' in response.text or 'User was not found' in response.text or 'UnauthorizedError' in response.text:
        token = HFRequests.register_user(user_id, 'Org2')
        response = HFRequests.invoke_balance_transfer(receiver, sender, token, channelName, chaincodeName, 'org2')
    return response

def on_request(json_data) :
    #requests.get(url=ACK_URL + str(json_data['job_id'])) #uncomment this
    #requests.get(url=NOT_READY_URL + user_id)
    if json_data['inputData'] == "None":
        json_data['inputData'] = None

    print("[on_request] in provider1.py")
    r, pull_time, run_time, container_name = run_and_invoke_docker(json_data['task_link'], str(str(json_data['job_id'])+"_container_")) #TODO
    total_time = math.ceil(((pull_time + run_time)/100.0))*100 
    print(pull_time, run_time, total_time)
    # HF_set_time(str(json_data['job_id']), total_time)
    # HF_invoke_balance_transfer(str(json_data['provider_id']), str(json_data['task_developer']))

    with open("results.csv", mode='a', newline='') as file:
    # Create a CSV writer object
        writer = csv.DictWriter(file, fieldnames=['PT', 'RT', 'TT'])        
        # Check if the file is empty, and if so, write the header
        if file.tell() == 0:
            writer.writeheader()
        data = {
            'PT':pull_time, 'RT': run_time, 'TT': total_time
        }
        # Write the data as a new row
        writer.writerow(data)


    delete_container_and_image(json_data['task_link'], container_name)
    response = {'stage':"dockerrun", 'Result': r, 'pull_time': pull_time, 'run_time': run_time, 'total_time': total_time, 'job_id': json_data['job_id']}
    global mclient
    mclient.publish(user_id, json.dumps(response).encode("utf-8"),qos=2)
    print("published response to scheduler")

def on_chained_request(json_data) :
    #requests.get(url=ACK_URL + str(json_data['job_id']))
   #requests.get(url=NOT_READY_URL + user_id)
    responses = []
    pull_times = []
    run_times = []
    total_times = []
    if json_data['inputData'] == "None":
        json_data['inputData'] = None
    for i in range(json_data['numberOfInvocations']):
        container_name = str(json_data['job_id']) + "_container_" + str(i)
        r, pull_time, run_time = run_docker(json_data['task_link'], container_name, json_data['inputData'] if i == 0 else responses[-1])
        responses.append(r)
        pull_times.append(pull_time)
        run_times.append(run_time)
        total_time = math.ceil(((pull_time + run_time)/100.0))*100
        total_times.append(total_time)
        print(pull_time,run_time,total_time)
        delete_container_and_image(json_data['task_link'])
        with open("results.csv", mode='a', newline='') as file:
        # Create a CSV writer object
            writer = csv.DictWriter(file, fieldnames=['PT', 'RT', 'TT'])        
            # Check if the file is empty, and if so, write the header
            if file.tell() == 0:
                writer.writeheader()
            data = {
                'PT':pull_time, 'RT': run_time, 'TT': total_time
            }
            # Write the data as a new row
            writer.writerow(data)
    # print(responses, pull_times, run_times)
    # HF_set_time(str(json_data['job_id']), total_time)
    # HF_invoke_balance_transfer(str(json_data['provider_id']), str(json_data['task_developer']))
    # delete_container_and_image(json_data['task_link'])
    return {'Result': responses, 'pull_time': pull_times, 'run_time': run_times, 'total_time': total_times}

# data = {
#     "is_provider": True,
#     "is_developer": False,
#     "active": True,
#     "ready": True,
#     "location": "TEST_PROV_1",
#     "ram": 8,
#     "cpu": 4
# }

def calc_benchmark_stats():
    #TODO
    print("calculating bench mark stats")
    bench_container_name = "benchTest"
    bench_image = "satyam098/testimage_largeruntime"
    image = imagePuller.request_image(bench_image)
    try:
        cont = client.containers.run(image, name=bench_container_name)
    except Exception as e:
        print(e)
        container_name+='b'
        cont = client.containers.run(image, name=bench_container_name)
    print(cont)
    print(str(cont.status))
    start_run_time=time.time()
    timeout = 40 # how long will this benchmark test run in seconds
    stack=[]
    run_vars={}
    runtime=timeout
    while ((cont != None) and ((str(cont.status) == 'running') or (str(cont.status) == 'created'))):
        if(time.time()-start_run_time > timeout):
            print("timeout reached")
            cont.kill()
            break
        #elapsed_time += stop_time
        s = cont.stats(decode=False, stream=False)
        if(s['memory_stats'] != {}):
            #stack.clear() #to get stats streamed throughout the process remove this line
            stack.clear() #only to save time
            stack.append(s)
        else: break
        #if(cont.status=='running'):print("running")
        #else: print("Not running")
        #sleep(stop_time)
    delete_container_and_image(bench_image, bench_container_name)
    run_time = int((time.time() - start_run_time)*1000)
    run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
    run_vars['cpu_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
    run_vars['actual_runtime'] = run_time
    run_vars['timeout']=timeout*1000
    #adding new lines for io_usage
    blkio_read=0
    blkio_write=0
    for entry in stack[0]['blkio_stats']['io_service_bytes_recursive']:
        if entry['op'] == 'Read':
            blkio_read += entry['value']
        elif entry['op'] == 'Write':
            blkio_write += entry['value']
    run_vars['io_read_stats'] = blkio_read
    run_vars['io_write_stats'] = blkio_write
    #updated code till here
    print(user_id)
    benchmark = {user_id: run_vars}
    append_data_to_file(benchmark, "benchmark_results.txt")
    #store one run as the reference benchmark.
    #calc efficiency score from this benchmark.
    #update_model()
    #send mqtt topic a msg request to calculate eff score and update the model.
    global mclient
    mclient.publish(topic=user_id, payload="Benchmark:"+json.dumps(benchmark), qos=2)
    print(benchmark)
    return benchmark


def set_reference_stats_for_service(service_id):
    container_name = service_id+"_reference_stats_"
    print(container_name)
    img = imagePuller.request_image(service_id)
    global client
    cont = client.containers.run(img, name=container_name)
    start_run_time=time.time()
    timeout = 500 # how long will this service run on reference in seconds
    stack=[]
    run_vars={}
    runtime=timeout
    while ((cont != None) and ((str(cont.status) == 'running') or (str(cont.status) == 'created'))):
        if(time.time()-start_run_time > timeout):
            print("timeout of 500 seconds reached in running service on the reference provider.")
            cont.kill()
            break
        #elapsed_time += stop_time
        s = cont.stats(decode=False, stream=False)
        if(s['memory_stats'] != {}):
            #stack.clear() #to get stats streamed throughout the process remove this line
            stack.clear() #only to save time
            stack.append(s)
        else: break

    run_time = int((time.time() - start_run_time)*1000)
    run_vars['service']=service_id
    run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
    run_vars['cpu_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
    run_vars['actual_runtime'] = run_time

    append_data_to_file(run_vars, 'TrainingData/Reference_Provider_Data.txt')
    global mclient
    # !IMPORTANT here user_id should actually be reference_user_id 
    mclient.publish(topic=user_id, payload="Stats for Reference Provider: "+json.dumps(run_vars), qos=2)
    return

# response = requests.POST(url=REGISTER_URL, data=data)
# user_id = response['user_id']

## mqtt implementation


#while(True):
#    a=1

while True:
    if procedural_shutdown_event.is_set():
        time_since_last_message = time.time() - last_message_time 
        with pending_jobs_lock:
            if pending_jobs == 0 and time_since_last_message >= 2: #if no job is actively running and no queued messages have been recieved in the past two seconds it will break out of the while loop
                print("No pending jobs. Exiting main loop.")
                break
    else:        
        time.sleep(1) #or you can just do a=1

# After the loop, perform cleanup
# Stop the MQTT client
print("performing procedural shutdown")
mclient.publish(topic=LWT_TOPIC, payload="offline_procedurally", qos=2)
mclient.loop_stop()
mclient.disconnect()


print("All jobs completed. Exiting procedurally.")



def job_queue():
    q = None
    # take arguments of on_request function out them in a dict array.
    # execute it one after other.
    # communicate services in the 