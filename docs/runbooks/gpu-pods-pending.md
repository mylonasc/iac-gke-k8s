# Runbook: GPU Pods Pending

## Symptoms

- GPU workloads stay in `Pending`.
- Scheduler events indicate no matching nodes or missing tolerations/selectors.

## Immediate checks

```bash
kubectl get nodes -L cloud.google.com/gke-nodepool
kubectl describe pod <pod-name> -n <namespace>
kubectl get events -n <namespace> --sort-by='.metadata.creationTimestamp'
```

## Common causes

- GPU node pools scaled to zero and autoscaler has not provisioned nodes yet.
- Pod is missing required tolerations for GPU pool taints.
- Pod requests GPU type that does not match available pool labels/taints.
- Quota exhaustion for GPU family or project-level limits.

## Triage and fix

1. Verify GPU pools exist and are enabled in Terraform vars.
2. Verify pod spec has matching selectors/tolerations.
3. Check project quota for GPU and regional capacity.
4. Run a Terraform plan to detect accidental drift in node pool definitions.

## Validation

```bash
kubectl get pods -n <namespace> -o wide
kubectl get nodes -o wide
```

Optionally validate inside a running GPU pod:

```bash
kubectl exec -it <gpu-pod> -n <namespace> -- nvidia-smi
```
