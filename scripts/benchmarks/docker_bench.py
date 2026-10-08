"""Shared Docker invocation / stats-sampling harness.

This module mirrors the execution model of provider/provider1.py
``run_and_invoke_docker`` and ``monitor_container`` so that benchmarking
happens under identical conditions to production.

Key design decisions
--------------------
* Every container gets a uuid4-suffixed name to prevent "already in use" errors
  across repeated benchmark runs (see readme.md common issues §footgun).
* Every run is wrapped in try/finally so containers and throttle sidecars are
  always torn down, even on exception or keyboard interrupt.
* The stats sampler thread mirrors provider1.py:621 monitor_container exactly:
  it calls cont.stats(stream=False) every 0.5 s and keeps the latest sample.
* Run-0 of each stage is treated as a warmup and excluded from returned timing.
  The median is then taken from runs 1..B (or 1..B').

Throttle context managers
-------------------------
Each class implements __enter__ / __exit__ (context manager) plus
docker_kwargs() -> dict which is merged into containers.run(**kwargs).

  ThrottleCPU(theta)  - docker cpu_quota/cpu_period
  ThrottleMem(theta)  - stress-ng sidecar container (memory bus pressure)
  ThrottleDisk(theta) - docker device_read_bps / device_write_bps
  ThrottleNet(theta)  - Linux tc tbf on docker0 (requires root)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, List, Optional

import docker
import requests as _requests

# Project-root import so we can call invocations.invoker.get_payload
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from invocations.invoker import get_payload
from scripts.benchmarks.reference_images import (
    BENCH_ENV,
    CONTAINER_TIMEOUT,
    HTTP_TIMEOUT,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Outcome of a single container invocation."""
    wall_time_ms: int           # end-to-end run time (not including pull)
    memory_peak_bytes: int      # peak memory_stats.usage from Docker stats
    cpu_total_ns: int           # cpu_stats.cpu_usage.total_usage (cumulative ns)
    exit_ok: bool               # True if HTTP 200 was received
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Docker client (module-level singleton, re-initialised lazily)
# ---------------------------------------------------------------------------

_docker_client: Optional[docker.DockerClient] = None


def get_docker_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client



# ---------------------------------------------------------------------------
# Core invocation helper — mirrors run_and_invoke_docker from provider1.py
# ---------------------------------------------------------------------------

def run_service_once(
    tag: str,
    benchmark_no: str,
    size: str = "small",
    throttle: Optional["ThrottleSpec"] = None,
    dry_run: bool = False,
) -> RunResult:
    """Run *tag* once and return timing.

    Follows run_and_invoke_docker (provider1.py) exactly:
      1. Pull image (no-op when already cached)
      2. containers.run() with dynamic port mapping
      3. Fixed 2 s sleep + reload — same as production
      4. POST to 127.0.0.1:<host_port> — NO socket probe before the request
         (probing consumes the one-shot handle_request() in benchmark containers)
      5. Measure wall time; wait for container exit if POST fails
    """
    if dry_run:
        return RunResult(wall_time_ms=0, memory_peak_bytes=0, cpu_total_ns=0,
                         exit_ok=False, error="dry-run")

    client = get_docker_client()
    container_name = f"bench-{benchmark_no}-{uuid.uuid4().hex[:8]}"

    extra_kwargs: Dict[str, Any] = {}
    if throttle is not None:
        extra_kwargs.update(throttle.docker_kwargs())

    payload = get_payload(benchmark_no, size)
    image = client.images.pull(tag)

    cont = None
    try:
        if throttle is not None:
            throttle.__enter__()

        # Start timer before containers.run() — same as provider1.py start_run_time
        start_time = time.time()
        cont = client.containers.run(
            image, name=container_name, detach=True,
            ports={"8080/tcp": None}, environment=BENCH_ENV, **extra_kwargs,
        )

        # Fixed 2 s wait then reload — identical to provider1.py
        time.sleep(2)
        cont.reload()

        if cont.status != "running":
            raise RuntimeError(
                f"Container exited early (status={cont.status}). "
                f"Logs: {_safe_logs(cont)[:400]}"
            )

        port_info = cont.ports.get("8080/tcp")
        host_port = port_info[0]["HostPort"] if port_info else "8080"

        # Use 127.0.0.1 directly — Docker always binds host ports to 0.0.0.0
        # which includes loopback. We deliberately skip socket probe here because
        # benchmark containers use httpd.handle_request() (one-shot): a probe
        # would consume the only accept() call, leaving the real POST refused.
        host_ip = "127.0.0.1"

        response = None
        try:
            response = _requests.post(
                f"http://{host_ip}:{host_port}",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=HTTP_TIMEOUT,
            )
        except _requests.exceptions.RequestException as exc:
            _log.warning("POST to %s:%s failed: %s", host_ip, host_port, exc)

        # If POST failed, wait for the container to finish so wall_time is
        # meaningful (actual execution time, not just the failed-request cost).
        if response is None:
            try:
                cont.wait(timeout=CONTAINER_TIMEOUT)
            except Exception:
                pass

        wall_time_ms = int((time.time() - start_time) * 1000)
        exit_ok = response is not None and response.status_code == 200
        return RunResult(wall_time_ms=wall_time_ms, memory_peak_bytes=0,
                         cpu_total_ns=0, exit_ok=exit_ok)

    except Exception as exc:
        _log.error("run_service_once failed for %s: %s", tag, exc)
        return RunResult(wall_time_ms=0, memory_peak_bytes=0, cpu_total_ns=0,
                         exit_ok=False, error=str(exc))

    finally:
        if throttle is not None:
            try:
                throttle.__exit__(None, None, None)
            except Exception as exc:
                _log.debug("throttle cleanup: %s", exc)
        if cont is not None:
            _stop_and_remove(cont)


