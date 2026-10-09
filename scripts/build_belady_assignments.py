#!/usr/bin/env python3
"""Build the assignment table for placement_mode=belady from a request trace.

The "Belady" arm is a clairvoyant reference policy, not a proven optimum:
  * it knows the whole trace (service of every request, arrival at 1 RPS);
  * runtimes are hindsight values -- the median *successful* run_time per
    (provider, service) observed in earlier arms of the same rep (--observed),
    falling back to t_ref * sigma from the function/machine benchmarks;
  * image pulls cost image_size / S_net of the provider unless the image is in
    that provider's cache; caches hold --cache-cap images and evict with
    Belady's rule (the image whose next use on that provider is furthest away);
  * each request goes, in arrival order, to the provider that finishes it
    earliest, preferring providers idle at its arrival -- the live scheduler
    only offers providers that reported READY, so a target that is still busy
    would fall back to the least-loaded provider.

Output: {"<trace_seq>": "<provider_uuid>"} -- the scheduler looks the request's
_trace_seq up in it (scheduler/providers/views.py, belady branch). The default
output path is the file experiment_prediction.yml copies to the scheduler.

Usage:
  .venv/bin/python scripts/build_belady_assignments.py \\
      --trace testbed/results/requests/steady_load_<RUN>_requests.json \\
      [--observed testbed/results/csv/<RUN>_jobs_enriched.csv ...] \\
      [--providers <uuid>,<uuid>,...] [--cache-cap 12]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from collections import defaultdict
from statistics import median

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH_DIR = os.path.join(ROOT, "ansible_utils", "benchmark_results")
DEFAULT_OUT = os.path.join(ROOT, "testbed", "results", "requests", "belady_assignments.json")
BEM_ID = "11111111-1111-1111-1111-111111111111"

# Scheduler DB Services.id -> docker image (developers_services.docker_container).
SERVICE_IMAGES = {
    14: "peercompute/benchmark.020.network-benchmark.python-3.9",
    16: "peercompute/benchmark.040.server-reply.python-3.9",
    17: "peercompute/benchmark.110.dynamic-html.python-3.9",
    18: "peercompute/benchmark.120.uploader.python-3.9",
    19: "peercompute/benchmark.210.thumbnailer.python-3.9",
    20: "peercompute/benchmark.311.compression.python-3.9",
    21: "peercompute/benchmark.501.graph-pagerank-3.9",
    22: "peercompute/benchmark.502.graph-mst-3.9",
    23: "peercompute/benchmark.503.graph-bfs-3.9",
    24: "peercompute/benchmark.504.dna-visualisation.python-3.9",
    25: "peercompute/benchmark.504.graph-bfs-3.9",
}
ARRIVAL_INTERVAL_S = 1.0


def load_machines():
    """provider_id -> {r_cpu, r_mem, r_disk, r_net, s_net}; ratios as in ingest_benchmarks."""
    raw = {}
    for path in glob.glob(os.path.join(BENCH_DIR, "machine_bench_*.json")):
        d = json.load(open(path))
        raw[str(d.get("provider_id"))] = d
    bem = raw.pop(BEM_ID, None)
    if bem is None:
        sys.exit("BEM machine benchmark (id %s) not found in %s" % (BEM_ID, BENCH_DIR))
    keys = {"cpu": "s_cpu_ops_per_sec", "mem": "s_mem_mbps", "disk": "s_disk_mbps", "net": "s_net_mbps"}
    machines = {}
    for pid, d in raw.items():
        m = {}
        for dim, k in keys.items():
            b, s = float(bem.get(k) or 0), float(d.get(k) or 0)
            m["r_" + dim] = b / s if b > 0 and s > 0 else 1.0
        m["s_net"] = float(d.get("s_net_mbps") or 0) or float(bem.get("s_net_mbps") or 10)
        machines[pid] = m
    return machines


def load_services():
    """docker image -> {t_ref, w_cpu, w_mem, w_disk, w_net, image_size_mb}."""
    d = json.load(open(os.path.join(BENCH_DIR, "function_bench.json")))
    return d["services"]


def predicted_runtime_ms(svc, mach):
    weights = [svc.get(k) or 0.0 for k in ("w_cpu", "w_mem", "w_disk", "w_net")]
    total = sum(weights) or 1.0
    ratios = [mach["r_cpu"], mach["r_mem"], mach["r_disk"], mach["r_net"]]
    sigma = sum(w / total * r for w, r in zip(weights, ratios))
    return float(svc["ref_runtime_ms"]) * sigma


def load_observed(paths):
    """(provider_uuid, service_id) -> median run_time of real successes (ms)."""
    samples = defaultdict(list)
    for path in paths:
        with open(path) as f:
            for row in csv.DictReader(f):
                if row.get("outcome") != "success":
                    continue
                resp = row.get("response") or ""
                if resp.lstrip().startswith('{"error"'):
                    continue
                try:
                    rt = float(row["run_time"])
                except (KeyError, ValueError):
                    continue
                if rt > 0:
                    samples[(row["provider_user_id"], int(float(row["service_id"])))].append(rt)
    return {k: median(v) for k, v in samples.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trace", required=True)
    ap.add_argument("--observed", nargs="*", default=[], help="enriched job CSVs from earlier arms")
    ap.add_argument("--providers", default="", help="comma-separated provider UUIDs to use (default: all benchmarked)")
    ap.add_argument("--cache-cap", type=int, default=12, help="images per provider cache")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    trace = json.load(open(args.trace))
    requests = trace["requests"] if isinstance(trace, dict) else trace
    jobs = [int(r["serviceID"]) for r in requests]
    machines = load_machines()
    if args.providers:
        wanted = [p.strip() for p in args.providers.split(",") if p.strip()]
        missing = [p for p in wanted if p not in machines]
        if missing:
            sys.exit(f"no machine benchmark for providers: {missing}")
        machines = {p: machines[p] for p in wanted}
    services = load_services()
    observed = load_observed(args.observed)

    unknown = sorted({s for s in jobs if s not in SERVICE_IMAGES or SERVICE_IMAGES[s] not in services})
    if unknown:
        sys.exit(f"trace services without benchmark data: {unknown}")

    # Next-use positions per service, for Belady eviction.
    uses = defaultdict(list)
    for i, s in enumerate(jobs):
        uses[s].append(i)

    def next_use(service, after):
        for i in uses[service]:
            if i > after:
                return i
        return float("inf")

    free_at = {p: 0.0 for p in machines}
    cache = {p: [] for p in machines}
    assignments, n_hist, n_pred, total_finish = {}, 0, 0, 0.0
    load = defaultdict(int)

    for seq, sid in enumerate(jobs):
        arrival = seq * ARRIVAL_INTERVAL_S
        svc = services[SERVICE_IMAGES[sid]]
        best = None
        for pid, m in machines.items():
            run_s = observed.get((pid, sid))
            source = "hist"
            if run_s is None:
                run_s, source = predicted_runtime_ms(svc, m), "pred"
            run_s /= 1000.0
            pull_s = 0.0 if sid in cache[pid] else (svc.get("image_size_mb") or 0) / m["s_net"]
            start = max(arrival, free_at[pid])
            finish = start + pull_s + run_s
            key = (start > arrival, finish)  # idle-at-arrival providers first
            if best is None or key < best[0]:
                best = (key, pid, finish, source)
        _, pid, finish, source = best
        assignments[str(seq)] = pid
        free_at[pid] = finish
        load[pid] += 1
        total_finish += finish - arrival
        n_hist += source == "hist"
        n_pred += source == "pred"
        if sid not in cache[pid]:
            if len(cache[pid]) >= args.cache_cap:
                victim = max(cache[pid], key=lambda s: next_use(s, seq))
                cache[pid].remove(victim)
            cache[pid].append(sid)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(assignments, f)
    print(f"wrote {len(assignments)} assignments to {args.out}")
    print(f"providers: {len(machines)}  runtimes: {n_hist} observed / {n_pred} predicted  "
          f"cache cap: {args.cache_cap}")
    print(f"simulated mean response (arrival -> finish): {total_finish / len(jobs):.1f} s")
    print("jobs per provider:", sorted(load.values(), reverse=True))


if __name__ == "__main__":
    main()
