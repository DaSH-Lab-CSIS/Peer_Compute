In serverless scheduling research, particularly with ILP-based job assignment (which involves optimization over batches of jobs), the scale of requests (or invocations) in a single testbench must balance computational feasibility, statistical significance for graphs (e.g., latency distributions, throughput, makespan), and demonstration of scheduler behavior under varied loads. Based on established benchmarks in similar papers (e.g., coded computation in AWS Lambda, FunctionBench, and vHive evaluations), a substantial raw request count per testbench typically ranges from **1,000 to 10,000 invocations**. This allows for clear trends in plots like CDFs of tail latency, resource utilization, or ILP solve times, while running experiments in reasonable time (e.g., minutes to hours on cloud setups).

### Rationale for This Scale
- **Statistical Reliability**: Fewer than 1,000 requests often yields noisy graphs due to variance in cold starts, network jitter, or ILP solver variability (e.g., Gurobi or CBC for ILP). At 1,000+, you can average 5–10 runs per scenario for confidence intervals (95% CI < 5% of mean).
- **Graph Effectiveness**: Visuals shine with this volume—e.g., histograms of assignment decisions or throughput vs. RPS curves show smooth curves, not scatter. Larger scales (10k+) highlight ILP scalability limits (e.g., solve time exploding beyond 500 concurrent jobs).
- **Practicality for ILP**: ILP formulations grow NP-hard with job count; testbenches with 100–500 jobs per batch (aggregated to 1k–10k total) let you tune constraints (e.g., via LP relaxation) without timeouts.
- **Alignment with Your Scenarios**:
  - **Baseline**: 100–500 requests (isolated, low RPS ~1–5) to baseline norms like avg. latency.
  - **Steady Load**: 2,000–5,000 requests (constant RPS 10–50, ramped over 5–10 min) for sustained ILP efficiency.
  - **Bursty Load**: 1,000–5,000 requests (Poisson spikes to 100–500 RPS, λ tuned for 20–50% burst factor) to stress queueing/assignment.
  - **Stress/Soak**: 5,000–10,000+ requests (max RPS 100–200 until 5–10% failure rate) to plot failure thresholds.
  - **Chaos/Edge**: 500–2,000 requests with 10–20% fault injection (e.g., node failures mid-ILP solve) for resilience curves.

### Evidence from Comparable Papers
| Paper/Benchmark | Scheduler Type | Total Requests/Invocations per Testbench | Key Scales Shown |
|-----------------|----------------|-----------------------------------------|------------------|
| *Towards Ubiquitous Serverless Computing* (2021, AWS Lambda + coded comp.) | LP-relaxed optimization (ILP-adjacent for stragglers) | 1,000–10,000 (e.g., 400–3,600 workers × iterations for KRR/ALS) | Matrix jobs (32k–400k dims.); graphs of runtime savings (25–44%) vs. redundancy. |
| *Benchmarking Serverless Computing* (2020, AWS/Azure) | N/A (baseline FaaS perf.) | 500–50,000 (e.g., 100 users × 500 queries × 10 loops) | Query workloads; CDFs of response times with 5–100 concurrency. |
| *REAP: Snapshot Isolation for Serverless* (2023, vHive) | Snapshot-based scheduling | 100–1,000 (10 per function × 10–100 functions) | Cold-start latency; but scaled to 10k+ in multi-worker extensions for throughput. |
| FunctionBench/vHive Suites (2022–2024) | General FaaS benchmarking | 1,000–5,000 (e.g., 100 RPS × 10–50s bursts) | ML/inference jobs; histograms of tail latency under spikes. |

### Recommendations for Your Paper
- **Start with 5,000 as a Default**: It's "substantial" yet feasible—e.g., process in batches of 200–500 jobs per ILP solve (total runtime <1s/solve with good formulation).
- **Vary for Ablation**: Show sensitivity (e.g., 1k vs. 10k) in appendices to prove results hold.
- **Metrics for Graphs**: Plot ILP-specifics like solve time vs. #jobs queued, alongside system-level (e.g., 99th percentile latency). Use 3–5 runs per point for error bars.
- **Tools**: Emulate with AWS Step Functions or OpenFaaS for ILP integration; trace with Jaeger for assignment visualizations.

This scale ensures your experiments feel rigorous without overkill, common in USENIX OSDI/ATC or SoCC venues. If your ILP is over very large graphs (e.g., >1k vars), drop to 500–2,000 and emphasize per-batch analysis.