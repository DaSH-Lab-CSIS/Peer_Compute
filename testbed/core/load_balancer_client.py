"""
Load Balancer Client - Async HTTP client for making requests to the load balancer API.
"""
import asyncio
import time
from typing import Dict, Optional, Any
from datetime import datetime
import httpx
from uuid import uuid4


class LoadBalancerClient:
    """Async HTTP client for load balancer API requests."""
    
    def __init__(
        self,
        base_url: str = "http://localhost:9001",
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        """
        Initialize the load balancer client.
        
        Args:
            base_url: Base URL of the load balancer
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.endpoint = f"{self.base_url}/loadbalancer/run_service/"
        self.status_endpoint = f"{self.base_url}/status"
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.client:
            await self.client.aclose()
    
    async def send_request(
        self,
        service_id: int,
        number_of_invocations: int = 1,
        chained: bool = False,
        input_data: str = "None",
        run_multiple_invocations: bool = False
    ) -> Dict[str, Any]:
        """
        Send a service request to the load balancer.
        
        Args:
            service_id: Service ID to invoke
            number_of_invocations: Number of invocations
            chained: Whether this is a chained request
            input_data: Input data for the service
            run_multiple_invocations: Whether to run multiple invocations
            
        Returns:
            Dictionary with request metadata and response
        """
        request_id = str(uuid4())
        enqueue_time = time.time()
        enqueue_timestamp = datetime.now().isoformat()
        
        payload = {
            "serviceID": service_id,
            "numberOfInvocations": number_of_invocations,
            "chained": chained,
            "input": input_data,
            "runMultipleInvocations": run_multiple_invocations
        }
        
        result = {
            'request_id': request_id,
            'service_id': service_id,
            'enqueue_time': enqueue_time,
            'enqueue_timestamp': enqueue_timestamp,
            'payload': payload,
            'success': False,
            'status_code': None,
            'response': None,
            'error': None,
            'latency': None
        }
        
        if not self.client:
            self.client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True
            )
        
        # Retry logic
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = await self.client.post(
                    self.endpoint,
                    json=payload,
                    headers={
                        "Accept": "*/*",
                        "Content-Type": "application/json"
                    }
                )
                
                result['status_code'] = response.status_code
                result['latency'] = time.time() - enqueue_time
                
                if response.status_code == 200:
                    try:
                        result['response'] = response.json()
                        result['success'] = True
                        
                        if isinstance(result['response'], dict):
                            # Promote job_id to top-level for easy tracking/export
                            job_id = result['response'].get('job_id')
                            if job_id is not None:
                                result['job_id'] = job_id

                            # Extract batch metadata from response if available
                            batch_metadata = result['response'].get('batch_metadata', {})
                            if batch_metadata:
                                result['batch_metadata'] = {
                                    'batch_id': batch_metadata.get('batch_id'),
                                    'current_batch_size': batch_metadata.get('current_batch_size'),
                                    'batch_age_seconds': batch_metadata.get('batch_age_seconds'),
                                    'ilp_state': batch_metadata.get('ilp_state'),
                                    'estimated_queue_depth': batch_metadata.get('estimated_queue_depth'),
                                    'batch_config': batch_metadata.get('batch_config', {})
                                }
                    except Exception as e:
                        result['error'] = f"Failed to parse JSON response: {str(e)}"
                        result['response'] = response.text
                else:
                    result['error'] = f"HTTP {response.status_code}: {response.text}"
                
                return result
                
            except httpx.TimeoutException as e:
                last_error = f"Request timeout: {str(e)}"
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    result['error'] = last_error
                    
            except httpx.ConnectError as e:
                last_error = f"Connection error: {str(e)}"
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    result['error'] = last_error
                    
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
                result['error'] = last_error
                return result
        
        result['error'] = last_error or "Unknown error"
        return result
    
    async def send_batch(
        self,
        requests: list[Dict[str, Any]],
        max_concurrency: int = 10
    ) -> list[Dict[str, Any]]:
        """
        Send multiple requests with controlled concurrency.
        
        Args:
            requests: List of request parameters (service_id, etc.)
            max_concurrency: Maximum concurrent requests
            
        Returns:
            List of request results
        """
        semaphore = asyncio.Semaphore(max_concurrency)
        
        async def send_with_semaphore(request_params):
            async with semaphore:
                return await self.send_request(**request_params)
        
        tasks = [send_with_semaphore(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    'request_id': str(uuid4()),
                    'error': f"Exception: {str(result)}",
                    'success': False
                })
            else:
                processed_results.append(result)
        
        return processed_results

    async def get_status(self) -> Dict[str, Any]:
        """
        Get load balancer status including batch information.
        
        Returns:
            Dictionary with load balancer status
        """
        if not self.client:
            self.client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True
            )
        
        try:
            response = await self.client.get(self.status_endpoint)
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': f"HTTP {response.status_code}"}
        except Exception as e:
            return {'error': str(e)}
    
    async def get_batch_info(self, batch_id: str) -> Dict[str, Any]:
        """
        Get information about a specific processed batch.
        
        Args:
            batch_id: Batch identifier
            
        Returns:
            Dictionary with batch information
        """
        if not self.client:
            self.client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True
            )
        
        try:
            response = await self.client.get(f"{self.base_url}/batch/{batch_id}")
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': f"HTTP {response.status_code}"}
        except Exception as e:
            return {'error': str(e)}
    
    async def get_recent_batches(self, limit: int = 20) -> Dict[str, Any]:
        """
        Get recent processed batches with ILP metrics.
        
        Args:
            limit: Maximum number of batches to return
            
        Returns:
            Dictionary with recent batches
        """
        if not self.client:
            self.client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True
            )
        
        try:
            response = await self.client.get(f"{self.base_url}/batches/recent", params={"limit": limit})
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': f"HTTP {response.status_code}"}
        except Exception as e:
            return {'error': str(e)}



