# CURRENT_SANDBOX_PAINPOINTS

## Scope of this analysis

This document summarizes the current sandbox pain points observed from repository code, docs, and recorded integration-test diagnostics.

Focus area:

- persistent sandbox behavior (slow startup, leases that appear to never end, python/tool execution failures)
- highest-impact improvements with lowest implementation cost
- benchmark scenarios to measure agent and k8s integration performance

## Executive summary

The system is structurally sound. Recent updates reduced several major pain points, but persistent mode still has meaningful cold-start and infrastructure-coupling costs.

Top themes:

1. Persistent workspace provisioning still adds cloud and k8s control-plane operations to the first tool-call path.
2. FUSE/WI integration failures are explicitly visible in integration artifacts (`FailedMount`, `Unauthenticated`).
3. Warm pool and template defaults can be misaligned, reducing the expected cold-start benefit.
4. Version/config skew (controller/images/templates) increases non-determinism.
5. New mitigation features are in place (janitor + fallback + runtime visibility) and now need instrumentation-driven validation.

## Symptoms and likely causes

## A) Slow startup for persistent sessions

Observed contributing factors:

- Persistent profile is the default runtime behavior.
- For first-use users, the backend may create bucket + GSA + KSA + WI binding + IAM + derived `SandboxTemplate` before execution.
- This work is serialized and depends on multiple control planes (IAM, Storage, Kubernetes API).

Likely impact:

- High p95 and p99 first-tool-call latency.
- More variance during project/cluster/API load.

## B) Lease appears to never end

Observed behavior (historical baseline):

- Expired lease reaping was called inside execution methods (`exec_python`/`exec_shell`).

Current status:

- A periodic in-process janitor loop now runs from app lifespan and reaps expired leases on a timer.
- Request-path reaping still exists as a safety backstop.

Likely impact:

- Stale claims/leases can remain active after user inactivity.
- Perceived "lease never ends" even when TTL metadata exists.

## C) Python/tool failures in persistent mode

Observed behavior (historical baseline):

- Persistent path returned immediate errors when workspace was still provisioning/reconciling.
- Integration artifacts show repeated mount failures:
  - `driver name gcsfuse.csi.storage.gke.io not found`
  - `rpc error: code = Unauthenticated ... context deadline exceeded`

Current status:

- Persistent mode now supports configurable auto-fallback to transient when workspace/template resolution fails.
- Session sandbox status now exposes active runtime and fallback state for explicit UI/agent feedback.

Likely remaining impact:

- User sees python failures or "retry" behavior on initial turns.
- Reliability depends heavily on GCS FUSE and Workload Identity correctness.

## D) Warm pool benefit may be partially lost

Observed behavior:

- Warm pool template can resolve to `python-runtime-template-pydata` when pydata template is enabled.
- App default template is `python-runtime-template-small`.

Likely impact:

- Warmed sandboxes may not match the most common execution template.
- Extra cold starts despite non-zero warm pool replicas.

## E) Version and image drift risk

Observed behavior:

- Agent Sandbox Terraform defaults still reference `v0.1.0` controller manifests.
- Runtime images default to `latest-main` tags in Terraform defaults.

Likely impact:

- Harder reproducibility and debugging across environments.
- Increased chance of subtle behavior changes over time.

## Prioritized improvements (current status)

## 1) Add periodic lease janitor in backend process

Status: implemented

What to change:

- Run `reap_expired_leases()` on a timer (for example every 30-60s), not only on tool execution.

Why high ROI:

- Directly addresses "lease never ends" with small code change.
- Reduces stale claim accumulation even during quiet periods.

## 2) Make `transient` default for general chat, keep persistent explicit

Status: pending

What to change:

- Default profile for new users/sessions becomes `transient`.
- Persistent mode is opt-in per session or user policy.

Why high ROI:

- Immediately removes first-turn provisioning overhead for most flows.
- Converts persistent path to a deliberate premium/advanced mode until hardened.

## 3) Align warm pool template with dominant execution template

Status: pending

What to change:

- Warm `python-runtime-template-small` if that is your default app template.

Why high ROI:

- Simple config-only change.
- Measurable cold-start reduction under moderate load.

## 4) Pin versions and reduce drift

Status: in progress

What to change:

- Pin Agent Sandbox release and runtime/router image tags (prefer immutable digests).
- Align backend `k8s-agent-sandbox` expectations with installed controller/runtime.

Why high ROI:

- Improves reproducibility and incident triage.
- Low implementation cost.

## 5) Persistent preflight + graceful fallback

Status: partially implemented

What to change:

- Add preflight checks for persistent mode (workspace status, template exists, FUSE prerequisites).
- Keep auto-fallback to transient enabled with explicit telemetry and user-visible status.

Why high ROI:

- Avoids hard user-facing failures.
- Makes failure mode deterministic and observable.

## 6) Reduce first-use provisioning in hot path

Status: in progress

What to change:

- Keep async provisioning, but gate tool execution with bounded wait + clearer UX.
- Continue rollout of per-flavor persistent template derivation so persistent selection does not collapse to a single default template path.
- Optionally pre-provision workspaces for active users in background.

Why ROI:

