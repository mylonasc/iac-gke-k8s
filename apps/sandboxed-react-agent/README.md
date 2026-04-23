# Sandboxed React Agent

Example full-stack app that demonstrates an LLM tool-calling agent with Python/shell tool execution.

It supports two execution targets:

- `cluster` mode: tool calls execute through Agent Sandbox in GKE.
- `local` mode: tool calls execute inside the backend container (for local testing).

- Frontend: React chat UI.
- Backend: FastAPI `/api/chat` endpoint.
- Tool execution: Agent Sandbox (`cluster`) or local subprocess (`local`).
- Route: `https://magarathea.ddns.net/sandboxed-react-agent`

## Architecture

1. Browser sends chat request to backend (`/sandboxed-react-agent/api/chat`).
2. Backend builds a per-session agent runtime and toolkit set, then calls OpenAI with tool definitions such as `sandbox_exec_python` and `sandbox_exec_shell`.
3. When tool calls are requested, toolkit modules invoke integration facades that manage sandbox execution, lease reuse, and asset persistence.
4. Tool output is returned to the model and then to the user.

The backend now separates responsibilities into four layers:

- `app/agent.py`: app-facing composition root for FastAPI, session ownership, and public APIs.
- `app/agents/runtime.py` and `app/agents/transport.py`: LangGraph run loop and assistant transport orchestration.
- `app/agents/toolkits/`: stateful tool providers that expose model-facing tools while holding injected runtime/session handles.
- `app/agents/integrations/`: facades over sandbox runtime, sandbox lease/session lifecycle, and asset storage.

This lets tool definitions evolve independently from sandbox backend details and keeps resource manipulation behind a stable Python abstraction.

Relevant design notes:

- `docs/sandbox-session-persistence-and-snapshots.md`
- `docs/sandbox-fuse-workspaces.md`

## Session Sandbox Control API

The backend exposes session-scoped sandbox control endpoints so runtime selection
and lifecycle can be managed per chat session (not only per user/global config).

- `GET /api/sessions/{session_id}/sandbox/status`
  - Returns effective runtime context, current session sandbox policy, lease
    metadata, workspace status, available sandbox options, and runtime
    resolution details (`active_runtime`, `runtime_resolution`).
- `GET /api/sessions/{session_id}/sandbox/policy`
  - Returns current persisted session sandbox policy overlay.
- `PATCH /api/sessions/{session_id}/sandbox/policy`
  - Updates session sandbox policy (`profile`, `template_name`,
    `execution_model`, etc.) and returns updated effective status.
- `POST /api/sessions/{session_id}/sandbox/actions`
  - Runs lifecycle actions such as `release_lease`, `reconcile_workspace`,
    `ensure_workspace_async`, and `ensure_workspace`.
- `POST /api/sessions/{session_id}/sandbox/terminal/open`
  - Opens a session-bound interactive terminal and returns a one-time websocket
    token + connect path.
- `DELETE /api/sessions/{session_id}/sandbox/terminal/{terminal_id}`
  - Closes an active interactive terminal session.
- `WS /api/sessions/{session_id}/sandbox/terminal/{terminal_id}/ws?token=...`
  - Bidirectional terminal stream (`stdin`, `stdout`, `stderr`, resize) bound
    to the same session sandbox lease used by chat tools.

The chat UI polls the status endpoint and provides inline session controls for
refresh, lease release, workspace reconcile, and policy updates.

During active `/api/assistant` runs, backend sandbox lifecycle updates are also
streamed in transport state (`sandbox_updates`, `sandbox_live`) so the UI can
render claim/runtime progress without coupling tool or lifecycle code to
frontend components.

When persistent workspace routing is selected but not ready, runtime can
auto-fallback to transient execution (configurable via
`SANDBOX_PERSISTENT_AUTO_FALLBACK_ENABLED`). The status payload and UI surface
this explicitly so users can see when fallback starts and which sandbox profile
and template are currently active.

