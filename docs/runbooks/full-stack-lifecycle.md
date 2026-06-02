# Full Stack Lifecycle Runbook

This is the canonical end-to-end lifecycle for reproducing and tearing down the GKE-hosted agent platform.

## Scope

This runbook covers:

- Terraform-managed GCP and GKE infrastructure in `iac/gke-secure-gpu-cluster`.
- Terraform-managed Kubernetes platform resources in `module.k8s`.
- Agent Sandbox controller, CRDs, templates, warm pool, and router.
- Janet app deployment from `apps/janet` through Helm.

It does not include real secret values, DNS registrar changes, or manual quota request approval.

## Source Of Truth

| Area | Source |
|---|---|
| GCP/GKE infrastructure | `iac/gke-secure-gpu-cluster` |
| Terraform vars | `iac/gke-secure-gpu-cluster/terraform.v3.tfvars` |
| Terraform backend | `iac/gke-secure-gpu-cluster/europe_backend.tf` |
| Kubernetes platform module | `iac/gke-secure-gpu-cluster/k8s` |
| Agent Sandbox Terraform | `iac/gke-secure-gpu-cluster/k8s/agent_sandbox.tf` |
| Janet app operations | `apps/janet/ops.sh` |
| Janet Helm charts | `apps/janet/helm/backend`, `apps/janet/helm/frontend` |
| Secret inventory | `docs/secrets-inventory.md` |

## Defaults

- Project: `gke-gpu-project-473410`
- Cluster: `gpu-spot-cluster`
- Location: `europe-west4-a`
- Namespace: `alt-default`
- App route: `https://magarathea.ddns.net/sandboxed-react-agent`

## Prerequisites

1. Authenticate to Google Cloud:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project gke-gpu-project-473410
```

2. Confirm local tools:

```bash
terraform version
gcloud version
kubectl version --client
helm version
```

3. Confirm access to the Terraform state bucket in `europe_backend.tf`.

4. Confirm GPU quota and accelerator availability before provisioning GPU pools:

```bash
gcloud compute accelerator-types list --filter="name:nvidia"
```

See `required_manual_adjustments.md` for quota notes.

## Deploy Infrastructure

From the Terraform root:

```bash
cd iac/gke-secure-gpu-cluster
terraform init
```

Preview the scripted two-stage deployment:

```bash
./scripts/deploy_with_secrets.sh --project gke-gpu-project-473410 --var-file terraform.v3.tfvars
```

Execute the deployment:

```bash
./scripts/deploy_with_secrets.sh \
  --execute \
  --project gke-gpu-project-473410 \
  --var-file terraform.v3.tfvars \
  --bootstrap-agent-sandbox
```

The helper performs:

1. Phase A targeted Terraform apply for APIs, service accounts, IAM, Secret Manager containers, cluster, and node pools.
2. Cluster credential refresh.
3. Optional Secret Manager version uploads from environment variables.
4. Phase B Terraform apply for `module.k8s`.
5. Optional two-pass Agent Sandbox bootstrap.

## Manual Agent Sandbox Bootstrap

For fresh clusters, CRDs must exist before runtime custom resources.

```bash
cd iac/gke-secure-gpu-cluster
terraform apply -target=module.k8s -var-file=terraform.v3.tfvars -var='enable_agent_sandbox_runtime=false'
terraform apply -target=module.k8s -var-file=terraform.v3.tfvars -var='enable_agent_sandbox_runtime=true'
```

## Verify Infrastructure

```bash
gcloud container clusters get-credentials gpu-spot-cluster --region europe-west4-a --project gke-gpu-project-473410
kubectl get nodes -o wide
kubectl get pods -A
kubectl -n alt-default get sa
kubectl get pods -n agent-sandbox-system
kubectl -n alt-default get sandboxtemplate,sandboxwarmpool
kubectl -n alt-default get deploy,svc | grep sandbox-router
```

Agent Sandbox lifecycle and execution should be checked separately:

```bash
# Lifecycle: Kubernetes API -> SandboxClaim -> Sandbox -> runtime pod/service
kubectl -n alt-default get sandboxclaim,sandbox
kubectl -n alt-default get pods -l sandbox

# Execution: backend/client -> sandbox-router-svc -> concrete sandbox runtime
kubectl -n alt-default rollout status deploy/sandbox-router-deployment
kubectl -n alt-default get endpoints sandbox-router-svc
```

A ready `SandboxClaim` with an unavailable router means sandbox creation works, but Janet cluster-mode tools such as `sandbox_exec_python`, `sandbox_exec_shell`, and sandbox file operations will fail.

## Prepare App Secrets

Use `docs/secrets-inventory.md` as the source of truth. At minimum, Janet expects these Kubernetes secrets in `alt-default`:

- `sandboxed-react-agent-secrets`
- `dockerhub-regcred`
- `sandboxed-react-agent-db-credentials`
- `wg-config`

Run the preflight check before deploying Janet:

```bash
cd apps/janet
./ops.sh preflight
```

## Deploy Janet

```bash
cd apps/janet
./ops.sh deploy
```

Verify:

```bash
kubectl -n alt-default get deploy,svc,ingress | grep sandboxed-react-agent
kubectl -n alt-default rollout status deploy/sandboxed-react-agent-backend
kubectl -n alt-default rollout status deploy/sandboxed-react-agent-frontend
kubectl -n alt-default logs deploy/sandboxed-react-agent-backend --tail=100
```

Health endpoints:

- `https://magarathea.ddns.net/sandboxed-react-agent/api/health`
- `https://magarathea.ddns.net/sandboxed-react-agent/api/state`

## Day-2 Operations

From `apps/janet`:

```bash
./ops.sh diag
./ops.sh versions
./ops.sh scale --stop
./ops.sh scale --start
```

From `iac/gke-secure-gpu-cluster`:

```bash
terraform plan -var-file=terraform.v3.tfvars
terraform plan -refresh-only -var-file=terraform.v3.tfvars
```

## Tear Down Janet Only

```bash
cd apps/janet
./ops.sh teardown
```

Optional cleanup:

```bash
./ops.sh teardown --delete-pull-secret --purge-legacy-manifests
```

This does not destroy the GKE cluster.

## Tear Down Infrastructure

Destroy app workloads before destroying cluster resources.

```bash
cd apps/janet
./ops.sh teardown --delete-pull-secret --purge-legacy-manifests
```

Destroy Terraform-managed Kubernetes resources while the API server still exists:

```bash
cd ../../iac/gke-secure-gpu-cluster
terraform destroy -target=module.k8s -var-file=terraform.v3.tfvars
```

Destroy remaining GCP infrastructure:

```bash
terraform destroy -var-file=terraform.v3.tfvars
```

## Teardown Caveats

- `cluster_deletion_protection` must be `false` for cluster deletion.
- The sandbox workspace bucket may block destroy if it contains objects.
- Secret Manager versions are out-of-band and may need separate review.
- Several Google APIs use `disable_on_destroy = false` and may remain enabled.
- The Terraform state backend bucket is not destroyed by this stack.

## Troubleshooting References

- `docs/runbooks/cluster-api-unreachable.md`
- `docs/runbooks/secret-access-failures.md`
- `docs/runbooks/gpu-pods-pending.md`
- `docs/deploy-and-operations.md`
- `apps/janet/README.md`
