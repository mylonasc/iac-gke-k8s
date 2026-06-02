---
name: janet-app-ops
description: Use when deploying, updating, debugging, scaling, or tearing down the Janet sandboxed React agent app in apps/janet.
---

# Janet App Ops

Use this skill for the main agent platform app in `apps/janet`, including Helm deploys, teardown, image updates, diagnostics, frontend/backend rollout, and app-level Kubernetes resources.

## Canonical Paths

- App root: `apps/janet`
- Operations entrypoint: `apps/janet/ops.sh`
- Backend chart: `apps/janet/helm/backend`
- Frontend chart: `apps/janet/helm/frontend`
- Backend values: `apps/janet/helm/backend/values.yaml`
- Frontend values: `apps/janet/helm/frontend/values.yaml`

## Runtime Defaults

- Namespace: `alt-default`
- Backend release: `sandboxed-react-agent-backend`
- Frontend release: `sandboxed-react-agent-frontend`
- Backend deployment/service: `sandboxed-react-agent-backend`
- Frontend deployment/service: `sandboxed-react-agent-frontend`
- Route: `https://magarathea.ddns.net/sandboxed-react-agent`

## Main Commands

From `apps/janet`:

```bash
./ops.sh deploy
./ops.sh diag
./ops.sh versions
./ops.sh scale --stop
./ops.sh scale --start
./ops.sh teardown
./ops.sh teardown --delete-pull-secret
./ops.sh teardown --purge-legacy-manifests
```

## Required Platform Dependencies

- Agent Sandbox controller/extensions installed.
- Router reachable at `sandbox-router-svc.alt-default.svc.cluster.local:8080` for cluster-mode tool execution and sandbox file operations.
- Runtime templates exist in `alt-default`.
- `sandbox-workspace-admin-ksa` exists and is annotated for Workload Identity.
- Backend chart RBAC can create/read/delete Agent Sandbox claims and related resources.

`SandboxClaim Ready=True` with `sandbox-router-deployment Ready=False` means sandbox lifecycle is working but Janet cluster-mode tool execution is not.

## Required App Secrets

The backend values expect these secrets in `alt-default`:

- `sandboxed-react-agent-secrets`
- `dockerhub-regcred` for private images
- `sandboxed-react-agent-db-credentials` for postgres mode
- `wg-config` when WireGuard sidecar is enabled

Create OpenAI/auth secret shape as needed:

```bash
kubectl -n alt-default create secret generic sandboxed-react-agent-secrets \
  --from-literal=openai-api-key="$OPENAI_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Verification

```bash
kubectl -n alt-default get deploy,svc,ingress | grep sandboxed-react-agent
kubectl -n alt-default rollout status deploy/sandboxed-react-agent-backend
kubectl -n alt-default rollout status deploy/sandboxed-react-agent-frontend
kubectl -n alt-default logs deploy/sandboxed-react-agent-backend --tail=100
```

Health endpoints:

- `https://magarathea.ddns.net/sandboxed-react-agent/api/health`
- `https://magarathea.ddns.net/sandboxed-react-agent/api/state`

## Safety Notes

- Prefer `./ops.sh` over legacy raw manifests in `apps/janet/k8s`.
- If resources exist from raw manifests, use Helm ownership takeover semantics or remove old resources first.
- `./ops.sh teardown` deletes `sandboxed-react-agent-secrets`; preserve values externally if needed.
- The app may scale the sandbox router by default unless `SCALE_SANDBOX_ROUTER=0` is set.

## References

- `apps/janet/README.md`
- `apps/janet/ops.sh`
- `apps/janet/scripts/start.sh`
- `apps/janet/scripts/teardown.sh`
- `apps/janet/scripts/diagnose_k8s_app.sh`
- `apps/janet/helm/backend/values.yaml`
- `apps/janet/helm/frontend/values.yaml`
