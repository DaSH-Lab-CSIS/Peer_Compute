"""Service list and benchmark defaults for the scaling-factor benchmarking harness.

This module is the single source of truth for:
  - which Docker images are considered valid (active) benchmark services,
  - their mapping from benchmark_no -> docker_tag,
  - and the default parameter values recommended by docs/runtime_prediction.tex §11.

Benchmark 010.sleep is excluded: a pure time.sleep workload produces zero
deviation under any throttle, and its production "large" payload exceeds the
harness's per-run time limit.

Valid service map (benchmark_no -> full docker tag):
  Mapping confirmed from readme.md §Benchmark Mapping. 020 and 040 were listed
  as inactive there but are active Services used by the experiment trace;
  030, 220 and 411 are omitted.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Service list
# ---------------------------------------------------------------------------

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
    # Services used by the experiment trace that had no t_ref / weights.
    # 010.sleep is deliberately absent: with the production "large" payload every
    # run exceeds the harness's 180 s per-run limit (~1 h of timeouts per full
    # run), and it is excluded from the steady_load trace.
    ("020", "peercompute/benchmark.020.network-benchmark.python-3.9"),
    ("040", "peercompute/benchmark.040.server-reply.python-3.9"),
    # Shares benchmark_no 504 with dna-visualisation: provider1.py derives the
    # payload from the number in the image name, so production sends this image
    # the 504 payload too. Benchmark it the same way.
    ("504", "peercompute/benchmark.504.graph-bfs-3.9"),
]

# Quick lookup: benchmark_no -> docker_tag. Numbers are not unique (504 maps to
# two images); this keeps the last one. Iterate SERVICES to get every image.
SERVICE_MAP: Dict[str, str] = dict(SERVICES)

# All valid benchmark numbers (for CLI validation), de-duplicated, in order.
VALID_BENCH_NOS: List[str] = list(dict.fromkeys(no for no, _ in SERVICES))

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
# Credentials are read from environment so they are never stored in source.
# Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION in .env before running.
BENCH_ENV: Dict[str, str] = {
    "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", ""),
    "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
    "AWS_REGION": os.environ.get("AWS_REGION", "ap-south-1"),
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
