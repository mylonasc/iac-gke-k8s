# Deploy and Operations Guide

This guide documents the recommended workflow for cluster lifecycle with minimal Terraform provider-ordering issues.

## Prerequisites

- Terraform >= 1.5
- `gcloud`, `kubectl`, and the GKE auth plugin
- Authenticated Google Cloud account with permissions for GKE, IAM, Secret Manager, and Compute

Helper scripts are available under `setup_scripts/pre-gke-deploy/` and `setup_scripts/post-gke-deploy/`.

## Deployment model (two-stage apply)

Why: the Kubernetes provider depends on the cluster endpoint and credentials. Creating cluster and Kubernetes resources in one step is brittle.

1. Phase A: apply GCP infra and cluster resources.
2. Upload secret versions to Secret Manager (if needed).
3. Phase B: apply `module.k8s`.

Canonical references:

- `iac/gke-secure-gpu-cluster/README.md`
- `iac/gke-secure-gpu-cluster/k8s/README.md`

## Scripted deployment (recommended)

From `iac/gke-secure-gpu-cluster`:

```bash
./scripts/deploy_with_secrets.sh --project <project-id> --var-file terraform.v3.tfvars
./scripts/deploy_with_secrets.sh --execute --project <project-id> --var-file terraform.v3.tfvars
```

Optional Agent Sandbox bootstrap:

```bash
./scripts/deploy_with_secrets.sh --execute --project <project-id> --var-file terraform.v3.tfvars --bootstrap-agent-sandbox
```

## Secrets model

- Terraform creates Secret Manager secret containers from `custom_cluster_secrets`.
- Secret values are added as Secret Manager versions (manual or CI), not in Terraform code.
- Optional direct K8s secret creation exists for docker pull auth via `module.k8s` variables.

## Verification after apply

- Cluster credentials:

```bash
gcloud container clusters get-credentials gpu-spot-cluster --region europe-west4-a --project <project-id>
```

- Core checks:

```bash
kubectl get nodes -o wide
kubectl get pods -A
kubectl -n alt-default get sa
```

- Agent Sandbox checks (if enabled):

```bash
kubectl get pods -n agent-sandbox-system
kubectl get sandboxtemplate,sandboxwarmpool -n alt-default
```

## Drift checks

From `iac/gke-secure-gpu-cluster`:

```bash
terraform plan -var-file=terraform.v3.tfvars
terraform plan -refresh-only -var-file=terraform.v3.tfvars
```

Recommended cadence: at least weekly and before any manual `gcloud` or `kubectl` change in managed resources.

## Rollback and safety notes

- Prefer reverting Terraform variable/resource changes and re-applying, instead of manual state edits.
- Avoid deleting/recreating cluster resources unless required.
- If changing Agent Sandbox runtime toggles, follow the documented two-pass flow to avoid partial CRD/runtime states.

## Diagnostics

Use:

- `gke_diagnostics.md` for command-based diagnostics collection.
- `docs/runbooks/` for incident-specific playbooks.
