import pulp

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

    # Create a binary variable for each combination of worker and job
    # this denotes if that combination is assigned (1) or not (0) p.s. 'assign' below is just a label.
    # for each job there is one worker who has value(x[worker,job]==1 and rest all workers for that job have x == 0)
    x = pulp.LpVariable.dicts('assign', ((worker, job) for worker in workers for job in jobs), cat='Binary')
    
    # pulp.LpMinimize will minimise the objective function
    prob = pulp.LpProblem("Minimize_Total_Cost", pulp.LpMinimize)
    
    # += opertator is to add constraints or objective functions to the problem
    # Objective function: total cost of runtimes + delay once per worker
    # Objective function is the expression to minimise/maximise
    # for loops are basically summation symbols here since it is inside lpSum.
    prob += pulp.lpSum(x[worker, job] * cost_matrix[worker][job] for worker in workers for job in jobs) + pulp.lpSum(delay[worker] * pulp.lpSum(x[worker, job] for job in jobs) for worker in workers)
    
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
    
    return assignment, total_cost

# Example usage
providers = ['Provider1', 'Provider2']
jobs = ['Job1', 'Job2', 'Job3']
cost_matrix = {
    'Provider1' : {'Job1': 20, 'Job2': 20, 'Job3': 30},
    'Provider2' : {'Job1': 15, 'Job2': 15, 'Job3': 15}
}
delay = {'Provider1': 0, 'Provider2': 30}

assignment, total_cost = minimize_total_cost(providers, jobs, cost_matrix, delay)

print("Job Assignments:")
print(assignment)
print("\nTotal Cost (including delay):", total_cost)