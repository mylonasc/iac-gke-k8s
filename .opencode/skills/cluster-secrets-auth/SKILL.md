---
name: cluster-secrets-auth
description: Use when working with Secret Manager, Kubernetes secrets, Docker pull secrets, Workload Identity, OAuth2, Dex, JWT auth, or authz policy.
---

# Cluster Secrets And Auth

Use this skill for secrets, auth, Workload Identity, Secret Manager, Kubernetes secret material, Docker pull credentials, Dex, oauth2-proxy, JWT, and authz policy wiring.

## Terraform Secrets Model

Terraform creates Secret Manager containers in `iac/gke-secure-gpu-cluster/secrets.tf` from `custom_cluster_secrets`:

- `dockerhub-ro-pat`
- `openai-api-key`

Secret values are added as Secret Manager versions out-of-band, not committed to Terraform code. The deploy helper can upload versions from environment variables:

- `DOCKER_CONFIG_JSON`
- `OPENAI_API_KEY`

## Workload Identity

Google service accounts:

- `default-service-account`
- `sandbox-workspace-admin`

Kubernetes service accounts in `alt-default`:

- `default-ksa`
- `sandbox-workspace-admin-ksa`

The backend admin GSA has elevated permissions for lazy workspace provisioning, including service account, storage, and Secret Manager admin permissions.

## App-Level Kubernetes Secrets

Janet backend/frontend expect these Kubernetes secrets in `alt-default`:

- `sandboxed-react-agent-secrets`
- `dockerhub-regcred`
- `sandboxed-react-agent-db-credentials`
- `wg-config`

`sandboxed-react-agent-secrets` may include:

- `openai-api-key`
- `auth-issuer`
- `auth-audience`
- `auth-jwks-url`
- `anon-identity-secret`

Private images require `dockerhub-regcred` in the same namespace as the pod.

## Common Commands

Create/update Janet OpenAI secret:

```bash
kubectl -n alt-default create secret generic sandboxed-react-agent-secrets \
  --from-literal=openai-api-key="$OPENAI_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Copy Docker pull secret from `default` to `alt-default`:

```bash
kubectl get secret dockerhub-regcred -n default -o yaml \
  | sed 's/namespace: default/namespace: alt-default/' \
  | kubectl apply -f -
```

Check secret presence without printing values:

```bash
kubectl -n alt-default get secret sandboxed-react-agent-secrets dockerhub-regcred sandboxed-react-agent-db-credentials wg-config
```

## Auth Components

- Dex helper files: `setup_scripts/other/auth/dex`
- oauth2-proxy helper files: `setup_scripts/other/auth/oauth2-proxy`
- Janet auth values: `apps/janet/helm/backend/values.yaml`
- Authz control plane references: `apps/cluster-authz-manager` and `apps/sandboxed-react-agent-authz`

## Safety Notes

- Never commit real secrets, kubeconfigs, tokens, WireGuard configs, or DB credentials.
- Avoid passing secret payloads through Terraform variables unless the user accepts that they may enter state.
- Prefer checking secret existence and key names over reading decoded values.
- Redact secret values from logs and command output.

## References

- `iac/gke-secure-gpu-cluster/secrets.tf`
- `iac/gke-secure-gpu-cluster/identity.tf`
- `iac/gke-secure-gpu-cluster/scripts/deploy_with_secrets.sh`
- `apps/janet/helm/backend/values.yaml`
- `apps/janet/README.md`
- `setup_scripts/other/auth/dex/README.md`
- `setup_scripts/other/auth/oauth2-proxy/SetupOAuth2-proxy.md`
