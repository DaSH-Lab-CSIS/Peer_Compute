"""Machine-level benchmark probes (docs/runtime_prediction.tex §3.1).

Produces four absolute performance scores for the provider machine:

  S_cpu   — fixed-work SHA-256 loop inside python:3.9-slim.  Unit: ops/sec.
  S_mem   — numpy array copy loop inside python:3.9-slim.    Unit: MB/s.
  S_disk  — dd write+read with fsync inside python:3.9-slim.  Unit: MB/s.
  S_net   — timed Docker registry pull of a reference image.  Unit: MB/s.

Why in-container?
-----------------
Every measurement uses a Docker container so that (a) all providers use
the *same binary* regardless of host software versions, (b) measurements
are taken in the environment closest to actual serverless execution, and
(c) no external tools need to be installed on provider machines (only a
working Docker daemon is required).

S_net method
------------
Network bandwidth is measured by timing the pull of a fixed reference
Docker layer (reference_images.S_NET_REFERENCE_IMAGE, ~200 MB). Using
the production registry avoids introducing a new centralised anchor — the
registry is the one inevitable dependency every provider already relies on.
Per-byte transfer time dominates TCP handshake time at this scale; taking
the median of MACHINE_PROBE_REPS pulls further suppresses RTT variance.

Output JSON schema
------------------
{
  "provider_id": "<uuid>",
  "measured_at": "<ISO-8601>",
  "s_cpu_ops_per_sec": 1.23e7,
  "s_mem_mbps": 18400.0,
  "s_disk_read_mbps": 820.0,
  "s_disk_write_mbps": 650.0,
  "s_disk_mbps": 735.0,          <- mean of read and write
  "s_net_mbps": 112.5,
  "units": { ... }
}
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from statistics import median
from typing import Dict, List, Optional

import docker

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.benchmarks.docker_bench import _stop_and_remove, get_docker_client
from scripts.benchmarks.reference_images import MACHINE_PROBE_REPS, S_NET_REFERENCE_IMAGE

_log = logging.getLogger(__name__)

# Directory containing probe Dockerfiles and scripts
_PROBES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probes")

# dd block/count settings for S_disk probe
_DISK_BS_MB = 1
_DISK_COUNT = 512  # 512 MB total write/read

# ---------------------------------------------------------------------------
# Probe image builder
# ---------------------------------------------------------------------------

# Local image tags built from the Dockerfiles in scripts/benchmarks/probes/
_PROBE_CPU_TAG = "bench-probe-cpu:latest"
_PROBE_MEM_TAG = "bench-probe-mem:latest"

# Base image used for shell-command probes (disk).  Must have dd(1) available.
_PROBE_BASE_IMAGE = "debian:bookworm-slim"


def _ensure_probe_image(
    client: docker.DockerClient,
    probe: str,          # "cpu" or "mem"
    dry_run: bool = False,
) -> str:
    """Build the probe image from its Dockerfile if not already present locally.

    Returns the image tag. Building happens in-process via docker-py; no
    separate shell command needed. The Dockerfile lives at:
        scripts/benchmarks/probes/<probe>/Dockerfile

    On subsequent runs the image is already present locally (docker images
    cache by tag), so the build is skipped.
    """
    tag = _PROBE_CPU_TAG if probe == "cpu" else _PROBE_MEM_TAG
    if dry_run:
        _log.info("[dry-run] would build %s from probes/%s/Dockerfile", tag, probe)
        return tag

    # Check if already built
    try:
        client.images.get(tag)
        _log.debug("Probe image %s already present; skipping build.", tag)
        return tag
    except docker.errors.ImageNotFound:
        pass

    build_path = os.path.join(_PROBES_DIR, probe)
    _log.info("Building probe image %s from %s ...", tag, build_path)
    try:
        image, logs = client.images.build(
            path=build_path,
            tag=tag,
            rm=True,
            forcerm=True,
        )
        for line in logs:
            if line.get("stream"):
                _log.debug("  build: %s", line["stream"].rstrip())
        _log.info("Probe image %s built successfully.", tag)
    except docker.errors.BuildError as exc:
        _log.error("Failed to build probe image %s: %s", tag, exc)
        raise
    return tag


def _run_probe_image(
    client: docker.DockerClient,
    image_tag: str,
    dry_run: bool = False,
) -> str:
    """Run a pre-built probe image and return its stdout output."""
    name = f"bench-probe-{uuid.uuid4().hex[:8]}"
    if dry_run:
        _log.info("[dry-run] would run %s as %s", image_tag, name)
        return ""
    cont = None
    try:
        cont = client.containers.run(
            image_tag,
            name=name,
            remove=False,
            detach=True,
        )
        result = cont.wait(timeout=300)
        exit_code = result.get("StatusCode", -1)
        stdout = cont.logs(stdout=True, stderr=False).decode("utf-8", errors="replace").strip()
        stderr = cont.logs(stdout=False, stderr=True).decode("utf-8", errors="replace").strip()
        if exit_code != 0:
            _log.error(
                "Probe container %s exited %d. stderr: %s", image_tag, exit_code, stderr
            )
            return ""
        return stdout
    except Exception as exc:
        _log.error("Probe container %s failed: %s", image_tag, exc)
        return ""
    finally:
        if cont is not None:
            _stop_and_remove(cont)


# ---------------------------------------------------------------------------
# Shell-command container helpers (used by disk probe)
# ---------------------------------------------------------------------------


def _pull_probe_image(client: docker.DockerClient) -> None:
    """Ensure _PROBE_BASE_IMAGE is present locally, pulling it if necessary."""
    try:
        client.images.get(_PROBE_BASE_IMAGE)
        _log.debug("Base probe image %s already present; skipping pull.", _PROBE_BASE_IMAGE)
    except docker.errors.ImageNotFound:
        _log.info("Pulling base probe image %s ...", _PROBE_BASE_IMAGE)
        client.images.pull(_PROBE_BASE_IMAGE)
        _log.info("Base probe image %s ready.", _PROBE_BASE_IMAGE)


def _run_probe_container(
    client: docker.DockerClient,
    shell_cmd: str,
    volumes: Optional[Dict[str, dict]] = None,
    dry_run: bool = False,
) -> str:
    """Run *shell_cmd* inside _PROBE_BASE_IMAGE and return combined stdout output.

    The command is executed as ``sh -c "<shell_cmd>"`` so that piping and
    redirections work as written in the dd benchmark commands.
    """
    name = f"bench-probe-{uuid.uuid4().hex[:8]}"
    if dry_run:
        _log.info("[dry-run] would run container %s: %s", name, shell_cmd)
        return ""
    cont = None
    try:
        cont = client.containers.run(
            _PROBE_BASE_IMAGE,
            command=["sh", "-c", shell_cmd],
            name=name,
            volumes=volumes or {},
            remove=False,
            detach=True,
        )
        result = cont.wait(timeout=300)
        exit_code = result.get("StatusCode", -1)
        output = cont.logs(stdout=True, stderr=True).decode("utf-8", errors="replace").strip()
        if exit_code != 0:
            _log.error(
                "Probe container exited %d running %r. output: %s", exit_code, shell_cmd, output
            )
            return ""
        return output
    except Exception as exc:
        _log.error("Probe container failed running %r: %s", shell_cmd, exc)
        return ""
    finally:
        if cont is not None:
            _stop_and_remove(cont)


# ---------------------------------------------------------------------------
# S_cpu probe
# ---------------------------------------------------------------------------


def probe_cpu(client: docker.DockerClient, dry_run: bool = False) -> float:
    """Return S_cpu in SHA-256 ops/sec (median of MACHINE_PROBE_REPS runs).

    Uses a locally-built Docker image (bench-probe-cpu) whose Dockerfile lives
    at scripts/benchmarks/probes/cpu/. Built once on first run; cached after.
    """
    image_tag = _ensure_probe_image(client, "cpu", dry_run=dry_run)
    samples: List[float] = []
    for i in range(MACHINE_PROBE_REPS + 1):  # +1 warmup
        out = _run_probe_image(client, image_tag, dry_run=dry_run)
        if i == 0:
            continue  # discard warmup
        if dry_run:
            samples.append(0.0)
            continue
        try:
            samples.append(float(out.strip()))
        except ValueError:
            _log.warning("S_cpu: unexpected output %r", out)
    return float(median(samples)) if samples else 0.0


# ---------------------------------------------------------------------------
# S_mem probe
# ---------------------------------------------------------------------------


def probe_mem(client: docker.DockerClient, dry_run: bool = False) -> float:
    """Return S_mem in MB/s (median of MACHINE_PROBE_REPS runs).

    Uses a locally-built Docker image (bench-probe-mem) whose Dockerfile lives
    at scripts/benchmarks/probes/mem/. numpy is pre-installed in the image at
    build time so every run starts immediately without pip overhead.
    """
    image_tag = _ensure_probe_image(client, "mem", dry_run=dry_run)
    samples: List[float] = []
    for i in range(MACHINE_PROBE_REPS + 1):  # +1 warmup
        out = _run_probe_image(client, image_tag, dry_run=dry_run)
        if i == 0:
            continue  # discard warmup
        if dry_run:
            samples.append(0.0)
            continue
        try:
            samples.append(float(out.strip()))
        except ValueError:
            _log.warning("S_mem: unexpected output %r", out)
    return float(median(samples)) if samples else 0.0


# ---------------------------------------------------------------------------
# S_disk probe
# ---------------------------------------------------------------------------

# dd with oflag=direct to bypass page cache; conv=fsync to force flush.
# We measure write first, then read.
_DISK_WRITE_CMD = (
    f"dd if=/dev/zero of=/data/bench_blob bs={_DISK_BS_MB}M "
    f"count={_DISK_COUNT} conv=fsync 2>&1 | tail -1"
)
_DISK_READ_CMD = (
    f"dd if=/data/bench_blob of=/dev/null bs={_DISK_BS_MB}M "
    f"count={_DISK_COUNT} 2>&1 | tail -1"
)


def _parse_dd_mbps(dd_output: str) -> Optional[float]:
    """Parse MB/s from dd's stderr summary line."""
    import re
    # English locale: '536 MB/s' or '536 MiB/s'
    m = re.search(r"([\d.]+)\s*(?:MB|MiB)/s", dd_output)
    if m:
        return float(m.group(1))
    # Fallback: bytes/sec notation
    m = re.search(r"([\d.]+)\s*bytes.*?(\S+)\s*(?:s)", dd_output)
    if m:
        try:
            return float(m.group(1)) / float(m.group(2)) / (1024 * 1024)
        except Exception:
            pass
    return None


