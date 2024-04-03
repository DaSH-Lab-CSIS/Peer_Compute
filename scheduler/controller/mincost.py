import pulp
import time
# Linear programming in essence is giving some constraint curves which set an area on the cartesian plane,
# now we have an objective function to maximise/minimise and this function/curve will be max/min at the vertices of the area.
# This is a topic from 12th CBSE maths see graph graph below for a visual proof.
# Photo explanation : https://calcworkshop.com/wp-content/uploads/linear-programming-example.png



# takes 4 inputs: 1. list of providers
#                 2. list of jobs
#                 3. cost_matrix; a dict of dicts in form Provider : {Job : cost}
#                 4. delay dict; a dict of delay in EACH provider. 

# returns 2 values: 1. a dict with keys as jobs and values as providers for the min cost combination
#                   2. total cost (including delays) of the min cost combination
def minimize_total_cost(workers, jobs, cost_matrix, delay):
    l = time.time()
    # Create a binary variable for each combination of worker and job
    # this denotes if that combination of worker and job is chosen (1) or not (0) p.s. 'chosen' below is just a label.
    # for each job there is one worker who has value(x[worker,job]==1 and rest all workers for that job have x == 0)
    x = pulp.LpVariable.dicts('chosen', ((worker, job) for worker in workers for job in jobs), cat='Binary')
    
    # pulp.LpMinimize will minimise the objective function
    prob = pulp.LpProblem("Minimize_Total_Cost", pulp.LpMinimize)
    
    # += opertator is to add constraints or objective functions to the problem
    # Objective function: total cost of runtimes + delay once per worker
    # Objective function is the expression to minimise/maximise
    # for loops are basically summation symbols here since it is inside lpSum.
    # the if statement are so that 1 taken because if a worker has taken more than 1 jobs it the delay should still
    # be multiplied with 1 and not the number of jobs.

    prob += pulp.lpSum(x[worker, job] * cost_matrix[worker][job] for worker in workers for job in jobs) + pulp.lpSum(delay[worker] * (pulp.lpSum(x[(worker, job)] for job in jobs) if pulp.lpSum(x[(worker, job)] for job in jobs) <= 1 else 1) for worker in workers)

    
    # Constraints: each job must be assigned to exactly one worker
    # Constraints are inequalities or equalities instead of an expression
    for job in jobs:
        prob += pulp.lpSum(x[worker, job] for worker in workers) == 1
    
    prob.solve()
    print("Time taken for Min Cost Algo: " + str(prob.solutionTime))
    
    # Check if the optimization was successful
    if pulp.LpStatus[prob.status] != 'Optimal':
        print("optimisation not succesful :(")
        return None, None
    
    # Store the min cost combination in a dict
    assignment = {}
    for worker in workers:
        for job in jobs:
            if pulp.value(x[worker, job]) == 1:
                assignment[job] = worker

    # Calculate the total cost considering only recruited workers
    total_cost = sum(cost_matrix[assignment[job]][job] for job in jobs)
    total_cost += sum(delay[worker] for worker in workers if any(pulp.value(x[worker, job]) == 1 for job in jobs))
    
    print("Time taken in wallclock sec by lp algo: ", time.time()-l)
    return assignment, total_cost


# # Generate workers and jobs
# workers = ['Worker1', 'Worker2', 'Worker3', 'Worker4', 'Worker5', 'Worker6']
# jobs = ['Job1', 'Job2', 'Job3', 'Job4', 'Job5', 'Job6', 'Job7', 'Job8', 'Job9', 'Job10']

# # Define fixed cost matrix
# cost_matrix = {
#     'Worker1': {'Job1': 10, 'Job2': 15, 'Job3': 20, 'Job4': 25, 'Job5': 30, 'Job6': 35, 'Job7': 40, 'Job8': 45, 'Job9': 50, 'Job10': 55},
#     'Worker2': {'Job1': 20, 'Job2': 25, 'Job3': 30, 'Job4': 35, 'Job5': 40, 'Job6': 45, 'Job7': 50, 'Job8': 55, 'Job9': 60, 'Job10': 65},
#     'Worker3': {'Job1': 30, 'Job2': 35, 'Job3': 40, 'Job4': 45, 'Job5': 50, 'Job6': 55, 'Job7': 60, 'Job8': 65, 'Job9': 70, 'Job10': 75},
#     'Worker4': {'Job1': 40, 'Job2': 45, 'Job3': 50, 'Job4': 55, 'Job5': 60, 'Job6': 65, 'Job7': 70, 'Job8': 75, 'Job9': 80, 'Job10': 85},
#     'Worker5': {'Job1': 50, 'Job2': 55, 'Job3': 60, 'Job4': 65, 'Job5': 70, 'Job6': 75, 'Job7': 80, 'Job8': 85, 'Job9': 90, 'Job10': 95},
#     'Worker6': {'Job1': 60, 'Job2': 65, 'Job3': 70, 'Job4': 75, 'Job5': 80, 'Job6': 85, 'Job7': 90, 'Job8': 95, 'Job9': 100, 'Job10': 105}
# }

# # Define fixed delay dictionary
# delay = {
#     'Worker1': 0, 'Worker2': 20, 'Worker3': 10, 'Worker4': 30, 'Worker5': 15, 'Worker6': 25
# }
# assignment, total_cost = minimize_total_cost(workers, jobs, cost_matrix, delay)

# print("Job Assignments:")
# print(assignment)
# print("Total Cost (including delay):", total_cost)