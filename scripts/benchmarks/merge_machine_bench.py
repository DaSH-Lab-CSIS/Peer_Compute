#!/usr/bin/env python3
"""Merge a (possibly partial) machine benchmark JSON into the stored one.

``benchmark.py provider --probes net`` writes 0 for every probe it did not run.
Copying that file over ``benchmark_results/machine_bench_<host>.json`` would
lose the stored cpu/mem/disk scores, so instead copy only the fields of the
probes that actually ran, and record when each probe was measured.

Usage:
    merge_machine_bench.py <new.json> <stored.json> --probes cpu,mem,disk,net
"""

from __future__ import annotations

import argparse
import json
import os
import sys

PROBE_FIELDS = {
    "cpu": ["s_cpu_ops_per_sec"],
    "mem": ["s_mem_mbps"],
    "disk": ["s_disk_read_mbps", "s_disk_write_mbps", "s_disk_mbps"],
    "net": ["s_net_mbps"],
}


def merge(new: dict, stored: dict, probes: list[str]) -> dict:
    out = dict(stored)
    out["provider_id"] = new.get("provider_id", stored.get("provider_id"))
    measured = dict(stored.get("measured_at_by_probe", {}))
    for probe in probes:
        fields = PROBE_FIELDS[probe]
        values = [new.get(f) for f in fields]
        # A failed probe also reports 0 — keep the stored value in that case.
        if not all(isinstance(v, (int, float)) and v > 0 for v in values):
            print(f"  {probe}: no valid measurement in new file, keeping stored value",
                  file=sys.stderr)
            continue
        for f, v in zip(fields, values):
            out[f] = v
        measured[probe] = new.get("measured_at")
        for section in ("units", "parameters"):
            if section in new:
                out.setdefault(section, {}).update(
                    {k: v for k, v in new[section].items() if any(k == f or probe in k for f in fields)}
                )
    out["measured_at_by_probe"] = measured
    if probes == list(PROBE_FIELDS):
        out["measured_at"] = new.get("measured_at")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("new")
    ap.add_argument("stored")
    ap.add_argument("--probes", required=True)
    args = ap.parse_args()

    probes = [p.strip() for p in args.probes.split(",") if p.strip()]
    unknown = sorted(set(probes) - set(PROBE_FIELDS))
    if unknown:
        sys.exit(f"unknown probes: {unknown}")

    with open(args.new) as f:
        new = json.load(f)
    stored = {}
    if os.path.exists(args.stored):
        with open(args.stored) as f:
            stored = json.load(f)

    merged = merge(new, stored, probes)
    with open(args.stored, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"merged {','.join(probes)} into {args.stored}: "
          + "  ".join(f"{k}={merged.get(k)}" for p in probes for k in PROBE_FIELDS[p]))


if __name__ == "__main__":
    main()
