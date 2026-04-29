"""
Service Analyzer - Analyzes avg_job_times.json to categorize services and provide selection utilities.
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import random
import yaml


class ServiceAnalyzer:
    """Analyzes service runtime characteristics from avg_job_times.json"""
    
    def __init__(self, avg_job_times_path: Optional[str] = None):
        """
        Initialize the service analyzer.
        
        Args:
            avg_job_times_path: Path to avg_job_times.json. If None, looks in project root.
        """
        if avg_job_times_path is None:
            # Look for avg_job_times.json in project root (parent of testbed/)
            project_root = Path(__file__).parent.parent.parent
            avg_job_times_path = project_root / "avg_job_times.json"
        
        self.avg_job_times_path = Path(avg_job_times_path)
        self.service_stats: Dict[int, Dict] = {}
        self.service_categories: Dict[str, List[int]] = {
            'light': [],    # < 5s
            'medium': [],   # 5-10s
            'heavy': []     # > 10s
        }
        
        self._load_and_analyze()
    
    def _load_and_analyze(self):
        """Load avg_job_times.json and analyze service characteristics."""
        if not self.avg_job_times_path.exists():
            self._load_from_services_config()
            return
        
        with open(self.avg_job_times_path, 'r') as f:
            data = json.load(f)
        
        # Group by service_id and calculate averages
        service_runtimes: Dict[int, List[int]] = defaultdict(list)
        # TODO: Future - also track total_time and pull_time
        # service_total_times: Dict[int, List[int]] = defaultdict(list)
        # service_pull_times: Dict[int, List[int]] = defaultdict(list)
        
        for entry in data:
            service_id = entry.get('service_id')
            run_time = entry.get('run_time')
            
            if service_id is not None and run_time is not None:
                service_runtimes[service_id].append(run_time)
                # TODO: Future - include total_time and pull_time analysis
                # total_time = entry.get('total_time')
                # pull_time = entry.get('pull_time')
                # if total_time is not None:
                #     service_total_times[service_id].append(total_time)
                # if pull_time is not None:
                #     service_pull_times[service_id].append(pull_time)
        
        # Calculate average run_time per service
        for service_id, run_times in service_runtimes.items():
            avg_runtime = sum(run_times) / len(run_times)
            min_runtime = min(run_times)
            max_runtime = max(run_times)
            
            self.service_stats[service_id] = {
                'avg_runtime': avg_runtime,
                'min_runtime': min_runtime,
                'max_runtime': max_runtime,
                'sample_count': len(run_times),
                'runtimes': run_times
            }
            
            # Categorize by average runtime
            if avg_runtime < 5000:  # < 5 seconds
                self.service_categories['light'].append(service_id)
            elif avg_runtime < 10000:  # 5-10 seconds
                self.service_categories['medium'].append(service_id)
            else:  # > 10 seconds
                self.service_categories['heavy'].append(service_id)
        
        # TODO: Future - calculate average total_time and pull_time per service
        # for service_id, total_times in service_total_times.items():
        #     if service_id in self.service_stats:
        #         self.service_stats[service_id]['avg_total_time'] = sum(total_times) / len(total_times)
        # for service_id, pull_times in service_pull_times.items():
        #     if service_id in self.service_stats:
        #         self.service_stats[service_id]['avg_pull_time'] = sum(pull_times) / len(pull_times)

    def _load_from_services_config(self):
        """
        Fallback when avg_job_times.json is unavailable.
        Uses testbed/config/services.yaml service_categories/known_services.
        """
        services_cfg_path = Path(__file__).parent.parent / "config" / "services.yaml"
        if not services_cfg_path.exists():
            raise FileNotFoundError(
                f"avg_job_times.json not found at {self.avg_job_times_path} "
                f"and fallback services config missing at {services_cfg_path}"
            )

        with open(services_cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        explicit_categories = cfg.get("service_categories") or {}
        known_services = cfg.get("known_services") or []

        # Build category buckets from explicit mapping first.
        light_ids = [int(s) for s in explicit_categories.get("light", [])]
        medium_ids = [int(s) for s in explicit_categories.get("medium", [])]
        heavy_ids = [int(s) for s in explicit_categories.get("heavy", [])]

        # If explicit categories are missing, treat known services as medium.
        if not (light_ids or medium_ids or heavy_ids):
            medium_ids = [int(s) for s in known_services]

        self.service_categories = {
            "light": light_ids,
            "medium": medium_ids,
            "heavy": heavy_ids,
        }

        # Create synthetic stats so API remains consistent.
        # Values are representative placeholders for category class.
        category_defaults = {
            "light": 3000.0,
            "medium": 7000.0,
            "heavy": 15000.0,
        }
        for category, service_ids in self.service_categories.items():
            default_rt = category_defaults[category]
            for service_id in service_ids:
                self.service_stats[service_id] = {
                    "avg_runtime": default_rt,
                    "min_runtime": default_rt,
                    "max_runtime": default_rt,
                    "sample_count": 1,
                    "runtimes": [default_rt],
                }
    
    def get_service_stats(self, service_id: int) -> Optional[Dict]:
        """Get statistics for a specific service."""
        return self.service_stats.get(service_id)
    
    def get_all_services(self) -> List[int]:
        """Get list of all service IDs."""
        return list(self.service_stats.keys())
    
    def get_services_by_category(self, category: str) -> List[int]:
        """
        Get services in a specific category.
        
        Args:
            category: 'light', 'medium', or 'heavy'
        """
        return self.service_categories.get(category, [])
    
    def categorize_service(self, service_id: int) -> Optional[str]:
        """Get the category of a specific service."""
        for category, services in self.service_categories.items():
            if service_id in services:
                return category
        return None
    
    def select_service_weighted(
        self,
        light_weight: float = 0.4,
        medium_weight: float = 0.4,
        heavy_weight: float = 0.2
    ) -> int:
        """
        Select a service using weighted random sampling by category.
        
        Args:
            light_weight: Probability of selecting a light service
            medium_weight: Probability of selecting a medium service
            heavy_weight: Probability of selecting a heavy service
            
        Returns:
            Selected service ID
        """
        # Normalize weights
        total_weight = light_weight + medium_weight + heavy_weight
        light_weight /= total_weight
        medium_weight /= total_weight
        heavy_weight /= total_weight
        
        # Select category based on weights
        rand = random.random()
        if rand < light_weight:
            category = 'light'
        elif rand < light_weight + medium_weight:
            category = 'medium'
        else:
            category = 'heavy'
        
        # Select random service from category
        services = self.service_categories.get(category, [])
        if not services:
            # Fallback to all services if category is empty
            services = self.get_all_services()
        
        return random.choice(services) if services else None
    
    def select_service_uniform(self) -> int:
        """Select a service uniformly at random from all services."""
        services = self.get_all_services()
        return random.choice(services) if services else None
    
    def select_service_from_list(self, service_list: List[int]) -> int:
        """Select a service uniformly from a provided list."""
        return random.choice(service_list) if service_list else None
    
    def get_summary(self) -> Dict:
        """Get a summary of service analysis."""
        return {
            'total_services': len(self.service_stats),
            'categories': {
                'light': len(self.service_categories['light']),
                'medium': len(self.service_categories['medium']),
                'heavy': len(self.service_categories['heavy'])
            },
            'service_ids': self.get_all_services(),
            'category_breakdown': {
                cat: services
                for cat, services in self.service_categories.items()
            }
        }



