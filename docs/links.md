# Project Links

Use these links as entry points. Replace placeholders where noted.

## Google Cloud console

- Project home:
  - `https://console.cloud.google.com/home/dashboard?project=<PROJECT_ID>`
- GKE clusters:
  - `https://console.cloud.google.com/kubernetes/list/overview?project=<PROJECT_ID>`
- Specific cluster details:
  - `https://console.cloud.google.com/kubernetes/clusters/details/<LOCATION>/<CLUSTER_NAME>/details?project=<PROJECT_ID>`
- Secret Manager:
  - `https://console.cloud.google.com/security/secret-manager?project=<PROJECT_ID>`
- IAM principals:
  - `https://console.cloud.google.com/iam-admin/iam?project=<PROJECT_ID>`
- Quotas page (GPU-related filtering can be applied in UI):
  - `https://console.cloud.google.com/iam-admin/quotas?project=<PROJECT_ID>`
- Logs Explorer:
  - `https://console.cloud.google.com/logs/query?project=<PROJECT_ID>`
- Metrics Explorer:
  - `https://console.cloud.google.com/monitoring/metrics-explorer?project=<PROJECT_ID>`
- Billing reports:
  - `https://console.cloud.google.com/billing?project=<PROJECT_ID>`

## Terraform and IaC references

- Root deployment docs:
  - `README.md`
  - `iac/gke-secure-gpu-cluster/README.md`
- Kubernetes module docs:
  - `iac/gke-secure-gpu-cluster/k8s/README.md`
- Backend bootstrap helper:
  - `iac/backend_bootstrap/gcp_make_terraform_backend_interactive.py`

## Kubernetes and GKE references

- GKE Standard docs:
  - `https://cloud.google.com/kubernetes-engine/docs/concepts/cluster-architecture`
- Workload Identity Federation for GKE:
  - `https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity`
- GKE GPU guide:
  - `https://cloud.google.com/kubernetes-engine/docs/how-to/gpus`
- GKE Sandbox (gVisor):
  - `https://cloud.google.com/kubernetes-engine/docs/concepts/sandbox-pods`

## Repo-local operations references

- Deploy helper script:
  - `iac/gke-secure-gpu-cluster/scripts/deploy_with_secrets.sh`
- Diagnostics guide:
  - `gke_diagnostics.md`
- Cluster inspection script:
  - `inspect_cluster.sh`
- Agent Sandbox notes:
  - `iac/gke-secure-gpu-cluster/k8s/agent-sandbox.md`
