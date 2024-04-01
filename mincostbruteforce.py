import time

class BruteForce:
    def __init__(self,cost_matrix,delay, job_identifiers, providers):
        self.cost_matrix=cost_matrix
        self.delay=delay
        self.min_cost=float('inf')
        self.min_cost_matrix=[]
        self.providers= providers
        self.job_identifiers=job_identifiers
    def func(self,current_job, current_matrix,current_cost,providers,accounted_for,run_times,job_identifiers,delays):
        if(current_job==len(job_identifiers)):
            if(current_cost<self.min_cost):
                self.min_cost=current_cost
                self.min_cost_matrix=current_matrix.copy()
            return
        for i,provider in enumerate(providers):
            state=accounted_for[i]
            if(state==0):
                current_cost+=delays[i]
                accounted_for[i]=1
            mapping= {job_identifiers[current_job]:run_times[i][current_job]}
            current_cost+=run_times[i][current_job]
            current_matrix.append({provider: mapping})
            self.func(current_job+1,current_matrix,current_cost,providers,accounted_for,run_times,job_identifiers,delays)
            current_matrix.pop()
            if(state==0):
                accounted_for[i]=0
                current_cost-=delays[i]
            current_cost-=run_times[i][current_job]
    def brute_force(self):
        l = time.time()
        accounted_for=[0]*len(self.cost_matrix)
        run_times = []
        for provider_data in self.cost_matrix.items():
            run_times_row = []
            for job_data in provider_data[1].items():
                run_times_row.append(job_data[1])
            run_times.append(run_times_row)
        delays=[]
        for d in self.delay.items():
            delays.append(d[1])
        self.func(0,[],0,self.providers,accounted_for,run_times,self.job_identifiers,delays)
        print("Time taken for recursive brute force: ", time.time()-l)
        return self.min_cost,self.min_cost_matrix
    
# Example usage
providers = ['Worker1', 'Worker2', 'Worker3', 'Worker4', 'Worker5', 'Worker6']
job_identifiers = ['Job1', 'Job2', 'Job3', 'Job4', 'Job5', 'Job6', 'Job7', 'Job8', 'Job9', 'Job10']
cost_matrix = {
    'Worker1': {'Job1': 10, 'Job2': 15, 'Job3': 20, 'Job4': 25, 'Job5': 30, 'Job6': 35, 'Job7': 40, 'Job8': 45, 'Job9': 50, 'Job10': 55},
    'Worker2': {'Job1': 20, 'Job2': 25, 'Job3': 30, 'Job4': 35, 'Job5': 40, 'Job6': 45, 'Job7': 50, 'Job8': 55, 'Job9': 60, 'Job10': 65},
    'Worker3': {'Job1': 30, 'Job2': 35, 'Job3': 40, 'Job4': 45, 'Job5': 50, 'Job6': 55, 'Job7': 60, 'Job8': 65, 'Job9': 70, 'Job10': 75},
    'Worker4': {'Job1': 40, 'Job2': 45, 'Job3': 50, 'Job4': 55, 'Job5': 60, 'Job6': 65, 'Job7': 70, 'Job8': 75, 'Job9': 80, 'Job10': 85},
    'Worker5': {'Job1': 50, 'Job2': 55, 'Job3': 60, 'Job4': 65, 'Job5': 70, 'Job6': 75, 'Job7': 80, 'Job8': 85, 'Job9': 90, 'Job10': 95},
    'Worker6': {'Job1': 60, 'Job2': 65, 'Job3': 70, 'Job4': 75, 'Job5': 80, 'Job6': 85, 'Job7': 90, 'Job8': 95, 'Job9': 100, 'Job10': 105}
}
delay = {
    'Worker1': 0, 'Worker2': 20, 'Worker3': 10, 'Worker4': 30, 'Worker5': 15, 'Worker6': 25
}
solver=BruteForce(cost_matrix,delay,job_identifiers,providers)
total_cost,total_cost_matrix=solver.brute_force()
print("Total cost: ",total_cost)
print("Total cost matrix: ",total_cost_matrix)
