What Those 3 Commits Did
Background: The prediction system before these commits
The scheduler's build_cost_matrix() — the function that feeds the ILP optimizer — needs a predicted runtime for every (provider, service) pair. Before commit 10c4f85 (Apr 17, the parent that made room), prediction lived on the provider side (the trainAndPredict/linear regression in provider1.py). That approach required MQTT round-trips to providers during every ILP run, which was slow and asynchronous.

f494f1d — "predict() - Scaling Factor Strategy + EMA fuse." (Apr 17)
What it added: A brand-new, scheduler-side prediction strategy called ScalingFactorStrategy in scheduler/providers/prediction/scaling_strategy.py.

The math it implements:


sigma(f, m)  = sum_i  w_i(f) * r_i(m)        # weighted hardware ratio
t_cold(f,m)  = t_ref(f) * sigma(f, m)         # cold-start estimate
t_hat(f, m)  = blend(EMA, t_cold, n, kappa)   # Bayesian blend with observed history
t_pull       = image_size / throughput          # piecewise pull time by cache state
predicted_ms = t_hat + t_pull
Key design choices:

r_i(m) are hardware ratios relative to a Benchmarking Environment Machine (BEM) — stored in the User model (r_cpu, r_mem, etc.)
w_i(f) are per-service resource sensitivity weights — stored in the Services model
EMA blending: once a provider has actually run a service n times, observed history gradually takes over from the cold-start formula (controlled by KAPPA=5, so after 5 observations the EMA dominates)
Pull time: accounts for whether the Docker image is already cached in memory, on disk, or needs a cold network pull
It was registered under the key "scaling" in scheduler/providers/prediction/registry.py
Database migrations added:

Services: cpu_cycles_required, memory_footprint, memory_bytes_per_second, reference_stats
User (provider): cpi, memory_bandwidth, clock_hz
c6f4667 — "machine benchmarking plus image benchmarking" (Apr 30)
What it added: A standalone benchmarking harness in scripts/benchmarks/ to populate the inputs that ScalingFactorStrategy needs.

Two subcommands in scripts/benchmarks/benchmark.py:

benchmark.py provider — runs synthetic CPU/mem/disk/net probes in Docker containers on a provider machine, producing machine_bench.json with the r_cpu, r_mem, r_disk, r_net, s_disk_mbps, s_net_mbps values
benchmark.py service — runs each benchmark Docker image repeatedly on the BEM, measures t_ref(f) (median runtime) and derives w_cpu, w_mem, w_disk, w_net by ablating individual resource dimensions
This is a prerequisite step — without running this script and loading results into the DB, ScalingFactorStrategy falls back to None predictions and the scheduler substitutes DEFAULT_RUNTIME (a constant fallback).

564bae4 — "scaling strate" (May 6)
What it changed: A single line in scheduler/providers/prediction/scaling_strategy.py:151:


# Before:
total = t_hat + t_pull

# After:
total = t_hat  #+ t_pull
Pull time was commented out. This means the prediction now ignores Docker image pull time entirely and only predicts execution runtime. Likely done because pull time was either not measurable without the benchmarking data populated, or was causing over-estimates in practice.

Effect on Your Experiments (experiment.yml + testbed)
The key setting controlling which strategy is active is in scheduler/scheduler/settings.py:66:


RUNTIME_PREDICTION_STRATEGY = os.environ.get("RUNTIME_PREDICTION_STRATEGY", "cpi")
Default is still "cpi" (the old CPI-based strategy). To use the new ScalingFactorStrategy, you'd need to set RUNTIME_PREDICTION_STRATEGY=scaling in the scheduler's .env before running experiment.yml.

If you switch to "scaling" without running the benchmarking scripts first:

r_cpu, r_mem, etc. fields on User rows will be NULL → ScalingFactorStrategy treats missing ratios as 1.0 (BEM parity)
ref_runtime_ms on ServicePredInput will be None → returns None → scheduler substitutes DEFAULT_RUNTIME for all services
Net effect: ILP gets a constant cost matrix, assignment is essentially arbitrary relative to runtime
If you run the benchmarking scripts and load results + switch to "scaling":

