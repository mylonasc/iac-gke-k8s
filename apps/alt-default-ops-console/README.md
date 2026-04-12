# alt-default Ops Console

FastAPI app to inspect and control selected resources in namespace `alt-default`.

It provides:

- simple web view for deployments, pods, and sandbox claims
- template-safe dropdowns for sandbox claim and warm-pool actions
- pod filtering by node and phase/status
- node inventory with ready count and instance-type breakdown
- resource snapshot for running nodes and PVCs
- hourly cost estimate for nodes, PVC capacity, and GKE cluster fee
- workspace/session lease health and historical lease analytics (via sandboxed-react-agent admin API)
- richer sandbox claim details (creation time, age, status, ownership mapping to lease/session/user)
- lease event filtering (status/user/session) and CSV export from the admin UI
- lease event pagination + text search and filtered-count visibility
- top-level state summary (sandbox phase counts + running node count)
- collapsible admin sections for token inspection and lease health
- user-centric warm-pool controls with backend user search
- API endpoints to scale managed deployments up/down
- API endpoints to create/delete Agent Sandbox claims
- API endpoints to create/scale Agent Sandbox warm pools
- API endpoint to search sandboxed-react-agent users for warm-pool targeting
- template-oriented warm-pool profile API for multi-template control panels
- JWT validation (signature + issuer + audience + expiry) before allowing access

## What it controls

- Deployments (allowlist by env var):
  - `sandboxed-react-agent-backend`
  - `sandboxed-react-agent-frontend`
  - `sandbox-router-deployment`
- Agent Sandbox resources in `alt-default`:
  - `SandboxClaim` create/delete
  - `SandboxWarmPool` create/scale/read
  - `Sandbox`, `SandboxTemplate` read/list

## Files

- `backend/app/main.py`: FastAPI controller + minimal UI + JWT auth checks
- `backend/Dockerfile`: image build
- `docker-compose.yml`: local stack for realistic Google OAuth flow
- `k8s/rbac.yaml`: ServiceAccount + least-privilege Role/RoleBinding
- `k8s/configmap.yaml`: runtime settings (JWT and namespace)
- `k8s/deployment.yaml`: app deployment
- `k8s/service.yaml`: ClusterIP service
- `k8s/ingress.magarathea.yaml`: ingress route `/alt-default-ops`

## Build image

From repo root:

```bash
docker build -t docker.io/<your-dockerhub-user>/alt-default-ops-console:0.1.0 ./apps/alt-default-ops-console/backend
docker push docker.io/<your-dockerhub-user>/alt-default-ops-console:0.1.0
```

Then update `apps/alt-default-ops-console/k8s/deployment.yaml` image field.

Or use the helper script (same pattern as `sandboxed-react-agent`):

```bash
./apps/alt-default-ops-console/push_images.sh
```

## Configure JWT checks

Edit `apps/alt-default-ops-console/k8s/configmap.yaml`:

- `JWT_JWKS_URL`: JWKS endpoint for Dex-issued tokens
- `JWT_ISSUERS`: comma-separated allowed issuers for Dex-issued tokens
- `JWT_AUDIENCE`: required audience for Dex-issued tokens (for this cluster: `oauth2-proxy`)
- `JWT_EMAIL_ALLOWLIST`: comma-separated email allowlist (recommended)
- `JWT_REQUIRED_GROUP`: optional required group claim
- `APP_BASE_PATH`: external ingress path prefix (set to `/alt-default-ops` in cluster, empty locally)
- `SRA_ADMIN_ENABLED`: enable integration with sandboxed-react-agent admin endpoints (`1`/`0`)
- `SRA_ADMIN_API_BASE_URL`: internal base URL for sandboxed-react-agent backend
- `SRA_ADMIN_API_TIMEOUT_SECONDS`: timeout per request
- `SRA_ADMIN_ANALYTICS_DAYS`: history window for lease analytics
- `SRA_ADMIN_RECENT_LIMIT`: max recent lease events shown

