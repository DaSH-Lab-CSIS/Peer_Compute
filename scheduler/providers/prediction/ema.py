"""EMA of observed runtimes (docs/runtime_prediction.tex, eq. "EMA Update").

    EMA_0 = t_cold(f, m)
    EMA_n = alpha * x_n + (1 - alpha) * EMA_{n-1}      n >= 1

Kept free of Django so the update rule can be unit tested on its own; the
scheduler persists the result in providers.models.PairRuntimeStats.
"""

from __future__ import annotations

from typing import Optional


def ema_update(prior_ms: Optional[float], observed_ms: float, alpha: float) -> float:
    """Return the EMA after observing ``observed_ms``.

    ``prior_ms`` is EMA_{n-1}, or t_cold for the first observation. With no
    prior at all (no cold-start prediction for this pair) the first
    observation initialises the EMA.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if prior_ms is None or prior_ms <= 0:
        return float(observed_ms)
    return alpha * float(observed_ms) + (1.0 - alpha) * float(prior_ms)