## Sandbox Toolkit Surface

The sandbox toolkit includes both execution tools and diagnostic/mutating
control tools:

- Execution: `sandbox_exec_python`, `sandbox_exec_shell`
- Diagnostics: `sandbox_get_session_status`, `sandbox_get_workspace_status`,
  `sandbox_list_available_sandboxes`, `sandbox_wait_for_workspace_ready`
- Mutations: `sandbox_set_session_policy`, `sandbox_release_session_lease`,
  `sandbox_reconcile_workspace`, `sandbox_open_interactive_shell`

The frontend also includes a temporary dev panel for terminal-only validation:

- `?dev_panel=terminal` renders an isolated terminal UI using
  `/api/dev/sessions/{session_id}/terminal/*` endpoints.

## Deployment diagram (KubeDiagrams)

To render diagrams on demand:

```bash
./apps/sandboxed-react-agent/render_k8s_diagrams.sh
```

![Deployment diagram (KubeDiagrams)](docs/diagrams/deployment-kubediagrams.svg)


### Component roles in the cluster

- 🌐 **Ingress (`sandboxed-react-agent-web`, `sandboxed-react-agent-api`)**
  - Terminates external HTTP(S) traffic for `magarathea.ddns.net`.
  - Routes UI requests to frontend and `/api/*` requests to backend.
- 🧩 **Frontend Deployment/Pod (`sandboxed-react-agent-frontend`)**
  - Serves the React app through NGINX.
  - Proxies `/api/*` to backend service (`BACKEND_UPSTREAM` in env).
- ⚙️ **Backend Deployment/Pod (`sandboxed-react-agent-backend`)**
  - Hosts FastAPI endpoints (`/api/chat`, `/api/health`, `/api/config`).
  - Contains the agent logic (LLM call loop + tool orchestration).
  - Uses `k8s-agent-sandbox` SDK in `cluster` mode.
- 🔐 **Secret + ServiceAccount + RBAC**
  - `sandboxed-react-agent-secrets` provides `OPENAI_API_KEY`.
  - `sandbox-workspace-admin-ksa` (annotated for Workload Identity) is used by backend.
  - Role/RoleBinding (`backend-sandbox-rbac.yaml`) allows creating `SandboxClaim` and reading related Agent Sandbox CRDs.
- 🛣️ **Sandbox Router (`sandbox-router-svc`, `sandbox-router-deployment`)**
  - Receives backend execution requests and forwards them to a concrete sandbox runtime.
  - Handles routing against claim/sandbox lifecycle resources.
  - Runs on the regular cluster node pool so gVisor nodes are reserved for sandbox runtimes.
- 🧱 **Agent Sandbox CRDs and runtime resources**
  - `SandboxTemplate` defines sandbox pod spec (runtime image, probes, constraints).
  - `SandboxWarmPool` optionally keeps pre-warmed sandboxes to reduce cold starts.
  - `SandboxClaim` requests an isolated runtime for execution.
  - `Sandbox` represents the bound runtime backing a claim.
  - Runtime pod uses `RuntimeClass: gvisor` and schedules to the gVisor node pool.

### Runtime interaction details

1. User opens the app URL; ingress routes to frontend service/pod.
2. Frontend sends chat input to backend `/api/chat` via ingress/API path.
3. Backend agent sends conversation + tools to OpenAI.
4. If model chooses a tool, backend requests execution through `sandbox-router-svc`.
5. Router ensures a sandbox exists (create/use `SandboxClaim` -> `Sandbox` -> runtime pod).
6. Tool command executes in sandbox runtime pod (`python-runtime-sandbox`).
7. Router returns tool output to backend.
8. Backend sends tool result back to OpenAI for final assistant response.
9. Final answer is returned to frontend and rendered to user.

## Interaction diagram

![Interaction diagram (KubeDiagrams)](docs/diagrams/interaction-kubediagrams.svg)


## Folder structure

