# REPO_ARCHITECTURE

## What this repository is

This repository is an infrastructure + application monorepo for running sandboxed LLM agents on GKE.

At a high level, it contains:

- Terraform IaC for a multi-pool GKE Standard cluster (GPU, general-purpose, and gVisor-isolated pools).
- Kubernetes module code that installs and manages Agent Sandbox controller/runtime resources.
- A full-stack example app (`apps/sandboxed-react-agent`) with:
  - FastAPI backend
  - React frontend
  - LangGraph-based tool-calling agent
  - Agent Sandbox integration for isolated Python/shell execution
  - Per-user workspace provisioning flow (Cloud Storage FUSE + Workload Identity)

The repo is designed to support both platform operations (cluster lifecycle, security, runtime management) and product iteration (agent UX, tool behavior, persistence model).

## Top-level structure

### `iac/`

Infrastructure-as-code and cluster bootstrap utilities.

- `gke-secure-gpu-cluster/`
  - Root Terraform stack for GKE cluster, node pools, IAM, storage, and k8s module wiring.
  - `k8s/` submodule applies namespace/service accounts and Agent Sandbox manifests.
  - `scripts/deploy_with_secrets.sh` automates the two-stage apply flow.
- `sandbox_workspace_provisioning_setup/`
  - Validation scripts/checklists for workspace provisioning prerequisites.
- `backend_bootstrap/`
  - Terraform backend bootstrapping scripts.

### `apps/`

Application workloads and examples deployed on top of the cluster.

- `sandboxed-react-agent/` (primary app)
  - `backend/` FastAPI + LangGraph orchestration + sandbox integrations
  - `frontend/` React UI
  - `k8s/` deployment/service/ingress/rbac/pvc manifests
  - `docs/` app-specific architecture and sandbox persistence notes
- Other app directories are additional services/examples.

### `docs/`

Operational and inventory documentation for the platform.

- deployment flow
- resource inventory
- runbooks
- links and completeness checks

### Other root files/scripts

- `README.md` root index and entry points
- `inspect_cluster.sh`, `gke_diagnostics.md` operational diagnostics
- policy/security notes and migration guides

## Main architecture slices

## 1) Platform infrastructure (Terraform)

Primary stack: `iac/gke-secure-gpu-cluster/`

- Creates GKE Standard cluster with Workload Identity.
- Creates node pools with specific workload intents:
  - `primary_nodes` for baseline/system reliability
  - `general_purpose_pool` and small spot pool for app workloads
  - GPU spot pools for GPU workloads
  - `gvisor_pool` for isolated sandbox runtime pods
- Enables Secret Manager integration and GCS Fuse CSI driver.
- Creates service accounts and IAM bindings needed by workloads.

## 2) Kubernetes runtime module

Module: `iac/gke-secure-gpu-cluster/k8s/`

- Creates namespace and workload KSAs.
- Installs Agent Sandbox controller + CRDs from upstream release manifests.
- Manages runtime resources:
  - `SandboxTemplate` variants (`small`, `default`, `large`, optional `pydata`)
  - `SandboxWarmPool`
  - router `Service` + `Deployment`

Runtime design intent:

- Router runs on regular node pools.
- Sandboxes run on tainted/labelled gVisor pool via `runtimeClassName: gvisor`.

## 3) Full-stack app and agent runtime

App: `apps/sandboxed-react-agent/`

### Backend layers

- `app/main.py`: API surface and middleware
- `app/agent.py`: composition root for services/runtime
- `app/agents/runtime.py`: LangGraph model/tool loop
- `app/agents/toolkits/`: tool provider abstractions
- `app/agents/integrations/`: facades over sandbox lifecycle and assets
- `app/sandbox_lifecycle.py`: lease acquisition/reuse/release orchestration
- `app/app_factory.py`: FastAPI app runtime wiring and background janitor loops
- `app/sandbox_manager.py`: actual python/shell execution calls
- `app/services/workspace_*`: per-user workspace provisioning/reconcile/deprovision
- `app/persistence/*`: SQLite persistence adapters

### Frontend

- Chat UI + runtime controls (sandbox mode/profile/template/policy/actions).
- Calls backend endpoints for chat, sandbox status, and workspace/admin ops.
- Advanced controls remain collapsible, while active runtime/fallback status is always visible.

### Persistence model

SQLite-backed operational state:

- sessions/messages/user config
- sandbox lease metadata
- workspace records
- async workspace job queue
- asset metadata

## 4) Sandbox execution model

Two axes define behavior:

- Runtime mode: `cluster` or `local`
- Execution model: `session` or `ephemeral`

Default production path is cluster mode with session-scoped lease reuse.

Profiles:

- `persistent_workspace`: per-user workspace-aware routing (derived template + FUSE mount)
  - selected base template flavor (`small`/`default`/`large`/`pydata`) is mapped to a user-derived template
  - if persistent prerequisites fail, runtime can auto-fallback to `transient` with explicit session status metadata
- `transient`: bypasses workspace provisioning path, uses configured template directly

Operational behavior:

- session sandbox lease cleanup runs both on-demand and via periodic janitor loop
- session sandbox status payload includes `active_runtime` and `runtime_resolution` for UI/agent visibility

## 5) Deployment and operations model

The repo uses a two-stage Terraform apply to avoid provider ordering issues:

1. Phase A: cloud infra + cluster
2. secret version upload (if needed)
3. Phase B: `module.k8s`

Agent Sandbox on fresh clusters can be bootstrapped with a two-pass runtime toggle.

## Recommended entry points

If you are new to this repo, start in this order:

1. `README.md`
2. `docs/README.md`
3. `iac/gke-secure-gpu-cluster/README.md`
4. `iac/gke-secure-gpu-cluster/k8s/agent-sandbox.md`
5. `apps/sandboxed-react-agent/README.md`
6. `apps/sandboxed-react-agent/docs/sandbox-fuse-workspaces.md`

## Design intent and boundaries

- Terraform owns stable platform resources and cluster-level runtime installs.
- The backend dynamically provisions user-specific workspace identities/templates.
- Agent-level tool execution is abstracted from infrastructure details via facades.
- Operational troubleshooting is documented and script-assisted (`diagnose_k8s_app.sh`, integration test artifacts, runbooks).
