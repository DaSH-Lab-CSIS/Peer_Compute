"""CPI / memory-bandwidth based prediction strategy.

Formula::

    compute_time_ms = (cpu_cycles_required * cpi) / clock_hz * 1000
    memory_time_ms  = (memory_footprint / memory_bandwidth) * 1000
    predicted_ms    = max(compute_time_ms, memory_time_ms)

If any required field on the provider or service is missing (``None``), the
strategy returns ``None`` for that service so the caller can substitute a
default runtime. This lets the scheduler keep running before benchmarks have
been collected.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .base import (
    PredictionInput,
    PredictionOutput,
    PredictionStrategy,
    ServicePredInput,
)


class CPIStrategy(PredictionStrategy):
    name = "cpi"

    def predict(self, data: PredictionInput) -> PredictionOutput:
        runtimes: dict[int, Optional[int]] = {}
        for svc in data.services:
            runtimes[svc.service_id] = self._predict_one(data, svc)
        return PredictionOutput(runtimes_ms=runtimes)

    @staticmethod
    def _predict_one(
        provider: PredictionInput, svc: ServicePredInput
    ) -> Optional[int]:
        compute_ms = CPIStrategy._compute_time_ms(
            svc.cpu_cycles_required, provider.cpi, provider.clock_hz
        )
        memory_ms = CPIStrategy._memory_time_ms(
            svc.memory_footprint, provider.memory_bandwidth
        )
        if compute_ms is None and memory_ms is None:
            return None
        predicted = max(compute_ms or 0, memory_ms or 0)
        if predicted <= 0:
            return None
        return int(predicted)

    @staticmethod
    def _compute_time_ms(
        cpu_cycles_required: Optional[int],
        cpi: Optional[Decimal],
        clock_hz: Optional[int],
    ) -> Optional[float]:
        if cpu_cycles_required is None or cpi is None or not clock_hz:
            return None
        try:
            return float(cpu_cycles_required) * float(cpi) / float(clock_hz) * 1000.0
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def _memory_time_ms(
        memory_footprint: Optional[int],
        memory_bandwidth: Optional[Decimal],
    ) -> Optional[float]:
        if memory_footprint is None or not memory_bandwidth:
            return None
        try:
            bw = float(memory_bandwidth)
            if bw <= 0:
                return None
            return float(memory_footprint) / bw * 1000.0
        except (TypeError, ValueError, ZeroDivisionError):
            return None