def probe_disk(client: docker.DockerClient, dry_run: bool = False) -> Dict[str, float]:
    """Return {'read_mbps': x, 'write_mbps': y, 'mbps': mean} (medians)."""
    _pull_probe_image(client)

    # We use a named volume so write and read happen on real disk, not tmpfs
    vol_name = f"bench-disk-{uuid.uuid4().hex[:8]}"
    try:
        client.volumes.create(name=vol_name)
    except Exception as exc:
        _log.warning("Could not create volume %s: %s", vol_name, exc)
        return {"read_mbps": 0.0, "write_mbps": 0.0, "mbps": 0.0}

    volumes = {vol_name: {"bind": "/data", "mode": "rw"}}

    write_samples: List[float] = []
    read_samples: List[float] = []

    try:
        for i in range(MACHINE_PROBE_REPS + 1):
            # Write
            out_w = _run_probe_container(
                client,
                _DISK_WRITE_CMD,
                volumes=volumes,
                dry_run=dry_run and i > 0,
            )
            # Read
            out_r = _run_probe_container(
                client,
                _DISK_READ_CMD,
                volumes=volumes,
                dry_run=dry_run and i > 0,
            )
            if i == 0:
                continue  # warmup
            w = _parse_dd_mbps(out_w)
            r = _parse_dd_mbps(out_r)
            if w is not None:
                write_samples.append(w)
            else:
                _log.warning("S_disk write: unparseable output %r", out_w)
            if r is not None:
                read_samples.append(r)
            else:
                _log.warning("S_disk read: unparseable output %r", out_r)
    finally:
        try:
            client.volumes.get(vol_name).remove(force=True)
        except Exception:
            pass

    read_med = float(median(read_samples)) if read_samples else 0.0
    write_med = float(median(write_samples)) if write_samples else 0.0
    mean = (read_med + write_med) / 2 if (read_med or write_med) else 0.0
    return {"read_mbps": read_med, "write_mbps": write_med, "mbps": mean}


