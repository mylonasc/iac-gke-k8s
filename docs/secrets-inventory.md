# Secrets Inventory

This inventory documents secret containers, Kubernetes secrets, expected keys, producers, and consumers. It intentionally does not include secret values.

## Rules

- Do not commit real secret values, kubeconfigs, WireGuard configs, Docker tokens, or database credentials.
- Prefer checking secret existence and key names over reading decoded values.
- Terraform manages Secret Manager secret containers; secret versions are normally added out-of-band by CI or operators.
- Kubernetes app secrets must exist in the same namespace as the consuming workload unless noted otherwise.

## Google Secret Manager

| Secret | Required | Producer | Consumer | Notes |
|---|---:|---|---|---|
| `dockerhub-ro-pat` | Conditional | Terraform creates container; CI/operator adds versions | Cluster/app image pull workflows | Used when private DockerHub access is needed. |
| `openai-api-key` | Yes for LLM calls | Terraform creates container; CI/operator adds versions | Agent backend/app secret provisioning | The app consumes a Kubernetes secret key with the same runtime value. |

Terraform source:

- `iac/gke-secure-gpu-cluster/secrets.tf`
- `iac/gke-secure-gpu-cluster/variables.tf`

Upload helper:

- `iac/gke-secure-gpu-cluster/scripts/deploy_with_secrets.sh`

Environment variables accepted by the helper:

- `DOCKER_CONFIG_JSON`
- `OPENAI_API_KEY`

## Kubernetes Secrets: `alt-default`

| Secret | Required keys | Required | Producer | Consumer |
|---|---|---:|---|---|
| `sandboxed-react-agent-secrets` | `openai-api-key`, `auth-issuer`, `auth-audience`, `auth-jwks-url`; optional `anon-identity-secret` | Yes | Operator/CI | `sandboxed-react-agent-backend` |
| `dockerhub-regcred` | `.dockerconfigjson` | Yes for private images | Operator/CI | Janet backend/frontend and pydata sandbox template |
| `sandboxed-react-agent-db-credentials` | `username`, `password` | Yes when postgres mode is enabled | Operator/CI | Janet backend |
| `wg-config` | `wg0.conf` | Yes when WireGuard sidecar is enabled | Operator/CI | Janet backend WireGuard sidecar |

Janet Helm source:

- `apps/janet/helm/backend/values.yaml`
- `apps/janet/helm/frontend/values.yaml`
- `apps/janet/helm/backend/templates/deployment.yaml`

Preflight check:

```bash
cd apps/janet
./ops.sh preflight
```

## Workload Identity Principals

| Kubernetes service account | Namespace | Google service account | Purpose |
|---|---|---|---|
| `default-ksa` | `alt-default` | `default-service-account@<project>.iam.gserviceaccount.com` | Default workload identity principal. |
| `sandbox-workspace-admin-ksa` | `alt-default` | `sandbox-workspace-admin@<project>.iam.gserviceaccount.com` | Janet backend workspace provisioning and sandbox management. |

Terraform source:

- `iac/gke-secure-gpu-cluster/identity.tf`
- `iac/gke-secure-gpu-cluster/k8s/main.tf`

## Auth And Authz Inputs

Janet backend auth defaults are configured in `apps/janet/helm/backend/values.yaml`:

- `AUTH_ENABLED=1`
- `AUTH_ISSUER` from `sandboxed-react-agent-secrets/auth-issuer`
- `AUTH_AUDIENCE` from `sandboxed-react-agent-secrets/auth-audience`
- `AUTH_JWKS_URL` from `sandboxed-react-agent-secrets/auth-jwks-url`
- `AUTHZ_POLICY_URL` defaults to `http://cluster-authz-manager-backend.alt-default.svc.cluster.local/api/apps/sandboxed-react-agent/policy/current`

Related setup references:

- `setup_scripts/other/auth/dex/README.md`
- `setup_scripts/other/auth/oauth2-proxy/SetupOAuth2-proxy.md`
- `apps/cluster-authz-manager/README.md`
- `apps/sandboxed-react-agent-authz/README.md`

## Sandbox Router Auth

No router auth secret is currently defined in this repo. The current Janet backend uses `k8s-agent-sandbox==0.2.1`, which sends router routing headers (`X-Sandbox-ID`, `X-Sandbox-Namespace`, `X-Sandbox-Port`) but does not send a `ROUTER_AUTH_TOKEN` bearer/header value.

The current upstream router image may require one of these runtime settings:

- `ROUTER_AUTH_TOKEN`: secure mode, requires compatible client-side token support.
- `ALLOW_UNAUTHENTICATED_ROUTER=true`: compatibility mode for clients that do not send router auth.

If compatibility mode is used, restrict router ingress with a NetworkPolicy so only expected clients, such as `sandboxed-react-agent-backend`, can reach `sandbox-router-svc`.

## Secret Presence Checks

Check Kubernetes secret names without printing values:

```bash
kubectl -n alt-default get secret sandboxed-react-agent-secrets dockerhub-regcred sandboxed-react-agent-db-credentials wg-config
```

Check key names only:

```bash
kubectl -n alt-default get secret sandboxed-react-agent-secrets -o go-template='{{range $k, $_ := .data}}{{printf "%s\n" $k}}{{end}}'
```
