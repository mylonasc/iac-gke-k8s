## About

Terraform deployment for a GKE Standard cluster with mixed node pools, Workload Identity, Secret Manager integration, and Terraform-managed Kubernetes resources (including Agent Sandbox).

Related project docs:

- `docs/README.md`
- `docs/deploy-and-operations.md`
- `docs/inventory.md`

## Implemented Features

| Feature | Status | Where configured |
|---|---|---|
| GKE Standard cluster | Enabled | `main.tf` (`google_container_cluster.primary`) |
| GPU node pool A (spot) | Enabled | `main.tf` (`google_container_node_pool.gpu_spot_pool_np_a`) |
| GPU node pool B (spot) | Enabled | `main.tf` (`google_container_node_pool.gpu_spot_pool_np_b`) |
| General-purpose pool | Enabled | `main.tf` (`google_container_node_pool.general_purpose_pool`) |
| General-purpose small spot pool | Enabled | `main.tf` (`google_container_node_pool.general_purpose_spot_pool_small`) |
| Isolated gVisor node pool | Enabled | `main.tf` (`google_container_node_pool.gvisor_pool`) |
| Secret Manager containers | Enabled | `secrets.tf` + targeted Phase A |
| Kubernetes namespace/service account/secrets | Enabled | `module "k8s"` |
| Agent Sandbox controller and CRDs | Enabled | `k8s/agent_sandbox.tf` |
| Agent Sandbox runtime (template/pool/router) | Enabled | `k8s/agent_sandbox.tf` with `enable_agent_sandbox_runtime=true` |
| Remote Terraform backend (GCS) | Enabled | `europe_backend.tf` |

## Backend State

State is configured to use GCS backend in `europe_backend.tf`.

- Reinitialize when backend settings change:

```bash
terraform init -reconfigure
```

- If you need a different bucket/prefix, edit `europe_backend.tf` and re-run init.
- If you need to bootstrap a backend bucket, use `iac/backend_bootstrap/gcp_make_terraform_backend_interactive.py`.

## Two-Stage Apply Pattern

This repository uses a two-stage apply to avoid Kubernetes provider ordering issues:

1. **Phase A**: create/refresh project services, secrets containers, service account, cluster, and node pools.
2. Upload secret versions to Secret Manager (from CI or manually).
3. **Phase B**: apply `module.k8s`.

Use the automation helper:

```bash
./scripts/deploy_with_secrets.sh --project <project-id> --var-file terraform.v3.tfvars
```

To execute (not dry-run):

```bash
./scripts/deploy_with_secrets.sh --execute --project <project-id> --var-file terraform.v3.tfvars
```

## Agent Sandbox (Terraform-managed)

Agent Sandbox is managed by Terraform in `module.k8s`.

For fresh bootstrap of runtime CRs, use two-pass rollout:

1. Controller + CRDs only:

```bash
terraform apply -target=module.k8s -var='enable_agent_sandbox_runtime=false' -var-file=terraform.v3.tfvars
```

2. Runtime resources:

```bash
terraform apply -target=module.k8s -var='enable_agent_sandbox_runtime=true' -var-file=terraform.v3.tfvars
```

Script shortcut:

```bash
./scripts/deploy_with_secrets.sh --execute --project <project-id> --var-file terraform.v3.tfvars --bootstrap-agent-sandbox
```

Notes:
- On clusters where runtime objects already exist, pass 1 can temporarily remove runtime objects before pass 2 recreates them.
- After pass 2, `terraform plan -target=module.k8s -var='enable_agent_sandbox_runtime=true'` should converge with no changes.
- To keep Agent Sandbox runtime installed but idle at zero gVisor nodes, set:
  - `enable_agent_sandbox_runtime = true`
  - `agent_sandbox_warm_pool_replicas = 0`
  - `agent_sandbox_router_replicas = 0`

Python client example:

- `scripts/agent_sandbox_claim_client.py`

## gVisor-Isolated Workloads

For details on scheduling workloads onto the isolated sandbox node pool, see:

- `k8s/gvisor-isolated-nodes.md`
