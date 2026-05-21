# ACM TOIT-Level Serverless Scheduler Testbed Design

Let me analyze your setup and design a rigorous experimental methodology.This is a rich and well-structured system. Let me design the full experimental framework, then visualize the methodology.Here is the complete ACM TOIT-grade testbed design, broken into every dimension that matters.

---

## Research questions to anchor everything

A TOIT paper needs explicit RQs that your testbed directly answers. Based on your system:

**RQ1 (Optimality):** Does ILP batch scheduling produce statistically lower p99 latency than greedy/FIFO baselines under equivalent load?

**RQ2 (Scalability):** How does ILP solve time scale with batch window size (50→500 jobs), and at what point does solve overhead dominate over scheduling quality gains?

**RQ3 (Resilience):** Under fault injection and thundering-herd bursts, does the ILP scheduler recover faster (lower MTTR) than non-optimizing alternatives?

**RQ4 (Fairness):** Across heterogeneous service mixes (light/medium/heavy), does ILP scheduling produce more equitable per-service latency distributions than simpler policies?

---

## Scenario design — what to run, how long, and why

**Baseline (RQ1 anchor):** 500 requests, low concurrency (≤5), 1–5s uniform intervals. Run 5 iterations per scheduler variant with identical seeds. This establishes your null distribution — every anomaly in other scenarios is measured as a delta from this. Duration: ~20–40 minutes per variant.

**Steady load (RQ1, RQ2 core):** Ramp from 1 RPS to 50 RPS in discrete steps (1, 5, 10, 25, 50), holding each level for 3 minutes. Total ~5,000 requests, 15–20 minutes per run. This is where you plot the ILP solve time curve against RPS and find the knee — the batch window where scheduling quality peaks before overhead wins. This is your most important figure for TOIT.

**Bursty load (RQ3):** 10 bursts of 400–500 requests each in a 10-second window, Poisson inter-burst intervals of 60–120s. Total ~5,000 requests. Measures thundering herd response — the key question is whether ILP batching absorbs spikes or amplifies them by delaying dispatch during long solve times.

**Stress/soak (RQ2, RQ3):** 100+ RPS sustained until 10% error rate OR 2 hours, whichever comes first, with a minimum floor of 5,000 requests. This is your memory leak and node exhaustion scenario. You want at least 3 runs to check variance — soak tests are notoriously noisy. Budget 6–10 hours of wall-clock experiment time for this scenario alone across iterations.

**Chaos/edge (RQ3, RQ4):** 2,000 requests with 15% fault injection — invalid service IDs, malformed payloads, negative invocation counts. Random delays 0.1–10s. Run 5 iterations. This validates error handling and tests whether ILP gracefully degrades or catastrophically fails when input assumptions break.

---

## The critical experimental control: seeded replay

This is what separates a TOIT paper from a workshop paper. Every scheduler variant must see **exactly the same request sequence**. Generate your seeds once, save the request traces, then replay identically across FIFO, round-robin, greedy, and ILP variants. Without this, any latency difference could be a workload artifact rather than a scheduler effect. Your system already supports this — use it rigorously.

---

## Statistical requirements TOIT reviewers will check

Run **5 iterations minimum** per (scenario × variant) cell, discarding the first as warm-up. This gives you 4 clean data points — enough for non-parametric tests. Use **Mann–Whitney U** (not t-test — latency is never normally distributed) for pairwise comparisons. Report **95% confidence intervals** on all p50/p95/p99 figures. Include **Cohen's d** effect size — reviewers will reject papers that claim "X is better" without quantifying by how much. Use **coefficient of variation** (CV) for any stability claim — your analyzer already flags CV > 20% as throughput instability, which is the right threshold.

For ILP-specific claims, show the **batch size distribution as a histogram**, not just a mean. A bimodal distribution (many tiny batches + rare giant batches) tells a completely different story than a tight Gaussian around 200–300 jobs.

---

## Figures the paper needs

The vulnerability report output you have is great for engineering; for a paper you additionally need: a **latency CDF overlay** comparing all scheduler variants at the same RPS level (the figure every systems paper needs), a **batch window ablation curve** plotting p99 latency and ILP solve time as batch size varies from 50→500 (this directly answers RQ2), a **queue depth heatmap** over time × RPS level showing where backlogs form, and a **fault injection recovery timeline** showing time-to-steady-state per variant (answers RQ3). Your visualizer already generates most of the raw charts — you need to add the overlay comparison plots that put all variants on the same axes.

---

## Total experimental scale

For research mode across all scenarios and a reasonable comparison of 3 scheduler variants (ILP vs. FIFO vs. round-robin) with 5 iterations each: approximately **330,000–450,000 total invocations**. Stress/soak is the wildcard — cap it at 2 hours per run and plan for 3 runs = up to 30 hours wall-clock just for soak. Budget a full week of experiment time minimum before you can begin analysis.

---

## What your testbed has that reviewers will appreciate

The ILP batch metrics (solve time, queue depth at batch formation, batch formation rate) are genuinely novel instrumentation that most serverless benchmarks lack entirely. That's your strongest contribution — lean into the ILP observability angle. The vulnerability detection framework (cascade detection, latency spike detection, distribution skew) is also unusual and worth a methods section paragraph explaining why automated vulnerability classification matters for reproducibility.