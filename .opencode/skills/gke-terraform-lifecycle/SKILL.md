---
name: gke-terraform-lifecycle
description: Use when managing Terraform, GKE cluster lifecycle, two-stage apply, terraform destroy, remote state, node pools, or files under iac/gke-secure-gpu-cluster.
---

# GKE Terraform Lifecycle

Use this skill for infrastructure work in `iac/gke-secure-gpu-cluster`, especially cluster creation, teardown, planning, state, node pools, and Terraform/provider ordering.

## Canonical Paths

- Terraform root: `iac/gke-secure-gpu-cluster`
- Active var file: `iac/gke-secure-gpu-cluster/terraform.v3.tfvars`
- Backend config: `iac/gke-secure-gpu-cluster/europe_backend.tf`
- K8s module: `iac/gke-secure-gpu-cluster/k8s`
- Deploy helper: `iac/gke-secure-gpu-cluster/scripts/deploy_with_secrets.sh`

## Current Defaults

- Project: `gke-gpu-project-473410`
- Cluster: `gpu-spot-cluster`
- Location variable is named `region`, but the value is zonal: `europe-west4-a`
- Runtime namespace: `alt-default`
- Remote state: GCS bucket `gcp-ops-data-tfstate-europe`, prefix `terraform/state`

## Deployment Model

This repo intentionally uses a two-stage apply to avoid Kubernetes provider initialization before the GKE API endpoint and credentials exist.

1. Phase A creates GCP services, Secret Manager containers, service accounts, IAM, the cluster, and node pools.
2. Secret versions may be uploaded to Secret Manager out-of-band.
3. Phase B applies `module.k8s` against the reachable cluster.

For fresh Agent Sandbox clusters, run `module.k8s` in two passes so CRDs exist before runtime custom resources:

```bash
terraform apply -target=module.k8s -var-file=terraform.v3.tfvars -var='enable_agent_sandbox_runtime=false'
terraform apply -target=module.k8s -var-file=terraform.v3.tfvars -var='enable_agent_sandbox_runtime=true'
```

## Preferred Commands

From `iac/gke-secure-gpu-cluster`:

```bash
terraform init
terraform plan -var-file=terraform.v3.tfvars
./scripts/deploy_with_secrets.sh --project gke-gpu-project-473410 --var-file terraform.v3.tfvars
./scripts/deploy_with_secrets.sh --execute --project gke-gpu-project-473410 --var-file terraform.v3.tfvars --bootstrap-agent-sandbox
```

Get credentials after Phase A:

```bash
gcloud container clusters get-credentials gpu-spot-cluster --region europe-west4-a --project gke-gpu-project-473410
```

Verify:

```bash
kubectl get nodes -o wide
kubectl get pods -A
kubectl -n alt-default get sa
kubectl get pods -n agent-sandbox-system
kubectl -n alt-default get sandboxtemplate,sandboxwarmpool
```

## Teardown Order

Do not destroy the cluster before destroying Terraform-managed Kubernetes resources.

1. Tear down apps, for example `apps/janet/ops.sh teardown`.
2. Destroy Kubernetes module while the API server still exists:

```bash
terraform destroy -target=module.k8s -var-file=terraform.v3.tfvars
```

3. Destroy remaining GCP infrastructure:

```bash
terraform destroy -var-file=terraform.v3.tfvars
```

## Safety Notes

- Check `cluster_deletion_protection` before destroy.
- Bucket contents may block destroy for `google_storage_bucket.sandbox_workspace`.
- Secret Manager secret versions are uploaded out-of-band; Terraform manages containers.
- Google APIs use `disable_on_destroy = false` in several resources and may remain enabled.
- The Terraform state backend bucket is not created or destroyed by this stack.
- Never change Terraform state manually unless the user explicitly asks and the state impact is understood.

## References

- `README.md`
- `docs/deploy-and-operations.md`
- `docs/inventory.md`
- `iac/gke-secure-gpu-cluster/README.md`
- `iac/gke-secure-gpu-cluster/k8s/README.md`
- `iac/gke-secure-gpu-cluster/main.tf`
- `iac/gke-secure-gpu-cluster/variables.tf`
- `iac/gke-secure-gpu-cluster/scripts/deploy_with_secrets.sh`
