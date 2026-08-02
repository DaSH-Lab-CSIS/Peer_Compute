"""
Job Enricher - Join testbed requests with scheduler Job state.

Two modes:
  1. Window mode (primary): scheduler is queried for all jobs in [since, until].
     Used when the LB is fire-and-forget and never returns job_ids to the client.
  2. Job-ID mode (fallback): job_ids.jsonl present and non-empty, used for LB
     designs that do return a job_id in the HTTP response.

In both cases the same output files are produced.
"""
import csv
import glob as _glob
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


TIMEOUT_SENTINEL_PREFIX = '{"sweep": "timeout"'
_PAGE_SIZE = 10000


# ---------------------------------------------------------------------------
# Outcome classification
# ---------------------------------------------------------------------------

def classify_outcome(finished: bool, run_time: Optional[int], response: Any) -> str:
    """Classify terminal state using the run_time > 0 rule."""
    if not finished:
        return "pending"
    response_text = response if isinstance(response, str) else json.dumps(response or "")
    if response_text.startswith(TIMEOUT_SENTINEL_PREFIX):
        return "timeout"
    if (run_time or 0) > 0:
        return "success"
    return "error"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _duration_ms(start: Optional[datetime], end: Optional[datetime]) -> Optional[int]:
    if not start or not end:
        return None
    return int((end - start).total_seconds() * 1000)


