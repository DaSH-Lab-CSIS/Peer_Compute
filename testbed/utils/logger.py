"""
Structured Logger - Provides structured logging for testbed operations.
"""
import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


def setup_logger(
    name: str = "testbed",
    log_level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_dir: Optional[str] = None
) -> logging.Logger:
    """
    Set up a structured logger.
    
    Args:
        name: Logger name
        log_level: Logging level
        log_file: Optional log file name
        log_dir: Optional log directory (defaults to results/ if log_file specified)
        
    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        if log_dir:
            log_path = Path(log_dir) / log_file
        else:
            log_path = Path("testbed/results") / log_file
        
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(log_level)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger



