---
name: gpu-nodepool-ops
description: Use when handling GPU quota, GPU node pools, taints, tolerations, NVIDIA drivers, GPU workloads, vLLM, or LiteLLM.
---

# GPU Nodepool Ops

Use this skill for GPU pool configuration, quota checks, spot scheduling, taints/tolerations, NVIDIA driver issues, and GPU workloads such as vLLM or LiteLLM.

## Terraform GPU Pools

Defined in `iac/gke-secure-gpu-cluster/main.tf`:

- `google_container_node_pool.gpu_spot_pool_np_a`
- `google_container_node_pool.gpu_spot_pool_np_b`

Active values in `terraform.v3.tfvars`:

- Pool A GPU: `nvidia-l4`
- Pool A machine: `g2-standard-4`
- Pool B GPU: `nvidia-tesla-t4`
- Pool B machine: `n1-standard-4`
- GPU count: `1`

## Scheduling And Taints

GPU spot pools are tainted with:

- `cloud.google.com/gke-spot=true:NoSchedule`
- `gpu-type=<gpu-type>:NoSchedule`

GKE also adds GPU-related taints/allocatable resources such as `nvidia.com/gpu`.

Workloads must have matching resource requests and tolerations.

## Quota And Availability

Check accelerator availability:

```bash
gcloud compute accelerator-types list --filter="name:nvidia"
```

Before first GPU provisioning, check quota notes in `required_manual_adjustments.md`. Search quotas for:

- `compute.googleapis.com/gpus_all_regions`
- regional GPU metrics for the selected location

## Useful Checks

```bash
kubectl get nodes -L cloud.google.com/gke-nodepool
kubectl describe nodes | grep -E "nvidia.com/gpu|Taints:|gpu-type|gke-spot"
kubectl get pods -A --field-selector=status.phase=Pending
```

Run repo taint inspection:

```bash
iac/gke-secure-gpu-cluster/inspect_taints.sh
```

## Related Workloads

- LiteLLM/vLLM app: `apps/litellm-gateway`
- L4 deployment: `apps/litellm-gateway/k8s/vllm-l4-deployment.yaml`
- T4 deployment: `apps/litellm-gateway/k8s/vllm-t4-deployment.yaml`

## Failure Modes

- GPU quota is unavailable, so autoscaler cannot create nodes.
- Accelerator type is unavailable in the selected zone.
- Pod lacks tolerations for spot or GPU-type taints.
- Pod requests a GPU type that does not match available node pools.
- Driver/plugin readiness is incomplete on new GPU nodes.

## References

- `iac/gke-secure-gpu-cluster/main.tf`
- `iac/gke-secure-gpu-cluster/variables.tf`
- `iac/gke-secure-gpu-cluster/terraform.v3.tfvars`
- `required_manual_adjustments.md`
- `docs/runbooks/gpu-pods-pending.md`
- `apps/litellm-gateway/README.md`
- `install_nvidia_drivers.sh`
