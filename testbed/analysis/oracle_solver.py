"""
oracle_solver.py — Offline clairvoyant oracle for distributed serverless scheduling.

Given an enriched CSV from a real run (where actual run_times are known), re-solves
the ILP assignment problem for each batch using actual runtimes as costs. This gives
the best possible makespan for each batch under perfect predictions — an upper-bound
baseline for scheduling quality.

Usage:
    python oracle_solver.py \\
        --enriched path/to/run_jobs_enriched.csv \\
        [--output-dir testbed/results/reports]

Output goes to <output-dir>/<run_id>_oracle/.
"""

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

import pandas as pd

# Add the scheduler package to sys.path so we can import mincost without Django
sys.path.insert(0, str(Path(__file__).parents[2] / "scheduler"))

# Suppress PuLP solver banner and CBC output
import pulp  # noqa: F401 — imported here to apply log suppression before mincost
logging.getLogger("pulp").setLevel(logging.WARNING)

from providers.mincost import minimize_total_cost  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Threshold (seconds) between consecutive assigned_to_provider_time values that
# signals a new batch boundary — same as scheduling_quality.py convention.
BATCH_GAP_SECONDS = 1.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute offline clairvoyant oracle makespans for each scheduling batch."
    )
    parser.add_argument(
        "--enriched",
        required=True,
        help="Path to enriched jobs CSV (e.g. <run_id>_jobs_enriched.csv).",
    )
    parser.add_argument(
        "--output-dir",
        default="testbed/results/reports",
        help="Parent directory for output. Results go into <output-dir>/<run_id>_oracle/.",
    )
    return parser.parse_args()


def load_success_jobs(enriched_path: Path) -> pd.DataFrame:
    """Load the enriched CSV and return only outcome=success rows with parsed datetimes."""
    df = pd.read_csv(enriched_path, low_memory=False)
    df = df[df["outcome"] == "success"].copy()
    if df.empty:
        raise ValueError(f"No success rows found in {enriched_path}")

    # Parse ISO datetimes (they carry timezone info).
    df["assigned_to_provider_time"] = pd.to_datetime(
        df["assigned_to_provider_time"], utc=True
    )
    df["finish_time"] = pd.to_datetime(df["finish_time"], utc=True)

    # Ensure run_time is numeric (milliseconds integer).
    df["run_time"] = pd.to_numeric(df["run_time"], errors="coerce").fillna(0).astype(int)

    df = df.sort_values("assigned_to_provider_time").reset_index(drop=True)
    return df


def split_into_batches(df: pd.DataFrame) -> list[pd.DataFrame]:
    """
    Split rows into batches by detecting gaps > BATCH_GAP_SECONDS between
    consecutive assigned_to_provider_time values.

    Returns a list of DataFrames, one per batch.
    """
    if df.empty:
        return []

    times = df["assigned_to_provider_time"].values
    batch_indices = [[0]]

    for i in range(1, len(df)):
        gap_s = (
            pd.Timestamp(times[i]) - pd.Timestamp(times[i - 1])
        ).total_seconds()
        if gap_s > BATCH_GAP_SECONDS:
            batch_indices.append([])
        batch_indices[-1].append(i)

    return [df.iloc[idxs].reset_index(drop=True) for idxs in batch_indices]


def build_service_medians(df: pd.DataFrame) -> dict[int, float]:
    """
    Compute median run_time (ms) for each service_id across all success rows.
    Used as the fill cost for (worker, job) pairs not observed in a batch.
    """
    return df.groupby("service_id")["run_time"].median().to_dict()


def compute_actual_makespan_ms(batch: pd.DataFrame) -> float:
    """
    Actual makespan = max(finish_time) - min(assigned_to_provider_time) in ms.
    """
    t_start = batch["assigned_to_provider_time"].min()
    t_end = batch["finish_time"].max()
    return (t_end - t_start).total_seconds() * 1000.0


def solve_oracle_batch(
    batch: pd.DataFrame,
    service_medians: dict[int, float],
    batch_idx: int,
) -> dict:
    """
    Solve the ILP oracle for one batch.

    Returns a dict with keys:
        batch_idx, n_jobs, oracle_makespan_ms, actual_makespan_ms,
        oracle_gap_pct, assignments
    """
    n_jobs = len(batch)
    actual_makespan_ms = compute_actual_makespan_ms(batch)

    # Trivial case: single job — oracle = actual run_time, no ILP needed.
    if n_jobs == 1:
        row = batch.iloc[0]
        oracle_ms = float(row["run_time"])
        gap_pct = ((actual_makespan_ms - oracle_ms) / oracle_ms * 100.0
                   if oracle_ms > 0 else 0.0)
        return {
            "batch_idx": batch_idx,
            "n_jobs": 1,
            "oracle_makespan_ms": oracle_ms,
            "actual_makespan_ms": actual_makespan_ms,
            "oracle_gap_pct": gap_pct,
            "assignments": [
                {
                    "job_id": int(row["job_id"]) if pd.notna(row.get("job_id")) else None,
                    "service_id": int(row["service_id"]),
                    "assigned_provider": str(row["provider_user_id"]),
                    "run_time_ms": int(row["run_time"]),
                }
            ],
        }

    workers = list(batch["provider_user_id"].unique())

    # Build job keys as (row_position, service_id) so every job has a unique key
    # even when multiple jobs share the same service_id.
    jobs = [(pos, int(row["service_id"])) for pos, (_, row) in enumerate(batch.iterrows())]

    # Build cost matrix: cost_matrix[worker][job_key] = run_time_ms.
    # For the worker that actually executed the job, use the real run_time.
    # For all other workers, use the service median across all success rows.
    cost_matrix: dict[str, dict[tuple, float]] = {w: {} for w in workers}

    for pos, (_, row) in enumerate(batch.iterrows()):
        job_key = (pos, int(row["service_id"]))
        actual_worker = str(row["provider_user_id"])
        actual_cost = float(row["run_time"])
        fill_cost = float(service_medians.get(int(row["service_id"]), actual_cost))

        for w in workers:
            cost_matrix[w][job_key] = actual_cost if w == actual_worker else fill_cost

    delay = {w: 0.0 for w in workers}

    # Suppress PuLP stdout during solve.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assignment, _total_cost = minimize_total_cost(workers, jobs, cost_matrix, delay)

    if assignment is None:
        log.warning(
            "Batch %d: ILP solve failed — falling back to actual makespan.", batch_idx
        )
        oracle_ms = actual_makespan_ms
        gap_pct = 0.0
        # Build trivial assignment (each job stays with its actual provider).
        assignment_records = [
            {
                "job_id": int(row["job_id"]) if pd.notna(row.get("job_id")) else None,
                "service_id": int(row["service_id"]),
                "assigned_provider": str(row["provider_user_id"]),
                "run_time_ms": int(row["run_time"]),
            }
            for _, row in batch.iterrows()
        ]
        return {
            "batch_idx": batch_idx,
            "n_jobs": n_jobs,
            "oracle_makespan_ms": oracle_ms,
            "actual_makespan_ms": actual_makespan_ms,
            "oracle_gap_pct": gap_pct,
            "assignments": assignment_records,
        }

    # Oracle makespan: for each worker, sum run_times of all assigned jobs;
    # oracle_makespan = max over workers of their total assigned run_time.
    worker_load: dict[str, float] = {w: 0.0 for w in workers}
    for job_key, assigned_worker in assignment.items():
        worker_load[assigned_worker] += cost_matrix[assigned_worker][job_key]

    oracle_ms = max(worker_load.values()) if worker_load else 0.0

    gap_pct = (
        (actual_makespan_ms - oracle_ms) / oracle_ms * 100.0
        if oracle_ms > 0
        else 0.0
    )

    # Build assignment records for JSON output.
    assignment_records = []
    for pos, (_, row) in enumerate(batch.iterrows()):
        job_key = (pos, int(row["service_id"]))
        assigned_worker = assignment.get(job_key, str(row["provider_user_id"]))
        assignment_records.append(
            {
                "job_id": int(row["job_id"]) if pd.notna(row.get("job_id")) else None,
                "service_id": int(row["service_id"]),
                "assigned_provider": assigned_worker,
                "run_time_ms": int(cost_matrix[assigned_worker][job_key]),
            }
        )

    return {
        "batch_idx": batch_idx,
        "n_jobs": n_jobs,
        "oracle_makespan_ms": oracle_ms,
        "actual_makespan_ms": actual_makespan_ms,
        "oracle_gap_pct": gap_pct,
        "assignments": assignment_records,
    }


def write_outputs(
    results: list[dict],
    run_id: str,
    output_dir: Path,
) -> None:
    """Write the three output files to <output_dir>/<run_id>_oracle/."""
    out_dir = output_dir / f"{run_id}_oracle"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. oracle_assignments_<run_id>.json
    json_path = out_dir / f"oracle_assignments_{run_id}.json"
    with open(json_path, "w") as fh:
        json.dump(results, fh, indent=2)
    log.info("Wrote %s", json_path)

    # 2. oracle_summary.csv
    csv_path = out_dir / "oracle_summary.csv"
    summary_rows = [
        {
            "batch_idx": r["batch_idx"],
            "n_jobs": r["n_jobs"],
            "oracle_makespan_ms": r["oracle_makespan_ms"],
            "actual_makespan_ms": r["actual_makespan_ms"],
            "oracle_gap_pct": r["oracle_gap_pct"],
        }
        for r in results
    ]
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(csv_path, index=False)
    log.info("Wrote %s", csv_path)

    # 3. oracle_summary.txt
    gaps = [r["oracle_gap_pct"] for r in results]
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    sorted_gaps = sorted(gaps)
    n = len(sorted_gaps)
    if n % 2 == 1:
        median_gap = sorted_gaps[n // 2]
    else:
        median_gap = (sorted_gaps[n // 2 - 1] + sorted_gaps[n // 2]) / 2.0

    best = min(results, key=lambda r: r["oracle_gap_pct"])
    worst = max(results, key=lambda r: r["oracle_gap_pct"])

    txt_path = out_dir / "oracle_summary.txt"
    with open(txt_path, "w") as fh:
        fh.write(f"Oracle Solver Report — run_id: {run_id}\n")
        fh.write("=" * 60 + "\n\n")
        fh.write(f"Total batches analysed : {len(results)}\n")
        fh.write(f"Mean oracle gap        : {mean_gap:.2f}%\n")
        fh.write(f"Median oracle gap      : {median_gap:.2f}%\n\n")
        fh.write("Best batch (smallest gap):\n")
        fh.write(
            f"  batch_idx={best['batch_idx']}, n_jobs={best['n_jobs']}, "
            f"oracle={best['oracle_makespan_ms']:.1f} ms, "
            f"actual={best['actual_makespan_ms']:.1f} ms, "
            f"gap={best['oracle_gap_pct']:.2f}%\n\n"
        )
        fh.write("Worst batch (largest gap):\n")
        fh.write(
            f"  batch_idx={worst['batch_idx']}, n_jobs={worst['n_jobs']}, "
            f"oracle={worst['oracle_makespan_ms']:.1f} ms, "
            f"actual={worst['actual_makespan_ms']:.1f} ms, "
            f"gap={worst['oracle_gap_pct']:.2f}%\n"
        )
    log.info("Wrote %s", txt_path)


def main() -> None:
    args = parse_args()
    enriched_path = Path(args.enriched).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not enriched_path.exists():
        log.error("Enriched CSV not found: %s", enriched_path)
        sys.exit(1)

    log.info("Loading success jobs from %s", enriched_path)
    df = load_success_jobs(enriched_path)

    run_id = str(df["run_id"].iloc[0]) if "run_id" in df.columns else enriched_path.stem
    log.info("run_id = %s  |  success rows = %d", run_id, len(df))

    service_medians = build_service_medians(df)
    log.info("Service median run_times: %s", {k: f"{v:.0f} ms" for k, v in service_medians.items()})

    batches = split_into_batches(df)
    log.info("Detected %d batches (gap threshold = %.1f s)", len(batches), BATCH_GAP_SECONDS)

    results = []
    for batch_idx, batch in enumerate(batches):
        log.info(
            "Batch %d / %d — %d jobs, workers: %s",
            batch_idx,
            len(batches) - 1,
            len(batch),
            list(batch["provider_user_id"].unique()),
        )
        result = solve_oracle_batch(batch, service_medians, batch_idx)
        results.append(result)
        log.info(
            "  oracle=%.1f ms  actual=%.1f ms  gap=%.2f%%",
            result["oracle_makespan_ms"],
            result["actual_makespan_ms"],
            result["oracle_gap_pct"],
        )

    write_outputs(results, run_id, output_dir)

    gaps = [r["oracle_gap_pct"] for r in results]
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    log.info("Done. Mean oracle gap across %d batches: %.2f%%", len(results), mean_gap)


if __name__ == "__main__":
    main()
