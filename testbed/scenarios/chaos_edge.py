"""
Chaos/Edge Scenario - Fault injection and edge case testing.
"""
import asyncio
import random
from typing import Dict, Any
from scenarios.base_scenario import BaseScenario
from core.load_balancer_client import LoadBalancerClient
from utils.distributions import uniform_interval


class ChaosEdgeScenario(BaseScenario):
    """Chaos/edge scenario for testing resilience and edge case handling."""
    
    async def run(self) -> 'MetricsCollector':
        """Run the chaos/edge scenario."""
        self.logger.info(f"Starting chaos/edge scenario (run_id: {self.run_id})")
        self.metrics_collector.start_collection()
        
        total_requests = self.config.get('total_requests', 200)
        fault_rate = self.config.get('fault_rate', 0.20)  # 20% faulty requests
        services = self.config.get('services', [])
        invalid_services = self.config.get('invalid_services', [9999, 9998, 9997])
        chained = self.config.get('chained', False)
        chained_services = self.config.get('chained_services', [])
        frequency_min = self.config.get('frequency_min', 0.1)
        frequency_max = self.config.get('frequency_max', 10.0)
        invocations = self.config.get('invocations', 1)
        
        fault_types = self.config.get('fault_types', ['invalid_service', 'malformed_input', 'negative_invocations'])
        
        self.logger.info(
            f"Total requests: {total_requests}, Fault rate: {fault_rate:.1%}, "
            f"Chained: {chained}"
        )
        
        async with LoadBalancerClient(base_url=self.load_balancer_url) as client:
            for i in range(total_requests):
                # Determine if this should be a faulty request
                is_faulty = random.random() < fault_rate
                
                if is_faulty:
                    # Generate faulty request
                    fault_type = random.choice(fault_types)
                    self.logger.debug(f"Generating faulty request: {fault_type}")
                    
                    if fault_type == 'invalid_service':
                        payload = self.request_generator.generate_faulty_request(
                            fault_type='invalid_service',
                            invalid_service_id=random.choice(invalid_services)
                        )
                    elif fault_type == 'malformed_input':
                        payload = self.request_generator.generate_faulty_request(
                            fault_type='malformed_input'
                        )
                    elif fault_type == 'negative_invocations':
                        payload = self.request_generator.generate_faulty_request(
                            fault_type='negative_invocations'
                        )
                    else:
                        payload = self.request_generator.generate_faulty_request()
                else:
                    # Generate normal request
                    if chained and chained_services:
                        # Use specific services for chained requests
                        payload = self.request_generator.generate_request_payload(
                            service_selection="from_list",
                            number_of_invocations=invocations,
                            chained=chained,
                            input_data="None",
                            run_multiple_invocations=False,
                            service_list=chained_services
                        )
                    else:
                        payload = self.request_generator.generate_request_payload(
                            service_selection="from_list" if services else "weighted",
                            number_of_invocations=invocations,
                            chained=chained,
                            input_data="None",
                            run_multiple_invocations=False,
                            service_list=services
                        )
                
                # Send request
                result = await self.send_request(client, payload)
                
                if result.get('success'):
                    self.logger.debug(f"Request {i + 1}/{total_requests} succeeded")
                else:
                    self.logger.debug(
                        f"Request {i + 1}/{total_requests} failed (expected for faults): "
                        f"{result.get('error', 'Unknown')}"
                    )
                
                # Random delay between requests
                delay = uniform_interval(frequency_min, frequency_max)
                await asyncio.sleep(delay)
                
                # Progress logging
                if (i + 1) % 50 == 0:
                    self.logger.info(f"Progress: {i + 1}/{total_requests} requests sent")
        
        self.metrics_collector.stop_collection()
        self.logger.info(f"Chaos/edge scenario completed (run_id: {self.run_id})")
        
        return self.metrics_collector

