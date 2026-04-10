# READ ME FIRST: sandboxed-react-agent + required infra

If you are making changes to `apps/sandboxed-react-agent` or the infrastructure it depends on, start here.

## Scope

This guide is for developers working on:

- app behavior (agent UX, tools, sandbox runtime behavior)
- backend sandbox orchestration and workspace lifecycle
- frontend controls and runtime visibility
- cluster/IaC resources required by the app

This guide is not a full platform manual. It is the fastest path to become productive without breaking the sandbox stack.

## 10-minute repo reading order

1. `000_READ_ME_FIRST_SANDBOXED_REACT_AGENT.md` (this file)
2. `REPO_ARCHITECTURE.md`
3. `apps/sandboxed-react-agent/README.md`
4. `apps/sandboxed-react-agent/docs/sandbox-fuse-workspaces.md`
5. `CURRENT_SANDBOX_PAINPOINTS.md`
6. `iac/gke-secure-gpu-cluster/k8s/agent-sandbox.md`

## Where to look first

### App code

- `apps/sandboxed-react-agent/backend/app/main.py`
- `apps/sandboxed-react-agent/backend/app/agent.py`
- `apps/sandboxed-react-agent/backend/app/sandbox_lifecycle.py`
- `apps/sandboxed-react-agent/backend/app/sandbox_manager.py`
- `apps/sandboxed-react-agent/backend/app/services/workspace_service.py`
- `apps/sandboxed-react-agent/backend/app/services/workspace_provisioning_service.py`
- `apps/sandboxed-react-agent/frontend/src/chat/ChatView.jsx`
- `apps/sandboxed-react-agent/frontend/src/hooks/useAppState.js`

### Infra that this app needs

- `iac/gke-secure-gpu-cluster/main.tf`
- `iac/gke-secure-gpu-cluster/variables.tf`
- `iac/gke-secure-gpu-cluster/k8s/agent_sandbox.tf`
- `apps/sandboxed-react-agent/k8s/backend-deployment.yaml`
- `apps/sandboxed-react-agent/k8s/frontend-deployment.yaml`
- `apps/sandboxed-react-agent/k8s/backend-sandbox-rbac.yaml`

## Architecture in one page

### Runtime model

- Agent calls sandbox tools from backend.
- Backend resolves runtime policy and obtains/reuses sandbox lease.
- In cluster mode, execution goes through Agent Sandbox router/templates.
- Workspace persistence uses user-specific resources (bucket + GSA + KSA + derived templates).

### Axes that control behavior

- `mode`: `cluster` or `local`
- `execution_model`: `session` or `ephemeral`
- `profile`: `persistent_workspace` or `transient`

### Important current behavior

- Persistent workspace now supports template flavor mapping:
  - requested base template flavor (for example `python-runtime-template-small`, `python-runtime-template-large`) is mapped to a user-derived template.
- Persistent failure path can auto-fallback to transient:
  - controlled by `SANDBOX_PERSISTENT_AUTO_FALLBACK_ENABLED`
  - exposed in session status (`active_runtime`, `runtime_resolution`)
- Lease cleanup is both:
  - request-path reaping, and
  - periodic janitor loop in app lifecycle (`SANDBOX_LEASE_JANITOR_*` envs)

## Mental model for common changes

### 1) "I need to change sandbox behavior"

Start in this order:

1. `backend/app/sandbox_lifecycle.py` (runtime resolution, lease scope, fallback)
2. `backend/app/agent.py` (status payload, policy merge, available options)
3. `backend/app/agents/toolkits/sandbox/__init__.py` (tool exposure + defaults)
4. `frontend/src/chat/ChatView.jsx` (user-visible runtime controls/status)

### 2) "I need to change persistent workspace provisioning"

Start in this order:

1. `backend/app/services/workspace_models.py`
2. `backend/app/services/workspace_provisioning_service.py`
3. `backend/app/services/workspace_service.py`
4. `backend/app/persistence/schema.py` and repositories
5. `apps/sandboxed-react-agent/docs/sandbox-fuse-workspaces.md`

### 3) "I need to change cluster runtime templates/warm pool"

Start in this order:

1. `iac/gke-secure-gpu-cluster/k8s/agent_sandbox.tf`
2. `iac/gke-secure-gpu-cluster/variables.tf`
3. `iac/gke-secure-gpu-cluster/terraform.v3.tfvars`
4. app deployment env in `apps/sandboxed-react-agent/k8s/backend-deployment.yaml`

Always verify app defaults and warm pool template still align.

## Guardrails (do not skip)

- Do not assume one global persistent template path; persistent is per-user and now base-template-flavor aware.
- Do not expose user-derived templates as primary user choices in public template lists.
- Keep advanced sandbox controls collapsible in UI, but keep active runtime visibility explicit.
- Treat fallback as a UX event, not just a backend implementation detail.
- Avoid silent behavior changes in default profile without feature flagging and benchmark validation.

## Environment knobs you will touch most

- `SANDBOX_MODE`
- `SANDBOX_EXECUTION_MODEL`
- `SANDBOX_SESSION_IDLE_TTL_SECONDS`
- `SANDBOX_PERSISTENT_AUTO_FALLBACK_ENABLED`
- `SANDBOX_LEASE_JANITOR_ENABLED`
- `SANDBOX_LEASE_JANITOR_INTERVAL_SECONDS`
- `SANDBOX_WORKSPACE_BASE_TEMPLATE_NAME`
- `SANDBOX_WORKSPACE_BASE_TEMPLATE_NAMES`

See:

- `apps/sandboxed-react-agent/.env.local.example`
- `apps/sandboxed-react-agent/.env.cluster.example`

## Fast verification checklist

After backend/runtime changes:

1. Run focused backend tests (workspace + lifecycle + API).
2. Verify status endpoint still returns:
   - `effective`
   - `active_runtime`
   - `runtime_resolution`
3. Validate persistent requested template flavor resolves to a user-derived template.
4. Validate fallback notification path (persistent unavailable -> transient active).

After frontend changes:

1. Run ChatView unit tests.
2. Confirm advanced controls remain hidden by default.
3. Confirm current runtime profile/template is visible.
4. Confirm fallback banner/notice behavior.

After infra changes:

1. Confirm templates/warm pool/resources are applied in cluster.
2. Confirm backend env vars match intended runtime policy.
3. Run at least one transient and one persistent tool call smoke check.

## Deployment flow for this app

From `apps/sandboxed-react-agent/`:

1. Build/push app images: `./push_images.sh`
2. Apply app manifests and wait rollout: `./start.sh`
3. Verify deployed images in cluster match manifest tags.

If infra (Terraform) changed, apply infra first, then app rollout.

## Known open priorities

- decide transient-vs-persistent default policy for general chat
- align warm pool/template defaults with real traffic
- improve instrumentation for workspace/claim/fallback timing
- reduce persistent cold-path variance and FUSE/WI fragility

Reference notes:

- `CURRENT_SANDBOX_PAINPOINTS.md`
