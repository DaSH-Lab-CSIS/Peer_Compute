"""
Scheduler profiling analysis script.

Usage:
    python3 analyze_profile.py [JSONL_FILE_OR_GLOB ...]

Default: analyses the most recent scheduler/logs/scheduler_profile_run_*.jsonl
Multiple files / globs are merged in chronological order.

Output folder is named automatically from the run codes in the input files:
    scheduler/logs/profile_charts_run_YYYYMMDD_HHMMSS/        (single run)
    scheduler/logs/profile_charts_run_XXX_run_YYY/            (merged runs)

A runs.txt file listing all analysed run codes is written into the folder.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LOGS_DIR = Path("scheduler/logs")
CHARTS_BASE = LOGS_DIR  # charts/<derived-name> lives next to the .jsonl files
RUN_GLOB = str(LOGS_DIR / "scheduler_profile_run_*.jsonl")


def _extract_run_code(path: str) -> str:
    """Return 'run_YYYYMMDD_HHMMSS' from a filename, or the plain file stem."""
    stem = Path(path).stem                         # e.g. scheduler_profile_run_20260430_110500
    m = re.search(r"(run_\d{8}_\d{6})", stem)
    return m.group(1) if m else stem


def _derive_output_dir(paths: list[str]) -> Path:
    """Build output dir name from the sorted run codes of the input files."""
    codes = sorted({_extract_run_code(p) for p in paths})
    if len(codes) == 1:
        folder = f"profile_charts_{codes[0]}"
    else:
        folder = f"profile_charts_{codes[0]}_{codes[-1]}"
    return CHARTS_BASE / folder

PHASE_COLS = [
    "db_pass_s",
    "pull_time_query_s",
    "delay_dict_s",
    "ilp_solve_s",
    "job_create_s",
    "mqtt_publish_s",
    "other_s",
]
PHASE_LABELS = {
    "db_pass_s":        "DB pass (job hist)",
    "pull_time_query_s":"Pull-time ORM",
    "delay_dict_s":     "Delay dict",
    "ilp_solve_s":      "ILP solve",
    "job_create_s":     "Job create",
    "mqtt_publish_s":   "MQTT publish",
    "other_s":          "Other",
}
PHASE_COLORS = [
    "#e74c3c", "#e67e22", "#f1c40f",
    "#2ecc71", "#3498db", "#9b59b6", "#95a5a6",
]

# ---------------------------------------------------------------------------
# Load + parse
# ---------------------------------------------------------------------------

def load_jsonl(paths: list[str]) -> list[dict]:
    rows = []
    for p in sorted(paths):
        with open(p, "r", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def to_df(raw: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(raw)
    if "ts_utc" in df.columns:
        df["ts"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Build per-batch summary
# ---------------------------------------------------------------------------

def build_batch_df(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot the flat event rows into one row per completed batch."""
    batches = []

    # Walk the df in time order; group by correlation_id (cid)
    # We gather the key timed events we care about.
    KEYS = {
        "batch-start":                        ["n_services", "lb", "queue_depth"],
        "batch-done":                          ["total_batch_time", "processed", "errors"],
        "find_providers-total":                ["elapsed_s", "n_providers"],
        "build_cost_matrix-db_pass":           ["elapsed_s", "job_latest_run_query_s",
                                                 "job_latest_run_calls", "db_pass_non_orm_s"],
        "build_cost_matrix-predict_all_providers": ["elapsed_s", "predict_strategy_s",
                                                     "pull_time_query_s", "pull_time_calls",
                                                     "cache_probe_s", "subdict_build_s",
                                                     "cache_python_overhead_s"],
        "build_delay_dict-provider_loop":      ["elapsed_s", "get_last_start_time_s",
                                                 "calculate_current_delay_s"],
        "build_delay_dict-total":              ["elapsed_s"],
        "find_providers-ilp_solve":            ["elapsed_s", "n_vars", "total_cost"],
        "process_assignments-tx1_job_create":  ["elapsed_s"],
        "process_assignments-mqtt_publish_jobs": ["elapsed_s", "n_sent"],
        "process_assignments-total":           ["elapsed_s"],
        "find_providers-get_ready_providers":  ["elapsed_s", "n_providers"],
        "find_providers-print_ready_providers_rows": ["elapsed_s"],
    }

    by_cid: dict[str, dict] = defaultdict(dict)
    ts_by_cid: dict[str, pd.Timestamp] = {}
    qd_by_cid: dict[str, int] = {}

    for _, row in df.iterrows():
        label = row.get("label", "")
        cid = row.get("correlation_id", "")
        if not cid:
            continue
        if label not in KEYS:
            continue
        rec = by_cid[cid]
        if label == "batch-start" and cid not in ts_by_cid:
            ts_by_cid[cid] = row.get("ts")
        for col in KEYS[label]:
            if col in row and pd.notna(row[col]):
                key = f"{label}__{col}" if col == "elapsed_s" else col
                rec[key] = row[col]

    for cid, rec in by_cid.items():
        if "total_batch_time" not in rec:
            continue  # incomplete batch
        rec["correlation_id"] = cid
        rec["ts"] = ts_by_cid.get(cid)
        batches.append(rec)

    if not batches:
        return pd.DataFrame()

    bdf = pd.DataFrame(batches).sort_values("ts").reset_index(drop=True)
    bdf["batch_index"] = range(1, len(bdf) + 1)

    # Derived columns - raw elapsed pointers
    bdf["db_pass_s"]         = bdf.get("build_cost_matrix-db_pass__elapsed_s", 0).fillna(0)
    bdf["pull_time_query_s"] = bdf.get("pull_time_query_s", 0).fillna(0)
    bdf["delay_dict_s"]      = bdf.get("build_delay_dict-total__elapsed_s", 0).fillna(0)
    bdf["ilp_solve_s"]       = bdf.get("find_providers-ilp_solve__elapsed_s", 0).fillna(0)
    bdf["job_create_s"]      = bdf.get("process_assignments-tx1_job_create__elapsed_s", 0).fillna(0)
    bdf["mqtt_publish_s"]    = bdf.get("process_assignments-mqtt_publish_jobs__elapsed_s", 0).fillna(0)

    accounted = bdf[["db_pass_s","pull_time_query_s","delay_dict_s",
                      "ilp_solve_s","job_create_s","mqtt_publish_s"]].sum(axis=1)
    bdf["other_s"] = (bdf["total_batch_time"] - accounted).clip(lower=0)

    # Per-service normalization
    bdf["n_services"] = bdf.get("n_services", 50).fillna(50).astype(float)
    bdf["total_s_per_service"] = bdf["total_batch_time"] / bdf["n_services"].replace(0, 1)
    bdf["db_s_per_service"]    = bdf["db_pass_s"]         / bdf["n_services"].replace(0, 1)
    bdf["pull_s_per_service"]  = bdf["pull_time_query_s"] / bdf["n_services"].replace(0, 1)

    # ORM overhead per call
    jqc = bdf.get("job_latest_run_calls", np.nan)
    jqs = bdf.get("job_latest_run_query_s", np.nan)
    bdf["ms_per_job_latest_run"] = (jqs / jqc.replace(0, np.nan) * 1000).where(jqc > 0)

    ptc = bdf.get("pull_time_calls", np.nan)
    pts = bdf.get("pull_time_query_s", np.nan)
    bdf["ms_per_pull_time"] = (pts / ptc.replace(0, np.nan) * 1000).where(ptc > 0)

    gls = bdf.get("get_last_start_time_s", np.nan)
    bdf["ms_per_get_last_start"] = (gls / bdf["n_providers"].replace(0, np.nan) * 1000
                                     ).where(bdf["n_providers"] > 0)

    return bdf


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def divider(title: str = "") -> None:
    w = 80
    if title:
        pad = (w - len(title) - 2) // 2
        print("\n" + "=" * pad + f" {title} " + "=" * (w - pad - len(title) - 2))
    else:
        print("\n" + "=" * w)