def _read_json_file(path: Path) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def _read_jsonl_file(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Scheduler data fetchers
# ---------------------------------------------------------------------------

def _fetch_jobs_by_ids(
    scheduler_url: str,
    job_ids: List[int],
    chunk_size: int = 200,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """Fetch job status rows for specific job IDs."""
    base = scheduler_url.rstrip("/")
    endpoint = f"{base}/providers/direct_invocation_status/"
    jobs: List[Dict[str, Any]] = []

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for i in range(0, len(job_ids), chunk_size):
            batch = job_ids[i:i + chunk_size]
            resp = client.post(endpoint, json={"job_ids": batch})
            resp.raise_for_status()
            jobs.extend(resp.json().get("jobs", []))

    return jobs


def _fetch_jobs_by_window(
    scheduler_url: str,
    since: str,
    until: str,
    timeout: float = 300.0,
) -> List[Dict[str, Any]]:
    """Fetch all jobs whose start_time is in [since, until], paginating as needed."""
    base = scheduler_url.rstrip("/")
    endpoint = f"{base}/providers/jobs_in_window/"
    jobs: List[Dict[str, Any]] = []
    offset = 0

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while True:
            resp = client.get(
                endpoint,
                params={"since": since, "until": until, "limit": _PAGE_SIZE, "offset": offset},
            )
            resp.raise_for_status()
            payload = resp.json()
            page = payload.get("jobs", [])
            jobs.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

    return jobs


# ---------------------------------------------------------------------------
# Profile log loader
# ---------------------------------------------------------------------------

def _resolve_profile_paths(profile_logs: str) -> List[Path]:
    """Expand a comma-separated list of paths/globs into concrete file paths."""
    paths: List[Path] = []
    for entry in profile_logs.split(","):
        entry = entry.strip()
        if not entry:
            continue
        expanded = _glob.glob(entry, recursive=True)
        if expanded:
            paths.extend(Path(p) for p in expanded)
        else:
            paths.append(Path(entry))
    return [p for p in paths if p.exists()]


def _load_profile_by_corr(profile_logs: str) -> Dict[str, Dict[str, Any]]:
    """Parse one or more scheduler profile JSONL files (comma-separated paths or globs)
    and return a merged per-correlation_id summary dict.

    Multiple schedulers each produce their own profile file; this merges them all.
    Each scheduler handles distinct batches so corr_id collisions are impossible.

    For each correlation_id the returned dict has keys:
      ilp_solve_ms, fp_total_ms, cost_matrix_ms, delay_dict_ms,
      process_assignments_ms, batch_total_ms, queue_depth_at_dispatch
    """
    paths = _resolve_profile_paths(profile_logs)
    if not paths:
        return {}

    rows: List[Dict[str, Any]] = []
    for p in paths:
        rows.extend(_read_jsonl_file(p))

    # First pass: group raw rows by correlation_id
    by_corr: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        cid = row.get("correlation_id")
        if not cid:
            continue
        by_corr.setdefault(str(cid), []).append(row)

    label_map = {
        "find_providers-ilp_solve": "ilp_solve_ms",
        "find_providers-total": "fp_total_ms",
        "build_cost_matrix-total": "cost_matrix_ms",
        "build_delay_dict-total": "delay_dict_ms",
        "process_assignments-total": "process_assignments_ms",
    }

    result: Dict[str, Dict[str, Any]] = {}
    for cid, crows in by_corr.items():
        summary: Dict[str, Any] = {
            "ilp_solve_ms": None,
            "fp_total_ms": None,
            "cost_matrix_ms": None,
            "delay_dict_ms": None,
            "process_assignments_ms": None,
            "batch_total_ms": None,
            "queue_depth_at_dispatch": None,
        }
        for row in crows:
            label = row.get("label", "")
            if label in label_map:
                elapsed = row.get("elapsed_s")
                if elapsed is not None:
                    summary[label_map[label]] = round(float(elapsed) * 1000, 3)
            elif label == "batch-done":
                t = row.get("total_batch_time")
                if t is not None:
                    summary["batch_total_ms"] = round(float(t) * 1000, 3)
            elif label == "batch-start":
                qd = row.get("queue_depth")
                if qd is not None:
                    summary["queue_depth_at_dispatch"] = qd
        result[cid] = summary

    return result


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------

def _build_enriched_row(
    run_id: str,
    job: Dict[str, Any],
    request_row: Optional[Dict[str, Any]] = None,
    profile_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request_row = request_row or {}

    response = job.get("response")
    outcome = classify_outcome(
        finished=bool(job.get("finished", False)),
        run_time=job.get("run_time"),
        response=response,
    )

    error_kind = None
    if isinstance(response, str) and response.startswith(TIMEOUT_SENTINEL_PREFIX):
        try:
            error_kind = json.loads(response).get("kind")
        except json.JSONDecodeError:
            error_kind = "timeout"

    lb_received_time = _parse_iso(job.get("lb_received_time"))
    scheduler_received_time = _parse_iso(job.get("scheduler_received_time"))
    assigned_time = _parse_iso(job.get("assigned_to_provider_time"))
    ack_time = _parse_iso(job.get("ack_time"))
    start_time = _parse_iso(job.get("start_time"))
    finish_time = _parse_iso(job.get("finish_time"))
    provider_total_time_ms = int(job.get("total_time") or 0)
    end_time = None
    if start_time and provider_total_time_ms > 0:
        end_time = start_time + timedelta(milliseconds=provider_total_time_ms)

    ps = profile_summary or {}
    response_val = job.get("response")
    response_truncated = (str(response_val or ""))[:500]

    return {
        "run_id": run_id,
        "request_id": request_row.get("request_id"),
        "job_id": job.get("job_id"),
        "service_id": job.get("service_id"),
        "provider_user_id": job.get("provider_user_id"),
        "outcome": outcome,
        "error_kind": error_kind,
        "finished": job.get("finished"),
        "run_time": job.get("run_time"),
        "pull_time": job.get("pull_time"),
        "total_time": job.get("total_time"),
        "lb_received_time": job.get("lb_received_time"),
        "scheduler_received_time": job.get("scheduler_received_time"),
        "assigned_to_provider_time": job.get("assigned_to_provider_time"),
        "ack_time": job.get("ack_time"),
        "start_time": job.get("start_time"),
        "lb_to_scheduler_ms": _duration_ms(lb_received_time, scheduler_received_time),
        "scheduler_to_dispatch_ms": _duration_ms(scheduler_received_time, assigned_time),
        "dispatch_to_ack_ms": _duration_ms(assigned_time, ack_time),
        "provider_total_time_ms": provider_total_time_ms,
        "end_to_end_ms": _duration_ms(lb_received_time, end_time),
        "request_enqueue_timestamp": request_row.get("enqueue_timestamp"),
        "request_latency": request_row.get("latency"),
        "request_success": request_row.get("success"),
        # New fields
        "corr_id": job.get("corr_id"),
        "response": response_truncated,
        "cost": job.get("cost"),
        "finish_time": job.get("finish_time"),
        "finish_latency_ms": _duration_ms(lb_received_time, finish_time),
        "memory_usage": job.get("memory_usage"),
        "cpu_usage": job.get("cpu_usage"),
        "cpu_efficiency_score": job.get("cpu_efficiency_score"),
        "memory_efficiency_score": job.get("memory_efficiency_score"),
        # Prediction fields
        "predicted_runtime_ms": job.get("predicted_runtime_ms"),
        "prediction_strategy": job.get("prediction_strategy"),
        "prediction_source": job.get("prediction_source"),
        # Derived prediction accuracy (only for successful finished jobs)
        "abs_error_ms": (
            abs(job["predicted_runtime_ms"] - job["run_time"])
            if job.get("predicted_runtime_ms") is not None
            and job.get("run_time") and job.get("finished")
            else None
        ),
        "abs_pct_error": (
            abs(job["predicted_runtime_ms"] - job["run_time"]) / job["run_time"] * 100
            if job.get("predicted_runtime_ms") is not None
            and job.get("run_time") and job.get("finished")
            else None
        ),
        "signed_error_ms": (
            job["predicted_runtime_ms"] - job["run_time"]
            if job.get("predicted_runtime_ms") is not None
            and job.get("run_time") is not None and job.get("finished")
            else None
        ),
        # Profile log columns (None when no profile provided or no match)
        "ilp_solve_ms": ps.get("ilp_solve_ms"),
        "fp_total_ms": ps.get("fp_total_ms"),
        "cost_matrix_ms": ps.get("cost_matrix_ms"),
        "delay_dict_ms": ps.get("delay_dict_ms"),
        "process_assignments_ms": ps.get("process_assignments_ms"),
        "batch_total_ms": ps.get("batch_total_ms"),
        "queue_depth_at_dispatch": ps.get("queue_depth_at_dispatch"),
    }


_FIELDNAMES = [
    "run_id", "request_id", "job_id", "service_id", "provider_user_id",
    "outcome", "error_kind", "finished", "run_time", "pull_time", "total_time",
    "lb_received_time", "scheduler_received_time", "assigned_to_provider_time",
    "ack_time", "start_time", "lb_to_scheduler_ms", "scheduler_to_dispatch_ms",
    "dispatch_to_ack_ms", "provider_total_time_ms", "end_to_end_ms",
    "request_enqueue_timestamp", "request_latency", "request_success",
    # New fields
    "corr_id", "response", "cost", "finish_time", "finish_latency_ms",
    "memory_usage", "cpu_usage", "cpu_efficiency_score", "memory_efficiency_score",
    # Prediction fields
    "predicted_runtime_ms", "prediction_strategy", "prediction_source",
    "abs_error_ms", "abs_pct_error", "signed_error_ms",
    # Profile log columns
    "ilp_solve_ms", "fp_total_ms", "cost_matrix_ms", "delay_dict_ms",
    "process_assignments_ms", "batch_total_ms", "queue_depth_at_dispatch",
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def enrich_run(
    run_id: str,
    results_dir: str,
    scheduler_url: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    chunk_size: int = 200,
    scheduler_profile_log: Optional[str] = None,
    fetch_timeout: float = 300.0,
) -> Dict[str, Any]:
    """Enrich run metrics with scheduler-side per-job status.

    Args:
        run_id:                  Testbed run identifier (used to locate result files).
        results_dir:             Root of testbed results tree (contains csv/ and json/).
        scheduler_url:           Base URL of the scheduler, e.g. http://host:8000.
        since:                   ISO-8601 window start for the window-mode fallback.
                                 If omitted, extracted from metrics.json start_time.
        until:                   ISO-8601 window end. If omitted, defaults to now on
                                 the scheduler side.
        chunk_size:              Batch size for job-ID mode requests.
        scheduler_profile_log:   Optional comma-separated paths or glob patterns pointing
                                 to scheduler profile JSONL files. All matched files are
                                 merged — pass one per scheduler node to get full coverage.
        fetch_timeout:           HTTP timeout in seconds for each scheduler request (default 300).
    """
    results_root = Path(results_dir)
    metrics_path = results_root / "json" / f"{run_id}_metrics.json"
    job_ids_path = results_root / "json" / f"{run_id}_job_ids.jsonl"

    if not metrics_path.exists():
        raise FileNotFoundError(f"Metrics file not found: {metrics_path}")

    metrics_payload = _read_json_file(metrics_path)
    request_details: List[Dict[str, Any]] = metrics_payload.get("request_details", [])

    # Build a lookup from job_id -> testbed request row (used in job-ID mode
    # and for any window-mode rows that happen to match).
    requests_by_job_id: Dict[int, Dict[str, Any]] = {}
    for req in request_details:
        jid = req.get("job_id")
        if jid is not None:
            requests_by_job_id[int(jid)] = req

    # ------------------------------------------------------------------
    # Load optional scheduler profile log
    # ------------------------------------------------------------------
    profile_by_corr: Dict[str, Dict[str, Any]] = {}
    if scheduler_profile_log:
        profile_by_corr = _load_profile_by_corr(scheduler_profile_log)

    # ------------------------------------------------------------------
    # Decide which fetching mode to use
    # ------------------------------------------------------------------
    job_id_rows: List[Dict[str, Any]] = []
    if job_ids_path.exists():
        job_id_rows = _read_jsonl_file(job_ids_path)

    use_window_mode = len(job_id_rows) == 0

    if use_window_mode:
        # Derive since from metrics start_time if not supplied
        if not since:
            raw_start = metrics_payload.get("aggregate_metrics", {}).get("start_time")
            if raw_start:
                since = datetime.fromtimestamp(float(raw_start)).astimezone().isoformat()
        if not since:
            raise ValueError(
                "Window mode requires 'since'. Pass it explicitly or ensure "
                "aggregate_metrics.start_time exists in metrics.json."
            )
        job_rows = _fetch_jobs_by_window(
            scheduler_url=scheduler_url,
            since=since,
            until=until or "",
            timeout=fetch_timeout,
        )
        # In window mode there are no per-request correlates, so request_row
        # will always be empty — that's expected.
        enriched_rows = [
            _build_enriched_row(
                run_id,
                job,
                profile_summary=profile_by_corr.get(str(job.get("corr_id", ""))) if profile_by_corr else None,
            )
            for job in job_rows
        ]
    else:
        job_ids = [int(r["job_id"]) for r in job_id_rows if r.get("job_id") is not None]
        jobs = _fetch_jobs_by_ids(
            scheduler_url=scheduler_url,
            job_ids=job_ids,
            chunk_size=chunk_size,
            timeout=fetch_timeout,
        )
        jobs_by_id = {int(j["job_id"]): j for j in jobs if j.get("job_id") is not None}
        enriched_rows = [
            _build_enriched_row(
                run_id,
                jobs_by_id.get(int(r["job_id"]), {}),
                requests_by_job_id.get(int(r["job_id"])),
                profile_summary=profile_by_corr.get(
                    str(jobs_by_id.get(int(r["job_id"]), {}).get("corr_id", ""))
                ) if profile_by_corr else None,
            )
            for r in job_id_rows
            if r.get("job_id") is not None
        ]

    # ------------------------------------------------------------------
    # Aggregate outcomes
    # ------------------------------------------------------------------
    outcome_breakdown = {"success": 0, "error": 0, "timeout": 0, "pending": 0}
    for row in enriched_rows:
        outcome_breakdown[row["outcome"]] += 1

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    csv_output = results_root / "csv" / f"{run_id}_jobs_enriched.csv"
    json_output = results_root / "json" / f"{run_id}_jobs_enriched.json"
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)

    with open(csv_output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for row in enriched_rows:
            writer.writerow(row)

    enriched_json_payload = {
        "run_id": run_id,
        "scheduler_url": scheduler_url,
        "mode": "window" if use_window_mode else "job_ids",
        "since": since,
        "until": until,
        "job_count": len(enriched_rows),
        "outcome_breakdown": outcome_breakdown,
        "rows": enriched_rows,
    }
    with open(json_output, "w") as f:
        json.dump(enriched_json_payload, f, indent=2, default=str)

    # Patch outcome_breakdown back into metrics.json
    aggregate_metrics = metrics_payload.get("aggregate_metrics", {})
    aggregate_metrics["outcome_breakdown"] = outcome_breakdown
    metrics_payload["aggregate_metrics"] = aggregate_metrics
    with open(metrics_path, "w") as f:
        json.dump(metrics_payload, f, indent=2, default=str)

    return {
        "csv_path": str(csv_output),
        "json_path": str(json_output),
        "metrics_path": str(metrics_path),
        "outcome_breakdown": outcome_breakdown,
        "mode": "window" if use_window_mode else "job_ids",
    }
