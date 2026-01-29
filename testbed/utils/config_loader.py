"""
Config Loader - Loads YAML/JSON configuration files.
"""
import yaml
import json
from pathlib import Path
from typing import Dict, Any, Optional


def load_yaml(file_path: str) -> Dict[str, Any]:
    """
    Load a YAML configuration file.
    
    Args:
        file_path: Path to YAML file
        
    Returns:
        Dictionary containing configuration
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {file_path}")
    
    with open(path, 'r') as f:
        return yaml.safe_load(f) or {}


def load_json(file_path: str) -> Dict[str, Any]:
    """
    Load a JSON configuration file.
    
    Args:
        file_path: Path to JSON file
        
    Returns:
        Dictionary containing configuration
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {file_path}")
    
    with open(path, 'r') as f:
        return json.load(f)


def load_config(file_path: str) -> Dict[str, Any]:
    """
    Load a configuration file (YAML or JSON).
    
    Args:
        file_path: Path to config file
        
    Returns:
        Dictionary containing configuration
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    
    if suffix in ['.yaml', '.yml']:
        return load_yaml(file_path)
    elif suffix == '.json':
        return load_json(file_path)
    else:
        # Try YAML first, then JSON
        try:
            return load_yaml(file_path)
        except:
            return load_json(file_path)


def get_scenario_config(
    config_dir: str,
    scenario_name: str
) -> Dict[str, Any]:
    """
    Get configuration for a specific scenario.
    
    Args:
        config_dir: Directory containing scenarios.yaml
        scenario_name: Name of the scenario
        
    Returns:
        Scenario configuration dictionary
    """
    scenarios_path = Path(config_dir) / "scenarios.yaml"
    scenarios = load_yaml(str(scenarios_path))
    
    if scenario_name not in scenarios:
        raise ValueError(f"Scenario '{scenario_name}' not found in config")
    
    return scenarios[scenario_name]


def get_services_config(config_dir: str) -> Dict[str, Any]:
    """
    Get services configuration.
    
    Args:
        config_dir: Directory containing services.yaml
        
    Returns:
        Services configuration dictionary
    """
    services_path = Path(config_dir) / "services.yaml"
    if not services_path.exists():
        return {}
    
    return load_yaml(str(services_path))



