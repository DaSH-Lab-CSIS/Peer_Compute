"""
Steady Load Scenario - Constant RPS over sustained periods with ramping.
"""
import asyncio
from typing import Dict, Any
from scenarios.base_scenario import BaseScenario
from core.load_balancer_client import LoadBalancerClient


class SteadyLoadScenario(BaseScenario):
    """Steady load scenario for measuring throughput ceilings."""
    
    async def run(self) -> 'MetricsCollector':
        """Run the steady load scenario."""
        self.logger.info(f"Starting steady load scenario (run_id: {self.run_id})")
        self.metrics_collector.start_collection()
        
        rps_levels = self.config.get('rps_levels', [1, 5, 10, 20, 30, 50])
        duration_per_level = self.config.get('duration_per_level', 300)  # seconds
        services = self.config.get('services', [])
        interval = self.config.get('interval', 1.0)
        invocations = self.config.get('invocations', 1)
        
        # Calculate total requests
        total_requests = sum(int(rps * duration_per_level) for rps in rps_levels)
        
        self.logger.info(f"RPS levels: {rps_levels}, Duration per level: {duration_per_level}s")
        self.logger.info(f"Total requests across all levels: {total_requests}")
        
        async with LoadBalancerClient(base_url=self.load_balancer_url) as client:
            for level_idx, target_rps in enumerate(rps_levels):
                self.logger.info(f"Starting RPS level {level_idx + 1}/{len(rps_levels)}: {target_rps} RPS")
                
                # Calculate interval between requests to achieve target RPS
                request_interval = 1.0 / target_rps if target_rps > 0 else interval
                total_requests = int(target_rps * duration_per_level)
                
                self.logger.info(f"  Target: {target_rps} RPS, Interval: {request_interval:.3f}s, Total requests: {total_requests}")
                
                # Load saved requests if replay mode (only for first level)
                if self.replay_file and level_idx == 0:
                    saved_data = self.request_generator.load_requests(self.replay_file)
                    all_saved_requests = saved_data['requests']
                    # Calculate how many requests we need up to this point
                    requests_needed = sum(int(rps * duration_per_level) for rps in rps_levels[:level_idx+1])
                    requests = all_saved_requests[:requests_needed] if len(all_saved_requests) >= requests_needed else all_saved_requests
                    self.logger.info(f"Replaying {len(requests)} requests from {self.replay_file}")
                else:
                    # Generate requests for this level
                    requests = self.request_generator.generate_requests(
                        count=total_requests,
                        service_selection="from_list" if services else "weighted",
                        number_of_invocations=invocations,
                        chained=False,
                        input_data="None",
                        run_multiple_invocations=False,
                        service_list=services
                    )
                
                # Send requests at target rate
                start_time = asyncio.get_event_loop().time()
                sent_count = 0
                
                async def send_request_at_time(request_index: int, send_time: float):
                    await asyncio.sleep(max(0, send_time - asyncio.get_event_loop().time()))
                    payload = requests[request_index]
                    result = await self.send_request(client, payload)
                    return result
                
                # Schedule requests
                tasks = []
                for i in range(total_requests):
                    send_time = start_time + (i * request_interval)
                    task = asyncio.create_task(send_request_at_time(i, send_time))
                    tasks.append(task)
                
                # Wait for all requests in this level
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Log progress
                successful = sum(1 for r in results if not isinstance(r, Exception) and r.get('success', False))
                self.logger.info(f"  Level {level_idx + 1} completed: {successful}/{total_requests} successful")
        
        self.metrics_collector.stop_collection()
        
        # Collect batch metrics from load balancer
        await self.collect_batch_metrics()
        
        self.logger.info(f"Steady load scenario completed (run_id: {self.run_id})")
        
        return self.metrics_collector

