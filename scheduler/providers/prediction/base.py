"""Contracts for the pluggable prediction engine.

``PredictionInput`` / ``ServicePredInput`` are intentionally plain dataclasses
of primitives (no Django model references) so that strategies stay free of
ORM coupling and can be unit tested without a database.

Note that the arguments received by predict() will be PredictionInput, which is Per-Provider stats + a list of ServicePredInput.
Essentially, when predict() is called, it must return a PredictionOutput (dict of service=>runtime).
Note that if you create a _predict(Machine, Service) it should be called on all service to get the expected PredictionOutput (which has runtimes for all benchmark services for a given provider)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass
class ServicePredInput:
    """Per-service features consumed by a prediction strategy."""

    service_id: int
    cpu_cycles_required: Optional[int] = None
    memory_footprint: Optional[int] = None
    memory_bytes_per_second: Optional[int] = None
    reference_stats: Optional[dict] = None


@dataclass
class PredictionInput:
    """Per-provider features + the list of services to predict for."""

    provider_id: int
    cpi: Optional[Decimal] = None
    memory_bandwidth: Optional[Decimal] = None
    clock_hz: Optional[int] = None
    cpu_efficiency_score: Optional[Decimal] = None
    memory_efficiency_score: Optional[Decimal] = None
    services: List[ServicePredInput] = field(default_factory=list)


@dataclass
class PredictionOutput:
    """Result of a ``predict()`` call.

    ``runtimes_ms`` maps ``service_id -> predicted_runtime_ms``. A value of
    ``None`` means the strategy could not produce a prediction (e.g. the
    required benchmark data is missing); callers should substitute a default.
    """

    runtimes_ms: Dict[int, Optional[int]] = field(default_factory=dict)


class PredictionStrategy(ABC):
    """Abstract base for all runtime-prediction strategies.

    Implementations must be stateless with respect to per-call data so they
    can be safely shared across threads.
    """

    name: str = "base"

    @abstractmethod
    def predict(self, data: PredictionInput) -> PredictionOutput:  # pragma: no cover - interface
        raise NotImplementedError
