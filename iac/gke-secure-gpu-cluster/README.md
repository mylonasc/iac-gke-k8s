## About

This is a deployment that creates a GKE in google cloud kybernetes engine. 

The cloud has the following features:
* 2 types of GPU-enabled nodes clusters
* 1 type of non-GPU general purpose nodes cluster
* 1 type of isolated autoscaled node pool for sandboxed workloads
* Secrets manager integration (e.g., for API keys)
* Remote backend integration


## Using a backend

A backend is a place to store and manage your statefile. 

Although statefiles can be local, it is recommended to use a GCP storage bucket for storing your state. 

Scripts for easy setup are provided in the `./backend_bootstrap` folder. 

Note on enabling remote state

This repository already contains a GCS backend configuration in `iac/gke-secure-gpu-cluster/europe_backend.tf`. In normal usage, run `terraform init -reconfigure` in this directory and Terraform will use that backend.

- If you need a different backend bucket/prefix, update the backend block and run `terraform init -reconfigure`.
- If you need to bootstrap a new backend bucket, use `iac/backend_bootstrap/gcp_make_terraform_backend_interactive.py`.

If you don't enable a remote backend, Terraform will default to local state.

## Public access
The most cost-effective (free) option is to use a node port for public access.
In order, however, to allow public access to pass google's firewall rules you must create an exception for your cluster. 

You can find the name of the available clusters by running:

```bash
gcloud container clusters list
```

## Extension with secret management

To create the Secret Manager containers (the secret resources) run the terraform apply for `secrets.tf` as part of Phase A (this repo's automation does that). Note: creating the secret *container* does not add a secret *version* (the actual secret value). You must upload secret versions from CI or manually via `gcloud secrets versions add` before the k8s module can read secret values.

```bash
terraform apply -target=google_secret_manager_secret.secrets -var-file=terraform.v2.tfvars
```

Also ensure secrets are present (versions) before running `terraform apply -target=module.k8s`.

## Two-stage apply and automation

This repo uses a two-stage apply pattern to avoid Terraform provider-init ordering issues: the Kubernetes provider needs a reachable cluster and Secret Manager secret versions to read before it can create Kubernetes resources.

Recommended flow:

1. Phase A: create project services, secret containers, service account, and the cluster (this repo contains a targeted apply example in `k8s/README.md`).
2. Provision secret versions to Secret Manager (preferably from CI using the CI secret store, or manually via `gcloud secrets versions add`).
3. Phase B: apply `module.k8s` (targeted apply) to create Kubernetes namespace, pull secrets, and service accounts.

Automation helper:

There is a helper script to automate the flow:

	iac/gke-secure-gpu-cluster/scripts/deploy_with_secrets.sh

It performs Phase A, waits for the cluster to be reachable and for nodes to be Ready, optionally uploads secret versions from environment variables (DOCKER_CONFIG_JSON, OPENAI_API_KEY), then runs Phase B to apply `module.k8s`.

Security note: prefer uploading secret versions from CI rather than placing secret payloads into Terraform state. The script supports a dry-run mode and should be used from CI or with care locally.

## Isolated sandboxed workloads

This Terraform module now includes a dedicated isolated node pool (`google_container_node_pool.gvisor_pool`) with:

- autoscaling from zero,
- GKE-managed sandbox taint plus labels for strict workload placement,
- a manifest example for requesting the `gvisor` runtime.

See `iac/gke-secure-gpu-cluster/k8s/gvisor-isolated-nodes.md` for create/de-provision steps, runtime verification, connectivity checks, and dynamic usage patterns from Python.