def fmt_s(v):
    if pd.isna(v):
        return "-"
    if abs(v) < 0.001:
        return f"{v*1000:.2f}ms"
    return f"{v:.3f}s"


def stats_table(series: pd.Series, label: str) -> None:
    vals = series.dropna()
    if vals.empty:
        return
    pcts = vals.quantile([0.5, 0.75, 0.95, 0.99])
    rows = [
        ("count",  f"{len(vals)}"),
        ("mean",   fmt_s(vals.mean())),
        ("min",    fmt_s(vals.min())),
        ("p50",    fmt_s(pcts[0.50])),
        ("p75",    fmt_s(pcts[0.75])),
        ("p95",    fmt_s(pcts[0.95])),
        ("p99",    fmt_s(pcts[0.99])),
        ("max",    fmt_s(vals.max())),
    ]
    print(f"\n  {label}")
    for k, v in rows:
        print(f"    {k:<8} {v}")


def print_batch_summary(bdf: pd.DataFrame) -> None:
    divider("BATCH SUMMARY")
    print(f"  Total batches: {len(bdf)}")
    n50 = bdf[bdf["n_services"] == 50]
    n1  = bdf[bdf["n_services"] == 1]
    print(f"  n_services=50 batches: {len(n50)}   n_services=1 batches: {len(n1)}")
    if bdf["ts"].notna().any():
        t0 = bdf["ts"].dropna().min()
        t1 = bdf["ts"].dropna().max()
        dur = (t1 - t0).total_seconds()
        print(f"  Time window: {t0.isoformat()}  ->  {t1.isoformat()}  ({dur:.0f}s)")


