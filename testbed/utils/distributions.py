"""
Timing Distributions - Utilities for generating request timing intervals.
"""
import random
import math
from typing import Optional

# Global random state for reproducibility
_random_state = None

def set_random_seed(seed: Optional[int] = None):
    """Set random seed for reproducible distributions."""
    global _random_state
    if seed is not None:
        random.seed(seed)
        try:
            import numpy as np
            np.random.seed(seed)
        except ImportError:
            pass
        _random_state = random.getstate()
    else:
        _random_state = None


def poisson_interval(mean: float, min_interval: Optional[float] = None) -> float:
    """
    Generate a random interval using Poisson distribution.
    
    Args:
        mean: Mean interval in seconds
        min_interval: Minimum interval (defaults to mean/10)
        
    Returns:
        Random interval in seconds
    """
    if min_interval is None:
        min_interval = mean / 10.0
    
    # Generate exponential random variable (Poisson inter-arrival times)
    interval = -mean * math.log(1.0 - random.random())
    
    return max(interval, min_interval)


def exponential_interval(rate: float, min_interval: Optional[float] = None) -> float:
    """
    Generate a random interval using exponential distribution.
    
    Args:
        rate: Rate parameter (lambda) - requests per second
        min_interval: Minimum interval
        
    Returns:
        Random interval in seconds
    """
    if min_interval is None:
        min_interval = 0.01
    
    # Exponential distribution: -ln(U) / lambda
    interval = -math.log(1.0 - random.random()) / rate
    
    return max(interval, min_interval)


def uniform_interval(min_val: float, max_val: float) -> float:
    """
    Generate a random interval using uniform distribution.
    
    Args:
        min_val: Minimum interval in seconds
        max_val: Maximum interval in seconds
        
    Returns:
        Random interval in seconds
    """
    return random.uniform(min_val, max_val)


def uniform_with_jitter(base_interval: float, jitter_percent: float = 0.2) -> float:
    """
    Generate a random interval with jitter around a base value.
    
    Args:
        base_interval: Base interval in seconds
        jitter_percent: Jitter as percentage of base (0.0 to 1.0)
        
    Returns:
        Random interval in seconds
    """
    jitter_range = base_interval * jitter_percent
    min_val = base_interval - jitter_range
    max_val = base_interval + jitter_range
    return uniform_interval(max(0.0, min_val), max_val)


def fixed_interval(interval: float) -> float:
    """
    Return a fixed interval (no randomness).
    
    Args:
        interval: Fixed interval in seconds
        
    Returns:
        The fixed interval
    """
    return interval


def get_interval(
    distribution_type: str,
    **kwargs
) -> float:
    """
    Get an interval based on distribution type.
    
    Args:
        distribution_type: Type of distribution ('poisson', 'exponential', 'uniform', 'uniform_jitter', 'fixed')
        **kwargs: Distribution-specific parameters
        
    Returns:
        Random interval in seconds
    """
    if distribution_type == 'poisson':
        return poisson_interval(
            mean=kwargs.get('mean', 1.0),
            min_interval=kwargs.get('min_interval')
        )
    elif distribution_type == 'exponential':
        return exponential_interval(
            rate=kwargs.get('rate', 1.0),
            min_interval=kwargs.get('min_interval')
        )
    elif distribution_type == 'uniform':
        return uniform_interval(
            min_val=kwargs.get('min', 0.0),
            max_val=kwargs.get('max', 1.0)
        )
    elif distribution_type == 'uniform_jitter':
        return uniform_with_jitter(
            base_interval=kwargs.get('base', 1.0),
            jitter_percent=kwargs.get('jitter_percent', 0.2)
        )
    elif distribution_type == 'fixed':
        return fixed_interval(kwargs.get('interval', 1.0))
    else:
        raise ValueError(f"Unknown distribution type: {distribution_type}")



