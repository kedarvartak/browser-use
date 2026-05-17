# Online-Mind2Web Roadmap

## Objective

Raise this repo's browser-agent performance beyond the current public Browser Use Online-Mind2Web reference point while keeping improvements general, measurable, and reproducible.

Public reference point:

- Browser Use Cloud reported `97%` on Online-Mind2Web on March 25, 2026.
- That result came from the separate `browser-use/online-mind2web` runner, not this repo alone.

This roadmap optimizes the open-source repo first, then uses the official benchmark flow for apples-to-apples validation.

## Success Criteria

- Improve benchmark-compatible performance with this repo's agent stack.
- Track both:
  - Raw score: `passed / 300`
  - Adjusted score: `passed / non-impossible`
- Turn every meaningful benchmark failure into a reproducible regression testcase.
- Avoid task-specific hacks that inflate one benchmark while degrading general browser automation quality.

## Phase 1: Baseline And Observability

### Objective

Create a reliable baseline so every improvement is tied to evidence instead of anecdotal wins.

### Work

- Standardize result artifacts for local benchmark runs.
- Record per-task metadata:
  - commit SHA
  - model name
  - browser configuration
  - agent configuration
  - concurrency
  - run date
  - duration
  - step count
  - final result
  - judge verdict
  - judge reasoning
  - failure category
- Document the current repo surfaces that matter:
  - `browser_use/agent/service.py`
  - `browser_use/agent/judge.py`
  - `tests/ci/evaluate_tasks.py`
  - `tests/mind2web_data/processed.json`
- Separate internal development data from official public benchmark runs in all reporting.

### Exit Criteria

- Every run emits comparable task-level artifacts.
- Failures can be clustered by root cause without manual log archaeology.
- A rerun of the same subset can be compared against the previous one directly.

### Test Cases

- Smoke benchmark run writes per-task results and an aggregate summary.
- Resumed run skips completed tasks without corrupting prior artifacts.
- Failed task still records enough trace data for diagnosis.
- Aggregate report includes both raw and adjusted score columns.

## Phase 2: Benchmark Harness Alignment

### Objective

Define a benchmark process that is fast for development and faithful for public comparison.

### Work

- Use two benchmark modes:
  - Local development mode with this repo's agent stack and small curated subsets
  - Official comparison mode through `browser-use/online-mind2web`
- Keep the public comparison path separate from repo-local experiments.
- Establish a required reporting format for both modes.
- Document how internal subsets map to the full official run:
  - smoke subset
  - domain-balanced subset
  - full `300` task run

### Exit Criteria

- Team can run fast local iterations without confusing them with leaderboard-grade results.
- Team can rerun the official public flow with the exact model/config intended for comparison.

### Test Cases

- `10`-task smoke subset completes and produces standardized artifacts.
- Domain-balanced subset spans multiple site categories and failure modes.
- Full `300`-task run produces raw and adjusted score summaries.
- Report clearly labels local-dev versus official-comparison mode.

## Phase 3: Failure Clustering And Regression Pack

### Objective

Organize work around recurring failure classes instead of isolated task fixes.

### Work

- Tag each failure into one primary bucket:
  - navigation and page-load instability
  - extraction hallucination or unsupported answer
  - action targeting and click/input miss
  - loop or stall behavior
  - iframe, popup, or dynamic widget handling
  - captcha, login, or impossible task
  - done-too-early or incomplete completion
- For every fixed benchmark miss, add:
  - root-cause summary
  - minimized reproduction if possible
  - regression testcase
  - expected behavior
- Maintain a running table of highest-frequency failure buckets.

### Exit Criteria

- Top failure classes are visible from aggregate run outputs.
- Each important fix has a regression entry, not just a one-off patch.

### Test Cases

- New benchmark fix adds a reproducible regression case.
- Regression pack can run independently from the full benchmark.
- Failures from a fresh run can be bucketed without inventing new labels every time.

## Phase 4: Agent Policy Improvements

### Objective

Improve decision-making, completion checks, and recovery behavior in the core agent loop.

### Work

- Tighten success criteria before `done` is called.
- Improve explicit verification of the previous action's actual effect.
- Strengthen replanning after repeated failures or stalled progress.
- Make extraction stricter when evidence on page or in trace is weak.
- Reduce cases where the agent claims completion with partial or ambiguous results.
- Prioritize existing repo control surfaces:
  - planning
  - loop detection
  - message compaction
  - screenshot sizing
  - vision detail level
  - judge-grounded completion validation

### Exit Criteria

- Agent completes fewer tasks prematurely.
- Stalls recover into new strategies instead of repeated low-value actions.
- Unsupported extracted claims are reduced.

### Test Cases

- Agent does not call `done` while required subgoals remain incomplete.
- Repeated failed actions trigger a recovery path instead of looping.
- Extraction test rejects answers not supported by the page or trace.
- Judge-focused tests catch false-positive task completion.

## Phase 5: Browser And DOM Robustness

### Objective

Raise live-site reliability by hardening the execution layer beneath the model.

### Work

- Improve clickable element selection quality.
- Reduce failures on dynamic UI:
  - delayed content
  - overlays
  - autocomplete
  - dropdowns
  - modals
  - popups
  - downloads
  - iframes
- Revisit wait heuristics and page readiness assumptions.
- Improve screenshot and coordinate fidelity where model perception depends on it.
- Review watchdog behavior around blank pages, popups, captcha, downloads, and DOM drift.

### Exit Criteria

- Fewer tasks fail for mechanical browser reasons.
- Dynamic sites require fewer retries and fewer brittle workarounds.

### Test Cases

- Navigation on slow or dynamic pages completes reliably.
- Dropdown and autocomplete interactions remain stable.
- Iframe and popup workflows behave consistently.
- Hidden or overlapped element scenarios no longer cause misclick-heavy loops.

## Phase 6: Score Gains Without Overfitting

### Objective

Ensure benchmark improvement reflects real product quality, not narrow tuning.

### Work

- Reject task-specific logic tailored to individual benchmark tasks.
- Compare benchmark gains against existing CI and real-task sanity checks.
- Keep a holdout slice for validation before accepting benchmark-tuned changes.
- Require a short run report for each benchmark-improving change:
  - what changed
  - which failure bucket moved
  - what stayed flat or regressed

### Exit Criteria

- Score gains hold on both benchmark subsets and broader sanity checks.
- Existing important CI coverage does not regress materially.

### Test Cases

- Rerun relevant `tests/ci` coverage after benchmark-oriented changes.
- Verify improvements on a holdout subset before claiming progress.
- Confirm both raw and adjusted scores move in the expected direction.

## Working Rules

- Do not remove tasks from reporting.
- Do not rename or substitute model names in reports.
- Prefer type-safe result schemas and structured outputs for benchmark artifacts.
- Treat impossible tasks as a separate reporting dimension, not an excuse to hide failures.
- Default model recommendation for Browser Use benchmarking remains `ChatBrowserUse`.

## Deliverables By Milestone

### Milestone A

- Baseline harness outputs
- Failure taxonomy
- Smoke and domain-balanced subsets

### Milestone B

- First regression pack
- First agent-policy fixes validated on subsets
- Run report template

### Milestone C

- Full benchmark-compatible run
- Raw and adjusted score tracking over time
- Holdout validation and CI guardrails
