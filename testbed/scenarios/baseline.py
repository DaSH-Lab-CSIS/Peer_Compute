"""
Baseline Scenario - Low-volume, isolated requests to establish norms.
"""
import asyncio
from typing import Dict, Any
from scenarios.base_scenario import BaseScenario
from core.load_balancer_client import LoadBalancerClient
from utils.distributions import get_interval


class BaselineScenario(BaseScenario):
    """Baseline scenario for establishing performance norms."""
    
    async def run(self) -> 'MetricsCollector':
        """Run the baseline scenario."""
        self.logger.info(f"Starting baseline scenario (run_id: {self.run_id})")
        self.metrics_collector.start_collection()
        
        total_requests = self.config.get('total_requests', 100)
        concurrency = self.config.get('concurrency', 5)
        services = self.config.get('services', [])
        service_weights = self.config.get('service_weights', {})
        frequency_config = self.config.get('frequency', {})
        invocations = self.config.get('invocations', 1)
        ilp_config = self.config.get('ilp_config', {})
        
        self.logger.info(f"Total requests: {total_requests}, Concurrency: {concurrency}")
        
        # Log seed if set
        seed = self.config.get('seed')
        if seed is not None:
            self.logger.info(f"Using random seed: {seed} (reproducible)")
        elif self.replay_file:
            self.logger.info(f"Replay mode: Using saved requests from {self.replay_file}")
        
        # Log ILP configuration if available
        if ilp_config:
            expected_min = ilp_config.get('expected_batch_size_min', 'N/A')
            expected_max = ilp_config.get('expected_batch_size_max', 'N/A')
            self.logger.info(
                f"ILP Config: Expected batch size {expected_min}-{expected_max}, "
                f"Max solve time: {ilp_config.get('max_solve_time', 'N/A')}s"
            )
        
        # Load saved requests if replay mode
        if self.replay_file:
            saved_data = self.request_generator.load_requests(self.replay_file)
            requests = saved_data['requests']
            # Generate timing intervals (these can still be random or use saved intervals)
            intervals = self.request_generator.generate_timing_sequence(
                count=len(requests),
                **frequency_config
            )
            self.logger.info(f"Replaying {len(requests)} requests from {self.replay_file}")
        else:
            # Generate all request payloads
            requests = self.request_generator.generate_requests(
                count=total_requests,
                service_selection="from_list" if services else "weighted",
                number_of_invocations=invocations,
                chained=False,
                input_data="None",
                run_multiple_invocations=False,
                service_weights=service_weights,
                service_list=services
            )
            
            # Generate timing intervals
            intervals = self.request_generator.generate_timing_sequence(
                count=total_requests,
                **frequency_config
            )
            
            # Save requests if requested
            if hasattr(self, 'save_requests') and self.save_requests:
                save_path = f"testbed/results/requests/{self.run_id}_requests.json"
                self.request_generator.save_requests(requests, save_path)
                self.logger.info(f"Saved {len(requests)} requests to {save_path}")
        
        # Update total_requests if replay mode changed it
        if self.replay_file:
            total_requests = len(requests)
        
        # If save_only mode, skip sending requests
        if hasattr(self, 'save_only') and self.save_only:
            self.logger.info("Save-only mode: Skipping request execution")
            self.metrics_collector.stop_collection()
            return self.metrics_collector
        
        async with LoadBalancerClient(base_url=self.load_balancer_url) as client:
            # Send requests with controlled concurrency and timing
            semaphore = asyncio.Semaphore(concurrency)
            
            async def send_with_timing(index: int):
                async with semaphore:
                    # Wait for the appropriate interval
                    if index > 0:
                        await asyncio.sleep(intervals[index - 1])
                    
                    payload = requests[index]
                    result = await self.send_request(client, payload)
                    
                    if result.get('success'):
                        self.logger.debug(f"Request {index + 1}/{total_requests} succeeded")
                    else:
                        self.logger.warning(f"Request {index + 1}/{total_requests} failed: {result.get('error')}")
            
            # Create tasks
            tasks = [send_with_timing(i) for i in range(total_requests)]
            
            # Run with progress logging
            completed = 0
            for coro in asyncio.as_completed(tasks):
                await coro
                completed += 1
                if completed % 10 == 0:
                    self.logger.info(f"Progress: {completed}/{total_requests} requests completed")
        
        self.metrics_collector.stop_collection()
        self.logger.info(f"Baseline scenario completed (run_id: {self.run_id})")
        
        return self.metrics_collector

