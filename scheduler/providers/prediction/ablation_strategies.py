"""Ablation baselines for the cold-start evaluation.

Each strategy removes one source of information from ``ScalingFactorStrategy``
so the evaluation can attribute placement quality to it (run with
``PREDICTION_FORCE_MODEL=true`` so history does not mask the strategy):

* ``uniform`` -- no runtime information: every (provider, service) pair costs the
  same, so the ILP is driven only by provider delay (in-flight load).
* ``ref``     -- function information only: ``t_ref(f)`` from the BEM with the
  machine scaling factor fixed at ``sigma = 1``. Identical to ``scaling`` in every
  other term (pull-time model, EMA blend), so ``ref`` vs ``scaling`` isolates the
  value of the machine benchmarks.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .base import PredictionInput, PredictionOutput, PredictionStrategy
from .scaling_strategy import ScalingFactorStrategy


class UniformStrategy(PredictionStrategy):
    """Same predicted runtime for every (provider, service) pair."""

    name = "uniform"

    # Matches the scheduler's DEFAULT_RUNTIME fallback, so ``uniform`` is the
    # explicitly labelled version of "no prediction available".
    RUNTIME_MS: int = 1000

    def predict(self, data: PredictionInput) -> PredictionOutput:
        return PredictionOutput(
            runtimes_ms={svc.service_id: self.RUNTIME_MS for svc in data.services}
        )


class ReferenceOnlyStrategy(ScalingFactorStrategy):
    """``scaling`` with the machine scaling factor fixed at 1 (t_ref only)."""

    name = "ref"

    @staticmethod
    def _resolve_ratios(
        provider: PredictionInput,
    ) -> Tuple[float, float, float, float]:
        return (1.0, 1.0, 1.0, 1.0)