- `backend/`: FastAPI service and Dockerfile.
- `backend/app/agents/`: backend agent abstractions.
- `backend/app/agents/toolkits/`: stateful LangGraph/LangChain-compatible tool providers.
- `backend/app/agents/integrations/`: facades for sandbox runtime, lease/session lifecycle, and assets.
- `frontend/`: redesigned modular React UI (default runtime frontend).
- `frontend-old/`: previous UI kept for reference.
- `k8s/`: Kubernetes manifests (deployments, services, ingress, secret example).

## Prerequisites

### For Docker Compose local testing

- Docker Engine with Compose v2 (`docker compose ...`).
- OpenAI API key.

### For Kubernetes deployment

- Agent Sandbox controller/extensions and runtime objects already installed in your cluster.
  - In this repo: `iac/gke-secure-gpu-cluster/k8s/agent-sandbox.md`
- Router service reachable in namespace `alt-default`:
  - `sandbox-router-svc.alt-default.svc.cluster.local:8080`
- Sandbox template exists:
  - `python-runtime-template-small` (higher density, faster scheduling under intermittent load)
  - `python-runtime-template` (balanced)
  - `python-runtime-template-large` (higher resource envelope)
  - `python-runtime-template-pydata` (opt-in extended stack)
- ingress-nginx and oauth2-proxy already configured for your host.

### Backend API token validation

The backend can enforce JWT/OIDC validation for all `/api/*` routes (except
`/api/health` and `/api/public/*` by default). Configure:

- `AUTH_ENABLED=1`
- `AUTH_ISSUER`
- `AUTH_AUDIENCE`
- `AUTH_JWKS_URL`
- optional: `AUTH_ALGORITHMS` (default `RS256`)
- optional: `AUTH_EXEMPT_PATH_PREFIXES` (default `/api/health,/api/public/`)
- optional: `AUTH_USER_ID_CLAIM` (default `sub`)

Admin-only ops endpoints (`/api/admin/ops/*`) are separately gated. Configure at
least one allowlist in shared environments:

- `OPS_ADMIN_EMAIL_ALLOWLIST` (comma-separated)
- `OPS_ADMIN_USER_ID_ALLOWLIST` (comma-separated)
- `OPS_ADMIN_GROUP_ALLOWLIST` (comma-separated)
- optional: `OPS_ADMIN_ALLOW_ALL_AUTHENTICATED=1` for trusted dev environments

Authorization policy is now YAML-driven and can be sourced from either local disk
or a dedicated authz control-plane backend:

- `AUTHZ_POLICY_PATH` (default: `/app/data/authz-policy.yaml`)
- optional: `AUTHZ_POLICY_URL` (for periodic remote refresh, e.g. authz service)
- optional: `AUTHZ_REFRESH_INTERVAL_SECONDS` (default: `30`)
- optional: `AUTHZ_REMOTE_TIMEOUT_SECONDS` (default: `3`)

Default policy template:

- `apps/sandboxed-react-agent/backend/config/authz-policy.default.yaml`

Standalone authz control plane component:

- `apps/sandboxed-react-agent-authz/`

Kubernetes manifests for authz control plane:

- `apps/sandboxed-react-agent-authz/k8s/backend-pvc.yaml`
- `apps/sandboxed-react-agent-authz/k8s/backend-deployment.yaml`
- `apps/sandboxed-react-agent-authz/k8s/backend-service.yaml`
- `apps/sandboxed-react-agent-authz/k8s/frontend-deployment.yaml`
- `apps/sandboxed-react-agent-authz/k8s/frontend-service.yaml`
- `apps/sandboxed-react-agent-authz/k8s/ingress.yaml`

Policy feature gates currently used by backend APIs:

- `terminal.open`
- `admin.ops.read`
- `admin.ops.write`
- `authz.policy.manage`

Session ownership is now scoped per authenticated user id claim. By default,
the backend stores and filters sessions by JWT `sub`.