ILP gets per-(provider, service) predictions that account for actual hardware differences between your Raspberry Pi nodes
After jobs complete, the EMA slowly calibrates — but the EMA update path (OnJobComplete) appears not yet wired in (the strategy computes from pre-loaded EMA state in ServicePredInput.ema_runtime_ms, but there's no code yet that persists updated EMA values back to the DB after each job)
Summary of experiment impact: These commits are currently inert in your experiments unless you explicitly set RUNTIME_PREDICTION_STRATEGY=scaling in .env. The benchmarking scripts (scripts/benchmarks/) need to be run manually per-machine before the strategy produces meaningful numbers. The experiment.yml playbook has no tasks that invoke the benchmarking harness — that's a gap if you want the scaling strategy to be useful end-to-end.

---

## Experiment Paths — 2026-08-04

### Why CPI and ScalingFactor predictions are currently broken

Diagnosis confirmed Aug 4: all CPI fields (`cpi`, `clock_hz`, `memory_bandwidth` on User; `cpu_cycles_required`, `memory_footprint` on Services) are NULL in the DB. No benchmark data has ever been collected or ingested. As a result:

- `CPIStrategy.predict()` returns `None` for every (provider, service) pair.
- `ScalingFactorStrategy.predict()` also returns `None` (same root cause for `ref_runtime_ms`, `r_cpu`, etc.).
- `build_cost_matrix` falls back to `DEFAULT_RUNTIME = 1000 ms` for every pair, then the cache pass adds actual `pull_time` from DB history, so `predicted_runtime_ms` ends up as `1000 + pull_time_ms` — not a real prediction.
- `prediction_source` is correctly labelled `fallback` for all jobs.

The `PREDICTION_FORCE_MODEL=true` flag works correctly (bypasses the DB history fast-path), but there is nothing meaningful behind it until benchmark data is ingested.

**What does work:**

- `ILP + history` (`force_model=false`): the DB fast-path returns the last actual `run_time` for every warm (provider, service) pair. All 22 cortalim providers have run all services in prior experiments, so the history is dense. ILP gets real, differentiated cost values.
- `RR` baseline: no prediction required.

---

### Path A — Proceed now with RR + ILP+history (chosen)

Run 5 repetitions of each config. These are the two valid scheduling policies available without benchmark data.

**RR baseline** (5 reps, rep 1 already done as `steady_load_20260804_155454`):

```bash
cd ansible_utils
./run_playbook.sh playbooks/experiment_prediction.yml \
  -e "placement_mode=rr prediction_strategy=cpi force_model=false scenario=steady_load seed=42 run_label=rr rep=<N>" \
  --ask-vault-pass
```

**ILP + history** (5 reps):

```bash
cd ansible_utils
./run_playbook.sh playbooks/experiment_prediction.yml \
  -e "placement_mode=ilp prediction_strategy=cpi force_model=false scenario=steady_load seed=42 run_label=ilp_history rep=<N>" \
  --ask-vault-pass
```

`prediction_strategy=cpi` is passed but is irrelevant for warm pairs — the DB fast-path fires for all of them when `force_model=false`. What the ILP actually optimises on is the real historical runtime.

Paper framing: ILP+history is the "warm-start" regime of the hybrid predictor (§3.3 of the design). It represents the scheduler's steady-state behaviour after the fleet has been exercised.

---

### Path B — Full matrix with CPI and ScalingFactor (deferred to Phase 2)

Requires three manual phases before any model-based experiment can run:

#### Step 1: Machine benchmarks (run on each provider node)

On each cortalim / palolem — SSH in and run:

```bash
# Requires Docker
sudo python /home/peercompute/deploy/Serverless_Scheduler/scripts/benchmarks/benchmark.py provider \
  --provider-id $(cat /home/cortalimN/provider_user_id.txt) \
  --out /tmp/machine_bench_$(hostname).json
```

Copy all `machine_bench_<hostname>.json` files back to a `benchmark_results/` directory on utorda1.

#### Step 2: Service (function) benchmarks (run on BEM — typically utorda1 or a cortalim with Docker)

```bash
sudo python scripts/benchmarks/benchmark.py service \
  --provider-id <bem-uuid> \
  --out benchmark_results/function_bench.json
```

This runs each Docker benchmark image B=5 times and with throttled dimensions, producing `w_cpu`, `w_mem`, `w_disk`, `w_net`, `ref_runtime_ms`, `image_size_mb` per service.

#### Step 3: Ingest into DB

```bash
cd scheduler
python manage.py ingest_benchmarks \
  --machine-dir ../benchmark_results/ \
  --bem-provider-id <bem-uuid> \
  --function-file ../benchmark_results/function_bench.json
```

Note: `ingest_benchmarks` populates ScalingFactor fields (`r_cpu`, `r_mem`, `ref_runtime_ms`, `w_*`, `s_disk_mbps`, `s_net_mbps`). The CPI fields (`cpi`, `clock_hz`, `memory_bandwidth`) need a separate characterization step — read `clock_hz` from `/proc/cpuinfo` and measure CPI / memory bandwidth via `perf stat` or a dedicated microbenchmark.

#### Step 4: Run model-based experiments

Once DB fields are populated, experiments become valid:

```bash
# ILP + CPI
./run_playbook.sh playbooks/experiment_prediction.yml \
  -e "placement_mode=ilp prediction_strategy=cpi force_model=true scenario=steady_load seed=42 run_label=ilp_cpi rep=<N>" \
  --ask-vault-pass

# ILP + ScalingFactor
./run_playbook.sh playbooks/experiment_prediction.yml \
  -e "placement_mode=ilp prediction_strategy=scaling force_model=true scenario=steady_load seed=42 run_label=ilp_scaling rep=<N>" \
  --ask-vault-pass
```

`force_model=true` is required to bypass the DB history fast-path so that CPI/Scaling actually fires. Without it, the warm history overrides the model for every pair.

#### Gap: CPI field population

The `ingest_benchmarks` management command does NOT populate `User.cpi`, `User.clock_hz`, or `User.memory_bandwidth` — those are not output by `benchmark.py provider` (which outputs ScalingFactor ratios). To populate CPI fields:

1. Read `clock_hz` from `/proc/cpuinfo` (`cpu MHz` field × 1e6) per provider.
2. Run `perf stat -e cycles,instructions <workload>` to measure CPI per hardware class, or use a synthetic loop.
3. Measure memory bandwidth with `sysbench memory` or the existing `s_mem_mbps` output from the benchmark script (convert MB/s → B/s and store in `memory_bandwidth`).
4. Populate `Services.cpu_cycles_required` and `Services.memory_footprint` from the function benchmark runs (requires matching CPU cycle counters to Docker container execution).

Until these are done, CPI predictions degrade to fallback regardless of `force_model` setting.
