# Benchmark Guide

## Purpose

This document explains how to test this repo against Online-Mind2Web without confusing local development results with public leaderboard-style results.

Online-Mind2Web is the live browser-agent benchmark covering `300` tasks across `136` websites. The public Browser Use Cloud result of `97%` was published on March 25, 2026 and used the separate `browser-use/online-mind2web` runner.

This repo should measure progress in two modes:

- Local development mode for fast iteration on the open-source agent
- Official comparison mode for public benchmark parity

## What We Report

Every benchmark report must include:

- Raw score: `passed / 300`
- Adjusted score: `passed / non-impossible`
- Run date
- Commit SHA
- Model name exactly as used
- Browser configuration
- Agent configuration
- Concurrency
- Median duration
- Median steps
- Top failure buckets

Never present local subset results as equivalent to the public leaderboard run.

## Benchmark Modes

### 1. Local Development Mode

Use this mode during iteration on the open-source repo.

Use it to:

- validate agent-policy changes quickly
- compare two code revisions on a small task set
- cluster failures and build regression cases

Recommended progression:

1. Smoke subset
2. Domain-balanced subset
3. Larger validation subset
4. Full benchmark-compatible run only after signal is positive

Suggested local inputs:

- repo-local benchmark subsets derived from internal task lists
- targeted reproductions from prior failures
- regression cases added under the test suite

Important:

- `tests/mind2web_data/processed.json` is internal processed data and should not be described as the official public `300`-task leaderboard set.

### 2. Official Comparison Mode

Use this mode when you want public-benchmark-compatible results.

Source of truth:

- `browser-use/online-mind2web`

That runner:

- loads all `300` Online-Mind2Web tasks
- runs them on live sites
- writes per-task `result.json` artifacts
- is the correct path for apples-to-apples comparison with the public Browser Use result

## Required Artifacts

Every run should produce or preserve:

- aggregate summary file
- per-task result file
- task ID
- task text
- final result returned by the agent
- binary judge verdict
- judge reasoning
- impossible-task flag
- captcha flag
- failure bucket
- timings
- step count
- configuration metadata

Recommended aggregate table columns:

| Date | Commit | Mode | Model | Raw Score | Adjusted Score | Median Steps | Median Duration | Top Failure Buckets |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Judge And Scoring Policy

Use binary pass/fail scoring.

Judge output should capture:

- verdict
- reasoning
- failure reason
- impossible-task flag
- captcha flag

Scoring rules:

- Raw score counts all `300` tasks.
- Adjusted score excludes tasks marked impossible by the benchmark policy.
- No task should be silently removed from reporting.
- Empty output, fabricated details, or incomplete fulfillment should be scored as failure.

## Recommended Workflow

### Step 1: Run A Smoke Subset

Purpose:

- catch broken configs
- validate artifact generation
- confirm judge output shape

Minimum checks:

- tasks execute
- artifacts are written
- summary table is generated
- failures are bucketed

### Step 2: Run A Domain-Balanced Subset

Purpose:

- detect broad weaknesses before paying for a full run

Include tasks across multiple categories such as:

- shopping
- travel
- finance
- government
- search and information retrieval

Minimum checks:

- compare scores against previous baseline
- inspect top failure buckets
- convert important new failures into regressions

### Step 3: Run Full Comparison

Purpose:

- obtain benchmark-compatible score tracking

Requirements:

- fixed commit SHA
- fixed model name
- fixed concurrency
- saved run artifacts
- saved report with raw and adjusted score

## Official Comparison Execution

For the public-comparison path, use the external runner rather than inventing a repo-local substitute.

High-level flow:

1. Clone `browser-use/online-mind2web`
2. Configure required API keys
3. Run the benchmark with the intended model and concurrency
4. Preserve `results/{task_id}/result.json` artifacts
5. Summarize:
   - raw pass rate
   - adjusted pass rate
   - failure bucket distribution
   - cost and latency

If we later add a helper script in this repo, it should wrap this flow without changing the source benchmark semantics.

## Repo-Local Validation

This repo already contains useful building blocks for local evaluation:

- `tests/ci/evaluate_tasks.py` for lightweight task evaluation
- judge support in `browser_use/agent/judge.py`
- agent execution and completion logic in `browser_use/agent/service.py`

Use repo-local validation to answer:

- Did this code change reduce false positives?
- Did loop recovery improve?
- Did action targeting get more reliable?
- Did extraction quality improve?

Do not use repo-local validation alone to claim leaderboard parity.

## Testcases Required For Each Roadmap Phase

### Phase 1: Baseline And Observability

- Smoke run writes task-level and aggregate artifacts
- Resume behavior skips completed tasks safely
- Failed task still captures debug data

### Phase 2: Harness Alignment

- Local-dev and official-comparison modes are labeled distinctly
- Full run report includes both raw and adjusted score
- Internal processed data is not mislabeled as official benchmark data

### Phase 3: Failure Clustering

- Every important fixed failure gets a regression testcase
- Failure buckets remain stable across runs

### Phase 4: Agent Policy

- Agent does not report success before required evidence exists
- Looping behavior triggers recovery instead of repeating
- Unsupported extraction claims are rejected

### Phase 5: Browser And DOM

- Dynamic widgets, iframes, and popups remain operable
- Slow pages do not collapse into false failures

### Phase 6: Anti-Overfitting

- Improvements survive holdout validation
- Relevant CI coverage remains healthy after benchmark-driven changes

## Reporting Template

Use a short run summary like this:

```md
Date: 2026-05-17
Commit: <sha>
Mode: local-dev | official-comparison
Model: <exact model name>
Concurrency: <n>
Raw Score: <passed>/300 (<percent>)
Adjusted Score: <passed>/<non-impossible> (<percent>)
Median Steps: <n>
Median Duration: <seconds>
Top Failure Buckets: <bucket list>
What Changed: <1-3 lines>
```

## Environment Notes

- Use `uv` for repo-local Python execution and dependency management.
- Do not replace or normalize model names in benchmark reports.
- Default model recommendation for Browser Use benchmarking is `ChatBrowserUse`.
- If Browser performance itself becomes the bottleneck in production-style testing, consider `Browser(use_cloud=True)` for remote browser infrastructure, but keep benchmark reports explicit about the environment used.
