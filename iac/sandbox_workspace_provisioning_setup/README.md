# Sandbox Workspace Provisioning Setup

This document lists the one-time manual and Terraform-backed setup required before the backend can lazily provision per-user sandbox workspaces using Google Cloud APIs.

To run the full diagnostic suite in one command, use:

- `./iac/sandbox_workspace_provisioning_setup/all_checks.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION> [--namespace <NAMESPACE>] [--bucket <BUCKET_NAME>] [--backend-ksa <KSA_NAME>] [--backend-admin-gsa <GSA_EMAIL>]`

The wrapper always runs checks `01` to `03` and conditionally runs later checks when the required flags are provided.

The target design is:

- one shared Cloud Storage bucket per environment
- one managed folder per user under `workspaces/<user_id>/`
- one Google service account per user
- one Kubernetes service account per user
- Workload Identity binding from each per-user KSA to its per-user GSA
- one user-derived `SandboxTemplate` mounting the user's managed folder at `/workspace`
- provisioning and deprovisioning driven by the backend through Google APIs and Kubernetes APIs

## What Must Exist Before Lazy Provisioning Can Work

The backend can create per-user resources on first use, but it still needs a pre-existing platform bootstrap.

That bootstrap is:

1. a GKE cluster with Workload Identity enabled
2. Cloud Storage FUSE CSI support in the cluster
3. a shared workspace bucket configured for managed folders
4. a backend admin GSA with permission to create and delete per-user identities and managed-folder IAM
5. a backend KSA bound to that admin GSA
6. backend Kubernetes RBAC allowing creation of per-user KSAs and user-derived sandbox templates

## Manual Checks In Google Cloud

## 1. Enable required APIs

These APIs must be enabled in the project that hosts the cluster and workspace bucket:

- `container.googleapis.com`
- `iam.googleapis.com`
- `cloudresourcemanager.googleapis.com`
- `storage.googleapis.com`

Checker:

- `./iac/sandbox_workspace_provisioning_setup/01_check_required_apis.sh --project-id <PROJECT_ID>`

Check as follows: (in the project that hosts the cluster)

```bash
gcloud services --list --enabled --filter="name:storage.googleapis.com"
```

enable as follows: 
```bash
gcould services enable storage.googleapis.com
```

## 2. Verify GKE Workload Identity is enabled

Your cluster must already be configured for Workload Identity Federation for GKE.

Confirm this in the cluster configuration before relying on lazy provisioning.

Checker:

- `./iac/sandbox_workspace_provisioning_setup/02_check_cluster_workload_identity.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION>`

## 3. Verify Cloud Storage FUSE CSI support is available

The sandbox pod templates will mount the shared workspace bucket through the GCS FUSE CSI driver.

Before rollout, confirm:

- the cluster version supports the driver features you plan to use
- the driver is enabled for the cluster mode you run
- test pods can mount a bucket successfully in the target namespace

Checker:

- `./iac/sandbox_workspace_provisioning_setup/03_check_gcs_fuse_support.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION>`

## 4. Create the shared workspace bucket

Create one shared bucket per environment and configure it with:

- uniform bucket-level access enabled
- hierarchical namespace enabled
- public access prevention enabled

Recommended naming:

- `gs://<environment>-sandbox-workspaces`

Recommended layout:

- `workspaces/<user_id>/`

Do not enable object versioning on the mounted workspace bucket path used by Cloud Storage FUSE.

Checker:

- `./iac/sandbox_workspace_provisioning_setup/04_check_workspace_bucket.sh --project-id <PROJECT_ID> --bucket <BUCKET_NAME>`

## 5. Create the backend admin Google service account

Create a dedicated GSA for the backend control plane, separate from the generic default service account if possible.

Example:

- `sandbox-workspace-admin@<project-id>.iam.gserviceaccount.com`

This identity is used by the backend to provision and deprovision per-user resources.

Checker:

- `./iac/sandbox_workspace_provisioning_setup/05_check_backend_admin_gsa.sh --project-id <PROJECT_ID> --backend-admin-gsa <GSA_EMAIL>`

## 6. Grant backend admin permissions

The backend admin GSA needs permission to do all of the following:

- create, get, and delete Google service accounts for users
- manage IAM policy bindings on those Google service accounts
- create managed folders under the workspace bucket
- get and set IAM policies on those managed folders
- create and remove Workload Identity bindings between per-user KSAs and GSAs

Use least privilege where practical, but make sure the backend can complete the full user lifecycle:

- first-use provisioning
- reuse
- deprovisioning

At minimum, review roles and equivalent custom-role permissions for:

- service account administration
- service account IAM policy administration
- Cloud Storage managed folder administration
- Cloud Storage managed folder IAM policy management

If you use predefined roles, verify they cover the exact managed-folder and service-account operations the backend will call.

Checker:

