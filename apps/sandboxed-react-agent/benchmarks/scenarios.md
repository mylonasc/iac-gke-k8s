# Benchmark Scenarios

This benchmark set is based on `CURRENT_SANDBOX_PAINPOINTS.md`.

## Key metrics

- `t_first_tool_ms`: first tool call latency for a session
- `t_steady_tool_ms`: subsequent tool call latency with lease reuse
- `t_workspace_prepare_ms`: workspace prepare/reconcile duration
- `t_workspace_ready_ms`: time until workspace is ready
- `t_claim_ready_ms`: claim-to-sandbox-ready duration
- `t_router_exec_ms`: router execution duration
- reliability counters:
  - tool failure rate
  - `FailedMount` event count
  - lease stale count (active beyond expected TTL)

## Core scenarios

| Scenario ID | Description | Primary signal |
| --- | --- | --- |
| S1 | Cold start, transient profile, router ready | baseline first-tool latency |
| S2 | Cold start, persistent profile, workspace absent | provisioning + startup overhead |
| S3 | Warm start, session lease reuse | steady-state performance |
| S4 | Router scaled to 0 then scaled up | router readiness recovery cost |
| S5 | gVisor pool low capacity (0 or 1 node) | scheduling sensitivity |
| S6 | Workspace reconcile after template drift | persistent-path resilience |
| S7 | Lease expiry with no traffic | janitor effectiveness / stale lease behavior |

## Deterministic task cases

| Task ID | Prompt |
| --- | --- |
| T1 | Use `sandbox_exec_python` once to print `2+2`. |
| T2 | Create `hello.txt` in `/workspace`, then read it back. |
| T3 | Generate a CSV and summarize row count. |
| T4 | Create an image asset and return it via asset exposure path. |
| T5 | Install a package in-session and run code using it. |

Run each task across:

- profile: `transient` and `persistent`
- execution model: `session` and `ephemeral`
- template: `python-runtime-template-small` and `python-runtime-template`

## Cluster-state matrix

| Variable | Values |
| --- | --- |
| Router replicas | `0`, `1` |
| Warm pool replicas | `0`, `>0` |
| gVisor min nodes | `0`, `1` |
| Background load | `low`, `moderate` |

This matrix helps identify whether latency is dominated by router readiness,
pod scheduling, or workspace provisioning.

## Run budget guidance (slow provisioning)

- Use `2` runs per case as baseline.
- Cap at `3` runs per case unless an anomaly needs confirmation.
- Prioritize these cases first when time is limited: `S1`, `S2`, `S3`, `S7`.
- Keep cluster state fixed during each pair of runs (router/warmpool/gVisor).
