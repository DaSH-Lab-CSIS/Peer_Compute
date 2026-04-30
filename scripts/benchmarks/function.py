"""Function (service) benchmarking — BEM only (docs/runtime_prediction.tex §3.2).

Produces for each benchmark service:
  ref_runtime_ms  — t_ref(f): median wall-clock time of B unthrottled runs.
  w_cpu           — resource sensitivity weight for CPU.
  w_mem           — resource sensitivity weight for memory bandwidth.
  w_disk          — resource sensitivity weight for disk I/O.
  w_net           — resource sensitivity weight for network.
  image_size_mb   — V(f): uncompressed image size from Docker manifest.

Algorithm (paper §3.2 + §4.2)
-------------------------------

Stage 1 (reference runtime)
  Run service B times unthrottled on the BEM; discard run-0 (warmup);
  take median -> t_ref(f).

Stage 2 (resource-sensitivity weight discovery)
  For each resource dimension i in {cpu, mem, disk, net}:
    Run service B' times with Throttle_i(theta); discard run-0; take median
    -> t_i_thr(f).
    Compute d_i = max(0, (t_i_thr - t_ref) / t_ref)  [clamped to >= 0]

  Normalise:
    if sum(d) < epsilon:  equal weights (0.25 each)  [fast-function fallback]
    else:                 w_i = d_i / sum(d)

Output JSON schema
------------------
{
  "bem_provider_id": "<uuid>",
  "measured_at": "<ISO-8601>",
  "parameters": {"B": 5, "B_prime": 3, "theta": 0.5, "size": "small",
                 "epsilon": 1e-6},
  "services": {
    "<docker_tag>": {
      "ref_runtime_ms": 420.0,
      "w_cpu": 0.61, "w_mem": 0.22, "w_disk": 0.05, "w_net": 0.12,
      "image_size_mb": 183.4,
      "raw": {
        "ref_runs_ms": [415, 422, 420, 419, 425],
        "throttled_runs_ms": {
          "cpu":  [810, 830, 820],
          "mem":  [430, 445, 440],
          "disk": [425, 420, 418],
          "net":  [480, 475, 490]
        },
        "deviations": {"cpu": 0.98, "mem": 0.05, "disk": 0.0, "net": 0.15}
      },
      "error": null
    }
  }
}
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from statistics import median
from typing import Dict, List, Optional, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.benchmarks.docker_bench import (
    get_docker_client,
    make_throttle,
    run_B_times,
    median_ms,
)
from scripts.benchmarks.reference_images import (
    DEFAULT_B,
    DEFAULT_B_PRIME,
    DEFAULT_EPSILON,
    DEFAULT_SIZE,
    DEFAULT_THETA,
    SERVICES,
)

_log = logging.getLogger(__name__)

_RESOURCES: Tuple[str, ...] = ("cpu", "mem", "disk", "net")


# ---------------------------------------------------------------------------
# Weight derivation (pure arithmetic; mirrors ScalingFactorStrategy._resolve_weights)
# ---------------------------------------------------------------------------


def compute_weights(
    deviations: Dict[str, float],
    epsilon: float = DEFAULT_EPSILON,
) -> Dict[str, float]:
    """Clamp, sum, and normalise deviations into sensitivity weights.

    Parameters
    ----------
    deviations : {'cpu': d_cpu, 'mem': d_mem, 'disk': d_disk, 'net': d_net}
                  Values are raw relative deviations (may be < 0 before clamping).
    epsilon    : If sum(clamped) < epsilon, return equal weights.

    Returns
    -------
    {'cpu': w_cpu, 'mem': w_mem, 'disk': w_disk, 'net': w_net} summing to 1.
    """
    clamped = {r: max(0.0, deviations.get(r, 0.0)) for r in _RESOURCES}
    total = sum(clamped.values())
    if total < epsilon:
        return {r: 0.25 for r in _RESOURCES}
    return {r: clamped[r] / total for r in _RESOURCES}


# ---------------------------------------------------------------------------
# Image size helper
# ---------------------------------------------------------------------------


def get_image_size_mb(tag: str) -> float:
    """Return the uncompressed Docker image size in MB.

    Falls back to 0.0 on any error (e.g. image not pulled yet; caller
    should ensure the image was pulled during Stage 1).
    """
    try:
        client = get_docker_client()
        img = client.images.get(tag)
        return img.attrs.get("Size", 0) / (1024 * 1024)
    except Exception as exc:
        _log.warning("Could not get image size for %s: %s", tag, exc)
        return 0.0


# ---------------------------------------------------------------------------
# Per-service benchmark
# ---------------------------------------------------------------------------


def benchmark_service(
    benchmark_no: str,
    tag: str,
    B: int = DEFAULT_B,
    B_prime: int = DEFAULT_B_PRIME,
    theta: float = DEFAULT_THETA,
    size: str = DEFAULT_SIZE,
    epsilon: float = DEFAULT_EPSILON,
    dry_run: bool = False,
    skip_dims: Optional[List[str]] = None,
) -> Dict:
    """Run both benchmark stages for a single service and return the result dict.

    Parameters
    ----------
    benchmark_no : 3-digit string used by get_payload() (e.g. "110").
    tag          : Docker Hub image tag.
    B            : Number of reference runs (warmup excluded).
    B_prime      : Number of throttled runs per dimension (warmup excluded).
    theta        : Throttle fraction for each dimension.
    size         : Payload size string (always "small" for benchmarking).
    epsilon      : Equal-weights fallback threshold.
    dry_run      : If True, return synthetic zero-timing results.
    skip_dims    : Dimensions to skip (e.g. ['net'] when tc unavailable).
    """
    skip_dims = skip_dims or []
    _log.info("--- Service %s (%s) ---", benchmark_no, tag)

    result: Dict = {
        "ref_runtime_ms": None,
        "w_cpu": None,
        "w_mem": None,
        "w_disk": None,
        "w_net": None,
        "image_size_mb": None,
        "raw": {
            "ref_runs_ms": [],
            "throttled_runs_ms": {},
            "deviations": {},
        },
        "error": None,
    }

    try:
        # -- Stage 1: Reference runtime --
        _log.info("  Stage 1: %d reference runs (size=%s) ...", B, size)
        ref_runs = run_B_times(tag, benchmark_no, B=B, size=size, dry_run=dry_run)
        result["raw"]["ref_runs_ms"] = ref_runs

        if not dry_run and all(t == 0 for t in ref_runs):
            raise RuntimeError("All Stage-1 runs returned 0 ms; container likely failed.")

        t_ref = median_ms(ref_runs) if ref_runs else 0.0
        result["ref_runtime_ms"] = round(t_ref, 2)
        _log.info("  t_ref = %.1f ms (median of %s)", t_ref, ref_runs)

        image_size = get_image_size_mb(tag)
        result["image_size_mb"] = round(image_size, 2)
        _log.info("  image_size = %.1f MB", image_size)

        # -- Stage 2: Throttled runs per dimension --
        deviations: Dict[str, float] = {}
        for dim in _RESOURCES:
            result["raw"]["throttled_runs_ms"][dim] = []
            if dim in skip_dims:
                _log.info("  Stage 2 [%s]: SKIPPED", dim)
                deviations[dim] = 0.0
                continue

            _log.info("  Stage 2 [%s]: %d runs with theta=%.2f ...", dim, B_prime, theta)
            throttle = make_throttle(dim, theta)
            thr_runs = run_B_times(
                tag, benchmark_no, B=B_prime, size=size,
                throttle=throttle, dry_run=dry_run
            )
            result["raw"]["throttled_runs_ms"][dim] = thr_runs

            t_thr = median_ms(thr_runs) if thr_runs else 0.0
            _log.info("    t_%s_thr = %.1f ms (median of %s)", dim, t_thr, thr_runs)

            # d_i = max(0, (t_thr - t_ref) / t_ref); skip if t_ref == 0
            if t_ref > 0:
                d = (t_thr - t_ref) / t_ref
            else:
                d = 0.0
            deviations[dim] = d
            _log.info("    d_%s = %.4f (raw, before clamping)", dim, d)

        result["raw"]["deviations"] = {k: round(v, 6) for k, v in deviations.items()}

        weights = compute_weights(deviations, epsilon=epsilon)
        result["w_cpu"] = round(weights["cpu"], 6)
        result["w_mem"] = round(weights["mem"], 6)
        result["w_disk"] = round(weights["disk"], 6)
        result["w_net"] = round(weights["net"], 6)

        _log.info(
            "  weights: cpu=%.3f mem=%.3f disk=%.3f net=%.3f",
            weights["cpu"], weights["mem"], weights["disk"], weights["net"],
        )

    except Exception as exc:
        _log.error("benchmark_service failed for %s: %s", tag, exc)
        result["error"] = str(exc)

    return result


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def run_service_benchmark(
    bem_provider_id: str,
    service_nos: Optional[List[str]] = None,
    B: int = DEFAULT_B,
    B_prime: int = DEFAULT_B_PRIME,
    theta: float = DEFAULT_THETA,
    size: str = DEFAULT_SIZE,
    epsilon: float = DEFAULT_EPSILON,
    dry_run: bool = False,
    skip_dims: Optional[List[str]] = None,
) -> Dict:
    """Benchmark all (or a subset of) valid services on the BEM.

    Parameters
    ----------
    bem_provider_id : UUID of the BEM (from CLI ``--provider-id``).
    service_nos     : List of benchmark numbers to run; None means all 8.
    B, B_prime, theta, size, epsilon : algorithm parameters (paper §11).
    dry_run         : If True, skip real Docker execution.
    skip_dims       : Resource dimensions to skip (e.g. ['net'] without root).

    Returns
    -------
    Dict suitable for JSON serialisation; see module docstring for schema.
    """
    if service_nos is None:
        service_nos = [no for no, _ in SERVICES]

    # Filter SERVICES to requested subset
    service_pairs = [(no, tag) for no, tag in SERVICES if no in service_nos]
    missing = set(service_nos) - {no for no, _ in service_pairs}
    if missing:
        _log.warning("Unknown benchmark numbers ignored: %s", sorted(missing))

    _log.info("=== Service benchmark on BEM %s ===", bem_provider_id)
    _log.info("Services: %s", [no for no, _ in service_pairs])
    _log.info("Params: B=%d B'=%d theta=%.2f size=%s epsilon=%.2g",
              B, B_prime, theta, size, epsilon)

    output: Dict = {
        "bem_provider_id": bem_provider_id,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "B": B,
            "B_prime": B_prime,
            "theta": theta,
            "size": size,
            "epsilon": epsilon,
        },
        "services": {},
    }

    for no, tag in service_pairs:
        output["services"][tag] = benchmark_service(
            benchmark_no=no,
            tag=tag,
            B=B,
            B_prime=B_prime,
            theta=theta,
            size=size,
            epsilon=epsilon,
            dry_run=dry_run,
            skip_dims=skip_dims,
        )

    return output
