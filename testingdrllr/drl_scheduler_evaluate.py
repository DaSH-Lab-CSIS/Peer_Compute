import time
from stable_baselines3 import DQN

# Import the SchedulingEnv class
from drl_scheduler_train import SchedulingEnv

def evaluate_drl_scheduler(
    workers, jobs, cost_matrix, delay, model_path="drl_model.zip"
):
    # Initialize the environment with the evaluation data
    env = SchedulingEnv(workers, jobs, cost_matrix, delay)
    # Load the saved model
    model = DQN.load(model_path, env=env)

    obs = env.reset()
    done = False
    assignment = {}
    while not done:
        action, _states = model.predict(obs, deterministic=True)
        worker_idx = action % env.num_workers
        job_idx = action // env.num_workers

        obs, reward, done, info = env.step(action)
        if env.job_status[job_idx]:
            assignment[env.jobs[job_idx]] = env.workers[worker_idx]
    total_cost = env.total_cost
    return assignment, total_cost


if __name__ == "__main__":
    # Workers and jobs
    workers = [
        "Worker1",
        "Worker2",
        "Worker3",
        "Worker4",
        "Worker5",
        "Worker6",
    ]
    jobs = [
        "Job1",
        "Job2",
        "Job3",
        "Job4",
        "Job5",
        "Job6",
        "Job7",
        "Job8",
        "Job9",
        "Job10",
    ]

    # Define the actual cost matrix and delay for evaluation
    cost_matrix = {
        "Worker1": {
            "Job1": 10,
            "Job2": 15,
            "Job3": 20,
            "Job4": 25,
            "Job5": 30,
            "Job6": 35,
            "Job7": 40,
            "Job8": 45,
            "Job9": 50,
            "Job10": 55,
        },
        "Worker2": {
            "Job1": 20,
            "Job2": 25,
            "Job3": 30,
            "Job4": 35,
            "Job5": 40,
            "Job6": 45,
            "Job7": 50,
            "Job8": 55,
            "Job9": 60,
            "Job10": 65,
        },
        "Worker3": {
            "Job1": 30,
            "Job2": 35,
            "Job3": 40,
            "Job4": 45,
            "Job5": 50,
            "Job6": 55,
            "Job7": 60,
            "Job8": 65,
            "Job9": 70,
            "Job10": 75,
        },
        "Worker4": {
            "Job1": 40,
            "Job2": 45,
            "Job3": 50,
            "Job4": 55,
            "Job5": 60,
            "Job6": 65,
            "Job7": 70,
            "Job8": 75,
            "Job9": 80,
            "Job10": 85,
        },
        "Worker5": {
            "Job1": 50,
            "Job2": 55,
            "Job3": 60,
            "Job4": 65,
            "Job5": 70,
            "Job6": 75,
            "Job7": 80,
            "Job8": 85,
            "Job9": 90,
            "Job10": 95,
        },
        "Worker6": {
            "Job1": 60,
            "Job2": 65,
            "Job3": 70,
            "Job4": 75,
            "Job5": 80,
            "Job6": 85,
            "Job7": 90,
            "Job8": 95,
            "Job9": 100,
            "Job10": 105,
        },
    }
    delay = {
        "Worker1": 0,
        "Worker2": 20,
        "Worker3": 10,
        "Worker4": 30,
        "Worker5": 15,
        "Worker6": 25,
    }

    # Evaluate the DRL scheduler using the saved model
    start_time = time.time()
    assignment, total_cost = evaluate_drl_scheduler(
        workers, jobs, cost_matrix, delay, model_path="drl_model.zip"
    )
    evaluation_time = time.time() - start_time

    print("Job Assignments:")
    print(assignment)
    print("Total Cost (including delay):", total_cost)
    print(f"Evaluation time: {evaluation_time:.2f} seconds")
