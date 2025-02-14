import pulp
import time
# Linear programming in essence is giving some constraint curves which set an area on the cartesian plane,
# now we have an objective function to maximise/minimise and this function/curve will be max/min at the vertices of the area.
# This is a topic from 12th CBSE maths see graph graph below for a visual proof.
# Photo explanation : https://calcworkshop.com/wp-content/uploads/linear-programming-example.png



# takes 4 inputs: 1. list of providers
#                 2. list of services
#                 3. cost_matrix; a dict of dicts in form Provider : {service : cost}
#                 4. delay dict; a dict of delay in EACH provider. 

# returns 2 values: 1. a dict with keys as services and values as providers for the min cost combination
#                   2. total cost (including delays) of the min cost combination
def minimize_total_cost(providers, services, cost_matrix, delay):
    l = time.time()
    # Create a binary variable for each combination of provider and service
    # this denotes if that combination of provider and service is chosen (1) or not (0) p.s. 'chosen' below is just a label.
    # for each service there is one provider who has value(x[provider,service]==1 and rest all providers for that service have x == 0)
    x = pulp.LpVariable.dicts('chosen', ((provider, service) for provider in providers for service in services), cat='Binary')
    
    # pulp.LpMinimize will minimise the objective function
    prob = pulp.LpProblem("Minimize_Total_Cost", pulp.LpMinimize)
    
    # += opertator is to add constraints or objective functions to the problem
    # Objective function: total cost of runtimes + delay once per provider
    # Objective function is the expression to minimise/maximise
    # for loops are basically summation symbols here since it is inside lpSum.
    # the if statement are so that 1 taken because if a provider has taken more than 1 services it the delay should still
    # be multiplied with 1 and not the number of services.

    prob += pulp.lpSum(x[provider, service] * cost_matrix[provider][service] for provider in providers for service in services) + pulp.lpSum(delay[provider] * (pulp.lpSum(x[(provider, service)] for service in services) if pulp.lpSum(x[(provider, service)] for service in services) <= 1 else 1) for provider in providers)


    
    # Constraints: each service must be assigned to exactly one provider
    # Constraints are inequalities or equalities instead of an expression
    for service in services:
        prob += pulp.lpSum(x[provider, service] for provider in providers) == 1
    
    prob.solve()
    print("Time taken for Min Cost Algo: " + str(prob.solutionTime))
    
    # Check if the optimization was successful
    if pulp.LpStatus[prob.status] != 'Optimal':
        print("optimisation not succesful :(")
        return None, None
    
    # Store the min cost combination in a dict
    assignment = {}
    for provider in providers:
        for service in services:
            if pulp.value(x[provider, service]) == 1:
                assignment[service] = provider

    # Calculate the total cost considering only recruited providers
    total_cost = sum(cost_matrix[assignment[service]][service] for service in services)
    total_cost += sum(delay[provider] for provider in providers if any(pulp.value(x[provider, service]) == 1 for service in services))
    
    print("Time taken in wallclock sec by lp algo: ", time.time()-l)
    return assignment, total_cost


# # Generate providers and services
# providers = ['provider1', 'provider2', 'provider3', 'provider4', 'provider5', 'provider6']
# services = ['service1', 'service2', 'service3', 'service4', 'service5', 'service6', 'service7', 'service8', 'service9', 'service10']

# # Define fixed cost matrix
# cost_matrix = {
#     'provider1': {'service1': 10, 'service2': 15, 'service3': 20, 'service4': 25, 'service5': 30, 'service6': 35, 'service7': 40, 'service8': 45, 'service9': 50, 'service10': 55},
#     'provider2': {'service1': 20, 'service2': 25, 'service3': 30, 'service4': 35, 'service5': 40, 'service6': 45, 'service7': 50, 'service8': 55, 'service9': 60, 'service10': 65},
#     'provider3': {'service1': 30, 'service2': 35, 'service3': 40, 'service4': 45, 'service5': 50, 'service6': 55, 'service7': 60, 'service8': 65, 'service9': 70, 'service10': 75},
#     'provider4': {'service1': 40, 'service2': 45, 'service3': 50, 'service4': 55, 'service5': 60, 'service6': 65, 'service7': 70, 'service8': 75, 'service9': 80, 'service10': 85},
#     'provider5': {'service1': 50, 'service2': 55, 'service3': 60, 'service4': 65, 'service5': 70, 'service6': 75, 'service7': 80, 'service8': 85, 'service9': 90, 'service10': 95},
#     'provider6': {'service1': 60, 'service2': 65, 'service3': 70, 'service4': 75, 'service5': 80, 'service6': 85, 'service7': 90, 'service8': 95, 'service9': 100, 'service10': 105}
# }

# # Define fixed delay dictionary
# delay = {
#     'provider1': 0, 'provider2': 20, 'provider3': 10, 'provider4': 30, 'provider5': 15, 'provider6': 25
# }
# assignment, total_cost = minimize_total_cost(providers, services, cost_matrix, delay)

# print("service Assignments:")
# print(assignment)
# print("Total Cost (including delay):", total_cost)