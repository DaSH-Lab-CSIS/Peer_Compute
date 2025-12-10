"""
Bursty Load Scenario - Sudden spikes with Poisson distribution.
"""
import asyncio
from typing import Dict, Any
from scenarios.base_scenario import BaseScenario
from core.load_balancer_client import LoadBalancerClient
from utils.distributions import poisson_interval


class BurstyLoadScenario(BaseScenario):
    """Bursty load scenario for testing load balancer responsiveness."""
    
    async def run(self) -> 'MetricsCollector':
        """Run the bursty load scenario."""
        self.logger.info(f"Starting bursty load scenario (run_id: {self.run_id})")
        self.metrics_collector.start_collection()
        
        burst_size = self.config.get('burst_size', 200)
        burst_window = self.config.get('burst_window', 10.0)  # seconds
        repeat_count = self.config.get('repeat_count', 5)
        services = self.config.get('services', [])
        frequency_mean = self.config.get('frequency_mean', 1.0)
        invocations = self.config.get('invocations', 1)
        idle_period = self.config.get('idle_period', 30.0)  # seconds between bursts
        
        self.logger.info(
            f"Burst size: {burst_size}, Window: {burst_window}s, "
            f"Repeats: {repeat_count}, Idle: {idle_period}s"
        )
        
        async with LoadBalancerClient(base_url=self.load_balancer_url) as client:
            # Load saved requests if replay mode
            all_saved_requests = None
            if self.replay_file:
                saved_data = self.request_generator.load_requests(self.replay_file)
                all_saved_requests = saved_data['requests']
                self.logger.info(f"Replaying {len(all_saved_requests)} requests from {self.replay_file}")
            
            request_index = 0
            for burst_num in range(repeat_count):
                self.logger.info(f"Starting burst {burst_num + 1}/{repeat_count}")
                
                # Use saved requests or generate new ones
                if all_saved_requests and request_index < len(all_saved_requests):
                    # Take next burst_size requests from saved list
                    end_index = min(request_index + burst_size, len(all_saved_requests))
                    requests = all_saved_requests[request_index:end_index]
                    request_index = end_index
                    # Pad if needed
                    while len(requests) < burst_size:
                        requests.append(requests[-1] if requests else self.request_generator.generate_request_payload(
                            service_selection="from_list" if services else "weighted",
                            number_of_invocations=invocations,
                            service_list=services
                        ))
                else:
                    # Generate requests for this burst
                    requests = self.request_generator.generate_requests(
                        count=burst_size,
                        service_selection="from_list" if services else "weighted",
                        number_of_invocations=invocations,
                        chained=False,
                        input_data="None",
                        run_multiple_invocations=False,
                        service_list=services
                    )
                
                # Generate Poisson-distributed intervals within burst window
                intervals = []
                current_time = 0.0
                while current_time < burst_window and len(intervals) < burst_size:
                    interval = poisson_interval(mean=frequency_mean, min_interval=0.01)
                    if current_time + interval <= burst_window:
                        intervals.append(interval)
                        current_time += interval
                    else:
                        break
                
                # Pad to burst_size if needed
                while len(intervals) < burst_size:
                    intervals.append(0.0)  # Send immediately
                
                # Send requests in burst
                start_time = asyncio.get_event_loop().time()
                tasks = []
                
                for i, payload in enumerate(requests[:len(intervals)]):
                    if i == 0:
                        send_time = start_time
                    else:
                        send_time = start_time + sum(intervals[:i])
                    
                    async def send_at_time(req_payload: Dict, send_t: float):
                        await asyncio.sleep(max(0, send_t - asyncio.get_event_loop().time()))
                        return await self.send_request(client, req_payload)
                    
                    task = asyncio.create_task(send_at_time(payload, send_time))
                    tasks.append(task)
                
                # Wait for burst to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)
                successful = sum(1 for r in results if not isinstance(r, Exception) and r.get('success', False))
                
                burst_end_time = asyncio.get_event_loop().time()
                actual_duration = burst_end_time - start_time
                
                self.logger.info(
                    f"  Burst {burst_num + 1} completed: {successful}/{len(tasks)} successful "
                    f"in {actual_duration:.2f}s"
                )
                
                # Idle period between bursts (except after last burst)
                if burst_num < repeat_count - 1:
                    self.logger.info(f"  Idle period: {idle_period}s")
                    await asyncio.sleep(idle_period)
        
        self.metrics_collector.stop_collection()
        self.logger.info(f"Bursty load scenario completed (run_id: {self.run_id})")
        
        return self.metrics_collector

