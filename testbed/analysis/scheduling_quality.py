#!/usr/bin/env python3
"""
scheduling_quality.py — Compare scheduling quality across policies.

For the ACM TOIT paper on a distributed serverless scheduler.

Usage
-----
python scheduling_quality.py \
    --runs rr:path/to/rr_enriched.csv ilp_cpi:path/to/ilp_cpi_enriched.csv \
    [--oracle oracle_assignments.json] \
    [--output-dir testbed/results/reports]
"""

import argparse
import json
import os
import sys
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_GAP_S = 1.0            # seconds gap between consecutive jobs to split batches
CACHE_HIT_THRESHOLD_MS = 200  # pull_time < 200 ms => proxy cache hit
BOOTSTRAP_N = 1000
RNG_SEED = 42
MIN_BATCHES_FOR_WILCOXON = 5
MIN_SUCCESS_FOR_BATCH = 2

POLICY_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args():
    p = argparse.ArgumentParser(
        description="Compare scheduling quality across policies (ACM TOIT paper).",
    )
    p.add_argument(
        "--runs",
        nargs="+",
        required=True,
        metavar="LABEL:PATH",
        help="One or more label:path pairs, e.g. rr:rr_enriched.csv ilp_cpi:ilp_cpi_enriched.csv",
    )
    p.add_argument(
        "--oracle",
        metavar="ORACLE_JSON",
        default=None,
        help="Path to oracle assignments JSON (from oracle_solver.py)",
    )
    p.add_argument(
        "--output-dir",
        default="testbed/results/reports",
        help="Base output directory; a scheduling_quality/ subdirectory will be created",
    )
    return p.parse_args()


def parse_runs(run_specs):
    """Parse label:path pairs from --runs arguments.  Returns OrderedDict."""
    runs = {}
    for spec in run_specs:
        if ":" not in spec:
            sys.exit(f"ERROR: --runs entry '{spec}' must be in label:path format")
        label, path = spec.split(":", 1)
        label = label.strip()
        path = path.strip()
        if label in runs:
            sys.exit(f"ERROR: duplicate policy label '{label}'")
        if not os.path.isfile(path):
            sys.exit(f"ERROR: file not found for policy '{label}': {path}")
        runs[label] = path
    return runs


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

REQUIRED_COLS = {
    "job_id", "service_id", "provider_user_id", "outcome",
    "run_time", "pull_time", "total_time",
    "assigned_to_provider_time", "finish_time", "start_time",
}

TIMESTAMP_COLS = ["assigned_to_provider_time", "finish_time", "start_time"]
MS_COLS = ["run_time", "pull_time", "total_time"]


def load_policy_df(label, path):
    """Load and validate an enriched CSV for one policy.

    Parses ISO-8601 timestamp columns to datetime[ns, UTC] and millisecond
    numeric columns to float.  Drops rows with null assigned_to_provider_time.
    """
    df = pd.read_csv(path, low_memory=False)

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        sys.exit(f"ERROR: CSV for '{label}' missing columns: {missing}")

    # Parse ISO-8601 timestamps; errors become NaT
    for col in TIMESTAMP_COLS:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    # Numeric ms columns
    for col in MS_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop rows with null assigned_to_provider_time (cannot batch or compute makespan)
    n_before = len(df)
    df = df.dropna(subset=["assigned_to_provider_time"]).reset_index(drop=True)
    n_dropped = n_before - len(df)
    if n_dropped:
        print(f"  [{label}] dropped {n_dropped} rows with null assigned_to_provider_time")

    df["policy"] = label
    return df


# ---------------------------------------------------------------------------
# Batch detection
# ---------------------------------------------------------------------------


