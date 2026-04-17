"""Pluggable runtime-prediction engine.

Public API:
    predict(data: PredictionInput) -> PredictionOutput
    get_strategy() -> PredictionStrategy

Strategies are resolved from the Django setting ``RUNTIME_PREDICTION_STRATEGY``
(default ``"cpi"``) via the registry in ``providers.prediction.registry``.
"""

from .base import (
    PredictionInput,
    PredictionOutput,
    PredictionStrategy,
    ServicePredInput,
)
from .registry import get_strategy


def predict(data: PredictionInput) -> PredictionOutput:
    """Run the currently-configured prediction strategy against ``data``."""
    return get_strategy().predict(data)


__all__ = [
    "PredictionInput",
    "PredictionOutput",
    "PredictionStrategy",
    "ServicePredInput",
    "get_strategy",
    "predict",
]
