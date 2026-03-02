# iac-gke-k8s

Infrastructure-as-code for a GKE Standard cluster with mixed node pools (GPU and non-GPU), gVisor-isolated workloads, Secret Manager integration, and Terraform-managed Agent Sandbox.

## Cluster Features

| Area | Implemented | Terraform resource/module | Notes |
|---|---|---|---|
| GKE control plane | Yes | `google_container_cluster.primary` | Standard (not Autopilot), Workload Identity enabled |
| Baseline node pool | Yes | `google_container_node_pool.primary_nodes` | Stable pool for system workloads |
| GPU spot pool A | Yes | `google_container_node_pool.gpu_spot_pool_np_a` | L4 on `g2-standard-4` |
| GPU spot pool B | Yes | `google_container_node_pool.gpu_spot_pool_np_b` | T4 on `n1-standard-4` |
| General-purpose pool | Yes | `google_container_node_pool.general_purpose_pool` | Tainted/labelled for app workloads |
| General-purpose small pool | Yes | `google_container_node_pool.general_purpose_spot_pool_small` | Cost-focused spot pool |
| gVisor isolated pool | Yes | `google_container_node_pool.gvisor_pool` | `sandbox_type = gvisor`, dedicated labels/taints |
| Secret Manager integration | Yes | root + `module.k8s` | Secret containers in Terraform, versions from CI/manual |
| Remote Terraform state | Yes | `iac/gke-secure-gpu-cluster/europe_backend.tf` | GCS backend supported and configured |
| Agent Sandbox controller/CRDs | Yes | `module.k8s` (`k8s/agent_sandbox.tf`) | Terraform-managed from upstream release manifests |
| Agent Sandbox runtime objects | Yes | `module.k8s` (`k8s/agent_sandbox.tf`) | `SandboxTemplate`, `SandboxWarmPool`, router `Service/Deployment` |

## Main Entry Points

- Primary deployment: `iac/gke-secure-gpu-cluster`
- Cluster-level docs: `iac/gke-secure-gpu-cluster/README.md`
- K8s module deployment flow: `iac/gke-secure-gpu-cluster/k8s/README.md`
- Agent Sandbox usage notes: `iac/gke-secure-gpu-cluster/k8s/agent-sandbox.md`

## Quick Setup Notes

Check GPU availability by region:

```bash
gcloud compute accelerator-types list --filter="name=nvidia-tesla-t4"
```

You will usually need quota adjustments before first GPU provisioning (see `required_manual_adjustments.md`).

Common GPU/machine-type mapping:

| GPU vRAM | GPU | Machine family example |
|---|---|---|
| 16GB | `nvidia-tesla-t4` | [N1](https://cloud.google.com/compute/docs/gpus#n1-gpus), for example `n1-standard-4` |
| 24GB | `nvidia-tesla-l4` | [G2](https://cloud.google.com/compute/docs/accelerator-optimized-machines#g2-vms), for example `g2-standard-4` |

Get cluster credentials:

```bash
gcloud container clusters get-credentials gpu-spot-cluster --region europe-west4-a --project <project-id>
```
