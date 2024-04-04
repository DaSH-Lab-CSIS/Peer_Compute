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

user_id = sys.argv[1]
controller_ip = "10.8.1.48" #change to .46
controller_port = "8000"
BROKER_ID = "broker.hivemq.com"
#uncomment requests.get ACK READY NOT READY
channelName = "mychannel"
chaincodeName = "monitoring"
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE2OTQxMjk2MzcsInVzZXJuYW1lIjoiY29udHJvbGxlciIsIm9yZ05hbWUiOiJPcmcxIiwiaWF0IjoxNjk0MDkzNjM3fQ.DNJZ4kB11PbDB4UO2HaMjwlqxgTbJ8b7JK3WsRzaePY"

client = docker.from_env()
container_name = "test104"
cont_num = 1
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
            data["stage"] = "dockerrun"
            
            response = {'Result': [], 'run_time': [], 'pull_time': [], 'total_time': []}
            
            if(data['runMultipleInvocations'] == True):
                if(data['numberOfInvocations'] == 1) :
                    response = on_request(data)
                elif(data['isChained'] == False):
                    for i in range(data['numberOfInvocations']):
                        container_name = str(data['job_id']) + "_container_" + str(i)
                        temp = on_request(data)
                        response['Result'].append(temp['Result'])
                        response['run_time'].append(temp['run_time'])
                        response['pull_time'].append(temp['pull_time'])
                        response['total_time'].append(temp['total_time'])
                else: 
                    response = on_chained_request(data)
            else:
                response = on_request(data)
            
            mqtt_client.publish(user_id, json.dumps(response).encode("utf-8"),qos=2)
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
    training_data=load_data_from_file("TrainingData/eff_score_data.txt")
    model = train_regression_model(training_data)
    #PREDICTION
    dummy_provider = 0 # this provider would be real if this were to run in the scheduler. Here it is useless as we use globals.
    predicted_runtime = predict_runtime(run_vars['service'], dummy_provider, model)
    return predicted_runtime[0]

def sendCurl():
    print("inside curl before sleep")
    sleep(10)
    headers = {
        'Accept': '*/*',
        'User-Agent': 'Thunder Client (https://www.thunderclient.com)',
        'Content-Type': 'application/json',
    }

    json_data = {
        'numberOfInvocations': 1,
        'chained': False,
        'input': 'None',
        'runMultipleInvocations': False,
    }
    global curl_count
    if(curl_count<100):
        global container_name
        global cont_num
        container_name += str(cont_num)
        response = requests.post('http://localhost:8000/developers/run_service/5', headers=headers, json=json_data)
        curl_count+=1
        cont_num+=1
    print("after sleep")
    print(curl_count)

def run_docker(body, inputData=None):
    start_pull_time = time.time()
    image = client.images.pull(body)
    print("Pull done!")
    pull_time = int((time.time() - start_pull_time) *1000)
    global container_name
    container_name += "n"
    print(container_name)
    print(body)
    start_run_time = 0
    if inputData == None:
        # result = client.containers.run(body, name=container_name)
        try:
            client.containers.create(body, name=container_name)
        except:
            container_name += "e"
            client.containers.create(body, name=container_name)
        cont = client.containers.get(container_name)
        cont.start()
        start_run_time = time.time()
    else:    
        try:
            client.containers.create(body, command=str(inputData), name=container_name)
        except:
            container_name += "n"
            client.containers.create(body, command=str(inputData), name=container_name)
        cont = client.containers.get(container_name)
        cont.start()
        start_run_time = time.time()

    result = "this is result" #remove this line uncomment below line
    #result = result.decode("utf-8") #this gives the Hello from Docker msg.
    print("Run Started!")
    print(body)
    timeout = 65
    stack = []
    run_vars = {}
    cont = client.containers.get(container_name)
    count = 0
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
    print(count)
    # run_vars['time_indexed_stats'] = time_indexed_stats
    run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
    run_vars['cpu_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
    run_vars['actual_runtime'] = run_time
    global cpu_efficiency_score
    run_vars['cpu_efficiency_score'] = cpu_efficiency_score
    global memory_efficiency_score
    run_vars['memory_efficiency_score'] = memory_efficiency_score

    append_data_to_file(run_vars, 'TrainingData/eff_score_data.txt')
    run_vars['service']=body # this is the task link

    print("Predicted Runtime:")
    print(trainAndPredict(run_vars))
    #print(predict_runtime(model, run_vars['time_indexed_stats'])) #a list of stats with timestamps
    print("Actual Runtime " + str(run_time))
    # Plot real-time predictions
    #plot_predictions(predictions)
    return result, pull_time, run_time

def delete_container_and_image(body):
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
    r, pull_time, run_time = run_docker(json_data['task_link'], json_data['inputData'])
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


    delete_container_and_image(json_data['task_link'])
    return {'Result': r, 'pull_time': pull_time, 'run_time': run_time, 'total_time': total_time}

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
        r, pull_time, run_time = run_docker(json_data['task_link'], json_data['inputData'] if i == 0 else responses[-1])
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
    global container_name
    container_name+="b"
    client.containers.create(client.images.get("satyam098/testimage_largeruntime"), name=container_name)
    cont = client.containers.get(container_name)
    cont.start()
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

    run_time = int((time.time() - start_run_time)*1000)
    run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
    run_vars['cpu_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
    run_vars['actual_runtime'] = run_time
    run_vars['timeout']=timeout*1000
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
    global container_name
    container_name+="r"
    print(str(service_id))
    global client
    client.containers.create(client.images.get(str(service_id)), name=container_name)
    cont = client.containers.get(container_name)
    cont.start()
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
# create_thread_and_subscribe(user_id)

# context = zmq.Context()
# socket = context.socket(zmq.ROUTER)
# socket.setsockopt(zmq.IDENTITY, user_id.encode("utf-8"))
# socket.connect("tcp://" + controller_ip + ":5555")
# print("Connected to : ", controller_ip)
# # socket.setsockopt_string(zmq.SUBSCRIBE, user_id)

# while True:
#         identity, _, json_data = socket.recv_multipart()
#         data = json.loads(json_data.decode("utf-8"))
        
#         print(f"Received identity: {identity.decode('utf-8')}")
#         print(f"Received data: {data}")

#         response = {'Result': [], 'run_time': [], 'pull_time': [], 'total_time': []}
        
#         if(data['runMultipleInvocations'] == True):
#             if(data['numberOfInvocations'] == 1) :
#                 response = on_request(data)
#             elif(data['isChained'] == False):
#                 for i in range(data['numberOfInvocations']):
#                     container_name = str(data['job_id']) + "_container_" + str(i)
#                     temp = on_request(data)
#                     response['Result'].append(temp['Result'])
#                     response['run_time'].append(temp['run_time'])
#                     response['pull_time'].append(temp['pull_time'])
#                     response['total_time'].append(temp['total_time'])
#             else: 
#                 response = on_chained_request(data)
#         else:
#             response = on_request(data)

#         socket.send_multipart([identity, json.dumps(response).encode("utf-8")])

#         requests.get(url=READY_URL+user_id)

def job_queue():
    q = None
    # take arguments of on_request function out them in a dict array.
    # execute it one after other.
    # communicate services in the 