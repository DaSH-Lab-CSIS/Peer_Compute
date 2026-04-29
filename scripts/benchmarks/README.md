# Scaling-Factor Benchmarking Harness

Produces the input data consumed by `ScalingFactorStrategy`
(`scheduler/providers/prediction/scaling_strategy.py`) as described in
`docs/runtime_prediction.tex`.

Two subcommands:

| Subcommand | Runs on | Output |
|------------|---------|--------|
| `provider` | Every provider **and** the BEM | `machine_bench.json` |
| `service`  | BEM only | `function_bench.json` |

---

## Quick start

```bash
# From the project root, with .venv activated:
cd /path/to/Serverless_Scheduler

# 1. Benchmark the current machine's hardware:
python scripts/benchmarks/benchmark.py provider \
    --provider-id 34933555-5cca-41fb-aded-4ab7900c48d5 \
    --out machine_bench.json

# 2. Benchmark all 8 services on the BEM (requires Docker):
sudo python scripts/benchmarks/benchmark.py service \
    --provider-id 34933555-5cca-41fb-aded-4ab7900c48d5 \
    --out function_bench.json

# 3. Smoke-test without running Docker:
python scripts/benchmarks/benchmark.py provider --provider-id test --dry-run
python scripts/benchmarks/benchmark.py service  --provider-id test --dry-run
```

> **Root / sudo** is required for the `service` subcommand on Linux because
> network throttling uses `tc tbf` on the `docker0` interface. Without root,
> the `net` dimension is skipped automatically and `w_net` is treated as 0 in
> the weight normalisation (paper §4.2 clamping rule).

---

## Prerequisites

### Python packages (minimal)

The harness only needs **`docker`** (Docker Engine API for Python) and
**`requests`** on the **host** interpreter. It does **not** need Django,
PostgreSQL drivers, or the full project `requirements.txt`.

Install from the small pin file in this directory:

```bash
cd /path/to/Serverless_Scheduler
python3 -m venv .venv-bench
.venv-bench/bin/pip install -r scripts/benchmarks/requirements.txt
```

`numpy` is installed **inside** the `python:3.9-slim` probe container during the
memory benchmark (`machine.py`); you do not need `numpy` in the host venv.

### Runtime

| Requirement | Notes |
|-------------|-------|
| Docker daemon running | `docker ps` should succeed |
| Docker Hub access | Images are pulled from `peercompute/` namespace |
| Python 3.9+ | Dedicated venv recommended (see above) |
| Linux `tc` + root | `service` subcommand, `net` dimension only |
| `polinux/stress-ng` image | Auto-pulled; needed for `mem` throttle in Stage 2 |

---

## Methodology rationale (paper alignment)

### Why in-container synthetic probes?

All machine probes (`S_cpu`, `S_mem`, `S_disk`, `S_net`) and service
invocations run inside Docker containers. This is the correct choice for a
paper on decentralised FaaS for three reasons:

1. **Same binary everywhere.** Every provider runs the exact same Python
   script from the same image, so ratios `r_i(m) = S_i(m_0) / S_i(m)` are
   apples-to-apples across machines with different distro versions.
2. **No tool-installation burden.** Requiring `apt install sysbench fio iperf3`
   on every provider is a deployment barrier and a source of version drift.
   A Docker daemon is the only prerequisite — providers already have one.
3. **No new centralised anchor.** `S_net` is measured by timing a pull of
   `peercompute/benchmark.311.compression.python-3.9` (~183 MB) from the same
   Docker Hub registry that providers already rely on in production.
   No separate `iperf3` endpoint is needed, and no new centralised server is
   introduced — preserving the decentralisation argument.

### Machine benchmark (§3.1)

| Score | Probe | Container |
|-------|-------|-----------|
| `S_cpu` | Fixed-work SHA-256 loop: 5M iterations over a 1 KB buffer. `S_cpu = iters / elapsed_s`. | `python:3.9-slim` |
| `S_mem` | NumPy `copyto` loop: copy a 256 MB array 5 times. `S_mem = total_MB / elapsed_s`. | `python:3.9-slim` (+ pip install numpy) |
| `S_disk` | `dd` write+fsync then read of a 512 MB blob on a named volume. `S_disk = mean(read, write) MB/s`. | `python:3.9-slim` |
| `S_net` | `docker.images.pull(REF_IMAGE)` timed. `S_net = image_size_MB / elapsed_s`. | Docker daemon (no container) |

Each probe runs **3 + 1** times (run-0 is a warmup); the median of runs 1–3
is reported.

### Function benchmark (§3.2)

**Stage 1 (reference runtime):** Run each of the 8 benchmark services
`B = 5` times unthrottled, with `size = "small"` payload. Discard run-0
(warmup); take the median → `t_ref(f)`.

