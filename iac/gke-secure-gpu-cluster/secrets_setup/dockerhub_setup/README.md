# DockerHub Secret Notes (Archived)

This directory is retained for legacy context only.

Current secret workflow:

- Terraform creates Secret Manager secret containers.
- Secret versions are uploaded via CI or manually.
- Deploy flow is documented in:
  - `iac/gke-secure-gpu-cluster/README.md`
  - `iac/gke-secure-gpu-cluster/k8s/README.md`
  - `docs/deploy-and-operations.md`

Historical background is tracked in `docs/archive/secrets-setup-legacy.md`.