When JWT auth is disabled (`AUTH_ENABLED=0`), the backend can still isolate
session ownership by issuing a signed anonymous identity cookie. Configure:

- `ANON_IDENTITY_ENABLED` (default `1`)
- `ANON_IDENTITY_SECRET` (recommended to set explicitly in each environment)
- optional: `ANON_IDENTITY_COOKIE_NAME` (default `sra_anon_uid`)
- optional: `ANON_IDENTITY_COOKIE_SECURE` (default `0`)
- optional: `ANON_IDENTITY_COOKIE_SAMESITE` (default `lax`)

In Kubernetes, these values are wired from `sandboxed-react-agent-secrets` in
`k8s/backend-deployment.yaml`.

If you run Kubernetes without JWT auth (`AUTH_ENABLED=0`), also provide
`anon-identity-secret` in `sandboxed-react-agent-secrets` and set
`ANON_IDENTITY_ENABLED=1`.

Frontend API calls include bearer auth when a token is available in:

- `window.__AUTH_TOKEN__`
- `localStorage[VITE_AUTH_TOKEN_STORAGE_KEY]` (default key: `sandboxed-react-agent-auth-token`)
- `sessionStorage[VITE_AUTH_TOKEN_STORAGE_KEY]`

You can also provide `VITE_AUTH_TOKEN` for local testing.

Quick check:

```bash
kubectl get svc -n alt-default sandbox-router-svc
kubectl get sandboxtemplate -n alt-default python-runtime-template-small
kubectl get sandboxtemplate -n alt-default python-runtime-template
kubectl get sandboxtemplate -n alt-default python-runtime-template-large
kubectl get sandboxtemplate -n alt-default python-runtime-template-pydata
kubectl get pods -n agent-sandbox-system
```

## Run locally with Docker Compose

This runs frontend + backend on your machine and exposes the app at `http://localhost:8080`.

### Unified local control script

Use the helper script for local lifecycle, mode switching, and router forwarding:

```bash
./apps/sandboxed-react-agent/dev-sandbox.sh help
```

Common flows:

```bash
# Start compose with local tool execution
./apps/sandboxed-react-agent/dev-sandbox.sh up local

# Start router port-forward for cluster-connected testing
./apps/sandboxed-react-agent/dev-sandbox.sh port-forward start

# Switch backend at runtime to cluster mode (no compose restart)
./apps/sandboxed-react-agent/dev-sandbox.sh mode cluster http://host.docker.internal:18080

# Switch sandbox sizing profile quickly
./apps/sandboxed-react-agent/dev-sandbox.sh template python-runtime-template-small

# Inspect runtime config and health
./apps/sandboxed-react-agent/dev-sandbox.sh status

# Tail local backend logs
./apps/sandboxed-react-agent/dev-sandbox.sh logs backend --follow

# Tail backend/router logs in Kubernetes
./apps/sandboxed-react-agent/dev-sandbox.sh logs backend-k8s --follow
./apps/sandboxed-react-agent/dev-sandbox.sh logs router-k8s --follow

# Stop compose
./apps/sandboxed-react-agent/dev-sandbox.sh down

# Stop router port-forward
./apps/sandboxed-react-agent/dev-sandbox.sh port-forward stop
```

`port-forward start` now checks router readiness and, by default, auto-scales
`sandbox-router-deployment` from `0` to `1` replica when needed for interactive testing.

Template presets for app-level experimentation:

- `python-runtime-template-small` (`150m` CPU / `256Mi` memory request)
- `python-runtime-template` (`250m` CPU / `512Mi` memory request)
- `python-runtime-template-large` (`500m` CPU / `1Gi` memory request)
- `python-runtime-template-pydata` (pydata runtime image)

### Option A: local-only tool execution

1. Create env file:

```bash
cp apps/sandboxed-react-agent/.env.local.example apps/sandboxed-react-agent/.env.local
```

2. Edit `apps/sandboxed-react-agent/.env.local` and set `OPENAI_API_KEY`.

3. Start:

