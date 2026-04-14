# Sandbox FUSE Workspaces With Strong Per-User Isolation

This document captures the implementation plan for user-bound sandbox workspaces backed by Cloud Storage FUSE, with strong isolation enforced at the Google Cloud IAM layer.

## Current implementation status (2026-04)

The app now implements the core persistent workspace path and several UX/reliability improvements:

- per-user workspace provisioning for bucket, GSA, KSA, WI, and user-derived templates
- persistent execution resolves selected base template flavors to user-derived templates
- optional persistent-to-transient fallback with explicit session status metadata
- periodic backend lease reaper loop in app lifecycle, with request-path reaping retained as backstop

What remains mostly roadmap-oriented in this document:

- deeper preflight diagnostics for FUSE/WI prerequisites
- warm pool and template alignment tuning by benchmark results
- default-policy decisions (for example transient-by-default for general chat)

One-time platform bootstrap steps are documented separately in:

- `iac/sandbox_workspace_provisioning_setup/README.md`

## Goal

Add reusable sandbox workspaces such that:

- each user gets a durable workspace stored in a dedicated bucket
- sandboxes for the same user can mount that user's workspace concurrently
- sandboxes for different users cannot access each other's workspace data at the Cloud Storage API layer
- active sandbox sessions reconnect to an existing `SandboxClaim` when possible

## What This Plan Assumes

- sandbox workspace persistence is for user files under `/workspace`
- full root filesystem and process-memory persistence is out of scope
- storage is shared through Cloud Storage FUSE, not through PVCs
- isolation must be enforced by Cloud Storage IAM, not only by mount configuration

## Why This Requires Per-User Buckets And Per-User Identities

Mounting a bucket prefix with `Cloud Storage FUSE` is not enough for strict tenant isolation.

- a mount option such as `only-dir` limits what appears in the mounted path
- it does not by itself prevent a principal with broader Cloud Storage access from reading or writing other prefixes through Cloud Storage APIs
- GCS FUSE CSI mount startup still requires bucket-level `storage.objects.list`, which makes strong shared-bucket prefix isolation impractical

To make isolation real at the IAM layer, use:

- one bucket per user workspace
- one Google service account per user workspace principal
- one Kubernetes service account per user workspace principal
- IAM bindings only on that user's bucket

That gives each sandbox pod an identity that can only access one bucket.

## Recommended Storage Layout

Use a dedicated bucket per user with uniform bucket-level access enabled.

Example layout:

- bucket: `gs://<environment>-sandbox-workspace-<user-suffix>`
- mounted path in sandbox: `/workspace`

Notes:

- do not enable object versioning on the FUSE-mounted workspace bucket; Cloud Storage FUSE docs call out unpredictable behavior there

## Security Model

### Shared infrastructure identity

Keep a platform/admin identity for bucket administration.

It is allowed to:

- create per-user buckets
- create per-user Google service accounts
- create Workload Identity bindings
- update bucket IAM policies

It is not used by sandbox pods.

### Per-user runtime identity

For each user, create:

- a Google service account, for example `sandbox-user-<stable-id>@<project>.iam.gserviceaccount.com`
- a Kubernetes service account, for example `sandbox-user-<stable-id>-ksa`

Grant the Google service account only the minimum roles on that user's bucket, typically:

- `roles/storage.objectUser` on `gs://<user-workspace-bucket>`

Do not grant broad object access on the bucket to the per-user runtime service accounts.

If the sandbox only needs read-only access for some modes, support:

- `roles/storage.objectViewer`

The backend should continue using its own service account and broader admin privileges where needed.

## Terraform Changes

## 1. Bucket resources

Add a dedicated Terraform file, for example `iac/gke-secure-gpu-cluster/storage.tf`.

Provision:

- `google_storage_bucket` for sandbox workspaces
- uniform bucket-level access enabled
- hierarchical namespace enabled
- public access prevention enabled
- lifecycle rules for stale temporary objects if needed

Add variables such as:

- `enable_sandbox_workspace_bucket`
- `sandbox_workspace_bucket_name`
- `sandbox_workspace_bucket_location`
- `sandbox_workspace_bucket_storage_class`

## 2. Admin identity for workspace provisioning

Add a dedicated GSA for backend-driven workspace administration, separate from the generic `default-service-account` if possible.

Grant it enough access to:

- create and manage per-user buckets
- set IAM policies on those buckets
- create and manage per-user Google service accounts
- manage Workload Identity bindings for per-user KSAs