def detect_batches(df):
    """Assign batch_idx by clustering on assigned_to_provider_time.

    Jobs are sorted by assigned_to_provider_time.  A new batch starts whenever
    the gap to the previous job exceeds BATCH_GAP_S seconds.

    Returns a copy of df with a 'batch_idx' integer column.
    """
    df = df.copy()
    df = df.sort_values("assigned_to_provider_time").reset_index(drop=True)

    atp = df["assigned_to_provider_time"]  # datetime64[ns, UTC]

    batch_ids = np.zeros(len(df), dtype=int)
    current = 0
    for i in range(1, len(df)):
        prev = atp.iloc[i - 1]
        curr = atp.iloc[i]
        if pd.isna(prev) or pd.isna(curr):
            current += 1
        else:
            gap_s = (curr - prev).total_seconds()
            if gap_s > BATCH_GAP_S:
                current += 1
        batch_ids[i] = current

    df["batch_idx"] = batch_ids
    return df


# ---------------------------------------------------------------------------
# Per-batch metrics
# ---------------------------------------------------------------------------


def compute_batch_metrics(df, policy):
    """Compute per-batch makespan, n_jobs, n_success.

    Only batches with n_success >= MIN_SUCCESS_FOR_BATCH are included.

    makespan_ms = (max(finish_time) - min(assigned_to_provider_time)).total_seconds() * 1000
    for success jobs in the batch.

    Returns DataFrame: policy, batch_idx, makespan_ms, n_jobs, n_success
    """
    rows = []
    for batch_idx, grp in df.groupby("batch_idx"):
        n_jobs = len(grp)
        success_grp = grp[grp["outcome"] == "success"].dropna(
            subset=["finish_time", "assigned_to_provider_time"]
        )
        n_success = len(success_grp)

        if n_success < MIN_SUCCESS_FOR_BATCH:
            continue

        ft_max = success_grp["finish_time"].max()
        atp_min = success_grp["assigned_to_provider_time"].min()

        if pd.isna(ft_max) or pd.isna(atp_min):
            continue

        makespan_ms = (ft_max - atp_min).total_seconds() * 1000.0

        rows.append(
            {
                "policy": policy,
                "batch_idx": int(batch_idx),
                "makespan_ms": makespan_ms,
                "n_jobs": n_jobs,
                "n_success": n_success,
            }
        )

    return pd.DataFrame(rows, columns=["policy", "batch_idx", "makespan_ms", "n_jobs", "n_success"])


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------


def bootstrap_ci(values, n=BOOTSTRAP_N, seed=RNG_SEED):
    """Return (lo, hi) 95% CI of the mean via bootstrap resampling."""
    rng = np.random.default_rng(seed)
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return (np.nan, np.nan)
    boot_means = np.fromiter(
        (rng.choice(values, size=len(values), replace=True).mean() for _ in range(n)),
        dtype=float,
        count=n,
    )
    return (float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5)))


# ---------------------------------------------------------------------------
# Per-policy aggregate metrics
# ---------------------------------------------------------------------------


def compute_policy_summary(policy, df_raw, batch_df):
    """Compute aggregate metrics for one policy.

    Parameters
    ----------
    policy   : str
    df_raw   : full DataFrame for this policy (after batch detection, all rows)
    batch_df : filtered batch metrics (n_success >= MIN_SUCCESS_FOR_BATCH)

    Returns a dict suitable for one row of policy_summary.csv.
    """
    makespans = batch_df["makespan_ms"].dropna().values

    if len(makespans) == 0:
        mean_ms = median_ms = p95_ms = ci_lo = ci_hi = np.nan
    else:
        mean_ms = float(np.mean(makespans))
        median_ms = float(np.median(makespans))
        p95_ms = float(np.percentile(makespans, 95))
        ci_lo, ci_hi = bootstrap_ci(makespans)

    # Throughput: total success jobs / total wall time in seconds
    # Wall time = max(finish_time) - min(assigned_to_provider_time) across all rows
    success_raw = df_raw[df_raw["outcome"] == "success"]
    total_success = len(success_raw)

    throughput = np.nan
    if total_success > 0:
        ft_all = df_raw["finish_time"].dropna()
        atp_all = df_raw["assigned_to_provider_time"].dropna()
        if len(ft_all) > 0 and len(atp_all) > 0:
            wall_s = (ft_all.max() - atp_all.min()).total_seconds()
            throughput = total_success / wall_s if wall_s > 0 else np.nan

    # Cache hit rate (proxy): pull_time < CACHE_HIT_THRESHOLD_MS
    pull = df_raw["pull_time"].dropna()
    cache_hit_rate = float((pull < CACHE_HIT_THRESHOLD_MS).mean()) if len(pull) > 0 else np.nan

    # Error rate = 1 - (success / total)
    total_jobs = len(df_raw)
    error_rate = 1.0 - (total_success / total_jobs) if total_jobs > 0 else np.nan

    return {
        "policy": policy,
        "mean_makespan": mean_ms,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "median_makespan": median_ms,
        "p95_makespan": p95_ms,
        "throughput": throughput,
        "cache_hit_rate": cache_hit_rate,
        "error_rate": error_rate,
    }


