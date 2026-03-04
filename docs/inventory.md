# Deployed Inventory

This inventory reflects resources defined in Terraform and key operational artifacts in this repository.

## Terraform root module

Path: `iac/gke-secure-gpu-cluster`

| Area | Resource(s) | Purpose | Managed by |
|---|---|---|---|
| Cluster | `google_container_cluster.primary` | GKE Standard control plane | Terraform |
| Primary pool | `google_container_node_pool.primary_nodes` | Stable baseline capacity | Terraform |
| GPU spot A | `google_container_node_pool.gpu_spot_pool_np_a` | L4 spot workloads | Terraform |
| GPU spot B | `google_container_node_pool.gpu_spot_pool_np_b` | T4 spot workloads | Terraform |
| General pool | `google_container_node_pool.general_purpose_pool` | Standard application workloads | Terraform |
| General small spot | `google_container_node_pool.general_purpose_spot_pool_small` | Cost-focused app capacity | Terraform |
| gVisor pool | `google_container_node_pool.gvisor_pool` | Isolated sandbox workloads | Terraform |
| Secret Manager API | `google_project_service.secretmanager` | Enables Secret Manager integration | Terraform |
| Secret containers | `google_secret_manager_secret.secrets` | Secret containers for runtime values | Terraform |
| GSA | `google_service_account.default_gsa` | Workload Identity principal for cluster workloads | Terraform |
| KSA->GSA IAM | `google_service_account_iam_member.workload_identity_user` | K8s service account impersonation of GSA | Terraform |
| Secret IAM | `google_secret_manager_secret_iam_member.secret_accessor` | GSA secret accessor rights | Terraform |

## Terraform module: Kubernetes resources

Path: `iac/gke-secure-gpu-cluster/k8s`

| Area | Resource(s) | Purpose | Managed by |
|---|---|---|---|
| Namespace | `kubernetes_namespace.app` | Runtime namespace (`alt-default` by default) | Terraform (`module.k8s`) |
| KSA | `kubernetes_service_account.default_ksa` | Workload Identity mapped KSA | Terraform (`module.k8s`) |
| Docker pull secret | `kubernetes_secret.docker_registry_secret` (optional) | Registry auth secret when enabled | Terraform (`module.k8s`) |
| Agent Sandbox install | `kubernetes_manifest.agent_sandbox_install` | Controller and core components | Terraform (`module.k8s`) |
| Agent Sandbox extensions | `kubernetes_manifest.agent_sandbox_extensions` | CRDs and extension components | Terraform (`module.k8s`) |
| Agent Sandbox runtime | `kubernetes_manifest.agent_sandbox_*` runtime resources | Sandbox template, warm pool, router | Terraform (`module.k8s`) |

## State and configuration artifacts

| Item | Location | Notes |
|---|---|---|
| Remote backend config | `iac/gke-secure-gpu-cluster/europe_backend.tf` | GCS backend bucket and prefix |
| Variable defaults | `iac/gke-secure-gpu-cluster/variables.tf` | Shared project/cluster/node pool settings |
| Active var file | `iac/gke-secure-gpu-cluster/terraform.v3.tfvars` | Current deployment values |
| Outputs | `iac/gke-secure-gpu-cluster/outputs.tf` | Endpoint and credential command |

## Operational scripts

| Script | Path | Purpose |
|---|---|---|
| Deploy helper | `iac/gke-secure-gpu-cluster/scripts/deploy_with_secrets.sh` | Two-stage apply + optional secret version uploads |
| Cluster inspection | `inspect_cluster.sh` | Read-only operational snapshot |
| Taint inspection | `iac/gke-secure-gpu-cluster/inspect_taints.sh` | Node taint verification |

## External integrations

- Google Cloud Secret Manager (secrets containers managed by Terraform, versions uploaded out-of-band).
- GCR/Artifact/Docker registry pull auth (optional K8s secret creation path).
- Optional DNS and OAuth helper manifests under `setup_scripts/other/`.
