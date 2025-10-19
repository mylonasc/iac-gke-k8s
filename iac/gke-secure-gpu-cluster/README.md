## About

This is a deployment that creates a GKE in google cloud kybernetes engine. 

The cloud has the following features:
* 2 types of GPU-enabled nodes clusters
* 1 type of non-GPU general purpose nodes cluster
* Secrets manager integration (e.g., for API keys)
* Remote backend integration


## Using a backend

A backend is a place to store and manage your statefile. 

Although statefiles can be local, it is recommended to use a GCP storage bucket for storing your state. 

Scripts for easy setup are provided in the `./backend_bootstrap` folder. 

## Public access
The most cost-effective (free) option is to use a node port for public access.
In order, however, to allow public access to pass google's firewall rules you must create an exception for your cluster. 

You can find the name of the available clusters by running:

```bash
gcloud container clusters list
```

## Extension with secret management

To create the `google_secret_manager` resource in google cloud and add a secret, run  the terraform apply on the `secrets.tf` file
```bash
terraform apply 
```

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


