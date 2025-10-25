# GKE diagnostics (for infra/coding assistant agents)

This document instructs an infra/coding assistant how to gather safe, useful diagnostics from the GKE cluster in this repo.

Principles
- Always ask for permission before accessing a production cluster. If the user requests diagnostics, confirm the target cluster name/region and whether it's a prod/test/dev cluster.
- Do NOT exfiltrate secrets or full logs that contain tokens/keys. Redact or mark sensitive files before sharing externally.
- Prefer read-only commands. If you must run commands that change state, explicitly note the action and get approval.

Prerequisites
- `gcloud` and `kubectl` configured locally and authenticated for the target project/cluster.
- Optional env helpers in this repo: `iac/util_scripts/get_account_id.sh`, `iac/util_scripts/get_project_id.sh`, and `iac/gke-secure-gpu-cluster/env.sh`.

Quick setup (get credentials)
```bash
# Example used in this repo (adjust cluster name/region as needed)
gcloud container clusters get-credentials gpu-spot-cluster --region europe-west4
```

Basic cluster snapshot (safe, read-only)
```bash
kubectl version --short > diagnostics/kubectl-version.txt
kubectl cluster-info > diagnostics/cluster-info.txt
kubectl get nodes -o wide > diagnostics/nodes.txt
kubectl get pods -A -o wide > diagnostics/pods-all-namespaces.txt
kubectl get events -A --sort-by='.metadata.creationTimestamp' > diagnostics/events.txt
kubectl describe nodes > diagnostics/nodes-describe.txt
```

System and control-plane components
```bash
kubectl -n kube-system get pods -o wide > diagnostics/kube-system-pods.txt
kubectl -n kube-system describe daemonset > diagnostics/kube-system-daemonsets.txt
# For each important pod in kube-system (e.g. kube-proxy, coredns, metrics-server)
# capture recent logs (tail 200 lines)
kubectl -n kube-system logs <pod-name> --tail=200 > diagnostics/kube-system-<pod-name>-logs.txt
```

Pod-level diagnostics (when a pod is failing)
```bash
# List pods in namespace
kubectl get pods -n <namespace> -o wide
# Describe the failing pod
kubectl describe pod <pod> -n <namespace> > diagnostics/pod-<namespace>-<pod>-describe.txt
# Fetch logs (main container). If there are multiple containers, run per container.
kubectl logs -n <namespace> <pod> --tail=200 > diagnostics/pod-<namespace>-<pod>-logs.txt
# For previous terminated container logs
kubectl logs -n <namespace> <pod> --previous --tail=200 > diagnostics/pod-<namespace>-<pod>-logs-previous.txt
```

Node / GPU specific checks
- This repo manages GPU nodes. To inspect taints, labels and GPU devices:
```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.labels}\n{end}' > diagnostics/node-labels.txt
kubectl describe node <node-name> > diagnostics/node-<node-name>-describe.txt
# Run the provided helper that inspects taints (exists in the repo)
bash iac/gke-secure-gpu-cluster/inspect_taints.sh > diagnostics/inspect_taints.txt
```

If you need to validate GPU visibility from a pod (run only with permission):
```bash
# If a GPU pod already exists, exec into it and run nvidia-smi
kubectl exec -it <gpu-pod> -n <namespace> -- nvidia-smi > diagnostics/<gpu-pod>-nvidia-smi.txt
# Alternatively, launch a short job (request GPUs) to run nvidia-smi
kubectl run --rm -it gpu-debug --image=nvidia/cuda:11.0-base --restart=Never -- bash -lc "nvidia-smi" > diagnostics/gpu-debug-nvidia-smi.txt
```

Resource usage
```bash
# Requires metrics-server to be installed; skip if not present
kubectl top nodes > diagnostics/top-nodes.txt || true
kubectl top pods -A > diagnostics/top-pods.txt || true
```

GKE / gcloud checks
```bash
# Node-pools and instance checks
gcloud container node-pools list --cluster gpu-spot-cluster --region europe-west4 > diagnostics/node-pools.txt
# List GCE instances for GKE nodes
gcloud compute instances list --filter="name~'gke-'" --project ${TGCP_PROJ:-$(./iac/util_scripts/get_project_id.sh)} > diagnostics/gce-instances.txt
```

Terraform context (infra state)
```bash
# From the infra folder in this repo
cd iac/gke-secure-gpu-cluster
terraform init -backend=false
terraform plan -var-file=terraform.v2.tfvars -refresh-only -out=refresh.plan
terraform show -json refresh.plan > ../diagnostics/terraform-refresh.json
terraform state list > ../diagnostics/terraform-state-list.txt || true
terraform output > ../diagnostics/terraform-outputs.txt || true
```

Collecting logs and packaging
```bash
mkdir -p diagnostics
# Run the above commands redirecting outputs into diagnostics/ files
# When finished:
tar -czf gke-diagnostics-$(date -u +%Y%m%dT%H%M%SZ).tgz diagnostics
```

Redaction and safety
- Before sharing a diagnostics archive externally, search and redact sensitive patterns (API keys, tokens, private IPs if necessary). Common places to check:
  - kubeconfig files, service account tokens (in pod envs), cloud provider metadata.
- If asked to produce shortened excerpts, include the command run and the minimal lines needed to show the problem (e.g., last 100 log lines, pod describe sections showing events).

Repo-specific pointers
- GPU test manifests: `k8s/test-pods/nvidia-t4-gpu-pod.yaml` and `k8s/test-pods/nvidia-l4-gpu-pod.yaml` can be used as smoke tests for GPU scheduling.
- Secrets setup scripts: `iac/gke-secure-gpu-cluster/secrets_setup/dockerhub_setup/` — avoid printing generated secret values.
- Helper scripts and bootstrapping: `iac/backend_bootstrap/gcp_make_terraform_backend_interactive.py`, `iac/gke-secure-gpu-cluster/inspect_taints.sh`, and `install_nvidia_drivers.sh` (root) are useful references.

What to include when asking a human for help
- Cluster name and region (example: `gpu-spot-cluster`, `europe-west4`).
- The exact commands you ran and the files you collected (attach the .tgz), or copy of the specific log snippets (with redaction).
- Terraform plan/state outputs if the problem looks infra-related.

If any of the above commands fail or the environment differs, capture stderr and note the exact error message. Ask for permission if a command requires creating pods/jobs or modifying infra.

---

If you'd like, I can also add a small helper script in `scripts/` that runs the safe subset of these commands and packages results automatically (redaction left to the operator).