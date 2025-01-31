import gymnasium as gym
from gymnasium import spaces
import numpy as np
import random
import time
from stable_baselines3 import DQN

class SchedulingEnv(gym.Env):
    def __init__(self, workers, jobs, cost_matrix, delay):
        super(SchedulingEnv, self).__init__()
        self.workers = workers
        self.jobs = jobs
        self.cost_matrix = cost_matrix
        self.delay = delay

        self.num_workers = len(workers)
        self.num_jobs = len(jobs)

        # Define action and observation space
        self.action_space = spaces.Discrete(self.num_workers * self.num_jobs)
        self.observation_space = spaces.Box(
            low=0, high=1, shape=(self.num_workers + self.num_jobs,), dtype=np.float32
        )

        self.reset()

    def reset(self):
        self.job_status = [0] * self.num_jobs  # 0: unassigned, 1: assigned
        self.worker_status = [0] * self.num_workers  # 0: available, 1: assigned
        self.current_step = 0
        self.total_cost = 0
        return self._get_obs()

    def _get_obs(self):
        return np.array(self.worker_status + self.job_status, dtype=np.float32)

    def step(self, action):
        worker_idx = action % self.num_workers
        job_idx = action // self.num_workers

        reward = 0
        done = False

        if self.job_status[job_idx] == 1:
            # Invalid action: job already assigned
            reward -= 100  # Heavy penalty
        else:
            # Assign job to worker
            self.job_status[job_idx] = 1
            self.worker_status[worker_idx] = 1  # Mark worker as assigned

            # Calculate cost
            cost = self.cost_matrix[self.workers[worker_idx]][self.jobs[job_idx]]
            delay_cost = (
                self.delay[self.workers[worker_idx]]
                if sum(self.worker_status) == 1
                else 0
            )
            total_action_cost = cost + delay_cost
            self.total_cost += total_action_cost

            # Reward is negative of cost
            reward -= total_action_cost

        self.current_step += 1

        # Check if all jobs are assigned
        if all(status == 1 for status in self.job_status):
            done = True

        obs = self._get_obs()
        info = {}
        return obs, reward, done, info

    def render(self, mode="human"):
        pass  # Rendering is not needed for this context

    def close(self):
        pass


def generate_random_data(num_samples, workers, jobs):
    data = []
    for _ in range(num_samples):
        # Randomly generate cost matrix and delay
        cost_matrix = {}
        delay = {}
        for worker in workers:
            cost_matrix[worker] = {}
            for job in jobs:
                cost_matrix[worker][job] = random.randint(10, 100)
            delay[worker] = random.randint(0, 30)
        data.append((cost_matrix, delay))
    return data


def train_drl_scheduler(
    workers, jobs, training_data, timesteps=50000, model_save_path="drl_model.zip"
):
    # Initialize environment with the first dataset
    env = SchedulingEnv(workers, jobs, training_data[0][0], training_data[0][1])
    model = DQN("MlpPolicy", env, verbose=1)

    # Train on each dataset sample
    for cost_matrix, delay in training_data:
        env.cost_matrix = cost_matrix
        env.delay = delay
        env.reset()
        model.set_env(env)
        try:
            model.learn(total_timesteps=timesteps, reset_num_timesteps=False)
        except Exception as e:
            print(e)
            print("try failed")

    # Save the trained model
    model.save(model_save_path)
    print(f"Model saved to {model_save_path}")
    return model


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

    # Generate random training data
    num_samples = 5  # Number of different datasets to train on
    training_data = generate_random_data(num_samples, workers, jobs)

    # Train the DRL scheduler and save the model
    start_time = time.time()
    train_drl_scheduler(
        workers, jobs, training_data, timesteps=50000, model_save_path="drl_model.zip"
    )
    training_time = time.time() - start_time
    print(f"Training time: {training_time:.2f} seconds")
