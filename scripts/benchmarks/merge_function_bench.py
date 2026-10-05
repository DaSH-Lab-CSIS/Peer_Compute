#!/usr/bin/env python3
"""Merge a function benchmark JSON into the stored one, per service.

A run limited with ``--services`` only contains those images. Copying it over
``benchmark_results/function_bench.json`` would drop every other service, so
replace only the services present in the new file and keep the rest.

Usage:
    merge_function_bench.py <new.json> <stored.json>
"""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    new_path, stored_path = sys.argv[1:]
    with open(new_path) as f:
        new = json.load(f)
    stored = {"services": {}}
    if os.path.exists(stored_path):
        with open(stored_path) as f:
            stored = json.load(f)

    merged = dict(stored)
    merged["bem_provider_id"] = new.get("bem_provider_id", stored.get("bem_provider_id"))
    merged["services"] = {**stored.get("services", {}), **new.get("services", {})}
    # Per-service run metadata, since services may now come from different runs.
    runs = dict(stored.get("runs_by_service", {}))
    for tag in new.get("services", {}):
        runs[tag] = {"measured_at": new.get("measured_at"), "parameters": new.get("parameters")}
    merged["runs_by_service"] = runs
    merged["measured_at"] = new.get("measured_at")
    merged["parameters"] = new.get("parameters", stored.get("parameters"))

    with open(stored_path, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"merged {len(new.get('services', {}))} service(s) into {stored_path}; "
          f"now {len(merged['services'])} total")


if __name__ == "__main__":
    main()