This likely belongs in `iac/gke-secure-gpu-cluster/identity.tf`.

## 3. Cluster service-account wiring

The current cluster only wires `default-ksa` to a GSA and the sandbox runtime template uses `sandbox-runtime-ksa` with `automountServiceAccountToken = false`.

Changes needed:

- keep backend identity on `default-ksa` or move to a more explicit backend KSA/GSA pair
- stop assuming one shared `sandbox-runtime-ksa` for all user-mounted sandboxes
- allow per-user KSAs to be referenced by user-derived sandbox templates

Because sandbox identities are user-specific, Terraform should provision the cluster-wide primitives, but the per-user KSA objects should be created dynamically by the app or an internal provisioning service.

## 4. GCS FUSE mount support in sandbox pods

Update the sandbox pod template strategy so user-derived templates can add:

- a GCS FUSE CSI volume
- mount path `/workspace`
- the target bucket
- the target per-user bucket for the user
- any needed mount options such as implicit dirs or cache sizing

This will require changes around:

- `iac/gke-secure-gpu-cluster/k8s/agent_sandbox.tf`

The static shared templates can remain as base templates, but the user-specific templates must be created dynamically because the service account and folder path differ per user.

## Runtime-Provisioned Resources

Terraform is the right place for stable infrastructure, but per-user identities and folder IAM should be provisioned at runtime.

For each new user workspace, the backend should provision:

1. a per-user bucket
2. a Google service account for that user workspace
3. a Kubernetes service account in the app namespace
4. a Workload Identity binding from that KSA to that GSA
5. IAM bindings on the bucket for that GSA
6. a user-derived `SandboxTemplate` that references the KSA and FUSE mount

Per-user provisioning should be done by the backend through Google Cloud APIs and Kubernetes APIs, not by shelling out to `gcloud`.

Use Google Cloud APIs for:

- service account creation and deletion
- service account IAM policy management
- bucket creation and deletion
- bucket IAM policy management

Use Kubernetes APIs for:

- per-user KSA creation and deletion
- user-derived `SandboxTemplate` creation and deletion

The per-user resources should be deterministic and idempotent.

## Backend Changes

## 1. Add workspace metadata tables

Extend `backend/app/persistence/schema.py` with workspace records such as:

- `user_workspaces`
  - `workspace_id`
  - `user_id`
  - `bucket_name`
  - `managed_folder_path`
  - `gsa_email`
  - `ksa_name`
  - `derived_template_name` (primary derived template for compatibility)
  - `created_at`
  - `updated_at`
  - `last_error`

- `workspace_mounts` or equivalent lease-linked metadata
  - `lease_id`
  - `workspace_id`
  - `claim_name`
  - `template_name`
  - `mounted_at`
  - `last_verified_at`

This lets the app track what identity and template belong to a user.

## 2. Add a workspace provisioning service

Create a backend service, for example `WorkspaceProvisioningService`, responsible for:

- ensuring the user workspace exists
- creating the per-user bucket if missing
- creating the per-user GSA if missing
- creating the per-user KSA if missing
- binding Workload Identity
- setting bucket IAM on the per-user bucket
- creating or refreshing the derived sandbox template

This service should be called before the first sandbox is launched for a user.

It should also support user deprovisioning so the full resource lifecycle is owned by the backend.

## 3. Add a workspace resolver service

Create a smaller runtime service, for example `WorkspaceService`, responsible for:

- resolving the current user's workspace record
- returning the derived template name and expected mount path
- confirming the session is only using the calling user's workspace

This service should not contain cloud admin logic itself; it should rely on the provisioned metadata.

## 4. Reconnect to existing claims

Update `backend/app/sandbox_lifecycle.py` so acquisition works like this:

1. look up active lease for the session or workspace scope
2. if `claim_name` exists, check whether that `SandboxClaim` still exists and is usable
3. if it does, reconnect to that existing claim instead of creating a fresh sandbox
4. if it does not, create a new `SandboxClaim` using the user's derived template
5. persist refreshed lease metadata

This is required for explicit continuity while a session stays active.

## 5. Move sandbox execution into `/workspace`

Update `backend/app/sandbox_manager.py` so the default execution context uses the mounted workspace:

- shell execution starts in `/workspace`
- Python execution runs with cwd `/workspace`
- optionally set `HOME=/workspace`

Without this, important files will continue to be written into non-persistent paths inside the sandbox container.

## 6. User-scoped template generation

The app should create deterministic per-user template names, for example:

