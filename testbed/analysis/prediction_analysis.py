import matplotlib
matplotlib.use('Agg')

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


AUDIT_STRATEGY_COLS = ['cpi_output', 'scaling_cold_output', 'scaling_ema_output']


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_enriched(paths):
    frames = [pd.read_csv(p, low_memory=False) for p in paths]
    return pd.concat(frames, ignore_index=True)


def load_audit(paths):
    records = []
    for p in paths:
        with open(p) as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    records.append(json.loads(stripped))
    return pd.DataFrame(records) if records else pd.DataFrame()


PREDICTION_COLS = [
    'predicted_runtime_ms', 'prediction_strategy', 'prediction_source',
    'abs_error_ms', 'abs_pct_error', 'signed_error_ms',
]


def ensure_prediction_cols(df):
    """Add missing prediction columns as NaN so downstream code is uniform."""
    for col in PREDICTION_COLS:
        if col not in df.columns:
            df[col] = float('nan')
    return df


def filter_predictable(df):
    df = ensure_prediction_cols(df)
    mask = (df['outcome'] == 'success') & df['predicted_runtime_ms'].notna()
    return df[mask].copy()


# ---------------------------------------------------------------------------
# Accuracy metrics
# ---------------------------------------------------------------------------

def compute_accuracy_from_cols(group):
    """Compute metrics from precomputed error columns in the enriched CSV."""
    ape = group['abs_pct_error'].dropna()
    abs_err = group['abs_error_ms'].dropna()
    signed_err = group['signed_error_ms'].dropna()
    n = len(group)
    return dict(
        mape=float(ape.mean()) if len(ape) else float('nan'),
        rmse=float(np.sqrt((abs_err ** 2).mean())) if len(abs_err) else float('nan'),
        median_ape=float(ape.median()) if len(ape) else float('nan'),
        signed_bias_ms=float(signed_err.mean()) if len(signed_err) else float('nan'),
        n_obs=n,
    )


def compute_accuracy_from_arrays(pred, actual):
    """Compute metrics from raw predicted and actual arrays (used for audit data)."""
    pred = np.asarray(pred, dtype=float)
    actual = np.asarray(actual, dtype=float)
    valid = (actual > 0) & np.isfinite(pred) & np.isfinite(actual)
    pred, actual = pred[valid], actual[valid]
    n = len(pred)
    if n == 0:
        return dict(mape=float('nan'), rmse=float('nan'), median_ape=float('nan'),
                    signed_bias_ms=float('nan'), n_obs=0)
    ape = np.abs(pred - actual) / actual * 100
    return dict(
        mape=float(ape.mean()),
        rmse=float(np.sqrt(((pred - actual) ** 2).mean())),
        median_ape=float(np.median(ape)),
        signed_bias_ms=float((pred - actual).mean()),
        n_obs=int(n),
    )


# ---------------------------------------------------------------------------
# Aggregation tables
# ---------------------------------------------------------------------------

def build_accuracy_summary_long(df):
    """One row per (prediction_strategy, prediction_source, metric)."""
    rows = []
    for (src, strat), g in df.groupby(
        ['prediction_source', 'prediction_strategy'], dropna=False
    ):
        m = compute_accuracy_from_cols(g)
        for metric, value in m.items():
            rows.append({
                'prediction_strategy': strat,
                'prediction_source': src,
                'metric': metric,
                'value': value,
            })
    return pd.DataFrame(rows)


def build_per_service_accuracy(df):
    """One row per (service_id, prediction_source, prediction_strategy) with MAPE/RMSE/n."""
    rows = []
    for (svc, src, strat), g in df.groupby(
        ['service_id', 'prediction_source', 'prediction_strategy'], dropna=False
    ):
        m = compute_accuracy_from_cols(g)
        rows.append({
            'service_id': svc,
            'prediction_source': src,
            'prediction_strategy': strat,
            'mape': m['mape'],
            'rmse': m['rmse'],
            'median_ape': m['median_ape'],
            'signed_bias_ms': m['signed_bias_ms'],
            'n_obs': m['n_obs'],
        })
    return pd.DataFrame(rows)


def build_coverage_matrix(df):
    ct = df.groupby(['service_id', 'provider_user_id']).size().reset_index(name='count')
    pivot = ct.pivot(index='service_id', columns='provider_user_id', values='count')
    return pivot.fillna(0).astype(int)


# ---------------------------------------------------------------------------
# Audit analysis
# ---------------------------------------------------------------------------