- `./iac/sandbox_workspace_provisioning_setup/06_check_backend_admin_permissions.sh --project-id <PROJECT_ID> --bucket <BUCKET_NAME> --backend-admin-gsa <GSA_EMAIL>`

## 7. Bind backend KSA to backend admin GSA

The backend pod needs to run with a Kubernetes service account that impersonates the backend admin GSA through Workload Identity.

Current repo note:

- Terraform now provisions a dedicated backend KSA, `sandbox-workspace-admin-ksa`
- backend workload identity should be bound to the backend admin GSA through that KSA
- `default-ksa` may still exist for legacy or transitional use, but it should not be the long-term backend identity

Checker:

- `./iac/sandbox_workspace_provisioning_setup/07_check_backend_ksa_binding.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION> --namespace <NAMESPACE> --backend-ksa <KSA_NAME> --backend-admin-gsa <GSA_EMAIL>`

## 8. Expand backend Kubernetes RBAC

The backend currently has RBAC for:

- `sandboxclaims`
- `sandboxtemplates`
- `sandboxwarmpools`
- read access to `sandboxes`

Lazy user provisioning also requires namespace-scoped permission to manage:

- `serviceaccounts`

If user-derived `SandboxTemplate`s are created dynamically, keep permission to create, patch, update, get, list, and delete `sandboxtemplates`.

Keep RBAC namespace-scoped to the app namespace.

Checker:

- `./iac/sandbox_workspace_provisioning_setup/08_check_backend_rbac.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION> --namespace <NAMESPACE> --backend-ksa <KSA_NAME>`

## 9. Decide the deletion policy before rollout

Because user deletion is in scope, decide and document the product behavior for deprovisioning.

Recommended default:

1. delete active sandbox claims for the user
2. delete the user-derived `SandboxTemplate`
3. delete the per-user KSA
4. remove Workload Identity binding
5. remove managed-folder IAM bindings
6. optionally delete the managed folder contents
7. optionally delete the managed folder resource
8. delete the per-user GSA
9. tombstone the workspace metadata in the backend database

If regulatory retention is required, do not immediately delete objects from Cloud Storage. Mark the workspace disabled first and retain data until the retention window expires.

Checker:

- `./iac/sandbox_workspace_provisioning_setup/09_check_deprovisioning_constraints.sh --project-id <PROJECT_ID> --bucket <BUCKET_NAME>`

## Terraform Work To Pair With This Manual Setup

The following should be added in Terraform:

1. shared workspace bucket resources
2. backend admin GSA
3. Workload Identity binding from backend KSA to backend admin GSA
4. backend Deployment KSA switch to `sandbox-workspace-admin-ksa`
5. backend RBAC updates for Kubernetes service accounts and dynamic sandbox templates

Suggested locations:

- `iac/gke-secure-gpu-cluster/storage.tf`
- `iac/gke-secure-gpu-cluster/identity.tf`
- `apps/sandboxed-react-agent/k8s/backend-sandbox-rbac.yaml`

## What The Backend Should Provision Lazily

For a new user on first sandbox use, the backend should create:

1. managed folder `workspaces/<user_id>/`
2. per-user GSA
3. per-user KSA in the app namespace
4. Workload Identity binding from KSA to GSA
5. managed-folder IAM granting only that GSA access to that folder
6. user-derived `SandboxTemplate`

The backend should do this via Google Cloud APIs and Kubernetes APIs, not by shelling out to `gcloud`.

## What The Backend Should Deprovision

When a user workspace is deleted or deactivated, the backend should:

1. terminate active user sandbox claims
2. delete the derived sandbox template
3. remove the per-user KSA
4. remove the Workload Identity binding
5. remove managed-folder IAM bindings
6. delete or archive managed-folder contents according to retention policy
7. delete the managed folder if allowed
8. delete the per-user GSA
9. mark the workspace as deleted in persistent metadata

These operations must be idempotent and safe to retry.

## Validation Checklist

Before enabling the feature in production, verify:

- backend pod identity is the intended admin GSA
- backend can create and delete a test GSA
- backend can create a test managed folder and set IAM on it
- backend can create a test KSA and Workload Identity binding
- a sandbox launched with a test per-user template can mount `/workspace`
- that sandbox can access only its own managed folder and not a sibling user's folder
- deleting a test user workspace fully removes or archives all expected resources

## Parameter Suggestions

The scripts require explicit flags so they are safe to run against the intended project and cluster.

Suggested values for this repo:

- `--namespace alt-default`
- `--backend-ksa sandbox-workspace-admin-ksa`
- `--backend-admin-gsa sandbox-workspace-admin@<PROJECT_ID>.iam.gserviceaccount.com`
- `--bucket <env>-sandbox-workspaces`

Assumptions:

- `gcloud`, `kubectl`, and `jq` are installed
- `gcloud auth login` and `gcloud container clusters get-credentials` are already available to you