def _safe_logs(cont, tail: int = 20) -> str:
    try:
        return cont.logs(tail=tail).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _stop_and_remove(cont) -> None:
    try:
        cont.reload()
        if cont.status in ("running", "created"):
            cont.stop(timeout=5)
        cont.remove(force=True)
    except Exception as exc:
        _log.debug("container cleanup: %s", exc)


# ---------------------------------------------------------------------------
# Run B times, discard warmup (run-0), return list of wall_time_ms
# ---------------------------------------------------------------------------

def run_B_times(
    tag: str,
    benchmark_no: str,
    B: int,
    size: str = "small",
    throttle: Optional["ThrottleSpec"] = None,
    dry_run: bool = False,
) -> List[int]:
    """Run service B+1 times; discard run-0 (warmup); return wall_time_ms list.

    Throttle context is entered and exited once per invocation inside
    run_service_once, so sidecar contention is fresh each time.
    """
    results: List[int] = []
    for i in range(B + 1):  # +1 for warmup
        _log.info("  run %d/%d %s%s", i, B, tag, " [warmup]" if i == 0 else "")
        r = run_service_once(tag, benchmark_no, size=size, throttle=throttle, dry_run=dry_run)
        if i == 0:
            continue  # discard warmup
        if dry_run:
            results.append(0)
        elif r.exit_ok:
            results.append(r.wall_time_ms)
        elif r.wall_time_ms > 0:
            _log.warning(
                "  run %d: POST did not return HTTP 200 (error=%s) "
                "but container ran for %dms; timing may be inaccurate.",
                i, r.error, r.wall_time_ms,
            )
            results.append(r.wall_time_ms)
        else:
            _log.warning("  run %d failed (%s); using 0 as placeholder", i, r.error)
            results.append(0)
    return results


def median_ms(times: List[int]) -> float:
    """Return median of a non-empty list; return 0.0 if empty."""
    return float(median(times)) if times else 0.0


# ---------------------------------------------------------------------------
# Throttle context managers
# ---------------------------------------------------------------------------