- `python-runtime-template-user-<stable-id>`

For additional base template flavors, create deterministic user-derived template names
per base template (for example by suffixing a stable hash of the base template name).

Configured base template flavors can be supplied via
`SANDBOX_WORKSPACE_BASE_TEMPLATE_NAMES` (CSV, first entry is primary).

The derived template should:

- reference the per-user KSA
- mount the user's bucket through the GCS FUSE CSI driver
- mount the bucket at `/workspace`
- keep the rest of the base runtime settings from the existing template

## 7. Authz checks in the app

Add app-level authorization checks so:

- a session can only resolve the authenticated user's workspace
- sandbox admin endpoints never allow rebinding a lease to another user's workspace
- the backend never accepts a client-provided bucket path or template name for workspace access

The IAM boundary is primary, but app-level authz still matters.

## 8. User deprovisioning

Add a deprovisioning path, for example in `WorkspaceProvisioningService.delete_workspace(user_id)`.

It should:

1. terminate active sandbox claims for the user
2. delete the user-derived `SandboxTemplate`
3. delete the per-user KSA
4. remove the Workload Identity binding from the per-user GSA
5. remove IAM bindings from the per-user bucket
6. delete or archive bucket contents according to retention policy
7. delete the per-user bucket if allowed
8. delete the per-user GSA
9. mark the workspace metadata as deleted or tombstoned in the database

This flow should be idempotent and safe to retry after partial failure.

## Operational Flow

### First sandbox for a user

1. request arrives with authenticated `user_id`
2. app ensures workspace resources exist for that user
3. app resolves the per-user derived template for the requested base template flavor
4. app creates a `SandboxClaim` against that template
5. sandbox mounts `gs://<user-workspace-bucket>/` at `/workspace`

### Additional sandbox for the same user

1. app reuses the same workspace metadata
2. app either reconnects to an existing active claim or creates another claim against the same user-derived template
3. multiple sandboxes for that user can mount the same bucket concurrently

### Future call in the same session

1. app checks stored claim metadata
2. if the claim still exists, app reconnects to it
3. tool execution continues in the same sandbox instead of starting a fresh one

### User deletion or workspace deprovisioning

1. app blocks new sandbox acquisition for that workspace
2. app terminates active claims for that user
3. app removes the user-derived template and KSA
4. app removes Workload Identity and bucket IAM bindings
5. app archives or deletes workspace objects according to retention policy
6. app deletes the per-user bucket and GSA if policy allows

## Non-Goals And Caveats

- Cloud Storage FUSE is not POSIX compliant
- it is not a good fit for sqlite, git internals, file locking, or in-place patching heavy workflows
- concurrent writes to the same object from multiple mounts are not safe as a product guarantee
- this design persists user files in `/workspace`, not arbitrary package installs or root filesystem mutations elsewhere in the container
- the existing Pod Snapshot design should stay separate from this path; the repo already documents that Cloud Storage FUSE CSI sidecars are not supported with Pod Snapshots

## Recommended Product Constraints

Even though multiple sandboxes can mount the same user workspace, add guardrails:

- document `/workspace` as the only durable path
- recommend caches and temporary scratch writes under `/tmp`
- detect and warn when more than one active sandbox for the same user is running
- consider read-only secondary mounts for future collaboration or audit modes

## Suggested Implementation Order

1. Terraform/project IAM for dynamic per-user buckets and cluster-wide admin identity
2. backend workspace schema and repositories
3. backend provisioning service for per-user buckets, GSAs, KSAs, and IAM
4. dynamic user-derived sandbox templates with GCS FUSE mounts
5. reconnect-to-existing-claim logic in `sandbox_lifecycle.py`
6. default tool execution under `/workspace`
7. deprovisioning flow for user cleanup
8. admin and session APIs exposing workspace state
9. tests for provisioning, deprovisioning, mount isolation, and reconnect behavior

## Minimum Acceptance Criteria

- a new user gets a deterministic per-user bucket
- the sandbox pod for that user authenticates as a per-user GSA through Workload Identity
- that GSA can read and write only that bucket, not sibling user buckets
- a sandbox mounts the user's workspace at `/workspace`
- a second sandbox for the same user can mount the same workspace concurrently
- a future tool call in the same session reconnects to the existing `SandboxClaim` when it still exists
- if the claim is gone, the app creates a new sandbox that mounts the same user workspace
- deleting a user workspace removes or archives the user's cloud and cluster resources according to policy