def print_timing_tables(bdf: pd.DataFrame) -> None:
    divider("TIMING STATS (n_services=50 batches)")
    b50 = bdf[bdf["n_services"] == 50]
    if b50.empty:
        print("  No n=50 batches found.")
        return

    for col, label in [
        ("total_batch_time",  "Total batch time"),
        ("db_pass_s",         "DB pass total (job_latest_run ORM loop)"),
        ("job_latest_run_query_s", "  -> job_latest_run_query_s (ORM only)"),
        ("db_pass_non_orm_s", "  -> db_pass_non_orm_s (loop overhead)"),
        ("pull_time_query_s", "Pull-time ORM (cache pass)"),
        ("delay_dict_s",      "build_delay_dict total"),
        ("get_last_start_time_s", "  -> get_last_start_time ORM"),
        ("calculate_current_delay_s", "  -> calculate_current_delay"),
        ("ilp_solve_s",       "ILP solve"),
        ("job_create_s",      "job create (tx1)"),
        ("mqtt_publish_s",    "MQTT publish"),
        ("other_s",           "Other (unaccounted)"),
    ]:
        if col in b50.columns:
            stats_table(b50[col], label)

    divider("PER-SERVICE LATENCY (n_services=50 batches)")
    for col, label in [
        ("total_s_per_service",  "Total batch time / n_services"),
        ("db_s_per_service",     "DB pass / n_services"),
        ("pull_s_per_service",   "Pull-time ORM / n_services"),
    ]:
        if col in b50.columns:
            stats_table(b50[col], label)

    divider("ORM LATENCY PER CALL (n_services=50 batches)")
    for col, label in [
        ("ms_per_job_latest_run", "ms per Job.get_latest_run_time()"),
        ("ms_per_pull_time",      "ms per Job.get_latest_pull_time()"),
        ("ms_per_get_last_start", "ms per provider.get_last_start_time()"),
    ]:
        if col in b50.columns:
            # These columns are already in ms; pass a series scaled to seconds so
            # fmt_s can render them cleanly in the right unit.
            stats_table(b50[col] / 1000.0, label)


def print_error_summary(bdf: pd.DataFrame) -> None:
    divider("ERROR SUMMARY")
    if "errors" in bdf.columns:
        total_errors = int(bdf["errors"].fillna(0).sum())
        total_processed = int(bdf["processed"].fillna(0).sum()) if "processed" in bdf.columns else 0
        print(f"  Total errors:    {total_errors}")
        print(f"  Total processed: {total_processed}")
        if total_errors + total_processed > 0:
            err_rate = total_errors / (total_errors + total_processed) * 100
            print(f"  Error rate:      {err_rate:.1f}%")


