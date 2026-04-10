# Benchmarks

This folder provides a repeatable benchmark workflow for the sandboxed react
agent, focused on the pain points documented in `CURRENT_SANDBOX_PAINPOINTS.md`.

It is designed to capture:

- text evidence (`notes.txt`, `repo_state.txt`, `cluster_state.txt`)
- table-friendly benchmark data (`results_rows.csv`, `results_table.md`)
- repo + cluster snapshots for each run to support debugging and insight

## Folder layout

- `scenarios.md`: benchmark scenarios, task prompts, and cluster-state matrix
- `scripts/init_run.sh`: create a timestamped benchmark run folder and templates
- `scripts/capture_state.sh`: capture repo and cluster state snapshots
- `templates/`: markdown/csv/txt templates copied into each run
- `runs/`: generated benchmark runs (ignored by git except docs)

## Quick start

From `apps/sandboxed-react-agent`:

```bash
bash benchmarks/scripts/init_run.sh baseline
```

This creates `benchmarks/runs/<timestamp>_baseline/` with:

- `repo_state.txt`
- `cluster_state.txt`
- `notes.txt`
- `results_table.md`
- `results_rows.csv`

After running benchmark scenarios, capture a post-run snapshot:

```bash
bash benchmarks/scripts/capture_state.sh benchmarks/runs/<run_id>
```

Run benchmark cases with the low-sample runner (default: 2 runs per case):

```bash
python3 benchmarks/scripts/benchmark_chat.py \
  --run-dir benchmarks/runs/<run_id> \
  --scenario-id S1 \
  --task-id T1 \
  --profile transient \
  --execution-model session \
  --template-name python-runtime-template-small
```

If the backend requires auth, pass a bearer token:

```bash
BENCHMARK_AUTH_TOKEN=<jwt> python3 benchmarks/scripts/benchmark_chat.py ...
```

If traffic goes through oauth2-proxy ingress, you can also pass either:

- forwarded access token header:

```bash
BENCHMARK_X_AUTH_REQUEST_ACCESS_TOKEN=<jwt> python3 benchmarks/scripts/benchmark_chat.py ...
```

- raw cookie header (example `_oauth2_proxy=...`) when using ingress URL:

```bash
BENCHMARK_COOKIE='_oauth2_proxy=...' python3 benchmarks/scripts/benchmark_chat.py ...
```

If you need to extract a JWT from your oauth2-proxy session, use
`apps/fastapi-token-inspection` and open:

```text
https://magarathea.ddns.net/token-inspection/raw
```

Generate/update the markdown summary table from collected rows:

```bash
python3 benchmarks/scripts/summarize_results.py --run-dir benchmarks/runs/<run_id>
```

## Suggested run flow

1. Create run folder (`init_run.sh`).
2. Execute scenarios from `scenarios.md`.
3. Record raw observations in `notes.txt`.
4. Enter timings and outcomes in `results_rows.csv`.
5. Update rollups in `results_table.md` (p50/p95/p99, failures, insights).
6. Capture post-run state (`capture_state.sh`) to correlate results with runtime state.

## Low-sample benchmarking policy

Because sandbox provisioning is expensive, use small repeat counts by default.

- Default: `2` runs per case.
- Recommended max: `3` runs per case.
- Compare paired runs (before/after) under the same cluster state window.
- Treat p95/p99 as directional only when `n < 5`; rely more on median + max.

## Notes

- Cluster capture defaults to namespace `alt-default`.
- Override defaults with env vars when needed:
  - `BENCHMARK_NAMESPACE`
  - `BENCHMARK_SYSTEM_NAMESPACE`
  - `BENCHMARK_BACKEND_DEPLOYMENT`
  - `BENCHMARK_ROUTER_DEPLOYMENT`