```bash
./apps/sandboxed-react-agent/dev-sandbox.sh up local
```

Direct compose also works (loads `apps/sandboxed-react-agent/.env.local` by default):

```bash
docker compose --project-directory apps/sandboxed-react-agent up --build
```

### Option B: cluster-connected tool execution

This mode expects your local kube context to have permissions to create
`sandboxclaims.extensions.agents.x-k8s.io` in `alt-default`.

1. Forward the cluster sandbox router to your local machine:

```bash
kubectl -n alt-default port-forward svc/sandbox-router-svc 18080:8080
```

2. Create env file:

```bash
cp apps/sandboxed-react-agent/.env.cluster.example apps/sandboxed-react-agent/.env.cluster
```

3. Edit `apps/sandboxed-react-agent/.env.cluster` and set `OPENAI_API_KEY`.

4. Start:

```bash
./apps/sandboxed-react-agent/dev-sandbox.sh up cluster
```

If running compose directly in cluster mode, pass the cluster env file explicitly:

```bash
docker compose --project-directory apps/sandboxed-react-agent --env-file apps/sandboxed-react-agent/.env.cluster up --build
```

Stop either mode:

```bash
./apps/sandboxed-react-agent/dev-sandbox.sh down
```

### Local checks

```bash
curl -sS http://localhost:8080/api/health
curl -sS http://localhost:8080/api/state
```

### Verify terminal from local compose

Interactive terminal uses cluster mode (Kubernetes exec stream), even when
frontend/backend run locally in Docker Compose.

Run the end-to-end check:

```bash
./apps/sandboxed-react-agent/test-local-terminal-compose.sh
```

This helper will:

- ensure router port-forward is running (`dev-sandbox.sh port-forward start` when needed)
- switch backend to `cluster` mode with `http://host.docker.internal:18080`
- run `frontend/e2e/terminal-compose.spec.js` against your local compose app

### Backend logging and tracing

Backend now emits structured JSON logs with request correlation and runtime metadata.
Every log event includes pod/container identity fields and request context when available.

Logged context fields include:

- `request_id`
- `session_id` (when known)
- `pod_name`, `pod_namespace`, `node_name`
- trace ids (`trace_id`, `span_id`) when tracing is enabled

Useful commands:

```bash
# Local compose backend logs
./apps/sandboxed-react-agent/dev-sandbox.sh logs backend --follow

# Kubernetes backend/router logs
./apps/sandboxed-react-agent/dev-sandbox.sh logs backend-k8s --follow
./apps/sandboxed-react-agent/dev-sandbox.sh logs router-k8s --follow
```

If you use `jq`, filtering by request id is straightforward:

```bash
./apps/sandboxed-react-agent/dev-sandbox.sh logs backend --follow | jq 'select(.request_id=="<request-id>")'
```

Tracing is optional and disabled by default. To enable OpenTelemetry export,
set these env vars for backend runtime:

- `TRACING_ENABLED=1`
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://<collector-host>:4318/v1/traces`
- optional: `TRACING_SAMPLE_RATIO=0.1`, `OTEL_SERVICE_NAME=sandboxed-react-agent-backend`

### Interactive notebook workflow

Notebook path:

- `apps/sandboxed-react-agent/notebooks/sandbox_agent_and_sandbox_playground.ipynb`

It includes:

- Agent path testing through backend (`/api/chat`) with runtime mode switching (`local`/`cluster`).
- Direct `SandboxClient` calls to the router for raw sandbox command execution.

Typical setup:

```bash
# Terminal 1: run app locally
./apps/sandboxed-react-agent/dev-sandbox.sh up local

# Terminal 2: expose sandbox router from cluster
./apps/sandboxed-react-agent/dev-sandbox.sh port-forward start
```

Then open the notebook and run cells top-to-bottom.

