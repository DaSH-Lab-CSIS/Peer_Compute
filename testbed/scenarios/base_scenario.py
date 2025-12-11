"""
Base Scenario - Base class for all test scenarios.
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from core.service_analyzer import ServiceAnalyzer
from core.load_balancer_client import LoadBalancerClient
from core.request_generator import RequestGenerator
from core.metrics_collector import MetricsCollector
from utils.logger import setup_logger


class BaseScenario(ABC):
    """Base class for all test scenarios."""
    
    def __init__(
        self,
        config: Dict[str, Any],
        service_analyzer: ServiceAnalyzer,
        load_balancer_url: str = "http://localhost:9001",
        run_id: Optional[str] = None,
        seed: Optional[int] = None,
        replay_file: Optional[str] = None
    ):
        """
        Initialize the base scenario.
        
        Args:
            config: Scenario configuration dictionary
            service_analyzer: ServiceAnalyzer instance
            load_balancer_url: Load balancer base URL
            run_id: Optional run ID (generated if not provided)
            seed: Optional random seed for reproducibility
            replay_file: Optional path to saved requests file for replay
        """
        self.config = config
        self.service_analyzer = service_analyzer
        self.load_balancer_url = load_balancer_url
        self.run_id = run_id or f"{self.__class__.__name__}_{asyncio.get_event_loop().time()}"
        self.replay_file = replay_file
        
        # Use seed from config if not provided
        if seed is None:
            seed = config.get('seed')
        
        self.request_generator = RequestGenerator(service_analyzer, seed=seed)
        self.metrics_collector = MetricsCollector(self.run_id)
        self.logger = setup_logger(f"scenario.{self.__class__.__name__}")
        self.save_requests = False  # Set by main.py if needed
        self.save_only = False  # Set by main.py if needed
        
        # Set seed for distributions
        if seed is not None:
            from utils.distributions import set_random_seed
            set_random_seed(seed)
    
    @abstractmethod
    async def run(self) -> MetricsCollector:
        """
        Run the scenario.
        
        Returns:
            MetricsCollector with collected metrics
        """
        pass
    
    async def send_request(self, client: LoadBalancerClient, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a single request and collect metrics.
        
        Args:
            client: LoadBalancerClient instance
            payload: Request payload (with camelCase keys like serviceID)
            
        Returns:
            Request result dictionary
        """
        # Convert camelCase payload to snake_case parameters expected by LoadBalancerClient
        client_params = {
            'service_id': payload.get('serviceID'),
            'number_of_invocations': payload.get('numberOfInvocations', 1),
            'chained': payload.get('chained', False),
            'input_data': payload.get('input', 'None'),
            'run_multiple_invocations': payload.get('runMultipleInvocations', False)
        }
        
        result = await client.send_request(**client_params)
        
        # Extract batch metadata from response and track it
        if result.get('success') and result.get('batch_metadata'):
            request_id = result.get('request_id', '')
            self.metrics_collector.add_batch_from_metadata(
                result['batch_metadata'],
                request_id
            )
        
        self.metrics_collector.add_request(result)
        return result
    
    def get_metrics(self) -> MetricsCollector:
        """Get the metrics collector."""
        return self.metrics_collector
    
    async def collect_batch_metrics(self):
        """
        Collect batch metrics from the load balancer at the end of the test run.
        This queries the load balancer for recent batches and adds batch size information.
        """
        try:
            async with LoadBalancerClient(base_url=self.load_balancer_url) as client:
                # Get recent batches from load balancer (query a large number to get all batches)
                batches_data = await client.get_recent_batches(limit=1000)
                
                if 'error' in batches_data:
                    self.logger.warning(f"Failed to get batch metrics: {batches_data['error']}")
                    return
                
                batches = batches_data.get('batches', [])
                self.logger.info(f"Collected {len(batches)} batch records from load balancer")
                
                # Add batch size information to metrics collector
                for batch in batches:
                    batch_size = batch.get('batch_size')
                    if batch_size is not None:
                        # Check if this batch already exists in metrics collector
                        batch_id = batch.get('batch_id')
                        existing_batch = None
                        if batch_id:
                            for existing in self.metrics_collector.ilp_batches:
                                if existing.get('batch_id') == batch_id:
                                    existing_batch = existing
                                    break
                        
                        if existing_batch:
                            # Update existing batch with batch_size from scheduler
                            existing_batch['batch_size'] = batch_size
                        else:
                            # Create new batch entry with batch_size from scheduler
                            batch_metrics = {
                                'batch_id': batch_id or batch.get('correlation_id'),
                                'batch_size': batch_size,
                                'ilp_solve_time': batch.get('ilp_solve_time'),
                                'batch_processing_time': batch.get('processing_time'),
                                'scheduler_name': batch.get('scheduler_name')
                            }
                            self.metrics_collector.add_ilp_batch(batch_metrics)
        except Exception as e:
            self.logger.warning(f"Error collecting batch metrics: {e}")

