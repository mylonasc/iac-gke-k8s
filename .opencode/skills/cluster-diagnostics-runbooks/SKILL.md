---
name: cluster-diagnostics-runbooks
description: Use when diagnosing cluster failures, pods pending, API unreachable, rollout issues, GPU scheduling, secret access, or app health.
---

# Cluster Diagnostics Runbooks

Use this skill for read-only or low-risk diagnostics across GKE, Kubernetes workloads, Agent Sandbox, secrets, GPU scheduling, and Janet app rollout health.

## Diagnostic Entry Points

- Cluster snapshot: `inspect_cluster.sh`
- Janet diagnostics: `apps/janet/ops.sh diag`
- Taint inspection: `iac/gke-secure-gpu-cluster/inspect_taints.sh`
- Runbooks: `docs/runbooks`

## General Checks

```bash
kubectl get nodes -o wide
kubectl get pods -A
kubectl get events -A --sort-by=.lastTimestamp
kubectl -n alt-default get deploy,svc,ingress
```

For a failing pod:

```bash
kubectl -n <namespace> describe pod <pod>
kubectl -n <namespace> logs <pod> --all-containers --tail=100
```

For deployments:

```bash
kubectl -n alt-default rollout status deploy/sandboxed-react-agent-backend
kubectl -n alt-default rollout status deploy/sandboxed-react-agent-frontend
kubectl -n alt-default rollout status deploy/sandbox-router-deployment
```

## Agent Sandbox Checks

```bash
kubectl get pods -n agent-sandbox-system
kubectl -n alt-default get sandboxtemplate,sandboxwarmpool,sandboxclaim
kubectl -n alt-default get deploy,svc | grep sandbox-router
```

## Secret Checks

Do not print secret values. Check presence and key names only.

```bash
kubectl -n alt-default get secret
kubectl -n alt-default describe secret sandboxed-react-agent-secrets
kubectl -n alt-default describe secret dockerhub-regcred
```

## GPU Scheduling Checks

```bash
kubectl get nodes -L cloud.google.com/gke-nodepool
kubectl describe nodes | grep -E "nvidia.com/gpu|Taints:|gpu-type|gke-spot"
kubectl get pods -A --field-selector=status.phase=Pending
```

## Common Failure Classes

- Cluster API unreachable after Phase A: wait, refresh credentials, verify project/location/cluster name.
- Terraform Kubernetes provider failure: avoid applying `module.k8s` before the cluster exists.
- Secret access failure: verify Secret Manager API, IAM binding, KSA annotation, and Kubernetes secret presence.
- Image pull failure: verify `dockerhub-regcred` in the workload namespace.
- GPU pods pending: check quota, taints/tolerations, accelerator availability, and node pool autoscaling.
- Agent Sandbox pods pending: check gVisor pool, runtimeClass, node selector, image pull secret, and warm pool replicas.
- Janet backend failure: check app secrets, DB/WireGuard config, auth values, and router reachability.

## References

- `docs/deploy-and-operations.md`
- `docs/runbooks/cluster-api-unreachable.md`
- `docs/runbooks/secret-access-failures.md`
- `docs/runbooks/gpu-pods-pending.md`
- `inspect_cluster.sh`
- `cluster_inspection_output.md`
- `apps/janet/scripts/diagnose_k8s_app.sh`