For agent cluster-mode through docker compose, use router URL
`http://host.docker.internal:18080` (the backend service is inside a container).
On Linux this is mapped in `docker-compose.yml` via `extra_hosts`.
The backend container also mounts your host kube and gcloud config so
`k8s-agent-sandbox` can create `SandboxClaim` resources. Keep the gcloud mount
writable in compose (`${HOME}/.config/gcloud:/root/.config/gcloud:rw`) because
the exec auth plugin writes `credentials.db` and logs during token refresh.

If direct `SandboxClient` calls in notebook fail with `Connection refused`:

```bash
./apps/sandboxed-react-agent/dev-sandbox.sh port-forward status
./apps/sandboxed-react-agent/dev-sandbox.sh port-forward restart
```

If port-forward fails with no ready endpoints, your runtime may be in idle-at-zero mode.
Scale the router deployment and retry:

```bash
kubectl -n alt-default scale deployment/sandbox-router-deployment --replicas=1
./apps/sandboxed-react-agent/dev-sandbox.sh port-forward restart
```

If `/api/chat` tool calls fail with `Invalid kube-config file. No configuration found.`,
restart compose so the `host.docker.internal` mapping is applied in the backend container,
then switch mode to cluster again:

```bash
./apps/sandboxed-react-agent/dev-sandbox.sh down
./apps/sandboxed-react-agent/dev-sandbox.sh up local
./apps/sandboxed-react-agent/dev-sandbox.sh mode cluster http://host.docker.internal:18080
```

Also verify the notebook kernel network location:

- host kernel: use `DIRECT_ROUTER_URL=http://127.0.0.1:18080`
- containerized kernel: use `DIRECT_ROUTER_URL=http://host.docker.internal:18080`

## Build and publish images (DockerHub)

Set your DockerHub user and image tag:

```bash
export DOCKERHUB_USER=<your-dockerhub-user>
export TAG=0.5.0
```

Build/push backend:

```bash
docker build -t docker.io/${DOCKERHUB_USER}/sandboxed-react-agent-backend:${TAG} ./apps/sandboxed-react-agent/backend
docker push docker.io/${DOCKERHUB_USER}/sandboxed-react-agent-backend:${TAG}
```

Build/push frontend:

```bash
docker build -t docker.io/${DOCKERHUB_USER}/sandboxed-react-agent-frontend:${TAG} ./apps/sandboxed-react-agent/frontend
docker push docker.io/${DOCKERHUB_USER}/sandboxed-react-agent-frontend:${TAG}
```

## Configure manifests

Edit image references in:

- `apps/sandboxed-react-agent/k8s/backend-deployment.yaml`
- `apps/sandboxed-react-agent/k8s/frontend-deployment.yaml`

Replace:

- `docker.io/<your-dockerhub-user>/sandboxed-react-agent-backend:0.1.0`
- `docker.io/<your-dockerhub-user>/sandboxed-react-agent-frontend:0.1.0`

## Create OpenAI key secret

Recommended command:

```bash
kubectl -n alt-default create secret generic sandboxed-react-agent-secrets \
  --from-literal=openai-api-key="$OPENAI_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Optional example file:

- `apps/sandboxed-react-agent/k8s/secret.example.yaml` (do not commit real keys)

## Create Docker pull secret in `alt-default`

If your DockerHub images are private, create the pull secret in the same namespace as the app:

```bash
kubectl get secret dockerhub-regcred -n default -o yaml \
  | sed 's/namespace: default/namespace: alt-default/' \
  | kubectl apply -f -
```

The app deployments are configured to use `imagePullSecrets: [dockerhub-regcred]`.

## Deploy

### Backend with Helm (recommended)

The backend now has a Helm chart at `apps/sandboxed-react-agent/helm/backend`.

1. Ensure required postgres + WireGuard secrets exist in `alt-default`:

```bash
cp apps/sandboxed-react-agent/k8s/postgres-db-credentials.secret.example.yaml /tmp/postgres-db-credentials.secret.yaml
cp apps/sandboxed-react-agent/k8s/wg-config.secret.example.yaml /tmp/wg-config.secret.yaml

