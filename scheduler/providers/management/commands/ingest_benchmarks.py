"""Management command to ingest benchmark results into the scheduler DB.

Populates the ScalingFactor fields on User (provider nodes) and Services
(serverless functions) from JSON files produced by scripts/benchmarks/.

Machine benchmark JSON schema (one file per provider node):
  {
    "provider_id": "<uuid>",
    "measured_at": "<ISO-8601>",
    "s_cpu_ops_per_sec": float,   # SHA-256 ops/sec
    "s_mem_mbps": float,          # numpy memcpy MB/s
    "s_disk_mbps": float,         # mean(read_mbps, write_mbps)
    "s_net_mbps": float,          # registry pull MB/s
    ...
  }
  Filename convention: machine_bench_<hostname>.json

Function benchmark JSON schema (single file, BEM only):
  {
    "bem_provider_id": "<uuid>",
    "measured_at": "<ISO-8601>",
    "services": {
      "<docker_tag>": {
        "ref_runtime_ms": float,
        "w_cpu": float,
        "w_mem": float,
        "w_disk": float,
        "w_net": float,
        "image_size_mb": float,
        "error": null | str
      }
    }
  }
  The key under "services" is the full Docker Hub tag, which maps to
  Services.docker_container.

Usage:
  python manage.py ingest_benchmarks \\
    --machine-dir benchmark_results/ \\
    --bem-provider-id <uuid> \\
    [--function-file benchmark_results/function_bench.json]

  --bem-provider-id must be the UUID stored in provider_user_id.txt on the
  BEM reference node (= User.user_id in the DB). Its raw scores become the
  denominator for all ratio calculations:
    r_i(m) = S_i(BEM) / S_i(m)   (>1 means m is slower than BEM)
"""

from __future__ import annotations

import glob
import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from developers.models import Services
from profiles.models import User