# ---------------------------------------------------------------------------
# Wilcoxon signed-rank tests
# ---------------------------------------------------------------------------


def compute_wilcoxon_tests(batch_dfs):
    """Paired Wilcoxon signed-rank test on batch makespan for each policy pair.

    Batches are aligned by position (batch_idx order within each policy).
    Requires at least MIN_BATCHES_FOR_WILCOXON matched pairs.

    Returns DataFrame: policy_a, policy_b, n_matched, W, p_value, effect_r, significant
    """
    policies = list(batch_dfs.keys())
    results = []

    for i in range(len(policies)):
        for j in range(i + 1, len(policies)):
            pa, pb = policies[i], policies[j]
            ms_a = batch_dfs[pa]["makespan_ms"].values
            ms_b = batch_dfs[pb]["makespan_ms"].values

            n_matched = min(len(ms_a), len(ms_b))
            if n_matched < MIN_BATCHES_FOR_WILCOXON:
                print(
                    f"  Skipping Wilcoxon [{pa}] vs [{pb}]: "
                    f"{n_matched} matched batches < {MIN_BATCHES_FOR_WILCOXON} required"
                )
                continue

            a = ms_a[:n_matched].astype(float)
            b = ms_b[:n_matched].astype(float)

            # Remove tied pairs (Wilcoxon requires non-zero differences)
            nonzero = a != b
            a_nz, b_nz = a[nonzero], b[nonzero]

            if len(a_nz) < 3:
                print(f"  Skipping Wilcoxon [{pa}] vs [{pb}]: too few non-tied pairs ({len(a_nz)})")
                continue

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                stat, pval = wilcoxon(a_nz, b_nz)

            # Rank-biserial correlation as effect size
            # r = 1 - (2 * W) / (n * (n + 1) / 2)
            n = len(a_nz)
            r = 1.0 - (2.0 * float(stat)) / (n * (n + 1) / 2.0)

            results.append(
                {
                    "policy_a": pa,
                    "policy_b": pb,
                    "n_matched": n_matched,
                    "W": float(stat),
                    "p_value": float(pval),
                    "effect_r": round(r, 4),
                    "significant": bool(pval < 0.05),
                }
            )

    return pd.DataFrame(
        results,
        columns=["policy_a", "policy_b", "n_matched", "W", "p_value", "effect_r", "significant"],
    )


# ---------------------------------------------------------------------------
# Oracle gap
# ---------------------------------------------------------------------------


def parse_oracle_json(oracle_path):
    """Load oracle JSON and return a dict {batch_idx: oracle_makespan_ms}.

    Supports two formats:
      Format A: {"0": {"makespan_ms": 1234.5}, "1": {...}, ...}
      Format B: [{"batch_idx": 0, "makespan_ms": 1234.5}, ...]
      Format C: {"0": 1234.5, "1": ...}  (direct float values)
    """
    with open(oracle_path) as f:
        data = json.load(f)

    oracle = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                bidx = int(k)
            except (ValueError, TypeError):
                continue
            if isinstance(v, dict):
                ms = v.get("makespan_ms")
            else:
                try:
                    ms = float(v)
                except (TypeError, ValueError):
                    ms = None
            if ms is not None:
                oracle[bidx] = float(ms)
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            bidx = item.get("batch_idx")
            ms = item.get("makespan_ms")
            if bidx is not None and ms is not None:
                oracle[int(bidx)] = float(ms)

    return oracle