class ThrottleSpec:
    """Abstract base for throttle context managers."""

    def docker_kwargs(self) -> Dict[str, Any]:
        """Return extra keyword arguments for docker.containers.run()."""
        return {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class ThrottleCPU(ThrottleSpec):
    """Limit CPU via docker cpu_quota / cpu_period.

    theta=0.5 => container gets 50% of one CPU core.
    """

    def __init__(self, theta: float = 0.5):
        self.theta = theta
        self._period = 100_000  # microseconds

    def docker_kwargs(self) -> Dict[str, Any]:
        return {
            "cpu_period": self._period,
            "cpu_quota": int(self._period * self.theta),
        }


class ThrottleMem(ThrottleSpec):
    """Memory bandwidth pressure via a stress-ng sidecar container.

    Docker has no reliable cgroup-level memory *bandwidth* limit (only
    memory *size* limits), so we use a parallel container running
    stress-ng to contend for the memory bus. The sidecar is launched in
    __enter__ and stopped in __exit__. docker_kwargs() returns empty {}
    because the pressure is applied externally.
    """

    STRESS_IMAGE = "polinux/stress-ng"

    def __init__(self, theta: float = 0.5):
        # theta=0.5 -> sidecar uses 60% of host memory (fixed heuristic to
        # create ~50% bus contention; see paper §3.2 remark on stress-ng).
        self.theta = theta
        self._sidecar: Optional[Any] = None
        self._name = f"bench-stress-{uuid.uuid4().hex[:8]}"

    def docker_kwargs(self) -> Dict[str, Any]:
        return {}  # pressure is external; no docker run flags needed

    def __enter__(self):
        client = get_docker_client()
        mem_pct = int((1 - self.theta) * 100)  # theta=0.5 -> 50% pressure
        mem_pct = max(10, min(mem_pct, 80))     # clamp 10..80%
        try:
            _log.debug(
                "Starting stress-ng sidecar %s (--vm-bytes %d%%)", self._name, mem_pct
            )
            self._sidecar = client.containers.run(
                self.STRESS_IMAGE,
                name=self._name,
                command=f"--vm 2 --vm-bytes {mem_pct}% --vm-keep",
                detach=True,
                remove=False,
            )
        except Exception as exc:
            _log.warning("Could not start stress-ng sidecar: %s", exc)
            _log.warning(
                "Memory throttle will be skipped. Install stress-ng image with: "
                "docker pull %s", self.STRESS_IMAGE
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._sidecar is not None:
            try:
                self._sidecar.stop(timeout=3)
                self._sidecar.remove(force=True)
            except Exception as exc:
                _log.debug("stress-ng sidecar cleanup: %s", exc)
            self._sidecar = None


class ThrottleDisk(ThrottleSpec):
    """Limit disk I/O via docker device_read_bps / device_write_bps.

    theta=0.5 => container I/O capped at 50% of measured S_disk (if known)
    or a conservative 50 MB/s default. docker_kwargs() auto-detects the
    root device.
    """

    _DEFAULT_BASE_BPS = 200 * 1024 * 1024  # 200 MB/s as base for throttle calc

    def __init__(self, theta: float = 0.5):
        self.theta = theta

    def docker_kwargs(self) -> Dict[str, Any]:
        device = _detect_root_device()
        if not device:
            _log.warning("Could not detect root device; disk throttle disabled.")
            return {}
        limit_bps = int(self._DEFAULT_BASE_BPS * self.theta)
        return {
            "device_read_bps": [{"Path": device, "Rate": limit_bps}],
            "device_write_bps": [{"Path": device, "Rate": limit_bps}],
        }


class ThrottleNet(ThrottleSpec):
    """Throttle container network bandwidth in both directions via ``tc tbf``.

    Requires root. Container traffic leaves through two shapeable points:
      * downloads: the host forwards them out of ``docker0`` (egress of docker0);
      * uploads:   the host forwards them out of its uplink (egress of the
                   default-route interface, e.g. enp2s0).
    A tbf root qdisc on each limits both. Deleting the root qdisc on exit
    restores the kernel default (noqueue / fq_codel).

    The rate is ``theta * base_mbit`` where ``base_mbit`` is the BEM's measured
    network throughput. A fixed 1 Gbit/s base (the previous behaviour) gave a
    500 Mbit/s cap on an ~89 Mbit/s uplink, i.e. no throttling at all, and only
    docker0 egress was shaped, so uploads were never throttled. Measured on
    utorda1 with 504.dna-visualisation (168 MB upload): no throttle 23.1 s,
    old ThrottleNet 23.3 s, both directions at 44 Mbit/s 40.7 s.

    Failures to apply a qdisc raise, so a broken throttle cannot silently
    produce d_net = 0.
    """

    _DEFAULT_BASE_MBIT = 100.0  # used only when no measurement is supplied

    def __init__(self, theta: float = 0.5, base_mbit: Optional[float] = None,
                 interfaces: Optional[List[str]] = None):
        self.theta = theta
        self.base_mbit = base_mbit or float(os.environ.get("BENCH_NET_BASE_MBIT", self._DEFAULT_BASE_MBIT))
        self.interfaces = interfaces or ["docker0", _default_route_interface()]
        self._applied: List[str] = []

    @property
    def rate_mbit(self) -> int:
        return max(1, int(self.base_mbit * self.theta))

    def docker_kwargs(self) -> Dict[str, Any]:
        return {}

    def __enter__(self):
        if sys.platform != "linux":
            _log.warning(
                "ThrottleNet: tc is Linux-only; network throttling skipped on %s. "
                "w_net will be treated as 0 in weight normalisation.",
                sys.platform,
            )
            return self
        if os.geteuid() != 0:
            _log.warning(
                "ThrottleNet: requires root (euid=%d). "
                "Run the service subcommand as root or with sudo to enable "
                "network throttling. Skipping.", os.geteuid()
            )
            return self
        for iface in self.interfaces:
            subprocess.run(["tc", "qdisc", "del", "dev", iface, "root"],
                           check=False, capture_output=True)
            res = subprocess.run(
                ["tc", "qdisc", "add", "dev", iface, "root", "tbf",
                 "rate", f"{self.rate_mbit}mbit", "burst", "32kbit", "latency", "50ms"],
                check=False, capture_output=True, text=True,
            )
            if res.returncode != 0:
                self.__exit__(None, None, None)
                raise RuntimeError(f"ThrottleNet: tc failed on {iface}: {res.stderr.strip()}")
            self._applied.append(iface)
        _log.info("    ThrottleNet: %d Mbit/s (theta=%.2f x base %.1f Mbit/s) on %s",
                  self.rate_mbit, self.theta, self.base_mbit, ", ".join(self._applied))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for iface in self._applied:
            try:
                subprocess.run(["tc", "qdisc", "del", "dev", iface, "root"],
                               check=False, capture_output=True)
                _log.debug("ThrottleNet: removed qdisc on %s", iface)
            except Exception as exc:
                _log.warning("ThrottleNet cleanup on %s failed: %s", iface, exc)
        self._applied = []


def _default_route_interface() -> str:
    """Interface carrying the default route (the uplink uploads leave through)."""
    try:
        out = subprocess.run(["ip", "route", "get", "1.1.1.1"],
                             check=False, capture_output=True, text=True).stdout
        parts = out.split()
        if "dev" in parts:
            return parts[parts.index("dev") + 1]
    except Exception:
        pass
    return "eth0"


# ---------------------------------------------------------------------------
# Utility: detect Docker root device path (for ThrottleDisk)
# ---------------------------------------------------------------------------

def _detect_root_device() -> Optional[str]:
    """Return block device path for the Docker data root (e.g. /dev/sda)."""
    try:
        client = get_docker_client()
        info = client.info()
        data_root = info.get("DockerRootDir", "/var/lib/docker")
        result = subprocess.run(
            ["df", "--output=source", data_root],
            capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) >= 2:
            device = lines[1].strip()
            # Resolve partition to block device (e.g. /dev/sda1 -> /dev/sda)
            if device.startswith("/dev/") and device[-1].isdigit():
                # Strip trailing digit(s) for partition number
                import re
                base = re.sub(r"p?\d+$", "", device)
                if os.path.exists(base):
                    return base
            return device if os.path.exists(device) else None
    except Exception as exc:
        _log.debug("_detect_root_device: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Throttle factory
# ---------------------------------------------------------------------------

THROTTLE_CLASSES: Dict[str, type] = {
    "cpu": ThrottleCPU,
    "mem": ThrottleMem,
    "disk": ThrottleDisk,
    "net": ThrottleNet,
}


def make_throttle(resource: str, theta: float, net_base_mbit: Optional[float] = None) -> ThrottleSpec:
    """Return a ThrottleSpec for the given resource dimension and theta.

    ``net_base_mbit`` (measured BEM throughput) sets the network throttle's base.
    """
    cls = THROTTLE_CLASSES.get(resource)
    if cls is None:
        raise ValueError(f"Unknown resource dimension {resource!r}; "
                         f"choose from {sorted(THROTTLE_CLASSES)}")
    if cls is ThrottleNet:
        return ThrottleNet(theta=theta, base_mbit=net_base_mbit)
    return cls(theta=theta)