def analyze_audit(audit_df, enriched_df):
    actuals = (
        enriched_df[['job_id', 'run_time']]
        .drop_duplicates('job_id')
    )
    merged = audit_df.merge(actuals, on='job_id', how='inner')

    rows = []
    for col in AUDIT_STRATEGY_COLS:
        if col not in merged.columns:
            continue
        sub = merged[merged[col].notna() & merged['run_time'].notna()]
        if sub.empty:
            continue
        m = compute_accuracy_from_arrays(sub[col], sub['run_time'])
        m['strategy_col'] = col
        rows.append(m)

    audit_acc = pd.DataFrame(rows)

    inference_rows = []
    if 'inference_ms' in audit_df.columns and audit_df['inference_ms'].notna().any():
        inf = audit_df['inference_ms'].dropna()
        inference_rows.append({
            'mean_inference_ms': float(inf.mean()),
            'median_inference_ms': float(inf.median()),
            'p95_inference_ms': float(inf.quantile(0.95)),
            'n': int(len(inf)),
        })
    inference_df = pd.DataFrame(inference_rows)
    return audit_acc, inference_df


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

SOURCE_COLORS = {'history': '#2196F3', 'model': '#FF5722', 'fallback': '#9E9E9E'}


def scatter_plot(df, strategy, outdir):
    fig, ax = plt.subplots(figsize=(6, 6))
    fallback_cycle = list(plt.cm.tab10.colors)
    sources = sorted(df['prediction_source'].dropna().unique())

    for i, src in enumerate(sources):
        sub = df[df['prediction_source'] == src]
        color = SOURCE_COLORS.get(src, fallback_cycle[i % len(fallback_cycle)])
        ax.scatter(
            sub['run_time'],
            sub['predicted_runtime_ms'],
            alpha=0.35,
            s=12,
            color=color,
            label=src,
            rasterized=True,
        )

    pred_vals = df['predicted_runtime_ms'].dropna()
    actual_vals = df['run_time'].dropna()
    lo = min(actual_vals.min(), pred_vals.min())
    hi = max(actual_vals.max(), pred_vals.max())
    ax.plot([lo, hi], [lo, hi], 'k--', linewidth=1, label='ideal (y=x)')
    ax.set_xlabel('Actual run_time (ms)')
    ax.set_ylabel('Predicted runtime (ms)')
    ax.set_title(f'Predicted vs Actual — strategy: {strategy}')
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(outdir / f'accuracy_scatter_{strategy}.png', dpi=150)
    plt.close(fig)


def error_distribution_plot(df, outdir):
    df2 = df.copy()
    df2['group'] = (
        df2['prediction_strategy'].fillna('unknown')
        + ' / '
        + df2['prediction_source'].fillna('unknown')
    )
    groups = sorted(df2['group'].unique())
    pairs = [
        (df2[df2['group'] == g]['abs_pct_error'].dropna().values, g)
        for g in groups
    ]
    pairs = [(d, g) for d, g in pairs if len(d) > 0]
    if not pairs:
        return

    data, group_labels = zip(*pairs)
    fig, ax = plt.subplots(figsize=(max(6, 2 * len(group_labels)), 5))
    ax.violinplot(list(data), showmedians=True, showextrema=True)
    ax.set_xticks(range(1, len(group_labels) + 1))
    ax.set_xticklabels(list(group_labels), rotation=25, ha='right', fontsize=8)
    ax.set_ylabel('Absolute % Error')
    ax.set_title('Error Distribution by Strategy x Source')
    fig.tight_layout()
    fig.savefig(outdir / 'error_distribution.png', dpi=150)
    plt.close(fig)


