"""
Request Generator - Generates service requests based on scenario parameters.
"""
import random
from typing import Dict, List, Any, Optional
from core.service_analyzer import ServiceAnalyzer
from utils.distributions import get_interval


class RequestGenerator:
    """Generates service requests with various selection and timing strategies."""
    
    def __init__(self, service_analyzer: ServiceAnalyzer, seed: Optional[int] = None):
        """
        Initialize the request generator.
        
        Args:
            service_analyzer: ServiceAnalyzer instance for service selection
            seed: Optional random seed for reproducibility
        """
        self.service_analyzer = service_analyzer
        self.seed = seed
        if seed is not None:
            random.seed(seed)
            # Also seed numpy if available (for distributions)
            try:
                import numpy as np
                np.random.seed(seed)
            except ImportError:
                pass
    
    def generate_request_payload(
        self,
        service_id: Optional[int] = None,
        service_selection: str = "weighted",
        number_of_invocations: int = 1,
        chained: bool = False,
        input_data: str = "None",
        run_multiple_invocations: bool = False,
        service_weights: Optional[Dict[str, float]] = None,
        service_list: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Generate a single request payload.
        
        Args:
            service_id: Specific service ID (overrides selection strategy)
            service_selection: Selection strategy ('weighted', 'uniform', 'from_list', 'specific')
            number_of_invocations: Number of invocations
            chained: Whether this is a chained request
            input_data: Input data for the service
            run_multiple_invocations: Whether to run multiple invocations
            service_weights: Weights for weighted selection (light, medium, heavy)
            service_list: List of services for 'from_list' strategy
            
        Returns:
            Request payload dictionary
        """
        # Select service if not provided
        if service_id is None:
            if service_selection == "weighted":
                weights = service_weights or {
                    'light': 0.4,
                    'medium': 0.4,
                    'heavy': 0.2
                }
                service_id = self.service_analyzer.select_service_weighted(
                    light_weight=weights.get('light', 0.4),
                    medium_weight=weights.get('medium', 0.4),
                    heavy_weight=weights.get('heavy', 0.2)
                )
            elif service_selection == "uniform":
                service_id = self.service_analyzer.select_service_uniform()
            elif service_selection == "from_list":
                if service_list:
                    service_id = self.service_analyzer.select_service_from_list(service_list)
                else:
                    service_id = self.service_analyzer.select_service_uniform()
            elif service_selection == "specific":
                if service_list:
                    service_id = random.choice(service_list)
                else:
                    service_id = self.service_analyzer.select_service_uniform()
            else:
                service_id = self.service_analyzer.select_service_uniform()
        
        return {
            "serviceID": service_id,
            "numberOfInvocations": number_of_invocations,
            "chained": chained,
            "input": input_data,
            "runMultipleInvocations": run_multiple_invocations
        }
    
    def generate_requests(
        self,
        count: int,
        service_selection: str = "weighted",
        number_of_invocations: int = 1,
        chained: bool = False,
        input_data: str = "None",
        run_multiple_invocations: bool = False,
        service_weights: Optional[Dict[str, float]] = None,
        service_list: Optional[List[int]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate multiple request payloads.
        
        Args:
            count: Number of requests to generate
            service_selection: Selection strategy
            number_of_invocations: Number of invocations per request
            chained: Whether requests are chained
            input_data: Input data for services
            run_multiple_invocations: Whether to run multiple invocations
            service_weights: Weights for weighted selection
            service_list: List of services for selection
            
        Returns:
            List of request payloads
        """
        requests = []
        for _ in range(count):
            payload = self.generate_request_payload(
                service_selection=service_selection,
                number_of_invocations=number_of_invocations,
                chained=chained,
                input_data=input_data,
                run_multiple_invocations=run_multiple_invocations,
                service_weights=service_weights,
                service_list=service_list
            )
            requests.append(payload)
        
        return requests
    
    def save_requests(self, requests: List[Dict[str, Any]], filepath: str):
        """
        Save generated requests to a file for later replay.
        
        Args:
            requests: List of request payloads
            filepath: Path to save requests JSON file
        """
        import json
        from pathlib import Path
        
        output_path = Path(filepath)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        save_data = {
            'seed': self.seed,
            'requests': requests
        }
        
        with open(output_path, 'w') as f:
            json.dump(save_data, f, indent=2)
    
    @staticmethod
    def load_requests(filepath: str) -> Dict[str, Any]:
        """
        Load saved requests from a file.
        
        Args:
            filepath: Path to saved requests JSON file
            
        Returns:
            Dictionary with 'seed' and 'requests' keys
        """
        import json
        from pathlib import Path
        
        with open(Path(filepath), 'r') as f:
            return json.load(f)
    
    def generate_timing_sequence(
        self,
        count: int,
        distribution_type: str = "uniform",
        **distribution_params
    ) -> List[float]:
        """
        Generate a sequence of timing intervals.
        
        Args:
            count: Number of intervals to generate
            distribution_type: Type of distribution
            **distribution_params: Distribution-specific parameters
            
        Returns:
            List of intervals in seconds
        """
        intervals = []
        for _ in range(count):
            interval = get_interval(distribution_type, **distribution_params)
            intervals.append(interval)
        
        return intervals
    
    def generate_faulty_request(
        self,
        fault_type: str = "invalid_service",
        invalid_service_id: int = 9999
    ) -> Dict[str, Any]:
        """
        Generate a faulty request for chaos/edge testing.
        
        Args:
            fault_type: Type of fault ('invalid_service', 'malformed_input', 'negative_invocations')
            invalid_service_id: Service ID to use for invalid_service fault
            
        Returns:
            Faulty request payload
        """
        if fault_type == "invalid_service":
            return {
                "serviceID": invalid_service_id,
                "numberOfInvocations": 1,
                "chained": False,
                "input": "None",
                "runMultipleInvocations": False
            }
        elif fault_type == "malformed_input":
            # Return a valid structure but with potentially problematic input
            service_id = self.service_analyzer.select_service_uniform()
            return {
                "serviceID": service_id,
                "numberOfInvocations": 1,
                "chained": False,
                "input": "INVALID_JSON_STRING{malformed}",
                "runMultipleInvocations": False
            }
        elif fault_type == "negative_invocations":
            service_id = self.service_analyzer.select_service_uniform()
            return {
                "serviceID": service_id,
                "numberOfInvocations": -1,
                "chained": False,
                "input": "None",
                "runMultipleInvocations": False
            }
        else:
            # Default: invalid service
            return self.generate_faulty_request("invalid_service", invalid_service_id)

