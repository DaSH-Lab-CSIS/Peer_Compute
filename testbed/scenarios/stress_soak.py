"""
Stress/Soak Scenario - Maximum sustained load until failure or timeout.
"""
import asyncio
from typing import Dict, Any
from scenarios.base_scenario import BaseScenario
from core.load_balancer_client import LoadBalancerClient


class StressSoakScenario(BaseScenario):
    """Stress/soak scenario for uncovering memory leaks and scaling limits."""
    
    async def run(self) -> 'MetricsCollector':
        """Run the stress/soak scenario."""
        self.logger.info(f"Starting stress/soak scenario (run_id: {self.run_id})")
        self.metrics_collector.start_collection()
        
        target_rps = self.config.get('target_rps', 100)
        max_duration = self.config.get('max_duration', 3600)  # 1 hour default
        max_error_rate = self.config.get('max_error_rate', 0.10)  # 10%
        min_requests = self.config.get('min_requests')  # Optional minimum requests
        services = self.config.get('services', [])
        invocations = self.config.get('invocations', 1)
        chained = self.config.get('chained', False)
        check_interval = self.config.get('check_interval', 60.0)  # Check every minute
        
        self.logger.info(
            f"Target RPS: {target_rps}, Max duration: {max_duration}s, "
            f"Max error rate: {max_error_rate:.1%}"
        )
        if min_requests:
            self.logger.info(f"Minimum requests: {min_requests}")
        
        request_interval = 1.0 / target_rps if target_rps > 0 else 0.01
        start_time = asyncio.get_event_loop().time()
        last_check_time = start_time
        request_counter = 0
        
        async with LoadBalancerClient(base_url=self.load_balancer_url) as client:
            while True:
                current_time = asyncio.get_event_loop().time()
                elapsed = current_time - start_time
                
                # Check termination conditions
                metrics = self.metrics_collector.calculate_aggregates()
                total_requests_sent = metrics.get('total_requests', 0)
                
                # Check if max duration reached
                duration_reached = elapsed >= max_duration
                
                # Check error rate periodically
                error_rate_check = False
                if current_time - last_check_time >= check_interval:
                    error_rate = metrics.get('error_rate', 0.0)
                    
                    self.logger.info(
                        f"Progress check: {elapsed:.0f}s elapsed, "
                        f"{total_requests_sent} requests, "
                        f"error rate: {error_rate:.2%}"
                    )
                    
                    if error_rate >= max_error_rate:
                        self.logger.warning(
                            f"Error rate ({error_rate:.2%}) exceeded threshold ({max_error_rate:.1%})"
                        )
                        error_rate_check = True
                    
                    last_check_time = current_time
                
                # Check if min_requests is satisfied (if specified)
                min_requests_satisfied = True
                if min_requests is not None:
                    min_requests_satisfied = total_requests_sent >= min_requests
                    if not min_requests_satisfied:
                        remaining = min_requests - total_requests_sent
                        if request_counter % 100 == 0:
                            self.logger.debug(f"Remaining requests for minimum: {remaining}")
                
                # Terminate if: (duration OR error_rate) AND min_requests (if specified)
                should_terminate = False
                if min_requests is not None:
                    # Must satisfy min_requests AND (duration OR error_rate)
                    should_terminate = min_requests_satisfied and (duration_reached or error_rate_check)
                else:
                    # Original behavior: duration OR error_rate
                    should_terminate = duration_reached or error_rate_check
                
                if should_terminate:
                    if duration_reached:
                        self.logger.info(f"Maximum duration ({max_duration}s) reached")
                    if error_rate_check:
                        self.logger.info("Error rate threshold exceeded")
                    if min_requests is not None and min_requests_satisfied:
                        self.logger.info(f"Minimum requests ({min_requests}) satisfied")
                    break
                
                # Generate and send request
                payload = self.request_generator.generate_request_payload(
                    service_selection="from_list" if services else "weighted",
                    number_of_invocations=invocations,
                    chained=chained,
                    input_data="None",
                    run_multiple_invocations=False,
                    service_list=services
                )
                
                # Send request
                send_time = start_time + (request_counter * request_interval)
                await asyncio.sleep(max(0, send_time - current_time))
                
                result = await self.send_request(client, payload)
                request_counter += 1
                
                # Log every 100 requests
                if request_counter % 100 == 0:
                    self.logger.info(f"Sent {request_counter} requests ({elapsed:.0f}s elapsed)")
        
        self.metrics_collector.stop_collection()
        self.logger.info(f"Stress/soak scenario completed (run_id: {self.run_id})")
        
        return self.metrics_collector