def calibration_plot(df, outdir):
    quantile_points = np.linspace(0, 100, 21)
    preds = df['predicted_runtime_ms'].dropna().values
    actuals = df['run_time'].dropna().values

    fracs = []
    for q in quantile_points:
        thresh = np.percentile(preds, q)
        fracs.append(float((actuals <= thresh).mean()))

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot(quantile_points / 100, fracs, 'o-', markersize=4, label='observed')
    ax.plot([0, 1], [0, 1], 'k--', linewidth=1, label='perfect calibration')
    ax.set_xlabel('Predicted percentile')
    ax.set_ylabel('Fraction of actuals <= predicted')
    ax.set_title('Calibration Plot (Reliability Diagram)')
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(outdir / 'calibration_plot.png', dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# LaTeX output
# ---------------------------------------------------------------------------

def write_latex_table(summary_long_df, outpath):
    if summary_long_df.empty:
        outpath.write_text('')
        return

    wide = summary_long_df.pivot_table(
        index=['prediction_source', 'prediction_strategy'],
        columns='metric',
        values='value',
        aggfunc='first',
    ).reset_index()

    def fmt(row, col, decimals=1):
        v = row.get(col)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return '---'
        return f'{v:.{decimals}f}'

    lines = [
        r'\begin{table}[t]',
        r'\centering',
        r'\caption{Prediction Accuracy by Strategy and Source}',
        r'\label{tab:prediction-accuracy}',
        r'\begin{tabular}{llrrrr}',
        r'\toprule',
        r'Source & Strategy & MAPE (\%) & RMSE (ms) & Median APE (\%) & Bias (ms) \\',
        r'\midrule',
    ]
    for _, row in wide.iterrows():
        src = str(row.get('prediction_source', ''))
        strat = str(row.get('prediction_strategy', ''))
        mape = fmt(row, 'mape', 1)
        rmse = fmt(row, 'rmse', 0)
        med = fmt(row, 'median_ape', 1)
        bias = fmt(row, 'signed_bias_ms', 0)
        n_obs_raw = row.get('n_obs')
        n_obs = int(n_obs_raw) if n_obs_raw is not None and not (isinstance(n_obs_raw, float) and np.isnan(n_obs_raw)) else 0
        lines.append(
            f'{src} & {strat} & {mape} & {rmse} & {med} & {bias} \\\\'
            f'  % n={n_obs}'
        )
    lines += [
        r'\bottomrule',
        r'\end{tabular}',
        r'\end{table}',
    ]
    outpath.write_text('\n'.join(lines) + '\n')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def derive_run_id(first_path):
    stem = Path(first_path).stem
    return stem.replace('_jobs_enriched', '')


def main():
    parser = argparse.ArgumentParser(
        description='Offline prediction accuracy analysis for the scheduler paper.'
    )
    parser.add_argument(
        '--enriched', nargs='+', required=True, metavar='CSV',
        help='Enriched job CSV file(s) (*_jobs_enriched.csv).',
    )
    parser.add_argument(
        '--audit', nargs='*', default=[], metavar='JSONL',
        help='Prediction audit JSONL file(s) (prediction_audit_*.jsonl).',
    )
    parser.add_argument(
        '--output-dir', default='testbed/results/reports',
        help='Base output directory (default: testbed/results/reports).',
    )
    args = parser.parse_args()

    enriched_paths = [Path(p) for p in args.enriched]
    audit_paths = [Path(p) for p in args.audit]

    run_id = derive_run_id(args.enriched[0])
    outdir = Path(args.output_dir) / f'{run_id}_prediction'
    outdir.mkdir(parents=True, exist_ok=True)

    print(f'Loading {len(enriched_paths)} enriched CSV file(s)...')
    raw = load_enriched(enriched_paths)
    print(f'  {len(raw)} total rows')

    raw = ensure_prediction_cols(raw)
    df = filter_predictable(raw)
    print(f'  {len(df)} rows with outcome=success and non-null predicted_runtime_ms')

    if df.empty:
        print('WARNING: No predictable rows found — writing empty CSVs, skipping plots.')
        for fname in ('prediction_accuracy_summary.csv', 'per_service_accuracy.csv'):
            pd.DataFrame().to_csv(outdir / fname, index=False)
        pd.DataFrame().to_csv(outdir / 'coverage_matrix.csv')
        (outdir / 'summary_table.txt').write_text('')
        return

    # Coverage matrix across all success rows (predicted or not)
    success_all = raw[raw['outcome'] == 'success']
    cov = build_coverage_matrix(success_all)
    cov.to_csv(outdir / 'coverage_matrix.csv')
    print(f'coverage_matrix.csv: {cov.shape[0]} services x {cov.shape[1]} providers')

    summary_long = build_accuracy_summary_long(df)
    summary_long.to_csv(outdir / 'prediction_accuracy_summary.csv', index=False)
    print(f'prediction_accuracy_summary.csv: {len(summary_long)} rows')

    per_svc = build_per_service_accuracy(df)
    per_svc.to_csv(outdir / 'per_service_accuracy.csv', index=False)
    print(f'per_service_accuracy.csv: {len(per_svc)} rows')

    write_latex_table(summary_long, outdir / 'summary_table.txt')
    print('summary_table.txt written')

    strategies = df['prediction_strategy'].dropna().unique().tolist()
    if not strategies:
        df = df.copy()
        df['prediction_strategy'] = 'all'
        strategies = ['all']

    for strat in strategies:
        sub = df[df['prediction_strategy'] == strat]
        if sub.empty:
            continue
        scatter_plot(sub, strat, outdir)
        print(f'accuracy_scatter_{strat}.png written')

    if df['abs_pct_error'].notna().any():
        error_distribution_plot(df, outdir)
        print('error_distribution.png written')
    else:
        print('WARNING: abs_pct_error all null — skipping error_distribution.png')

    calibration_plot(df, outdir)
    print('calibration_plot.png written')

    if audit_paths:
        print(f'\nLoading {len(audit_paths)} audit JSONL file(s)...')
        audit_df = load_audit(audit_paths)
        if audit_df.empty:
            print('WARNING: No audit records loaded.')
        else:
            print(f'  {len(audit_df)} audit records')
            audit_acc, inference_df = analyze_audit(audit_df, raw)
            audit_acc.to_csv(outdir / 'audit_strategy_accuracy.csv', index=False)
            print(f'audit_strategy_accuracy.csv: {len(audit_acc)} rows')
            if not inference_df.empty:
                inference_df.to_csv(outdir / 'audit_inference_times.csv', index=False)
                print('audit_inference_times.csv written')

    print(f'\nAll outputs -> {outdir}')


if __name__ == '__main__':
    main()
