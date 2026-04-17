"""Registry for prediction strategies.

Strategies are resolved by name from the Django setting
``RUNTIME_PREDICTION_STRATEGY`` (default ``"cpi"``). The resolved instance is
cached on first use.
"""

from __future__ import annotations

from threading import Lock
from typing import Dict, Optional, Type

from .base import PredictionStrategy
from .cpi_strategy import CPIStrategy
from .scaling_strategy import ScalingFactorStrategy

_STRATEGIES: Dict[str, Type[PredictionStrategy]] = {
    "cpi": CPIStrategy,
    "scaling": ScalingFactorStrategy,
}

_instance_lock = Lock()
_instance: Optional[PredictionStrategy] = None
_instance_name: Optional[str] = None


def register_strategy(name: str, cls: Type[PredictionStrategy]) -> None:
    """Register a new strategy class under ``name``. Intended for plug-ins/tests."""
    _STRATEGIES[name] = cls


def _resolve_strategy_name() -> str:
    try:
        from django.conf import settings

        return getattr(settings, "RUNTIME_PREDICTION_STRATEGY", "cpi") or "cpi"
    except Exception:
        return "cpi"


def get_strategy() -> PredictionStrategy:
    """Return the currently-configured strategy instance (cached)."""
    global _instance, _instance_name
    name = _resolve_strategy_name()
    with _instance_lock:
        if _instance is None or _instance_name != name:
            cls = _STRATEGIES.get(name)
            if cls is None:
                raise ValueError(
                    f"Unknown RUNTIME_PREDICTION_STRATEGY {name!r}; "
                    f"available: {sorted(_STRATEGIES)}"
                )
            _instance = cls()
            _instance_name = name
        return _instance


def reset_cache() -> None:
    """Drop the cached strategy instance. Useful in tests."""
    global _instance, _instance_name
    with _instance_lock:
        _instance = None
        _instance_name = None
