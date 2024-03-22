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
BROKER_ID = "10.60.5.46"
#uncomment requests.get ACK READY NOT READY
channelName = "mychannel"
chaincodeName = "monitoring"
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE2OTQxMjk2MzcsInVzZXJuYW1lIjoiY29udHJvbGxlciIsIm9yZ05hbWUiOiJPcmcxIiwiaWF0IjoxNjk0MDkzNjM3fQ.DNJZ4kB11PbDB4UO2HaMjwlqxgTbJ8b7JK3WsRzaePY"

client = docker.from_env()
container_name = "test74"
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


# Function to preprocess the data
def preprocess_data(streaming_data):
    # Convert timestamp to datetime object
    #print(streaming_data)
    streaming_data['timestamp'] = pd.to_datetime(streaming_data['timestamp'])
    # Sort DataFrame by timestamp
    streaming_data.sort_values(by='timestamp', inplace=True)
    # Calculate time intervals between measurements
    streaming_data['time_interval'] = streaming_data['timestamp'].diff().dt.total_seconds().fillna(0)
    return streaming_data



# Function to predict runtime from the return values of run_docker
def predict_runtime(model, timed_stats):
    # Preprocess the datas
    preprocessed_data = preprocess_data(pd.DataFrame(timed_stats))
    
    # Separate features
    X = np.array(preprocessed_data[['cpu_total_usage', 'memory_usage', 'time_interval']])

    # Make prediction using the trained model
    predicted_runtime = model.predict(X)

    print(predicted_runtime)
    return predicted_runtime # Return the first predicted runtime if multiple rows are predicted




def train_model(filename):

    data = load_data_from_file(filename)
    #print(data)
    # Initialize lists to store features and targets
    X_list = []
    y_list = []

    # Process data to associate each actual_runtime with its time_indexed_stats
    for entry in data:
        time_indexed_stats = entry['time_indexed_stats']
        actual_runtime = entry['actual_runtime']
        # Create separate feature rows for each time_indexed_stats list
        for stat_entry in time_indexed_stats:
            X_list.append([stat_entry['cpu_total_usage'], stat_entry['memory_usage'], (pd.to_datetime(stat_entry['timestamp']) - pd.to_datetime(time_indexed_stats[0]['timestamp'])).total_seconds()])
            y_list.append(actual_runtime)

    # Convert lists to DataFrames
    X = np.array(pd.DataFrame(X_list, columns=['cpu_total_usage', 'memory_usage', 'time_interval']))
    y = pd.Series(y_list)

    # Train a new linear regression model
    model = LinearRegression()
    model.fit(X, y)

    save_model(model, 'LRModels/service5/model1.pkl')
    print('Model saved to disk')
    return model



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


# Function to plot predictions against time
    
def plot_predictions(predictions):
    first_timestamp = predictions[0]['timestamp']
    timestamps = [(pd.to_datetime(entry['timestamp']) - pd.to_datetime(first_timestamp)).total_seconds() for entry in predictions]
    predicted_runtimes = [entry['predicted_runtime'] for entry in predictions]
    plt.figure(figsize=(10, 6))
    plt.plot(timestamps, predicted_runtimes, marker='o', linestyle='-')
    plt.xlabel('Timestamp')
    plt.ylabel('Predicted Runtime')
    plt.title('Predicted Runtimes Over Time')
    plt.xticks(rotation=45)
    plt.tight_layout()
    print(predicted_runtimes)
    plt.savefig('LRModels/service5/livePredictions2.png')




