## GPU Quota Adjustment

If you plan to use GPU node pools, request quota before first deployment.

Notes:

- GPU quotas are enforced both per-region and for some global metrics.
- In Quotas, search for `compute.googleapis.com/gpus_all_regions` and the regional GPU metrics you intend to use.

Useful links:

- Project quotas page:
  - `https://console.cloud.google.com/iam-admin/quotas?project=<PROJECT_ID>`
- GKE GPU documentation:
  - `https://cloud.google.com/kubernetes-engine/docs/how-to/gpus`

## Sandbox Workspace Provisioning

If you want lazy first-use provisioning of per-user sandbox workspaces backed by Cloud Storage FUSE with IAM-enforced isolation, complete the one-time bootstrap described here:

- `iac/sandbox_workspace_provisioning_setup/README.md`

This includes:

- shared workspace bucket setup
- backend admin service account setup
- Workload Identity wiring
- backend RBAC expansion
- provisioning and deprovisioning prerequisites
