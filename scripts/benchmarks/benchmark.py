#!/usr/bin/env python3
"""CLI entry-point for the scaling-factor benchmarking harness.

Two subcommands:

  provider  — measure absolute hardware scores (S_cpu, S_mem, S_disk, S_net)
              on the current machine.  Run on every provider and on the BEM.

  service   — measure reference runtimes and resource-sensitivity weights
              for each of the 8 valid benchmark services.
              MUST be run on the BEM only (requires Docker + optional root
              for network throttling).

Usage examples
--------------
# Benchmark the current machine as provider <uuid>:
  python scripts/benchmarks/benchmark.py provider \\
      --provider-id 34933555-5cca-41fb-aded-4ab7900c48d5 \\
      --out machine_bench.json

# Benchmark all 8 services on the BEM:
  python scripts/benchmarks/benchmark.py service \\
      --provider-id 34933555-5cca-41fb-aded-4ab7900c48d5 \\
      --out function_bench.json

# Benchmark a subset of services, override params:
  python scripts/benchmarks/benchmark.py service \\
      --provider-id ... \\
      --services 110,311 \\
      --B 3 --B-prime 2 --theta 0.5 \\
      --out partial_bench.json

# Smoke-test without executing Docker (prints planned actions):
  python scripts/benchmarks/benchmark.py provider --provider-id test --dry-run
  python scripts/benchmarks/benchmark.py service  --provider-id test --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.benchmarks.reference_images import (
    DEFAULT_B,
    DEFAULT_B_PRIME,
    DEFAULT_EPSILON,
    DEFAULT_SIZE,
    DEFAULT_THETA,
    VALID_BENCH_NOS,
)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def _check_docker() -> None:
    """Abort with a helpful message if docker-py is missing or the daemon is unreachable."""
    try:
        import docker
    except ModuleNotFoundError:
        print(
            "ERROR: Python package 'docker' is not installed for this interpreter.\n"
            "If you used `sudo python3`, that is usually the system Python — it does not\n"
            "see your venv. Either:\n"
            "  sudo python3 -m pip install docker requests\n"
            "or run without sudo after adding your user to the docker group:\n"
            "  sudo usermod -aG docker \"$USER\"   # then log out and back in\n"
            "  source .venv/bin/activate && python scripts/benchmarks/benchmark.py ...\n"
            "Also ensure the subcommand is spelled `provider` (one word), not `provide` + line break.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:
        print(
            f"ERROR: Cannot connect to Docker daemon: {exc}\n"
            "Make sure Docker is running and your user has permission to "
            "access the Docker socket (e.g. `sudo usermod -aG docker $USER`).",
            file=sys.stderr,
        )
        sys.exit(1)


def _check_root_for_net() -> bool:
    """Return True if we have root, log a warning otherwise."""
    if sys.platform != "linux":
        logging.getLogger(__name__).warning(
            "Network throttling (ThrottleNet) uses Linux `tc` and is not "
            "supported on %s. The 'net' dimension will be skipped; w_net "
            "will be treated as 0 in weight normalisation.", sys.platform
        )
        return False
    if os.geteuid() != 0:
        logging.getLogger(__name__).warning(
            "Network throttling requires root (current euid=%d). "
            "Run with sudo to enable the 'net' dimension, or accept that "
            "w_net will be 0. Continuing without network throttle.",
            os.geteuid(),
        )
        return False
    return True


def _write_output(data: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Output written to {path}")


# ---------------------------------------------------------------------------
# Subcommand: provider
# ---------------------------------------------------------------------------

def _cmd_provider(args: argparse.Namespace) -> None:
    _check_docker()
    from scripts.benchmarks.machine import run_machine_benchmark

    probes = None  # all four
    if args.probes:
        probes = [p.strip() for p in args.probes.split(",")]
        invalid = [p for p in probes if p not in ("cpu", "mem", "disk", "net")]
        if invalid:
            print(f"ERROR: Invalid probe names: {invalid}. "
                  "Choose from cpu,mem,disk,net.", file=sys.stderr)
            sys.exit(1)

    result = run_machine_benchmark(
        provider_id=args.provider_id,
        dry_run=args.dry_run,
        probes=probes,
    )
    _write_output(result, args.out)

    print("\n=== Summary ===")
    for k, v in result.items():
        if k not in ("units", "parameters"):
            print(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# Subcommand: service
# ---------------------------------------------------------------------------

def _cmd_service(args: argparse.Namespace) -> None:
    _check_docker()

    # Parse requested service list
    if args.services:
        requested = [s.strip() for s in args.services.split(",")]
        invalid = [s for s in requested if s not in VALID_BENCH_NOS]
        if invalid:
            print(
                f"ERROR: Unknown benchmark numbers: {invalid}.\n"
                f"Valid options: {VALID_BENCH_NOS}",
                file=sys.stderr,
            )
            sys.exit(1)
        service_nos = requested
    else:
        service_nos = None  # all 8

    # Determine which resource dimensions to skip
    skip_dims: list = []
    has_root = _check_root_for_net()
    if not has_root and "net" not in (args.skip_dims or []):
        skip_dims.append("net")
    if args.skip_dims:
        for d in args.skip_dims.split(","):
            d = d.strip()
            if d and d not in skip_dims:
                skip_dims.append(d)

    if skip_dims:
        logging.getLogger(__name__).info(
            "Skipping dimensions: %s", skip_dims
        )

    from scripts.benchmarks.function import run_service_benchmark

    result = run_service_benchmark(
        bem_provider_id=args.provider_id,
        service_nos=service_nos,
        B=args.B,
        B_prime=args.B_prime,
        theta=args.theta,
        size=args.size,
        epsilon=DEFAULT_EPSILON,
        dry_run=args.dry_run,
        skip_dims=skip_dims,
    )
    _write_output(result, args.out)

    # Print summary table
    print("\n=== Summary ===")
    print(f"{'Tag':<55} {'t_ref':>8} {'w_cpu':>6} {'w_mem':>6} {'w_disk':>6} {'w_net':>6}")
    print("-" * 95)
    for tag, svc in result.get("services", {}).items():
        err = svc.get("error")
        if err:
            print(f"  {tag:<53} ERROR: {err}")
        else:
            print(
                f"  {tag:<53} {svc['ref_runtime_ms']:>8.1f} "
                f"{svc['w_cpu']:>6.3f} {svc['w_mem']:>6.3f} "
                f"{svc['w_disk']:>6.3f} {svc['w_net']:>6.3f}"
            )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark.py",
        description=(
            "Scaling-factor benchmarking harness.\n"
            "Produces machine_bench.json (provider subcommand) and "
            "function_bench.json (service subcommand) for use with "
            "ScalingFactorStrategy."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging."
    )

    sub = parser.add_subparsers(dest="subcommand", required=True)

    # -- provider --
    p_prov = sub.add_parser(
        "provider",
        help="Measure absolute hardware scores for this machine.",
        description=(
            "Run synthetic CPU, memory, disk, and network probes inside "
            "Docker containers. Safe to run on any provider machine."
        ),
    )
    p_prov.add_argument(
        "--provider-id", required=True,
        help="UUID identifying this machine (used as a key in the output JSON)."
    )
    p_prov.add_argument(
        "--out", default="machine_bench.json",
        help="Output file path (default: machine_bench.json)."
    )
    p_prov.add_argument(
        "--probes", default=None,
        help="Comma-separated subset of probes to run: cpu,mem,disk,net. "
             "Default: all four."
    )
    p_prov.add_argument(
        "--dry-run", action="store_true",
        help="Print planned Docker invocations without executing them."
    )
    p_prov.set_defaults(func=_cmd_provider)

    # -- service --
    p_svc = sub.add_parser(
        "service",
        help="Measure reference runtimes and resource weights (BEM only).",
        description=(
            "Stage 1: run each service B times unthrottled -> t_ref.\n"
            "Stage 2: run B' times per resource dimension with theta throttle "
            "-> sensitivity weights w_cpu..w_net.\n\n"
            "Network throttling uses Linux tc and requires root (or sudo). "
            "Without root, the net dimension is skipped and w_net=0."
        ),
    )
    p_svc.add_argument(
        "--provider-id", required=True,
        help="UUID of the BEM (Benchmarking Environment Machine)."
    )
    p_svc.add_argument(
        "--out", default="function_bench.json",
        help="Output file path (default: function_bench.json)."
    )
    p_svc.add_argument(
        "--services", default=None,
        help=f"Comma-separated benchmark numbers to run. "
             f"Default: all 8 ({','.join(VALID_BENCH_NOS)}). "
             f"Example: --services 110,311,501"
    )
    p_svc.add_argument(
        "--B", type=int, default=DEFAULT_B,
        help=f"Reference runs per service (default: {DEFAULT_B})."
    )
    p_svc.add_argument(
        "--B-prime", type=int, default=DEFAULT_B_PRIME, dest="B_prime",
        help=f"Throttled runs per dimension (default: {DEFAULT_B_PRIME})."
    )
    p_svc.add_argument(
        "--theta", type=float, default=DEFAULT_THETA,
        help=f"Throttle fraction 0<theta<1 (default: {DEFAULT_THETA}). "
             "theta=0.5 halves each resource for the duration of Stage 2 runs."
    )
    p_svc.add_argument(
        "--size", default=DEFAULT_SIZE,
        choices=["test", "small", "large"],
        help=f"Benchmark payload size (default: {DEFAULT_SIZE})."
    )
    p_svc.add_argument(
        "--skip-dims", default=None, dest="skip_dims",
        help="Comma-separated dimensions to skip entirely (e.g. --skip-dims net,disk). "
             "net is auto-skipped without root on Linux."
    )
    p_svc.add_argument(
        "--dry-run", action="store_true",
        help="Print planned Docker invocations without executing them."
    )
    p_svc.set_defaults(func=_cmd_service)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    args.func(args)


if __name__ == "__main__":
    main()