- Medium effort, high user-experience gain on persistent path.

## Benchmark and test plan

## Key metrics to track

- End-to-end tool latency:
  - `t_first_tool_ms` (first tool call in session)
  - `t_steady_tool_ms` (subsequent tool call with reused lease)
- Provisioning timings:
  - `t_workspace_prepare_ms`
  - `t_workspace_ready_ms`
- Sandbox lifecycle timings:
  - `t_claim_ready_ms`
  - `t_router_exec_ms`
- Reliability:
  - tool failure rate
  - mount failure count (`FailedMount`)
  - lease stale count (active beyond expected TTL)
  - fallback activation rate (`runtime_resolution.fallback_active`)
  - fallback reason distribution (`runtime_resolution.fallback_reason_code`)

## Core benchmark scenarios

1. Cold start, transient profile, router ready
2. Cold start, persistent profile, workspace absent
3. Warm start, session lease reuse
4. Router scaled to 0 then scaled up
5. gVisor pool low capacity / scale from 0 or 1
6. Workspace reconcile after template drift
7. Lease expiry correctness with no traffic (janitor effectiveness)
8. Persistent requested template flavor (`small/default/large/pydata`) resolves to matching user-derived template
9. Persistent failure path triggers explicit transient fallback notice and active runtime change

## Agent task test cases

Use deterministic prompts so comparisons are stable:

1. "Use `sandbox_exec_python` once to print `2+2`."
2. "Create `hello.txt` in `/workspace`, then read it back."
3. "Generate a CSV and summarize row count."
4. "Create an image asset and return it via asset exposure path."
5. "Install a package in-session and run code using it" (session continuity check).

For each case, run with:

- transient vs persistent profile
- session vs ephemeral execution model
- small vs default template

## Cluster-state matrix for benchmarking

- Router replicas: 0 vs 1
- Warm pool replicas: 0 vs >0
- gVisor min nodes: 0 vs 1
- Background load: low vs moderate

This matrix will show where startup cost is dominated by pod scheduling, workspace provisioning, or router readiness.

## Observations from live benchmark runs (2026-04-09)

Reference artifacts:

- `apps/sandboxed-react-agent/benchmarks/runs/20260409T195734Z_auth-live-jwt/results_rows.csv`
- `apps/sandboxed-react-agent/benchmarks/runs/20260409T202550Z_auth-live-jwt-new-user/results_rows.csv`

Important caveat:

- Sample size is intentionally small (2 runs per case) due to slow provisioning.
- S2 is sensitive to pre-existing workspace state; one run set was not a pure workspace-absent cold path.

Observed patterns:

1. **High cold-start variance is real and large**.
   - Transient first-tool latency ranged from ~14s to ~78s.
   - Persistent first-tool latency ranged from ~2s to ~91s.
   - This indicates occasional very slow cold paths even when median looks acceptable.

2. **Steady-state execution is much faster than first tool call**.
   - Most `t_steady_tool_ms` values were ~2s to ~4.5s.
   - This confirms that startup/provisioning dominates latency, not normal in-session execution.

3. **Warm pool was 0 during runs, with router at 1 replica**.
   - Bench runs were collected with warm pool disabled (`warm_pool_replicas=0`).
   - This likely contributes to observed long-tail cold starts.

4. **Persistent path behavior is non-deterministic across users/runs**.
   - One new-user persistent run had ~91s first-tool latency while another was ~2.3s.
   - Prior user run also showed persistent variability and signs of pre-ready workspace masking true cold cost.

5. **Reliability is mostly good, but mount-related risk remains**.
   - Tool failure rate in these runs was 0%.
   - A `FailedMount` event was observed in the new-user run window, consistent with earlier painpoint evidence.

6. **Short TTL lease test did not show stale active lease in sampled checks**.
   - With `session_idle_ttl_seconds=30` and 45s idle waits, sampled post-status snapshots showed `lease_stale_count=0`.
   - This is encouraging but not sufficient to conclude janitor effectiveness cluster-wide.

Implications for performance tuning priority:

- First focus should be reducing cold-path variance (warm pool/template alignment, scheduling/startup path instrumentation).
- Then validate persistent cold-start specifically with strict preconditions (workspace absent, same cluster state).
- Keep low-sample paired comparisons (2-3 runs) but require max/median tracking, not median alone.

## Suggested implementation sequence (next)

1. Instrument lifecycle spans and benchmark fields for workspace/claim/fallback phases.
2. Switch default profile to transient (feature flag) for general chat.
3. Align warm pool template with dominant runtime template and re-benchmark.
4. Pin Agent Sandbox/controller/runtime artifacts to explicit versions or digests.
5. Run benchmark matrix and compare p50/p95/p99 plus fallback rate before/after.
6. Decide persistent-default policy once FUSE/WI failure rate and variance are within targets.

## Notes on evidence source

This analysis is based on:

- backend orchestration and lifecycle code
- Terraform and k8s manifests
- integration test suite and generated diagnostics artifacts

Notably, multiple artifacts repeatedly contain `FailedMount` and `Unauthenticated` events for `workspace-gcs-fuse`, which strongly suggests persistent-path instability independent of transient/session reuse behavior.