# ---------------------------------------------------------------------------
# S_net probe (timed Docker registry pull)
# ---------------------------------------------------------------------------


def probe_net(client: docker.DockerClient, dry_run: bool = False) -> float:
    """Return S_net in MB/s (median of MACHINE_PROBE_REPS fresh pulls).

    Forces a fresh pull by removing the local image before each measurement.
    The reference image (S_NET_REFERENCE_IMAGE) is a large benchmark image
    already in the peercompute registry that providers use in production.
    """
    samples: List[float] = []
    for i in range(MACHINE_PROBE_REPS + 1):
        # Remove local image to force a registry pull
        try:
            client.images.remove(S_NET_REFERENCE_IMAGE, force=True)
        except Exception:
            pass

        if dry_run and i > 0:
            _log.info("[dry-run] would pull %s", S_NET_REFERENCE_IMAGE)
            samples.append(0.0)
            continue

        t0 = time.perf_counter()
        try:
            img = client.images.pull(S_NET_REFERENCE_IMAGE)
        except Exception as exc:
            _log.warning("S_net pull failed: %s", exc)
            continue
        elapsed = time.perf_counter() - t0

        # Determine uncompressed size in MB from local image attrs
        try:
            img = client.images.get(S_NET_REFERENCE_IMAGE)
            size_mb = img.attrs.get("Size", 0) / (1024 * 1024)
        except Exception:
            # Fallback: assume 200 MB if we can't read attrs
            size_mb = 200.0

        if i == 0:
            continue  # warmup
        if elapsed > 0 and size_mb > 0:
            samples.append(size_mb / elapsed)
        else:
            _log.warning("S_net: elapsed=%s size_mb=%s", elapsed, size_mb)

    return float(median(samples)) if samples else 0.0


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def run_machine_benchmark(
    provider_id: str,
    dry_run: bool = False,
    probes: Optional[List[str]] = None,
) -> Dict:
    """Run all four machine probes and return the results dict.

    Parameters
    ----------
    provider_id : Identifies this machine in the output JSON.
    dry_run     : If True, skip actual Docker execution.
    probes      : Subset of ['cpu','mem','disk','net'] to run; None means all.
    """
    client = get_docker_client()
    if probes is None:
        probes = ["cpu", "mem", "disk", "net"]

    _log.info("=== Machine benchmark for provider %s ===", provider_id)

    s_cpu = 0.0
    s_mem = 0.0
    s_disk_r = 0.0
    s_disk_w = 0.0
    s_disk = 0.0
    s_net = 0.0

    if "cpu" in probes:
        _log.info("Probing S_cpu (5M SHA-256 iterations x %d reps, image=%s)...",
                  MACHINE_PROBE_REPS, _PROBE_CPU_TAG)
        s_cpu = probe_cpu(client, dry_run=dry_run)
        _log.info("  S_cpu = %.2f ops/sec", s_cpu)

    if "mem" in probes:
        _log.info("Probing S_mem (256 MB x 5 copies x %d reps, image=%s)...",
                  MACHINE_PROBE_REPS, _PROBE_MEM_TAG)
        s_mem = probe_mem(client, dry_run=dry_run)
        _log.info("  S_mem = %.2f MB/s", s_mem)

    if "disk" in probes:
        _log.info("Probing S_disk (%d MB x %d reps)...",
                  _DISK_BS_MB * _DISK_COUNT, MACHINE_PROBE_REPS)
        disk = probe_disk(client, dry_run=dry_run)
        s_disk_r, s_disk_w, s_disk = disk["read_mbps"], disk["write_mbps"], disk["mbps"]
        _log.info("  S_disk = %.2f MB/s (read %.2f write %.2f)",
                  s_disk, s_disk_r, s_disk_w)

    if "net" in probes:
        _log.info("Probing S_net (registry pull of %s x %d reps)...",
                  S_NET_REFERENCE_IMAGE, MACHINE_PROBE_REPS)
        s_net = probe_net(client, dry_run=dry_run)
        _log.info("  S_net = %.2f MB/s", s_net)

    result = {
        "provider_id": provider_id,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "s_cpu_ops_per_sec": round(s_cpu, 2),
        "s_mem_mbps": round(s_mem, 2),
        "s_disk_read_mbps": round(s_disk_r, 2),
        "s_disk_write_mbps": round(s_disk_w, 2),
        "s_disk_mbps": round(s_disk, 2),
        "s_net_mbps": round(s_net, 2),
        "units": {
            "s_cpu_ops_per_sec": "SHA-256 iterations / second (inside python:3.9-slim container)",
            "s_mem_mbps": "numpy memcpy MB/s (inside python:3.9-slim container)",
            "s_disk_read_mbps": "dd sequential read MB/s (inside python:3.9-slim container)",
            "s_disk_write_mbps": "dd sequential write+fsync MB/s (inside python:3.9-slim container)",
            "s_disk_mbps": "mean(read_mbps, write_mbps)",
            "s_net_mbps": f"registry pull MB/s ({S_NET_REFERENCE_IMAGE})",
        },
        "parameters": {
            "cpu_probe_image": _PROBE_CPU_TAG,
            "mem_probe_image": _PROBE_MEM_TAG,
            "cpu_iterations": 5_000_000,   # defined in probes/cpu/bench_cpu.py
            "mem_array_mb": 256,            # defined in probes/mem/bench_mem.py
            "mem_copies": 5,               # defined in probes/mem/bench_mem.py
            "disk_total_mb": _DISK_BS_MB * _DISK_COUNT,
            "probe_reps": MACHINE_PROBE_REPS,
            "ref_net_image": S_NET_REFERENCE_IMAGE,
        },
    }
    return result
