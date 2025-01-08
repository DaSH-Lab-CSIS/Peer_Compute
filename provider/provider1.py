from threading import Thread
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

user_id = sys.argv[1]
controller_ip = "10.8.1.48" #change to .46
controller_port = "8000"
#BROKER_ID = "10.60.12.47"
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

# REGISTER_URL = 'https://' + controller_ip + ":" + controller_port + "/profiles/register_user/"
ACK_URL = "http://" + controller_ip + ":" + controller_port + "/providers/job_ack/"
NOT_READY_URL = "http://" + controller_ip + ":" + controller_port + "/providers/not_ready/"
READY_URL = "http://" + controller_ip + ":" + controller_port + "/providers/ready/"

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

def on_message(mqtt_client, userdata, msg):
    print(f'Received message on topic: {msg.topic} with payload: {msg.payload}')
    
    try: 
        data = json.loads(msg.payload.decode("utf-8"))
        if(data["stage"] == "dockernotrun"):
            data["stage"] = "dockerrunning"
            
            # response = {'Result': [], 'run_time': [], 'pull_time': [], 'total_time': []}
            # on_request initially returned a dictionary.
            if(data['runMultipleInvocations'] == True):
                if(data['numberOfInvocations'] == 1) :
                    on_request(data)
                elif(data['isChained'] == False):
                    for i in range(data['numberOfInvocations']):
                        container_name = str(data['job_id']) + "_container_" + str(i)
                        temp = on_request(data)
                        # response['Result'].append(temp['Result'])
                        # response['run_time'].append(temp['run_time'])
                        # response['pull_time'].append(temp['pull_time'])
                        # response['total_time'].append(temp['total_time'])
                else: 
                    on_chained_request(data)
            else:
                on_request(data)
            
            # mqtt_client.publish(user_id, json.dumps(response).encode("utf-8"),qos=2)
            #mqtt_client.loop_stop()
            #mqtt_client.disconnect()
    except:
        #print(str({msg.payload}))
        if(msg.payload.decode("utf-8")=="calculate_efficiency"):
            calc_benchmark_stats()
        if(msg.payload.decode("utf-8").startswith("EfficiencyScoreSet:")):
            scoreset = json.loads(msg.payload[19:])
            global cpu_efficiency_score
            cpu_efficiency_score = scoreset['cpu']
            global memory_efficiency_score
            memory_efficiency_score = scoreset['memory']
            print("Fetched this provider's efficiency score set")
            print(cpu_efficiency_score)
            print(memory_efficiency_score)
        if(msg.payload.decode("utf-8").startswith("ref_run_service_id/")):
            service_id = msg.payload.decode("utf-8")[19:]
            set_reference_stats_for_service(service_id)


def on_subscribe(mqtt_client, userdata, mid, qos, properties=None):
    pass

# tell scheduler that this provider has started. waits for the request to get then proceeds.
requests.get("http://localhost:8000/providers/startup/"+user_id)


mclient = mqtt.Client(callback_api_version= mqtt.CallbackAPIVersion.VERSION2)
# make a socket bind to tcp and make a dealer
mclient.on_connect = on_connect
mclient.on_message = on_message
mclient.on_subscribe= on_subscribe

mclient.connect(host=BROKER_ID,port=1883)
#client subscribe is in on_connect
mclient.loop_start() #different thread

mclient.publish(topic="EVERYONE", payload="start_connect"+user_id, qos=2)
mclient.publish(topic="EVERYONE", payload="get_efficiency_score"+user_id, qos=2)

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

    r, pull_time, run_time, container_name = run_docker(json_data['task_link'], str(str(json_data['job_id'])+"_container_"), json_data['inputData'])
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


while(True):
    a=1


def job_queue():
    q = None
    # take arguments of on_request function out them in a dict array.
    # execute it one after other.
    # communicate services in the 