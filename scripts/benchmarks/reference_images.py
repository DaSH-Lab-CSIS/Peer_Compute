"""Service list and benchmark defaults for the scaling-factor benchmarking harness.

This module is the single source of truth for:
  - which Docker images are considered valid (active) benchmark services,
  - their mapping from benchmark_no -> docker_tag,
  - and the default parameter values recommended by docs/runtime_prediction.tex §11.

Benchmark 010.sleep is intentionally excluded: a pure time.sleep workload
produces zero deviation under any resource throttle, so the weight-discovery
step (Stage 2) would always hit the equal-weights fallback. Including it wastes
time without adding information.

Valid service map (benchmark_no -> full docker tag):
  Mapping confirmed from readme.md §Benchmark Mapping; inactive entries
  (020, 030, 040, 220, 411) are omitted.
"""

from __future__ import annotations
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Service list
# ---------------------------------------------------------------------------

# Each entry: (benchmark_no, docker_tag)
#   benchmark_no : 3-digit string used by invocations/invoker.py get_payload()
#   docker_tag   : fully-qualified Docker Hub tag
SERVICES: List[Tuple[str, str]] = [
    ("110", "peercompute/benchmark.110.dynamic-html.python-3.9"),
    ("120", "peercompute/benchmark.120.uploader.python-3.9"),
    ("210", "peercompute/benchmark.210.thumbnailer.python-3.9"),
    ("311", "peercompute/benchmark.311.compression.python-3.9"),
    ("501", "peercompute/benchmark.501.graph-pagerank-3.9"),
    ("502", "peercompute/benchmark.502.graph-mst-3.9"),
    ("503", "peercompute/benchmark.503.graph-bfs-3.9"),
    ("504", "peercompute/benchmark.504.dna-visualisation.python-3.9"),
]

# Quick lookup: benchmark_no -> docker_tag
SERVICE_MAP: Dict[str, str] = {no: tag for no, tag in SERVICES}

# All valid benchmark numbers (for CLI validation)
VALID_BENCH_NOS: List[str] = [no for no, _ in SERVICES]

# ---------------------------------------------------------------------------
# Machine-benchmark probe image
# S_net is measured by timing the pull of this reference blob. It must be
# large enough (~200 MB) that per-byte transfer time dominates TCP handshake.
# Using the peercompute namespace avoids introducing a new registry anchor
# beyond the one providers already use in production.
# ---------------------------------------------------------------------------
S_NET_REFERENCE_IMAGE: str = "peercompute/benchmark.311.compression.python-3.9"

# ---------------------------------------------------------------------------
# Default algorithm parameters (docs/runtime_prediction.tex §11)
# ---------------------------------------------------------------------------
DEFAULT_B: int = 5        # Reference runs for t_ref (Stage 1)
DEFAULT_B_PRIME: int = 3  # Throttled runs per resource dimension (Stage 2)
DEFAULT_THETA: float = 0.5  # Throttle fraction
DEFAULT_EPSILON: float = 1e-6  # Sum-of-deviations threshold for equal-weights fallback
DEFAULT_SIZE: str = "small"   # Benchmark payload size (overrides provider1.py "large")

# Number of repetitions for each machine-benchmark probe
MACHINE_PROBE_REPS: int = 3

# Docker AWS environment variables required by benchmark containers
# (mirrored from provider/provider1.py containers.run call)
BENCH_ENV: Dict[str, str] = {
    "AWS_ACCESS_KEY_ID": "AKIA3KAG6W36BSXOEHWD",
    "AWS_SECRET_ACCESS_KEY": "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",
    "AWS_REGION": "ap-south-1",
}

# Seconds to wait after container start before probing port 8080 (legacy fixed sleep)
CONTAINER_STARTUP_WAIT: float = 2.0

# Max seconds to wait for the container's HTTP server to become ready (readiness poll)
CONTAINER_READY_TIMEOUT: float = 30.0

# Seconds between readiness poll attempts
CONTAINER_READY_POLL_INTERVAL: float = 0.5

# Number of times to retry a failed POST before giving up
HTTP_POST_RETRIES: int = 3

# Seconds to wait between POST retries
HTTP_POST_RETRY_BACKOFF: float = 1.0

# HTTP request timeout per service invocation (seconds)
HTTP_TIMEOUT: int = 60

# Container run timeout before force-kill (seconds); same spirit as provider1.py
CONTAINER_TIMEOUT: int = 120