# Edit placeholders before apply:
# - username/password in postgres-db-credentials.secret.yaml
# - wg0.conf values in wg-config.secret.yaml

kubectl apply -f /tmp/postgres-db-credentials.secret.yaml
kubectl apply -f /tmp/wg-config.secret.yaml
```

2. Install/upgrade backend in sqlite mode first:

```bash
helm upgrade --install sandboxed-react-agent-backend \
  ./apps/sandboxed-react-agent/helm/backend \
  -n alt-default
```

If backend resources already exist from `kubectl apply`, include `--take-ownership`
on the first Helm run.

3. Switch to postgres mode once VPN/DB reachability is verified:

```bash
# Option A: inline toggle
helm upgrade --install sandboxed-react-agent-backend \
  ./apps/sandboxed-react-agent/helm/backend \
  -n alt-default \
  --set database.type=postgres

# Option B: use example postgres+WireGuard overrides file
# (copy it and set your DB/VPN values first)
# cp apps/sandboxed-react-agent/helm/backend/values.postgres-wireguard.example.yaml /tmp/sra-postgres-values.yaml
# helm upgrade --install sandboxed-react-agent-backend \
#   ./apps/sandboxed-react-agent/helm/backend \
#   -n alt-default \
#   -f /tmp/sra-postgres-values.yaml
```

4. Verify backend pod can reach postgres alias over the WireGuard sidecar:

```bash
kubectl -n alt-default exec deploy/sandboxed-react-agent-backend -c backend -- getent hosts postgres-db-svc
kubectl -n alt-default exec deploy/sandboxed-react-agent-backend -c backend -- nc -zv postgres-db-svc 5432
kubectl -n alt-default exec deploy/sandboxed-react-agent-backend -c wg-sidecar -- wg show
```

If you are migrating an already-running backend managed by raw manifests, remove the old backend deployment/service first or use Helm ownership takeover semantics in your environment.

### Legacy manifests

```bash
kubectl apply -f apps/sandboxed-react-agent/k8s/backend-deployment.yaml
kubectl apply -f apps/sandboxed-react-agent/k8s/backend-service.yaml
kubectl apply -f apps/sandboxed-react-agent/k8s/frontend-deployment.yaml
kubectl apply -f apps/sandboxed-react-agent/k8s/frontend-service.yaml
kubectl apply -f apps/sandboxed-react-agent/k8s/ingress.magarathea.yaml
```

## Verify

```bash
kubectl -n alt-default get deploy,svc,ingress | grep sandboxed-react-agent
kubectl -n alt-default rollout status deploy/sandboxed-react-agent-backend
kubectl -n alt-default rollout status deploy/sandboxed-react-agent-frontend
kubectl -n alt-default logs deploy/sandboxed-react-agent-backend --tail=100
```

Open:

- `https://magarathea.ddns.net/sandboxed-react-agent`

Health/state endpoints:

- `https://magarathea.ddns.net/sandboxed-react-agent/api/health`
- `https://magarathea.ddns.net/sandboxed-react-agent/api/state`

For local Docker Compose runs, open the app at `http://localhost:8080`.

## Runtime configuration from UI

The chat UI includes a **Backend Configuration** panel that can update runtime settings
without restarting the container.

Configuration is scoped per authenticated user id. A change in one account does not
affect other users.

Configurable settings include:

- OpenAI model (`model`)
- Tool safety limit per turn (`max_tool_calls_per_turn`)
- Sandbox mode (`local` or `cluster`)
- Sandbox profile (`persistent_workspace` or `transient`)
- Sandbox router/template/namespace and execution limits
- Sandbox execution model (`ephemeral` or `session`)
- Session sandbox idle TTL (`sandbox_session_idle_ttl_seconds`)

When profile is `transient`, tool calls explicitly bypass user workspace provisioning
and run against the configured runtime template without per-user FUSE workspace routing.

