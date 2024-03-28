min_cost_matrix=[]
min_cost=float('inf')
providers = ['A', 'B']
accounted_for=[0,0]
run_times = [
    [20, 20, 30],  # Run times for provider A
    [15, 15, 15],  # Run times for provider B   # Run times for provider C
]
delay = [0,30]
job_identifiers = ['j1', 'j2', 'j3']

cost_matrix = []

for i, provider in enumerate(providers):
    run_time_mapping = {job_identifiers[j]: run_times[i][j] for j in range(len(run_times[i]))}
    cost_matrix.append({provider: run_time_mapping})
def fun(current_job, current_matrix,current_cost):
    if(current_job==len(job_identifiers)):
        global min_cost
        global min_cost_matrix
        if(current_cost<min_cost):
            min_cost=current_cost
            #print(current_matrix)
            min_cost_matrix=current_matrix.copy()
            #print(min_cost_matrix)
        return
    for i,provider in enumerate(providers):
        state=accounted_for[i]
        if(state==0):
            current_cost+=delay[i]
            accounted_for[i]=1
        mapping= {job_identifiers[current_job]:run_times[i][current_job]}
        current_cost+=run_times[i][current_job]
        current_matrix.append({provider: mapping})
        fun(current_job+1,current_matrix,current_cost)
        current_matrix.pop()
        if(state==0):
            accounted_for[i]=0
            current_cost-=delay[i]
        current_cost-=run_times[i][current_job]
fun(0,[],0)
print(min_cost_matrix)
print(min_cost)