def print_queue_growth(bdf: pd.DataFrame) -> None:
    divider("QUEUE DEPTH")
    if "queue_depth" in bdf.columns:
        qd = bdf["queue_depth"].dropna()
        if qd.empty:
            return
        print(f"  min={qd.min():.0f}  max={qd.max():.0f}  final={qd.iloc[-1]:.0f}")
        # check if growing
        if len(qd) >= 4:
            first_half = qd.iloc[:len(qd)//2].mean()
            second_half = qd.iloc[len(qd)//2:].mean()
            direction = "GROWING" if second_half > first_half * 1.1 else (
                "shrinking" if second_half < first_half * 0.9 else "stable"
            )
            print(f"  Trend: {direction} (first-half avg {first_half:.0f} -> second-half avg {second_half:.0f})")


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _save(fig: plt.Figure, name: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / name
    fig.savefig(path, bbox_inches="tight", dpi=130)
    plt.close(fig)
    print(f"  saved: {path}")


def chart_phase_stacked_bar(bdf: pd.DataFrame, output_dir: Path) -> None:
    """Stacked bar: time breakdown per batch."""
    data = bdf[["batch_index"] + PHASE_COLS].copy()
    x = data["batch_index"].values
    bottoms = np.zeros(len(x))

    fig, ax = plt.subplots(figsize=(14, 5))
    for col, color in zip(PHASE_COLS, PHASE_COLORS):
        vals = data[col].fillna(0).values
        ax.bar(x, vals, bottom=bottoms, color=color, label=PHASE_LABELS[col], width=0.85)
        bottoms += vals

    ax.set_xlabel("Batch index")
    ax.set_ylabel("Seconds")
    ax.set_title("Batch time breakdown by phase")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1fs"))
    fig.tight_layout()
    _save(fig, "01_phase_stacked_bar.png", output_dir)


def chart_total_batch_time_trend(bdf: pd.DataFrame, output_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 4))
    b50 = bdf[bdf["n_services"] == 50]
    b1  = bdf[bdf["n_services"] != 50]
    if not b50.empty:
        ax.plot(b50["batch_index"], b50["total_batch_time"], "o-", color="#e74c3c",
                markersize=4, label="n_services=50")
    if not b1.empty:
        ax.scatter(b1["batch_index"], b1["total_batch_time"], color="#3498db", s=30,
                   zorder=5, label="n_services<50")
    ax.set_xlabel("Batch index")
    ax.set_ylabel("Total batch time (s)")
    ax.set_title("Total batch time over time")
    ax.legend(fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1fs"))
    fig.tight_layout()
    _save(fig, "02_total_batch_trend.png", output_dir)


def chart_orm_breakdown(bdf: pd.DataFrame, output_dir: Path) -> None:
    """For n=50 batches: show split of db_pass into ORM vs overhead, and pull_time."""
    b50 = bdf[bdf["n_services"] == 50]
    if b50.empty:
        return

    x = b50["batch_index"].values
    fig, ax = plt.subplots(figsize=(14, 5))

    cols = ["job_latest_run_query_s", "pull_time_query_s", "get_last_start_time_s"]
    labels = ["Job.get_latest_run_time (db_pass)", "Job.get_latest_pull_time (cache pass)",
              "provider.get_last_start_time (delay_dict)"]
    colors = ["#c0392b", "#e67e22", "#f39c12"]
    bottoms = np.zeros(len(x))
    for col, lbl, clr in zip(cols, labels, colors):
        vals = b50[col].fillna(0).values if col in b50.columns else np.zeros(len(x))
        ax.bar(x, vals, bottom=bottoms, color=clr, label=lbl, width=0.85)
        bottoms += vals

    ax.set_xlabel("Batch index")
    ax.set_ylabel("Seconds")
    ax.set_title("ORM call time breakdown (n_services=50 batches)")
    ax.legend(fontsize=8, loc="upper left")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1fs"))
    fig.tight_layout()
    _save(fig, "03_orm_breakdown.png", output_dir)


def chart_per_call_latency(bdf: pd.DataFrame, output_dir: Path) -> None:
    """ms per ORM call over batches."""
    b50 = bdf[bdf["n_services"] == 50]
    if b50.empty:
        return

    fig, axes = plt.subplots(1, 3, figsize=(15, 4), sharey=False)
    specs = [
        ("ms_per_job_latest_run", "Job.get_latest_run_time", "#c0392b"),
        ("ms_per_pull_time",      "Job.get_latest_pull_time", "#e67e22"),
        ("ms_per_get_last_start", "provider.get_last_start_time", "#f39c12"),
    ]
    for ax, (col, label, color) in zip(axes, specs):
        if col not in b50.columns:
            ax.set_visible(False)
            continue
        data = b50[col].dropna()
        if data.empty:
            ax.set_visible(False)
            continue
        ax.plot(b50.loc[data.index, "batch_index"], data, "o-", color=color, markersize=4)
        ax.axhline(data.mean(), linestyle="--", color="gray", linewidth=1, label=f"mean {data.mean():.1f}ms")
        ax.set_title(label, fontsize=9)
        ax.set_ylabel("ms per call")
        ax.set_xlabel("Batch index")
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1fms"))
        ax.legend(fontsize=8)
    fig.suptitle("ORM latency per call (n_services=50 batches)", y=1.01)
    fig.tight_layout()
    _save(fig, "04_orm_per_call_latency.png", output_dir)


def chart_queue_depth(bdf: pd.DataFrame, output_dir: Path) -> None:
    if "queue_depth" not in bdf.columns:
        return
    fig, ax = plt.subplots(figsize=(12, 4))
    qd = bdf["queue_depth"].fillna(0)
    ax.fill_between(bdf["batch_index"], qd, alpha=0.3, color="#3498db")
    ax.plot(bdf["batch_index"], qd, color="#2980b9", linewidth=1.5)
    ax.set_xlabel("Batch index")
    ax.set_ylabel("Queue depth at batch start")
    ax.set_title("Request queue depth over batches")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    fig.tight_layout()
    _save(fig, "05_queue_depth.png", output_dir)


def chart_phase_pct_pie(bdf: pd.DataFrame, output_dir: Path) -> None:
    """Average fraction of total time per phase (n=50 only)."""
    b50 = bdf[bdf["n_services"] == 50]
    if b50.empty:
        return
    means = {PHASE_LABELS[c]: b50[c].fillna(0).mean() for c in PHASE_COLS}
    values = np.array(list(means.values()))
    labels = list(means.keys())
    non_zero = [(l, v) for l, v in zip(labels, values) if v > 0.001]
    if not non_zero:
        return
    labels_nz, values_nz = zip(*non_zero)

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(
        values_nz, labels=labels_nz, autopct="%1.1f%%",
        colors=PHASE_COLORS[:len(values_nz)], startangle=140
    )
    for t in autotexts:
        t.set_fontsize(8)
    ax.set_title("Average time breakdown (n_services=50 batches)")
    fig.tight_layout()
    _save(fig, "06_phase_pie.png", output_dir)


def chart_db_pass_vs_services(bdf: pd.DataFrame, output_dir: Path) -> None:
    """db_pass_s vs n_services scatter — reveals O(n) scaling."""
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(bdf["n_services"], bdf["db_pass_s"], alpha=0.7, color="#c0392b", s=50)
    ax.set_xlabel("n_services per batch")
    ax.set_ylabel("DB pass elapsed (s)")
    ax.set_title("DB pass time vs batch size (linear = one query per service)")
    # Fit a line
    mask = bdf["db_pass_s"].notna() & bdf["n_services"].notna()
    x = bdf.loc[mask, "n_services"].values
    y = bdf.loc[mask, "db_pass_s"].values
    if len(x) > 2:
        m, b = np.polyfit(x, y, 1)
        xf = np.linspace(x.min(), x.max(), 100)
        ax.plot(xf, m * xf + b, "--", color="gray", label=f"fit: {m*1000:.1f}ms per service")
        ax.legend(fontsize=9)
    fig.tight_layout()
    _save(fig, "07_db_pass_vs_services.png", output_dir)


def chart_throughput(bdf: pd.DataFrame, output_dir: Path) -> None:
    """Services per second over batches."""
    fig, ax = plt.subplots(figsize=(12, 4))
    tps = bdf["n_services"] / bdf["total_batch_time"].replace(0, np.nan)
    ax.bar(bdf["batch_index"], tps, color="#2ecc71", width=0.85)
    ax.set_xlabel("Batch index")
    ax.set_ylabel("Services / second")
    ax.set_title("Scheduler throughput (services per second)")
    ax.axhline(tps.mean(), linestyle="--", color="gray", label=f"mean {tps.mean():.1f} svc/s")
    ax.legend(fontsize=9)
    fig.tight_layout()
    _save(fig, "08_throughput.png", output_dir)


def chart_error_rate(bdf: pd.DataFrame, output_dir: Path) -> None:
    if "errors" not in bdf.columns or "n_services" not in bdf.columns:
        return
    err_rate = bdf["errors"].fillna(0) / bdf["n_services"].replace(0, np.nan) * 100
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.bar(bdf["batch_index"], err_rate, color="#e74c3c", width=0.85)
    ax.set_xlabel("Batch index")
    ax.set_ylabel("Error rate (%)")
    ax.set_title("Per-batch error rate")
    ax.set_ylim(0, 110)
    fig.tight_layout()
    _save(fig, "09_error_rate.png", output_dir)


def chart_delay_dict_breakdown(bdf: pd.DataFrame, output_dir: Path) -> None:
    """get_last_start_time vs calculate_current_delay vs remainder."""
    b50 = bdf[bdf["n_services"] == 50]
    if b50.empty or "get_last_start_time_s" not in b50.columns:
        return

    x = b50["batch_index"].values
    fig, ax = plt.subplots(figsize=(12, 4))
    gls = b50["get_last_start_time_s"].fillna(0).values
    ccd = b50["calculate_current_delay_s"].fillna(0).values if "calculate_current_delay_s" in b50.columns else np.zeros(len(x))
    total = b50["delay_dict_s"].fillna(0).values
    remainder = np.clip(total - gls - ccd, 0, None)

    ax.bar(x, gls, color="#f39c12", label="get_last_start_time ORM", width=0.85)
    ax.bar(x, ccd, bottom=gls, color="#e67e22", label="calculate_current_delay", width=0.85)
    ax.bar(x, remainder, bottom=gls + ccd, color="#95a5a6", label="other (prints / branching)", width=0.85)
    ax.set_xlabel("Batch index")
    ax.set_ylabel("Seconds")
    ax.set_title("build_delay_dict breakdown (n_services=50 batches)")
    ax.legend(fontsize=9)
    fig.tight_layout()
    _save(fig, "10_delay_dict_breakdown.png", output_dir)


def chart_ilp_solve_trend(bdf: pd.DataFrame, output_dir: Path) -> None:
    b50 = bdf[bdf["n_services"] == 50]
    if b50.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.plot(b50["batch_index"], b50["ilp_solve_s"] * 1000, "o-", color="#2ecc71", markersize=4)
    ax.set_xlabel("Batch index")
    ax.set_ylabel("ILP solve (ms)")
    ax.set_title("ILP solve time (n_services=50 batches)")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0fms"))
    fig.tight_layout()
    _save(fig, "11_ilp_solve_trend.png", output_dir)


def chart_process_assignments_breakdown(bdf: pd.DataFrame, output_dir: Path) -> None:
    b50 = bdf[bdf["n_services"] == 50]
    if b50.empty:
        return
    x = b50["batch_index"].values
    fig, ax = plt.subplots(figsize=(12, 4))
    jc = b50["job_create_s"].fillna(0).values
    mp = b50["mqtt_publish_s"].fillna(0).values
    ax.bar(x, jc, color="#3498db", label="job create (tx1)", width=0.85)
    ax.bar(x, mp, bottom=jc, color="#9b59b6", label="MQTT publish", width=0.85)
    ax.set_xlabel("Batch index")
    ax.set_ylabel("Seconds")
    ax.set_title("process_assignments breakdown (n_services=50 batches)")
    ax.legend(fontsize=9)
    fig.tight_layout()
    _save(fig, "12_process_assignments_breakdown.png", output_dir)


def print_top_bottlenecks(bdf: pd.DataFrame) -> None:
    divider("TOP BOTTLENECKS (mean seconds, n=50 batches)")
    b50 = bdf[bdf["n_services"] == 50]
    if b50.empty:
        return

    cols_interest = {
        "job_latest_run_query_s":     "Job.get_latest_run_time ORM loop",
        "pull_time_query_s":           "Job.get_latest_pull_time ORM loop",
        "get_last_start_time_s":       "provider.get_last_start_time ORM loop",
        "calculate_current_delay_s":   "provider.calculate_current_delay",
        "db_pass_non_orm_s":           "DB pass non-ORM overhead",
        "cache_probe_s":               "cache probe (is_service_cached)",
        "subdict_build_s":             "subdict build (pure Python)",
        "ilp_solve_s":                 "ILP solve (CBC)",
        "job_create_s":                "job create (DB write)",
        "mqtt_publish_s":              "MQTT publish",
        "other_s":                     "Other unaccounted",
    }

    rows = []
    for col, label in cols_interest.items():
        if col in b50.columns:
            mean_v = b50[col].dropna().mean()
            total_v = b50["total_batch_time"].dropna().mean()
            pct = mean_v / total_v * 100 if total_v > 0 else 0
            rows.append((mean_v, label, pct))

    rows.sort(reverse=True)
    print(f"\n  {'Mean(s)':>10}  {'% of batch':>10}  Phase")
    print(f"  {'-'*10}  {'-'*10}  {'-'*40}")
    for mean_v, label, pct in rows:
        print(f"  {mean_v:>10.3f}  {pct:>9.1f}%  {label}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def write_runs_txt(paths: list[str], out_dir: Path) -> None:
    """Write runs.txt listing every analysed run code + file path."""
    lines = ["Analysed runs\n", "=" * 60 + "\n"]
    for p in sorted(paths):
        code = _extract_run_code(p)
        abs_p = str(Path(p).resolve())
        lines.append(f"{code}  {abs_p}\n")
    (out_dir / "runs.txt").write_text("".join(lines), encoding="utf-8")
    print(f"  runs.txt:  {out_dir / 'runs.txt'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze scheduler profiling JSONL logs.")
    parser.add_argument(
        "logs", nargs="*",
        help="JSONL files or globs. Default: most recent scheduler_profile_run_*.jsonl",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Override output directory (default: auto-derived from run codes)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Merge ALL run files found in scheduler/logs/",
    )
    args = parser.parse_args()

    paths: list[str] = []

    if args.all:
        patterns = [RUN_GLOB]
    elif args.logs:
        patterns = args.logs
    else:
        patterns = []

    if patterns:
        for pat in patterns:
            expanded = sorted(glob.glob(pat))
            if expanded:
                paths.extend(expanded)
            elif os.path.exists(pat):
                paths.append(pat)
            else:
                print(f"Warning: no files matched '{pat}'", file=sys.stderr)
    else:
        # Default: most recent run file
        candidates = sorted(glob.glob(RUN_GLOB))
        if candidates:
            paths = [candidates[-1]]
            print(f"Auto-selected most recent run: {paths[0]}")
        else:
            # Fallback: any scheduler_profile*.jsonl
            candidates = sorted(glob.glob(str(LOGS_DIR / "scheduler_profile*.jsonl")))
            if candidates:
                paths = [candidates[-1]]
                print(f"Auto-selected: {paths[0]}")

    if not paths:
        print("No log files found. Run the scheduler first, or pass a file path.", file=sys.stderr)
        sys.exit(1)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique_paths: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)
    paths = unique_paths

    print(f"Loading {len(paths)} file(s):")
    for p in paths:
        print(f"  {p}  (run: {_extract_run_code(p)})")

    raw = load_jsonl(paths)
    print(f"Loaded {len(raw)} raw rows.")

    df = to_df(raw)
    bdf = build_batch_df(df)

    if bdf.empty:
        print("No completed batches found in logs.")
        sys.exit(0)

    print(f"Found {len(bdf)} completed batches.")

    # Determine output dir
    out_dir = Path(args.output_dir) if args.output_dir else _derive_output_dir(paths)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {out_dir}")

    # runs.txt
    write_runs_txt(paths, out_dir)

    # Print analysis
    print_batch_summary(bdf)
    print_error_summary(bdf)
    print_queue_growth(bdf)
    print_timing_tables(bdf)
    print_top_bottlenecks(bdf)

    # Save summary CSV
    csv_path = out_dir / "batch_summary.csv"
    csv_cols = [c for c in bdf.columns
                if bdf[c].dtype in (np.float64, np.int64, float, int)
                or c in ("correlation_id", "ts", "lb")]
    bdf[csv_cols].to_csv(csv_path, index=False)
    print(f"\n  Batch summary CSV: {csv_path}")

    # Charts
    divider("CHARTS")
    chart_phase_stacked_bar(bdf, out_dir)
    chart_total_batch_time_trend(bdf, out_dir)
    chart_orm_breakdown(bdf, out_dir)
    chart_per_call_latency(bdf, out_dir)
    chart_queue_depth(bdf, out_dir)
    chart_phase_pct_pie(bdf, out_dir)
    chart_db_pass_vs_services(bdf, out_dir)
    chart_throughput(bdf, out_dir)
    chart_error_rate(bdf, out_dir)
    chart_delay_dict_breakdown(bdf, out_dir)
    chart_ilp_solve_trend(bdf, out_dir)
    chart_process_assignments_breakdown(bdf, out_dir)

    divider()
    print("Done.")


if __name__ == "__main__":
    main()