def run_docker(body, inputData=None):
    start_pull_time = time.time()
    image = client.images.pull(body)
    print("Pull done!")
    pull_time = int((time.time() - start_pull_time) *1000)
    global container_name
    container_name += "n"
    print(container_name)
    start_run_time = time.time()
    if inputData == None:
        # result = client.containers.run(body, name=container_name)

        client.containers.create(body, name=container_name)
        cont = client.containers.get(container_name)
        cont.start()
    else:    

        client.containers.create(body, command=str(inputData), name=container_name)
        cont = client.containers.get(container_name)
        cont.start()


    result = "this is result" #remove this line uncomment below line
    #result = result.decode("utf-8") #this gives the Hello from Docker msg.
    print("Run Started!")

    timeout = 60
    stop_time = 0.1
    elapsed_time = 0
    stack = []
    run_vars = {}
    time_indexed_stats = []
    cont = client.containers.get(container_name)
    count = 0
    runs = 0
    #model = load_model('LRModels/service5/model1.pkl')
    livepredictions = {} # dict with two keys predicted_runtime and timestamp
    predictions = [] # list of livepredictions

    while ((cont != None) and (str(cont.status) == 'running')):
        if(elapsed_time > timeout):
            print("timeout exceeded")
            break
        elapsed_time += stop_time
        s = cont.stats(decode=False, stream=False)
        if(s['memory_stats'] != {}):
            #stack.clear() #to get stats streamed throughout the process remove this line
            # var = {}
            # var['timestamp'] = s['read'] #understand read preread and see if time.now() would yeild better model
            # var['cpu_total_usage'] = s['cpu_stats']['cpu_usage']['total_usage']
            # var['memory_usage']=s['memory_stats']['usage']
            # time_indexed_stats.append(var)
            # livepredictions = {}
            # livepredictions['predicted_runtime']=predict_runtime(model, time_indexed_stats)
            # livepredictions['timestamp']=var['timestamp']
            # predictions.append(livepredictions)
            stack.clear() #only to save time
            stack.append(s)
        else: break
        if(cont.status=='running'):runs+=1
        count+=1
        sleep(stop_time)

    print(stack) #uncomment this to get full stats
    run_time = int((time.time() - start_run_time)*1000)
    # run_vars['time_indexed_stats'] = time_indexed_stats
    run_vars['memory_usage'] = stack[0]['memory_stats']['usage']
    run_vars['memory_usage'] = stack[0]['cpu_stats']['cpu_usage']['total_usage']
    run_vars['actual_runtime'] = run_time
    # print(run_vars)
    #print(count)
    # print("sending curl")
    # sendCurl()
    # print("curl sent")
    # UNCOMMENT BEFORE DEBUGGING, DO NOT SPOIL TRAINING DATA
    #append_data_to_file(run_vars, 'TrainingData/service5.txt') #uncomment during debugging
    # # UNCOMMENT BEFORE DEBUGGING, DO NOT SPOIL TRAINING DATA

    
    #get a freshly trained model on txt file
    #model = train_model('TrainingData/service5.txt')

    #load model without training it
    #model = load_model('LRModels/service5/model1.pkl')

    print("Predicted Runtime:")
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

## mqtt implementation


def on_connect(mqtt_client, userdata, flags, rc, callback_api_version):
    if rc == 0:
        print('Connected successfully')
        mqtt_client.subscribe("34933555-5cca-41fb-aded-4ab7900c48d5")
    else:
        print('Bad connection. Code:', rc)

def on_message(mqtt_client, userdata, msg):
    print("Inside on_message of provider1.py")
    print(f'Received message on topic: {msg.topic} with payload: {msg.payload}')
    data = json.loads(msg.payload.decode("utf-8"))
    try: 
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
        print(traceback.format_exc())
        print(f'Received in except with TOPIC: {msg.topic} with PAYLOAD: {msg.payload}')
    #socket.send_multipart([identity, json.dumps(response).encode("utf-8")])

    #requests.get(url=READY_URL+user_id)



def on_subscribe(mqtt_client, userdata, mid, qos, properties=None):
    print("subbed to topic from provider1.py")


mclient = mqtt.Client(callback_api_version= mqtt.CallbackAPIVersion.VERSION2)
# make a socket bind to tcp and make a dealer
mclient.on_connect = on_connect
mclient.on_message = on_message
mclient.on_subscribe= on_subscribe

mclient.connect(host=BROKER_ID,port=1883)

#client subscribe is in on_connect
mclient.loop_start() #different thread
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