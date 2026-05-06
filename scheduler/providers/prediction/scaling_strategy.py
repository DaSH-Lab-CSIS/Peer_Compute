"""Scaling-factor runtime-prediction strategy.

Implements Algorithm 1 from ``docs/runtime_prediction.tex``: a benchmark-derived
cold-start prediction blended with an exponential moving average (EMA) of
observed runtimes, plus a piecewise pull-time adjustment based on image cache
state and machine throughput.

The math
--------

For a function ``f`` on a machine ``m`` with resource set
``R = {cpu, mem, disk, net}``::

    sigma(f, m)       = sum_i  w_i(f) * r_i(m)
    t_cold(f, m)      = t_ref(f) * sigma(f, m)

    t_hat(f, m)       = t_cold                               if n == 0
                      = (n / (n + kappa)) * EMA
                        + (kappa / (n + kappa)) * t_cold     if n >= 1

    t_pull(f, m)      = 0                                    if cached in memory
                      = V(f) / S_disk(m)                     if cached on disk
                      = V(f) / S_net(m)                      if cold pull

    predicted_ms      = round(t_hat + t_pull)

Expected inputs
---------------

This strategy reads the following optional fields that callers are expected to
populate (see ``docs/runtime_prediction.tex`` Section 10). Any missing field is
handled gracefully:

``PredictionInput`` (per-provider):
    * ``r_cpu``, ``r_mem``, ``r_disk``, ``r_net`` -- performance ratios
      ``S_i(m_0) / S_i(m)`` relative to the Benchmarking Environment Machine.
    * ``s_disk_mbps``, ``s_net_mbps`` -- absolute throughput in MB/s, used for
      pull time.

``ServicePredInput`` (per-service):
    * ``ref_runtime_ms`` -- ``t_ref(f)`` median BEM runtime.
    * ``w_cpu``, ``w_mem``, ``w_disk``, ``w_net`` -- resource sensitivity
      weights, intended to sum to ~1.
    * ``image_size_mb`` -- ``V(f)`` compressed image size.
    * ``ema_runtime_ms``, ``observation_count`` -- per-(provider, service) EMA
      state (to be pre-fetched by the caller from a summary table).
    * ``cache_state`` -- one of ``"memory"``, ``"disk"``, ``"cold"``.

Fallback policy
---------------

* Missing ``ref_runtime_ms`` -> return ``None`` for that service (caller
  substitutes a default).
* Missing individual ``r_i`` -> treat as ``1.0`` (BEM parity on that axis).
* All weights missing or sum below ``EPSILON`` -> equal weights 0.25 each.
* Partial weights -> zero-fill the missing ones and renormalize; fall back to
  equal weights if renormalized sum is still below ``EPSILON``.
* ``observation_count <= 0`` or ``ema_runtime_ms is None`` -> pure cold start.
* ``cache_state`` missing or unknown -> treat as ``"cold"``.
* ``s_disk_mbps`` / ``s_net_mbps`` missing when needed -> contribute ``0`` pull
  time (logged once per process on first occurrence to avoid spam).
* Any arithmetic error on a service -> ``None`` for that service; other
  services in the batch are unaffected.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from .base import (
    PredictionInput,
    PredictionOutput,
    PredictionStrategy,
    ServicePredInput,
)

_log = logging.getLogger(__name__)

_RESOURCES: Tuple[str, ...] = ("cpu", "mem", "disk", "net")


class ScalingFactorStrategy(PredictionStrategy):
    """Cold-start scaling factor + EMA-blended runtime predictor."""

    name = "scaling"

    # Bayesian-shrinkage pseudo-count: how many observations until the EMA
    # dominates the cold-start benchmark. Paper recommends [3, 7]; default 5.
    KAPPA: float = 5.0

    # EMA smoothing factor. Only used by the EMA update path (OnJobComplete),
    # not by predict(). Included here so both paths share one source of truth
    # once the update is implemented.
    ALPHA: float = 0.25

    # Threshold below which a sum of weights is treated as "all zero" and the
    # equal-weights fallback kicks in.
    EPSILON: float = 1e-6

    # One-time warnings for missing throughput fields, to avoid log spam.
    _warned_missing_s_disk: bool = False
    _warned_missing_s_net: bool = False

    def predict(self, data: PredictionInput) -> PredictionOutput:
        runtimes: dict[int, Optional[int]] = {}
        for svc in data.services:
            try:
                runtimes[svc.service_id] = self._predict_one(data, svc)
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning(
                    "[scaling] predict failed for service %s on provider %s: %s",
                    svc.service_id,
                    data.provider_id,
                    exc,
                )
                runtimes[svc.service_id] = None
        return PredictionOutput(runtimes_ms=runtimes)

    def _predict_one(
        self, provider: PredictionInput, svc: ServicePredInput
    ) -> Optional[int]:
        t_ref = _as_float(svc.ref_runtime_ms)
        if t_ref is None or t_ref <= 0:
            return None

        weights = self._resolve_weights(svc)
        ratios = self._resolve_ratios(provider)
        sigma = self._sigma(weights, ratios)
        t_cold = self._cold_start_ms(t_ref, sigma)
        if t_cold is None:
            return None

        t_hat = self._blend(
            t_cold=t_cold,
            ema=_as_float(svc.ema_runtime_ms),
            n=max(0, int(svc.observation_count or 0)),
            kappa=self.KAPPA,
        )

        t_pull = self._pull_time_ms(
            cache_state=svc.cache_state,
            image_size_mb=_as_float(svc.image_size_mb),
            s_disk_mbps=_as_float(provider.s_disk_mbps),
            s_net_mbps=_as_float(provider.s_net_mbps),
        )

        total = t_hat #+ t_pull
        if total <= 0:
            return None
        return int(round(total))

    @staticmethod
    def _resolve_weights(svc: ServicePredInput) -> Tuple[float, float, float, float]:
        """Return (w_cpu, w_mem, w_disk, w_net), normalized and fallback-filled."""
        raw = (
            _as_float(svc.w_cpu),
            _as_float(svc.w_mem),
            _as_float(svc.w_disk),
            _as_float(svc.w_net),
        )

        if all(w is None for w in raw):
            return (0.25, 0.25, 0.25, 0.25)

        filled = tuple(max(0.0, w) if w is not None else 0.0 for w in raw)
        total = sum(filled)
        if total < ScalingFactorStrategy.EPSILON:
            return (0.25, 0.25, 0.25, 0.25)
        return tuple(w / total for w in filled)  # type: ignore[return-value]

    @staticmethod
    def _resolve_ratios(
        provider: PredictionInput,
    ) -> Tuple[float, float, float, float]:
        """Return (r_cpu, r_mem, r_disk, r_net); missing axes default to 1.0."""
        return (
            _positive_or_default(provider.r_cpu, 1.0),
            _positive_or_default(provider.r_mem, 1.0),
            _positive_or_default(provider.r_disk, 1.0),
            _positive_or_default(provider.r_net, 1.0),
        )

    @staticmethod
    def _sigma(
        weights: Tuple[float, float, float, float],
        ratios: Tuple[float, float, float, float],
    ) -> float:
        return sum(w * r for w, r in zip(weights, ratios))

    @staticmethod
    def _cold_start_ms(t_ref: float, sigma: float) -> Optional[float]:
        if sigma <= 0:
            return None
        return t_ref * sigma

    @staticmethod
    def _blend(
        t_cold: float, ema: Optional[float], n: int, kappa: float
    ) -> float:
        if n <= 0 or ema is None or ema <= 0:
            return t_cold
        if kappa <= 0:
            return ema
        denom = n + kappa
        return (n / denom) * ema + (kappa / denom) * t_cold

    @classmethod
    def _pull_time_ms(
        cls,
        cache_state: Optional[str],
        image_size_mb: Optional[float],
        s_disk_mbps: Optional[float],
        s_net_mbps: Optional[float],
    ) -> float:
        state = (cache_state or "cold").lower()
        if state == "memory":
            return 0.0

        if image_size_mb is None or image_size_mb <= 0:
            return 0.0

        if state == "disk":
            if s_disk_mbps is None or s_disk_mbps <= 0:
                if not cls._warned_missing_s_disk:
                    cls._warned_missing_s_disk = True
                    _log.warning(
                        "[scaling] s_disk_mbps missing; disk-cache pull time treated as 0"
                    )
                return 0.0
            return (image_size_mb / s_disk_mbps) * 1000.0

        # "cold" (or any unknown value) -> cold pull
        if s_net_mbps is None or s_net_mbps <= 0:
            if not cls._warned_missing_s_net:
                cls._warned_missing_s_net = True
                _log.warning(
                    "[scaling] s_net_mbps missing; cold pull time treated as 0"
                )
            return 0.0
        return (image_size_mb / s_net_mbps) * 1000.0


def _as_float(value) -> Optional[float]:
    """Coerce Decimal/int/float/None into Optional[float] without raising."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_or_default(value, default: float) -> float:
    """Return ``float(value)`` if it is a positive finite number, else ``default``."""
    f = _as_float(value)
    if f is None or f <= 0:
        return default
    return f