def compute_oracle_gap(oracle_path, batch_dfs):
    """Compute per-batch oracle_gap_pct for each policy.

    oracle_gap_pct = (policy_makespan - oracle_makespan) / oracle_makespan * 100

    Returns a DataFrame: policy, batch_idx, makespan_ms, oracle_makespan_ms, oracle_gap_pct
    or None if oracle data cannot be parsed / no overlapping batches are found.
    """
    oracle = parse_oracle_json(oracle_path)
    if not oracle:
        print("  WARNING: oracle JSON parsed to empty dict; skipping oracle gap")
        return None

    rows = []
    for policy, bdf in batch_dfs.items():
        for _, row in bdf.iterrows():
            bidx = int(row["batch_idx"])
            if bidx not in oracle:
                continue
            oracle_ms = oracle[bidx]
            if oracle_ms <= 0:
                continue
            gap_pct = (row["makespan_ms"] - oracle_ms) / oracle_ms * 100.0
            rows.append(
                {
                    "policy": policy,
                    "batch_idx": bidx,
                    "makespan_ms": row["makespan_ms"],
                    "oracle_makespan_ms": oracle_ms,
                    "oracle_gap_pct": gap_pct,
                }
            )

    if not rows:
        print("  WARNING: no overlapping batches between oracle and policies")
        return None

    return pd.DataFrame(
        rows,
        columns=["policy", "batch_idx", "makespan_ms", "oracle_makespan_ms", "oracle_gap_pct"],
    )


# ---------------------------------------------------------------------------
# Colour helper
# ---------------------------------------------------------------------------


def color_map(policies):
    return {p: POLICY_COLORS[i % len(POLICY_COLORS)] for i, p in enumerate(policies)}


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------


def plot_makespan_cdf(batch_dfs, out_path):
    """CDF of batch makespan per policy (one line per policy)."""
    cmap = color_map(list(batch_dfs.keys()))
    fig, ax = plt.subplots(figsize=(8, 5))

    for policy, bdf in batch_dfs.items():
        vals = np.sort(bdf["makespan_ms"].dropna().values)
        if len(vals) == 0:
            continue
        cdf = np.arange(1, len(vals) + 1) / len(vals)
        ax.step(vals, cdf, label=policy, color=cmap[policy], linewidth=2, where="post")

    ax.set_xlabel("Batch Makespan (ms)", fontsize=12)
    ax.set_ylabel("Cumulative Fraction", fontsize=12)
    ax.set_title("CDF of Batch Makespan by Policy", fontsize=13)
    ax.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path}")


def plot_makespan_bars(summary_df, out_path):
    """Bar chart: mean makespan per policy with 95% bootstrap CI error bars."""
    df = summary_df.dropna(subset=["mean_makespan"]).reset_index(drop=True)
    if df.empty:
        print("  WARNING: no data for makespan bar chart; skipping")
        return

    cmap = color_map(df["policy"].tolist())
    fig, ax = plt.subplots(figsize=(max(6, len(df) * 1.6), 5))

    x = np.arange(len(df))
    means = df["mean_makespan"].values
    # Clamp error bars so they cannot go negative on the plot
    yerr_lo = np.maximum(means - df["ci_lo"].values, 0.0)
    yerr_hi = np.maximum(df["ci_hi"].values - means, 0.0)

    ax.bar(
        x,
        means,
        color=[cmap[p] for p in df["policy"]],
        width=0.6,
        yerr=[yerr_lo, yerr_hi],
        capsize=5,
        error_kw={"elinewidth": 1.5, "ecolor": "black"},
    )

    ax.set_xticks(x)
    ax.set_xticklabels(df["policy"].tolist(), fontsize=11)
    ax.set_ylabel("Mean Batch Makespan (ms)", fontsize=12)
    ax.set_title("Mean Batch Makespan per Policy with 95% Bootstrap CI", fontsize=13)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path}")