class Command(BaseCommand):
    help = (
        "Ingest machine and function benchmark JSON results into the scheduler DB, "
        "populating ScalingFactor fields on User and Services models."
    )

    # ------------------------------------------------------------------
    # CLI definition
    # ------------------------------------------------------------------

    def add_arguments(self, parser):
        parser.add_argument(
            "--machine-dir",
            metavar="DIR",
            help=(
                "Directory containing machine_bench_<hostname>.json files. "
                "One file per provider node."
            ),
        )
        parser.add_argument(
            "--bem-provider-id",
            metavar="UUID",
            help=(
                "User.user_id (UUID) of the BEM reference node — read from "
                "provider_user_id.txt on that node. Its raw scores are used as "
                "the denominator when computing performance ratios for all other nodes."
            ),
        )
        parser.add_argument(
            "--function-file",
            metavar="FILE",
            help=(
                "Path to function_bench.json produced by the BEM service "
                "benchmark (scripts/benchmarks/benchmark.py service)."
            ),
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        machine_dir = options.get("machine_dir")
        bem_provider_id = options.get("bem_provider_id")
        function_file = options.get("function_file")

        if not machine_dir and not function_file:
            raise CommandError(
                "Provide at least one of --machine-dir or --function-file."
            )

        if machine_dir and not bem_provider_id:
            raise CommandError(
                "--bem-provider-id is required when --machine-dir is provided."
            )

        machines_updated = 0
        machines_skipped = 0
        services_updated = 0
        services_skipped = 0

        # ---- Machine benchmarks ----------------------------------------
        if machine_dir:
            upd, skp = self._ingest_machine_benchmarks(machine_dir, bem_provider_id)
            machines_updated += upd
            machines_skipped += skp

        # ---- Function benchmarks ----------------------------------------
        if function_file:
            upd, skp = self._ingest_function_benchmarks(function_file)
            services_updated += upd
            services_skipped += skp

        # ---- Summary ----------------------------------------------------
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== ingest_benchmarks summary ==="))
        self.stdout.write(
            self.style.SUCCESS(
                f"  Machines updated : {machines_updated}"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f"  Machines skipped : {machines_skipped}"
            ) if machines_skipped else self.style.SUCCESS(
                f"  Machines skipped : {machines_skipped}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"  Services updated : {services_updated}"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                f"  Services skipped : {services_skipped}"
            ) if services_skipped else self.style.SUCCESS(
                f"  Services skipped : {services_skipped}"
            )
        )

    # ------------------------------------------------------------------
    # Machine benchmark ingestion
    # ------------------------------------------------------------------

    def _ingest_machine_benchmarks(
        self, machine_dir: str, bem_provider_id: str
    ) -> tuple[int, int]:
        """Load machine_bench_*.json files and write r_* / s_* fields to User rows.

        Matches each JSON file to a User row via the ``provider_id`` field in
        the JSON (= User.user_id UUID). Returns (updated_count, skipped_count).
        """
        pattern = os.path.join(machine_dir, "machine_bench_*.json")
        bench_files = sorted(glob.glob(pattern))

        if not bench_files:
            self.stdout.write(
                self.style.WARNING(
                    f"No machine benchmark files found matching: {pattern}"
                )
            )
            return 0, 0

        self.stdout.write(
            f"Found {len(bench_files)} machine benchmark file(s) in {machine_dir}"
        )

        # ---- Load all files -------------------------------------------
        # List of (hostname_label, provider_id_str, raw_data) tuples.
        bench_entries: list[tuple[str, str, dict]] = []
        for path in bench_files:
            hostname = self._hostname_from_path(path)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                provider_id = str(data.get("provider_id", "")).strip()
                bench_entries.append((hostname, provider_id, data))
                self.stdout.write(
                    f"  Loaded {path} (hostname={hostname!r}, provider_id={provider_id!r})"
                )
            except (OSError, json.JSONDecodeError) as exc:
                self.stdout.write(
                    self.style.WARNING(f"  Could not load {path}: {exc} — skipping")
                )

        if not bench_entries:
            self.stdout.write(self.style.ERROR("No machine benchmark files could be loaded."))
            return 0, len(bench_files)

        # ---- Locate BEM baseline data ---------------------------------
        bem_entry = next(
            (e for e in bench_entries if e[1] == bem_provider_id), None
        )
        if bem_entry is None:
            available = [e[1] for e in bench_entries]
            raise CommandError(
                f"BEM provider_id {bem_provider_id!r} not found in any loaded file. "
                f"Available provider_ids: {available}"
            )

        bem_hostname, _, bem_data = bem_entry
        bem_cpu = float(bem_data.get("s_cpu_ops_per_sec", 0) or 0)
        bem_mem = float(bem_data.get("s_mem_mbps", 0) or 0)
        bem_disk = float(bem_data.get("s_disk_mbps", 0) or 0)
        bem_net = float(bem_data.get("s_net_mbps", 0) or 0)

        self.stdout.write(
            f"BEM baseline ({bem_hostname!r}, id={bem_provider_id!r}): "
            f"cpu={bem_cpu:.2f} ops/s  mem={bem_mem:.2f} MB/s  "
            f"disk={bem_disk:.2f} MB/s  net={bem_net:.2f} MB/s"
        )

        for label, val in [
            ("s_cpu_ops_per_sec", bem_cpu),
            ("s_mem_mbps", bem_mem),
            ("s_disk_mbps", bem_disk),
            ("s_net_mbps", bem_net),
        ]:
            if val == 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"  WARNING: BEM {label} is 0 — ratio for this "
                        f"dimension will be None for all nodes."
                    )
                )

        # ---- Write to DB ----------------------------------------------
        updated = 0
        skipped = 0

        with transaction.atomic():
            for hostname, provider_id, data in bench_entries:
                if not provider_id:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  {hostname!r}: missing provider_id in JSON — skipping"
                        )
                    )
                    skipped += 1
                    continue

                user = User.objects.filter(user_id=provider_id).first()
                if user is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  No User with user_id={provider_id!r} "
                            f"(hostname={hostname!r}) — skipping"
                        )
                    )
                    skipped += 1
                    continue

                s_cpu = float(data.get("s_cpu_ops_per_sec", 0) or 0)
                s_mem = float(data.get("s_mem_mbps", 0) or 0)
                s_disk = float(data.get("s_disk_mbps", 0) or 0)
                s_net = float(data.get("s_net_mbps", 0) or 0)

                user.r_cpu = (bem_cpu / s_cpu) if s_cpu else None
                user.r_mem = (bem_mem / s_mem) if s_mem else None
                user.r_disk = (bem_disk / s_disk) if s_disk else None
                user.r_net = (bem_net / s_net) if s_net else None
                user.s_disk_mbps = s_disk or None
                user.s_net_mbps = s_net or None

                user.save(
                    update_fields=[
                        "r_cpu", "r_mem", "r_disk", "r_net",
                        "s_disk_mbps", "s_net_mbps",
                    ]
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Updated User user_id={provider_id!r} ({hostname!r}): "
                        f"r_cpu={user.r_cpu}  r_mem={user.r_mem}  "
                        f"r_disk={user.r_disk}  r_net={user.r_net}  "
                        f"s_disk_mbps={user.s_disk_mbps}  s_net_mbps={user.s_net_mbps}"
                    )
                )
                updated += 1

        return updated, skipped

    # ------------------------------------------------------------------
    # Function benchmark ingestion
    # ------------------------------------------------------------------

    def _ingest_function_benchmarks(
        self, function_file: str
    ) -> tuple[int, int]:
        """Load function_bench.json and write weight / timing fields to Services rows.

        Returns (updated_count, skipped_count).
        """
        try:
            with open(function_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            self.stdout.write(
                self.style.ERROR(
                    f"Could not load function benchmark file {function_file}: {exc}"
                )
            )
            return 0, 0

        services_map: dict = data.get("services", {})
        if not services_map:
            self.stdout.write(
                self.style.WARNING(
                    f"No 'services' key found in {function_file} — nothing to ingest."
                )
            )
            return 0, 0

        self.stdout.write(
            f"Found {len(services_map)} service entry/entries in {function_file}"
        )

        updated = 0
        skipped = 0

        with transaction.atomic():
            for docker_tag, entry in services_map.items():
                # Skip entries that failed during benchmarking.
                if entry.get("error"):
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Service tag={docker_tag!r} has benchmark error "
                            f"({entry['error']!r}) — skipping"
                        )
                    )
                    skipped += 1
                    continue

                # Match by docker_container field (the JSON key is the full
                # Docker Hub tag stored in Services.docker_container).
                service = Services.objects.filter(
                    docker_container=docker_tag
                ).first()

                if service is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  No Services row with docker_container={docker_tag!r} "
                            f"— skipping"
                        )
                    )
                    skipped += 1
                    continue

                ref_ms = entry.get("ref_runtime_ms")
                service.ref_runtime_ms = (
                    int(round(ref_ms)) if ref_ms is not None else None
                )
                service.w_cpu = entry.get("w_cpu")
                service.w_mem = entry.get("w_mem")
                service.w_disk = entry.get("w_disk")
                service.w_net = entry.get("w_net")
                service.image_size_mb = entry.get("image_size_mb")

                service.save(
                    update_fields=[
                        "ref_runtime_ms",
                        "w_cpu", "w_mem", "w_disk", "w_net",
                        "image_size_mb",
                    ]
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Updated Service docker_container={docker_tag!r} "
                        f"(id={service.id}): "
                        f"ref_runtime_ms={service.ref_runtime_ms}  "
                        f"w_cpu={service.w_cpu}  w_mem={service.w_mem}  "
                        f"w_disk={service.w_disk}  w_net={service.w_net}  "
                        f"image_size_mb={service.image_size_mb}"
                    )
                )
                updated += 1

        return updated, skipped

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hostname_from_path(path: str) -> str:
        """Extract the hostname from a path like .../machine_bench_<hostname>.json."""
        basename = os.path.basename(path)  # e.g. "machine_bench_cortalim1.dashlab.in.json"
        # Strip prefix "machine_bench_" and suffix ".json"
        name = basename
        if name.startswith("machine_bench_"):
            name = name[len("machine_bench_"):]
        if name.endswith(".json"):
            name = name[:-5]
        return name