When profile is `persistent_workspace`, the selected runtime template is treated as
the base flavor (`small`/`default`/`large`/`pydata`) and resolved to a user-scoped
derived template for that flavor. Configure supported base flavors with
`SANDBOX_WORKSPACE_BASE_TEMPLATE_NAMES` (CSV; first entry is the primary base).
If an optional base flavor is not installed in-cluster, workspace provisioning skips
that flavor and keeps the workspace ready on the primary base template.

The panel calls backend API endpoints:

- `GET /api/config`
- `POST /api/config`
- `GET /api/sandboxes`

Admin operators can also load an Ops Snapshot from Settings, backed by:

- `GET /api/admin/ops/sandbox-index`
- `GET /api/admin/ops/workspace-jobs`
- `GET /api/admin/ops/users/search`
- `GET /api/sandboxes/{lease_id}`
- `POST /api/sandboxes/{lease_id}/release`

Persistence model in SQLite:

- `users` table stores `user_id` and user `tier` (default: `default`).
- `user_configs` stores per-user runtime config values.
- `sessions` remain user-owned and are filtered by `user_id`.

## Kubernetes notes

- The frontend container expects `BACKEND_UPSTREAM` at runtime.
  - In Kubernetes manifests it is set to `sandboxed-react-agent-backend:80`.
  - In Docker Compose it is set to `backend:8000`.
- `sandbox-workspace-admin-ksa` requires namespaced RBAC to create Agent Sandbox claims and user-scoped KSAs.
  - This repo includes `apps/sandboxed-react-agent/k8s/backend-sandbox-rbac.yaml`.
  - `start.sh` applies it automatically.
- `start.sh` can auto-scale the sandbox router deployment (if present).
  - Enabled by default with `SCALE_SANDBOX_ROUTER=1` and `SANDBOX_ROUTER_REPLICAS=1`.
  - Set `SCALE_SANDBOX_ROUTER=0` to skip this step.

## Kubernetes diagnostics

Run the built-in diagnostics script:

```bash
./apps/sandboxed-react-agent/diagnose_k8s_app.sh
```

Optional parameters:

- `NAMESPACE=alt-default` (default)
- `LOG_SINCE=20m` (window for backend timeout/error detection)
- `TIMEOUT_CURL=60` and `TIMEOUT_WAIT_POD=90s`

## API endpoints

- `POST /api/chat`
  - body: `{ "message": "...", "session_id": "optional" }`
- `GET /api/health`
- `GET /api/state`
- `GET /api/config`
- `POST /api/config`
- `POST /api/sessions/{session_id}/reset`
- `GET /api/admin/ops/sandbox-index` (admin-only)
- `GET /api/admin/ops/lease-analytics` (admin-only)
- `GET /api/admin/ops/users/search` (admin-only)

## Teardown

```bash
./apps/sandboxed-react-agent/teardown.sh
```

Optional cleanup of Docker pull secret too:

```bash
./apps/sandboxed-react-agent/teardown.sh --delete-pull-secret
```

## Notes and limitations

- This is an example implementation for rapid iteration.
- Session state is cached in memory and persisted in local SQLite; scaling backend replicas still requires shared storage.
- In `session` sandbox execution mode, tool calls in the same session reuse one sandbox lease until TTL expiry or explicit release.
- Lease cleanup runs periodically in-process via backend reaper; tune with
  `SANDBOX_LEASE_REAPER_ENABLED`,
  `SANDBOX_LEASE_REAPER_INTERVAL_SECONDS`, and
  `SANDBOX_PENDING_LEASE_REAPER_TTL_SECONDS`.
- For backward compatibility, legacy janitor envs
  `SANDBOX_LEASE_JANITOR_ENABLED` and
  `SANDBOX_LEASE_JANITOR_INTERVAL_SECONDS` are still accepted.
- In `local` mode, tool commands run in the backend container and are not isolated like Agent Sandbox.
- Add rate limiting, authz, and prompt/tool guardrails before production usage.
