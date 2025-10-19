
What this will create

- The namespace
- The docker pull secret (only if you provide the secret payload to the module or have uploaded a Secret Manager secret version beforehand — see options below)
- The Kubernetes ServiceAccount with the correct annotation for Workload Identity

Important: the docker pull secret is created by the module only when you either pass the base64-encoded dockerconfig JSON into the module (via `dockerconfig_secret_data_b64` and `create_docker_registry_secret=true`) or when a Secret Manager secret version is present and you run the module after uploading that version. The module will not fail cluster creation if secret versions are missing; instead follow the two-stage flow below to provision secrets post-hoc.

Why a two-stage apply
- Terraform evaluates data sources (for example: the cluster endpoint and Secret Manager secret versions) during plan. The Kubernetes provider inside this module depends on those data sources being available. If you try to apply the module at the same time you create/replace the cluster, Terraform will fail because the cluster (or the Secret Manager API/secrets) does not yet exist.

The two-stage apply creates the Google resources and the cluster first, waits for the cluster to become reachable, then applies the k8s module. This gives a reliable ordering without hacks or provider reconfiguration.

Exact two-stage apply (copy/paste)
1) Initialize the working directory (once per machine/CI):

```bash
cd /home/charilaos/Workspace/iac-gke-k8s/iac/gke-secure-gpu-cluster
terraform init
```

2) Phase A — create project services, secrets, service account and the cluster (targeted apply)

Run a targeted apply that creates the APIs, Secret Manager secrets, the GSA and the GKE cluster but does not try to initialize the Kubernetes provider yet:

```bash
terraform plan \
  -target=google_project_service.gke_api \
  -target=google_project_service.compute_api \
  -target=google_project_service.secretmanager \
  -target=google_secret_manager_secret.secrets \
  -target=google_service_account.default_gsa \
  -target=google_service_account_iam_member.workload_identity_user \
  -target=google_container_cluster.primary \
  -var-file=terraform.v2.tfvars

terraform apply \
  -target=google_project_service.gke_api \
  -target=google_project_service.compute_api \
  -target=google_project_service.secretmanager \
  -target=google_secret_manager_secret.secrets \
  -target=google_service_account.default_gsa \
  -target=google_service_account_iam_member.workload_identity_user \
  -target=google_container_cluster.primary \
  -var-file=terraform.v2.tfvars
```

- Notes:
- The `-target` list is intentionally conservative. At minimum, include the project services, the Secret Manager secret *containers* and the cluster. If you want nodes to be available immediately for Phase B, include at least the primary node pool in Phase A (see example below). You can shorten it but ensure the data sources used by the k8s module will succeed after this step.
- Creating the cluster can take several minutes. Wait for the apply to finish and for the cluster to be healthy before proceeding.

3) Update kubeconfig and verify cluster readiness

After Phase A completes, update your kubeconfig so the Kubernetes provider (and `kubectl`) can reach the new cluster:

```bash
gcloud container clusters get-credentials ${cluster_name:-gpu-spot-cluster} --zone ${zone:-europe-west4-a} --project ${project_id:-gke-gpu-project-473410}
kubectl get nodes -o wide
```

Confirm that nodes are Ready and that you can list namespaces. If `kubectl` cannot reach the API, wait and retry — the cluster is still provisioning.

4) Phase B  apply the k8s module

Once the cluster is reachable and nodes are Ready (or you have verified the k8s API is accessible), apply only the k8s module:

```bash
terraform apply -target=module.k8s -var-file=terraform.v2.tfvars
```

Notes on secrets and options
- If you want the module to create the docker pull secret directly, run Phase B with these variables set (CI-friendly but note secret data may be present in state):

  ```bash
  terraform apply -target=module.k8s -var='create_docker_registry_secret=true' -var='dockerconfig_secret_data_b64=<base64-encoded-dockerconfigjson>' -var-file=terraform.v2.tfvars
  ```

- Preferred, more secure option: upload secret *versions* to Secret Manager (CI or manual) and then run Phase B. Example:

  ```bash
  echo -n "$DOCKER_CONFIG_JSON" | gcloud secrets versions add dockerhub-ro-pat --data-file=- --project=<project>
  terraform apply -target=module.k8s -var-file=terraform.v2.tfvars
  ```

This two-stage approach keeps cluster creation independent from secret provisioning and is recommended for long-term maintainability.

5) Finalize (optional full apply)

If you want to ensure any remaining resources are up-to-date, run a full apply:

```bash
terraform apply -var-file=terraform.v2.tfvars
```

Troubleshooting tips
- If `module.k8s` fails because Secret Manager API is disabled, ensure Phase A included `google_project_service.secretmanager` and wait a few minutes for API enablement to propagate.
- If the cluster data source still cannot find the cluster (`not found`), confirm `var.cluster_name` and `var.region` match the created cluster and that you used the same `project_id` and zone/region.
- If you prefer not to read secret values during plan, you can change the module to accept the secret value (or secret version id) as an input variable and pass it from the root after Phase A.

Automation helper
-----------------
To make the two-stage flow repeatable from CI or locally, this repo includes a helper script:

  iac/gke-secure-gpu-cluster/scripts/deploy_with_secrets.sh

What it does:
- Runs Phase A (targeted terraform apply for APIs, secret containers, service account, and the cluster)
- Waits until the cluster control plane is reachable and at least one node is Ready (if node pools were created)
- Optionally uploads secret versions to Secret Manager from environment variables (DOCKER_CONFIG_JSON and OPENAI_API_KEY)
- Runs Phase B: `terraform apply -target=module.k8s`

Usage:

  # Dry-run (does not perform changes):
  ./scripts/deploy_with_secrets.sh --project gke-gpu-project-473410

  # Execute (reads secrets from env and uploads to Secret Manager):
  DOCKER_CONFIG_JSON='{"auths":{}}' OPENAI_API_KEY='sk-...' ./scripts/deploy_with_secrets.sh --execute --project gke-gpu-project-473410

Security note: the script uploads secrets from environment variables to Secret Manager. Keep secrets out of shell history and CI logs. Prefer using your CI's secret store.

Why keep this separation
- Prevents provider-init ordering problems when replacing the cluster.
- Allows you to recreate or replace clusters without forcing Terraform to re-initialize the Kubernetes provider mid-apply.
- Keeps lifecycle boundaries clear: infra (GCP) vs runtime manifests (K8s).

If you want, I can generate a small shell script that automates Phase A -> wait -> Phase B (dry-run by default and `--execute` to run). Contact me and I will add it under `scripts/`.