def plot_oracle_gap(gap_df, out_path):
    """Bar chart of mean oracle_gap_pct per policy, sorted ascending."""
    mean_gap = (
        gap_df.groupby("policy")["oracle_gap_pct"]
        .mean()
        .reset_index()
        .sort_values("oracle_gap_pct")
        .reset_index(drop=True)
    )

    cmap = color_map(mean_gap["policy"].tolist())
    fig, ax = plt.subplots(figsize=(max(6, len(mean_gap) * 1.6), 5))

    x = np.arange(len(mean_gap))
    ax.bar(
        x,
        mean_gap["oracle_gap_pct"].values,
        color=[cmap[p] for p in mean_gap["policy"]],
        width=0.6,
    )
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels(mean_gap["policy"].tolist(), fontsize=11)
    ax.set_ylabel("Mean Oracle Gap (%)", fontsize=12)
    ax.set_title("Mean Oracle Optimality Gap per Policy", fontsize=13)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ---------------------------------------------------------------------------
# LaTeX table
# ---------------------------------------------------------------------------


def make_latex_table(summary_df, out_path):
    """Emit a LaTeX booktabs table of policy_summary for paper inclusion."""

    def fmt(v, decimals=1):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "--"
        return f"{v:.{decimals}f}"

    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Scheduling Quality Comparison Across Policies}",
        r"\label{tab:scheduling_quality}",
        r"\begin{tabular}{lrrrrrrr}",
        r"\toprule",
        (
            r"Policy & Mean MS & 95\% CI & Median MS & P95 MS"
            r" & Throughput & Cache Hit$^\dagger$ & Error Rate \\"
        ),
        r"& (ms) & (ms) & (ms) & (ms) & (jobs/s) & (proxy) & \\ \midrule",
    ]

    for _, row in summary_df.iterrows():
        ci = f"[{fmt(row['ci_lo'])},\\ {fmt(row['ci_hi'])}]"
        lines.append(
            f"{row['policy']} & "
            f"{fmt(row['mean_makespan'])} & "
            f"{ci} & "
            f"{fmt(row['median_makespan'])} & "
            f"{fmt(row['p95_makespan'])} & "
            f"{fmt(row['throughput'], 2)} & "
            f"{fmt(row['cache_hit_rate'], 3)} & "
            f"{fmt(row['error_rate'], 3)} \\\\"
        )

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"{\footnotesize $^\dagger$ Cache hit is a proxy: \texttt{pull\_time} $<$ 200\,ms.}",
        r"\end{table}",
    ]

    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  Saved: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = parse_args()

    out_dir = os.path.join(args.output_dir, "scheduling_quality")
    os.makedirs(out_dir, exist_ok=True)
    print(f"Output directory: {out_dir}")

    # ------------------------------------------------------------------
    # 1. Parse and load policy CSVs
    # ------------------------------------------------------------------
    runs = parse_runs(args.runs)
    policies = list(runs.keys())
    print(f"\nPolicies: {policies}")

    print("\n=== Loading data ===")
    policy_dfs_raw = {}
    for label, path in runs.items():
        print(f"  Loading [{label}] from {path} ...")
        df = load_policy_df(label, path)
        print(f"    {len(df)} rows  |  outcomes: {df['outcome'].value_counts().to_dict()}")
        policy_dfs_raw[label] = df

    # ------------------------------------------------------------------
    # 2. Batch detection + per-batch metrics
    # ------------------------------------------------------------------
    print("\n=== Detecting batches and computing per-batch metrics ===")
    policy_dfs = {}         # with batch_idx column
    batch_metric_dfs = {}   # filtered per-batch metrics

    for policy, df in policy_dfs_raw.items():
        df_b = detect_batches(df)
        policy_dfs[policy] = df_b
        bdf = compute_batch_metrics(df_b, policy)
        batch_metric_dfs[policy] = bdf
        n_batches_total = df_b["batch_idx"].nunique()
        print(
            f"  [{policy}] {n_batches_total} batches detected  |  "
            f"{len(bdf)} with n_success >= {MIN_SUCCESS_FOR_BATCH}"
        )

    # Save batch_makespans.csv
    all_batches = pd.concat(batch_metric_dfs.values(), ignore_index=True)
    batch_path = os.path.join(out_dir, "batch_makespans.csv")
    all_batches.to_csv(batch_path, index=False)
    print(f"\n  Saved: {batch_path}")

    # ------------------------------------------------------------------
    # 3. Per-policy summary
    # ------------------------------------------------------------------
    print("\n=== Computing per-policy aggregates ===")
    summary_rows = []
    for policy in policies:
        row = compute_policy_summary(policy, policy_dfs[policy], batch_metric_dfs[policy])
        summary_rows.append(row)
        n = len(batch_metric_dfs[policy])
        print(
            f"  [{policy}]  batches={n}  "
            f"mean={row['mean_makespan']:.1f} ms  "
            f"CI=[{row['ci_lo']:.1f}, {row['ci_hi']:.1f}]  "
            f"throughput={row['throughput']:.2f} jobs/s  "
            f"cache_hit={row['cache_hit_rate']:.3f}  "
            f"error_rate={row['error_rate']:.3f}"
        )

    summary_df = pd.DataFrame(summary_rows)
    summary_path = os.path.join(out_dir, "policy_summary.csv")
    summary_df.to_csv(summary_path, index=False)
    print(f"  Saved: {summary_path}")

    # ------------------------------------------------------------------
    # 4. Wilcoxon tests
    # ------------------------------------------------------------------
    print("\n=== Statistical tests (Wilcoxon signed-rank) ===")
    wilcoxon_path = os.path.join(out_dir, "wilcoxon_tests.csv")
    _empty_wilcoxon = pd.DataFrame(
        columns=["policy_a", "policy_b", "n_matched", "W", "p_value", "effect_r", "significant"]
    )

    if len(policies) < 2:
        print("  Only one policy — Wilcoxon tests skipped")
        _empty_wilcoxon.to_csv(wilcoxon_path, index=False)
    else:
        wilcoxon_df = compute_wilcoxon_tests(batch_metric_dfs)
        if wilcoxon_df.empty:
            print("  No tests produced (insufficient matched batches for all pairs)")
            _empty_wilcoxon.to_csv(wilcoxon_path, index=False)
        else:
            wilcoxon_df.to_csv(wilcoxon_path, index=False)
            print(f"  Saved: {wilcoxon_path}")
            for _, r in wilcoxon_df.iterrows():
                sig = "SIGNIFICANT" if r["significant"] else "not significant"
                print(
                    f"  [{r['policy_a']}] vs [{r['policy_b']}]  "
                    f"W={r['W']:.1f}  p={r['p_value']:.4f}  "
                    f"r={r['effect_r']:.3f}  [{sig}]"
                )

    # ------------------------------------------------------------------
    # 5. Oracle gap
    # ------------------------------------------------------------------
    if args.oracle:
        print("\n=== Oracle gap analysis ===")
        gap_df = compute_oracle_gap(args.oracle, batch_metric_dfs)
        if gap_df is not None:
            for policy in policies:
                pol_gap = gap_df[gap_df["policy"] == policy]["oracle_gap_pct"]
                if len(pol_gap) > 0:
                    print(f"  [{policy}] mean oracle gap: {pol_gap.mean():.1f}%  (n={len(pol_gap)} batches)")
            oracle_gap_path = os.path.join(out_dir, "oracle_gap.png")
            plot_oracle_gap(gap_df, oracle_gap_path)
        else:
            print("  Oracle gap chart skipped (no data)")

    # ------------------------------------------------------------------
    # 6. Plots
    # ------------------------------------------------------------------
    print("\n=== Generating plots ===")
    plot_makespan_cdf(batch_metric_dfs, os.path.join(out_dir, "makespan_cdf.png"))
    plot_makespan_bars(summary_df, os.path.join(out_dir, "makespan_bars.png"))

    # ------------------------------------------------------------------
    # 7. LaTeX table
    # ------------------------------------------------------------------
    print("\n=== Generating LaTeX table ===")
    make_latex_table(summary_df, os.path.join(out_dir, "summary_table.txt"))

    print("\nDone.")


if __name__ == "__main__":
    main()