If `JWT_EMAIL_ALLOWLIST` and `JWT_REQUIRED_GROUP` are both empty, any valid JWT for issuer/audience is accepted.
For strict single-user access, set `JWT_EMAIL_ALLOWLIST` to exactly your Google account email.

The app accepts two token sources:

- Dex tokens forwarded by ingress/oauth2-proxy, verified with `JWT_JWKS_URL`, `JWT_ISSUERS`, and `JWT_AUDIENCE`
- Google ID tokens from the built-in `Login with Google` flow, verified against Google's JWKS using `OAUTH_CLIENT_ID` as the expected audience

## Run locally (UI + auth flow)

This local setup uses real Google OAuth authorization-code flow and validates the
returned ID token (JWKS signature, issuer, audience, expiry, and email allowlist).

Prepare local env file:

```bash
cp apps/alt-default-ops-console/.env.local.example apps/alt-default-ops-console/.env.local
```

Edit `apps/alt-default-ops-console/.env.local` and set:

- `OAUTH_CLIENT_ID`
- `OAUTH_CLIENT_SECRET`

Start:

```bash
./apps/alt-default-ops-console/run-local.sh
```

Open:

- `http://localhost`
- (also exposed on `http://localhost:8080`)

In the UI:

1. Click `Login with Google`.
2. Complete Google sign-in and consent.
3. Google redirects to `http://localhost/auth2/callback`.
4. API calls are allowed only when the validated token email is `mylonas.charilaos@gmail.com`.

Stop:

```bash
./apps/alt-default-ops-console/stop-local.sh
```

Note: local mode still runs with `MOCK_CLUSTER=1`, so resource lists/scaling are simulated
in-memory while you test the real auth flow.

## Deploy

```bash
./apps/alt-default-ops-console/app_up.sh
```

Open:

- `https://magarathea.ddns.net/alt-default-ops`

## API examples

Scale deployment:

```bash
curl -X POST \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"replicas":0}' \
  "https://magarathea.ddns.net/alt-default-ops/api/deployments/sandboxed-react-agent-backend/scale"
```

Create sandbox claim:

```bash
curl -X POST \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"template_name":"python-runtime-template"}' \
  "https://magarathea.ddns.net/alt-default-ops/api/sandboxclaims"
```

Delete sandbox claim:

```bash
curl -X DELETE \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://magarathea.ddns.net/alt-default-ops/api/sandboxclaims/<claim-name>"
```

Upsert warm pool:

```bash
curl -X POST \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"warm_pool_name":"python-sandbox-warmpool","template_name":"python-runtime-template","replicas":3}' \
  "https://magarathea.ddns.net/alt-default-ops/api/sandboxwarmpools"
```

Scale warm pool:

```bash
curl -X POST \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"replicas":5}' \
  "https://magarathea.ddns.net/alt-default-ops/api/sandboxwarmpools/python-sandbox-warmpool/scale"
```

Warm pool profiles (template-oriented control data):

```bash
curl -X GET \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://magarathea.ddns.net/alt-default-ops/api/sandboxwarmpool-profiles"
```

Search users (for user-centric warm-pool controls):

```bash
curl -X GET \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://magarathea.ddns.net/alt-default-ops/api/users/search?q=user&limit=20"
```

## Cost estimate notes

- `/api/overview` includes a lightweight hourly estimate derived from live node and PVC inventory.
- The estimate currently uses `europe-west4` list prices and includes:
  - Compute Engine E2 core and RAM rates (on-demand + spot)
  - Persistent Disk class rates (`standard`, `balanced`)
  - GKE cluster management fee ($0.10/hour)
- Source references:
  - https://cloud.google.com/compute/all-pricing
  - https://cloud.google.com/kubernetes-engine/pricing

## Remove

```bash
./apps/alt-default-ops-console/app_down.sh
```