**Stage 2 (weight discovery):** For each resource dimension `i ∈ {cpu, mem,
disk, net}`, run the service `B' = 3` times with `Throttle_i(θ = 0.5)`.
Discard run-0; take the median → `t_i_thr(f)`.

```
d_i(f) = max(0,  (t_i_thr - t_ref) / t_ref )   # relative slowdown, clamped

w_i(f) = d_i / Σ_j d_j                           # normalised weight
         (equal 0.25 each if Σ d_j < ε = 1e-6)  # fast-function fallback
```

These weights are the inputs the scheduler's `ScalingFactorStrategy` uses to
compute `σ(f, m) = Σ_i w_i(f) · r_i(m)` and then `t̂_cold(f, m) = t_ref(f) · σ`.

### Throttle mechanisms

| Dimension | Mechanism | Notes |
|-----------|-----------|-------|
| CPU | `docker --cpu-quota` / `--cpu-period` | Native; no sidecar needed |
| Memory BW | `polinux/stress-ng --vm 2 --vm-bytes N%` sidecar | No cgroup BW limit on most kernels; paper §3.2 explicitly recommends this |
| Disk I/O | `docker --device-read-bps` / `--device-write-bps` | Requires cgroup v1 or v2 with blkio controller |
| Network | `tc qdisc add dev docker0 root tbf rate <N>mbit` | Linux-only; requires root; skipped otherwise |

---

## Output schema

### `machine_bench.json`

```json
{
  "provider_id": "34933555-5cca-41fb-aded-4ab7900c48d5",
  "measured_at": "2026-04-18T12:00:00+00:00",
  "s_cpu_ops_per_sec": 1.23e7,
  "s_mem_mbps": 18400.0,
  "s_disk_read_mbps": 820.0,
  "s_disk_write_mbps": 650.0,
  "s_disk_mbps": 735.0,
  "s_net_mbps": 112.5,
  "units": { "...": "..." },
  "parameters": { "...": "..." }
}
```

### `function_bench.json`

```json
{
  "bem_provider_id": "34933555-5cca-41fb-aded-4ab7900c48d5",
  "measured_at": "2026-04-18T12:00:00+00:00",
  "parameters": { "B": 5, "B_prime": 3, "theta": 0.5, "size": "small", "epsilon": 1e-6 },
  "services": {
    "peercompute/benchmark.110.dynamic-html.python-3.9": {
      "ref_runtime_ms": 420.0,
      "w_cpu": 0.610, "w_mem": 0.220, "w_disk": 0.050, "w_net": 0.120,
      "image_size_mb": 183.4,
      "raw": {
        "ref_runs_ms": [415, 422, 420, 419, 425],
        "throttled_runs_ms": { "cpu": [810, 830, 820], "mem": [...], "disk": [...], "net": [...] },
        "deviations": { "cpu": 0.976, "mem": 0.052, "disk": 0.0, "net": 0.148 }
      },
      "error": null
    }
  }
}
```

Raw samples are included to make the paper's reproducibility section
self-contained — reviewers can re-derive the weights from the medians alone.

---

## Downstream: ingesting results into the scheduler

This script produces measurement files only. DB ingestion is a separate
step (not yet implemented). A future ingest script will:

1. Read the BEM's `machine_bench.json` as `S_i(m_0)`.
2. For each other provider's `machine_bench.json`, compute
   `r_i(m) = S_i(m_0) / S_i(m)` and write to `User.{r_cpu, r_mem, r_disk, r_net}`
   plus the absolute `s_disk_mbps` / `s_net_mbps` columns needed for pull-time.
3. Read `function_bench.json` and write to
   `Services.{ref_runtime_ms, w_cpu, w_mem, w_disk, w_net, image_size_mb}`.

Until the ingest step runs, `ScalingFactorStrategy` returns `None` for every
service (all new fields are `Optional`), and the scheduler falls back to
`DEFAULT_RUNTIME = 1000 ms`. No regressions occur.

---

## CLI reference

```
python scripts/benchmarks/benchmark.py --help
python scripts/benchmarks/benchmark.py provider --help
python scripts/benchmarks/benchmark.py service  --help
```

Key flags:

| Flag | Subcommand | Default | Description |
|------|-----------|---------|-------------|
| `--provider-id` | both | required | UUID identifying this machine |
| `--out` | both | see below | Output JSON file path |
| `--dry-run` | both | off | Print plan; skip Docker execution |
| `--probes` | provider | all | Comma-separated subset: `cpu,mem,disk,net` |
| `--services` | service | all 8 | Comma-separated benchmark numbers |
| `--B` | service | 5 | Reference runs per service |
| `--B-prime` | service | 3 | Throttled runs per dimension |
| `--theta` | service | 0.5 | Throttle fraction |
| `--size` | service | small | Payload size (`test`/`small`/`large`) |
| `--skip-dims` | service | auto | Dimensions to skip (e.g. `net,disk`) |
