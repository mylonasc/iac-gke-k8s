# Sandboxed Session Persistence And Snapshots

This document records the current live cluster state for sandboxing, the IaC changes required to support native GKE Pod Snapshots, the latest snapshot API surface, and the recommended design for process-level persistent sandbox sessions in `apps/sandboxed-react-agent`.

## Current live state

The following was verified against the current kube context (2026-04-10):

- Context: `gke_gke-gpu-project-473410_europe-west4-a_gpu-spot-cluster`
- Kubernetes server version: `v1.34.4-gke.1193000`
- Agent Sandbox CRDs installed:
  - `sandboxes.agents.x-k8s.io`
  - `sandboxclaims.extensions.agents.x-k8s.io`
  - `sandboxtemplates.extensions.agents.x-k8s.io`
  - `sandboxwarmpools.extensions.agents.x-k8s.io`
- Installed Agent Sandbox controller form: `StatefulSet`
- Installed Agent Sandbox controller image: `registry.k8s.io/agent-sandbox/agent-sandbox-controller:v0.1.0`
- Live runtime templates in `alt-default`:
  - `python-runtime-template`
  - `python-runtime-template-small`
  - `python-runtime-template-large`
  - `python-runtime-template-pydata`
  - plus user-derived workspace templates (`python-runtime-template-user-*`)
- Live runtime templates use:
  - `runtimeClassName: gvisor`
  - base templates use `serviceAccountName: sandbox-runtime-ksa`
  - user-derived templates use per-user KSAs created by workspace provisioning
  - `nodeSelector.workload-isolation: gvisor`

Important negative finding:

- The GKE Pod Snapshot API is not enabled in the cluster right now.
- `kubectl api-resources --api-group=podsnapshot.gke.io` returned no resources.
- These CRDs are absent:
  - `podsnapshots.podsnapshot.gke.io`
  - `podsnapshotmanualtriggers.podsnapshot.gke.io`
  - `podsnapshotpolicies.podsnapshot.gke.io`
  - `podsnapshotstorageconfigs.podsnapshot.gke.io`

## Relevant repo state

### Terraform / Kubernetes

Current IaC references:

- Cluster definition: `iac/gke-secure-gpu-cluster/main.tf`
- Agent Sandbox install and templates: `iac/gke-secure-gpu-cluster/k8s/agent_sandbox.tf`
- Cluster variables: `iac/gke-secure-gpu-cluster/variables.tf`
- Active tfvars: `iac/gke-secure-gpu-cluster/terraform.v3.tfvars`

Important findings:

- Terraform default `agent_sandbox_version` is still `v0.1.0` in `iac/gke-secure-gpu-cluster/variables.tf`.
- That matches the live controller image and explains why the cluster is still on the older StatefulSet-based controller.
- The cluster already has Workload Identity enabled via `workload_identity_config`.
- The cluster already has a dedicated gVisor node pool via `node_config.sandbox_config { sandbox_type = "gvisor" }`.
- The gVisor pool machine type is currently `e2-medium` by default.

### Backend package versions

The app backend is already aligned with the newer Python client release:

- `apps/sandboxed-react-agent/backend/uv.lock` pins `k8s-agent-sandbox` `0.2.1`

That means the app dependency graph already knows about the `PodSnapshotSandboxClient`, but the cluster and IaC do not yet provide the required GKE Pod Snapshot APIs.

### Current app behavior relevant to this doc

The app now supports persistent workspace routing and reliability UX improvements:

- per-user workspace persistence through GCS FUSE-backed derived templates
- per-template-flavor derived template mapping for persistent sessions
- optional persistent-to-transient fallback with explicit runtime status in session APIs

This is file/workspace persistence, not full process/memory snapshot persistence.

## Why snapshots matter for this app

The current app persists:

- chat/session history in SQLite
- lease metadata in SQLite
- exported assets in the app asset store

The current app does not persist or restore:

- the live sandbox runtime handle
- downloaded files left in the sandbox root filesystem
- installed packages added inside the sandbox during a session

For this app, GKE Pod Snapshots are a strong fit because they are designed to preserve:

- Pod memory state
- root filesystem changes
- `emptyDir` / `tmpfs` changes

That is much closer to the desired user experience of “resume my sandboxed process later” than the current workspace + lease model.

## IaC changes required for native snapshot support

These are the changes needed at the platform layer before the app can use native sandbox snapshots.

### 1. Upgrade Agent Sandbox install to `v0.2.1` or newer

Current state:

- live controller is `v0.1.0`
- Terraform default is `v0.1.0`

Recommended change:

- set `agent_sandbox_version = "v0.2.1"` or later

Why:

- aligns cluster installation with the backend Python client version already in use
- aligns the repo with the release that documents Python SDK snapshot support
- moves off the old StatefulSet-based install to the newer Deployment-based controller packaging

Note:

- This is not what enables GKE Pod Snapshots by itself.
- Pod Snapshots are a GKE feature, not an Agent Sandbox CRD feature.
- The upgrade is still recommended to reduce version skew.

### 2. Enable GKE Pod Snapshots on the cluster

Current state:

- `podsnapshot.gke.io` APIs are not present

Required change:

- enable the cluster feature flag equivalent to:

```bash
gcloud beta container clusters update CLUSTER_NAME \
  --enable-pod-snapshots \
  --location=CONTROL_PLANE_LOCATION
```

Terraform note:

- this repo does not currently configure any Pod Snapshot feature flag in `google_container_cluster.primary`
- if the Terraform provider version you use exposes a native field for Pod Snapshots, that should be preferred
- if not, add a temporary explicit enablement step outside the current `google_container_cluster` block, for example a controlled `gcloud beta container clusters update --enable-pod-snapshots` step in your deployment workflow

Suggested repo policy:

- keep the desired state documented in Terraform variables and docs even if the provider needs a temporary imperative step
- once provider support exists, move the feature enablement fully into Terraform

### 3. Move the gVisor pool off `E2`

Current state:

- `gvisor_pool_machine_type = "e2-medium"`

Required change:

- choose a non-`E2` machine type for the gVisor pool

Why:

- GKE Pod Snapshots do not support `E2` machine types
- restore compatibility requires the same machine series and architecture as the source Pod
- GKE explicitly excludes `E2` because of its dynamic underlying architecture

This is a hard blocker for snapshot-based restore on the current gVisor node pool.

### 4. Add a GCS bucket for Pod Snapshot storage

Current state:

- no snapshot storage bucket is defined in Terraform for this feature

Required bucket properties:

- same location as the cluster
- hierarchical namespace enabled
- uniform bucket-level access enabled
- soft delete disabled

Representative create command from GKE docs:

```bash
gcloud storage buckets create "gs://BUCKET_NAME" \
  --uniform-bucket-level-access \
  --enable-hierarchical-namespace \
  --soft-delete-duration=0d \
  --location="LOCATION"
```

Recommended Terraform shape:

- add a dedicated bucket resource for sandbox snapshots
- keep one bucket per environment
- use managed folders or prefixed paths per namespace/app if you want per-tenant separation

### 5. Grant IAM to the runtime KSA and GKE service agent

Current state:

- runtime Pods use `sandbox-runtime-ksa`
- no snapshot-specific bucket IAM is configured in the repo

Required IAM:

- for the sandbox runtime KSA principal:
  - `roles/storage.bucketViewer`
  - `roles/storage.objectUser`
- for the GKE service agent:
  - `roles/storage.objectUser` on the bucket

Why:

- the snapshot system needs workload access to store and access snapshot data
- the GKE-managed components need bucket access for snapshot lifecycle operations and cleanup

Recommended principal target:

- the Workload Identity principal for `ns/alt-default/sa/sandbox-runtime-ksa`

### 6. Create `PodSnapshotStorageConfig`

Current state:

- no `PodSnapshotStorageConfig` exists

Required new manifest:

```yaml
apiVersion: podsnapshot.gke.io/v1alpha1
kind: PodSnapshotStorageConfig
metadata:
  name: sandbox-session-storage
spec:
  snapshotStorageConfig:
    gcs:
      bucket: <snapshot-bucket>
      path: sandboxes/alt-default
```

Recommended Terraform ownership:

- manage this CR with `kubernetes_manifest`
- add an explicit dependency on cluster feature enablement and bucket IAM

### 7. Create `PodSnapshotPolicy`

Current state:

- no `PodSnapshotPolicy` exists

Recommended initial policy mode:

- `triggerConfig.type: manual`
- `triggerConfig.postCheckpoint: resume`

Why manual first:

- the app needs to checkpoint at controlled times
- it aligns better with per-session quotas and user-triggered persistence
- it avoids hidden snapshot churn from workload-driven checkpointing

Recommended label strategy:

- add a dedicated label to sandbox runtime templates, for example:
  - `snapshot-profile: sandbox-session`
- target the policy selector to that label

Why a dedicated label matters:

- the current template labels are mostly about networking and generic template identity
- a dedicated snapshot label gives a stable policy binding that is separate from other scheduling or app concerns

Representative policy:

```yaml
apiVersion: podsnapshot.gke.io/v1alpha1
kind: PodSnapshotPolicy
metadata:
  name: sandbox-session-manual
  namespace: alt-default
spec:
  storageConfigName: sandbox-session-storage
  selector:
    matchLabels:
      snapshot-profile: sandbox-session
  triggerConfig:
    type: manual
    postCheckpoint: resume
```

### 8. Add snapshot labels or annotations to the sandbox templates

Current state:

- live templates do not include snapshot-specific metadata

Recommended change:

- add snapshot policy selection labels to all templates that should support persistence
- keep ephemeral-only templates without that label if you want separate cost controls

Suggested split:

- persistent-capable templates:
  - `python-runtime-template`
  - `python-runtime-template-pydata`
- optional persistent-capable templates if cost allows:
  - `python-runtime-template-small`
  - `python-runtime-template-large`

### 9. Consider bucket lifecycle and quota policy at IaC level

Recommended additions:

- GCS lifecycle rules for old snapshots if app-level retention is not enough
- optionally separate bucket prefixes by environment and namespace
- document expected storage growth from memory + rootfs snapshots

## Latest snapshot API surface

The latest upstreams relevant here are:

- Agent Sandbox Python client `0.2.1`
- GKE Pod Snapshots API

### Agent Sandbox Python client

The `0.2.1` Python package includes:

- `k8s_agent_sandbox.gke_extensions.PodSnapshotSandboxClient`

What it actually supports in code:

- `snapshot(trigger_name)`

What it does not currently expose as a dedicated SDK method:

- `restore()`

Relevant files:

- `clients/python/agentic-sandbox-client/k8s_agent_sandbox/gke_extensions/podsnapshot_client.py`
- `clients/python/agentic-sandbox-client/k8s_agent_sandbox/gke_extensions/podsnapshot.md`

Important note:

- the markdown/docs say “restore” is supported, but the `v0.2.1` Python extension only implements snapshot creation
- restore is currently a GKE-side concept that the app must orchestrate via Kubernetes resources

### GKE Pod Snapshot resources

API group:

- `podsnapshot.gke.io/v1alpha1`

Important resource kinds:

- `PodSnapshotStorageConfig`
- `PodSnapshotPolicy`
- `PodSnapshotManualTrigger`
- `PodSnapshot`

#### `PodSnapshotStorageConfig`

Purpose:

- defines the storage backend used by snapshots

Key fields:

- `spec.snapshotStorageConfig.gcs.bucket`
- `spec.snapshotStorageConfig.gcs.path` optional

#### `PodSnapshotPolicy`

Purpose:

- binds snapshot behavior to matching Pods

Key fields:

- `spec.storageConfigName`
- `spec.selector.matchLabels` or `matchExpressions`
- `spec.triggerConfig.type` = `manual` or `workload`
- `spec.triggerConfig.postCheckpoint` = `resume` or `stop`
- optional `spec.retentionConfig.lastAccessTimeout`

#### `PodSnapshotManualTrigger`

Purpose:

- manually requests a snapshot for a target Pod

Shape:

```yaml
apiVersion: podsnapshot.gke.io/v1alpha1
kind: PodSnapshotManualTrigger
metadata:
  name: session-123-savepoint
  namespace: alt-default
spec:
  targetPod: sandbox-pod-name
```

Observed status fields used by the upstream Python extension:

- `status.conditions[]`
- `status.snapshotCreated.name`

Success condition used in the client:

- `type=Triggered`
- `status=True`
- `reason=Complete`

#### `PodSnapshot`

Purpose:

- represents the actual created snapshot object

Important fields / conditions:

- `status.conditions`
- `status.lastAccessTime`
- `status.storageStatus.gcs.observedGCSPath`
- must have a `Ready` condition to be forced during restore

## Restore semantics

GKE restore is not a “reattach to old client” operation.

It works by starting a new compatible Pod and restoring Pod state into it.

Important behavior:

- default behavior restores the latest compatible `PodSnapshot`
- to force a specific snapshot, the new Pod can be annotated with:

```yaml
metadata:
  annotations:
    podsnapshot.gke.io/ps-name: "POD_SNAPSHOT_NAME"
```

Important restore caveats:

- the new Pod gets a new Pod/IP/hostname identity
- active network connections are lost
- listening sockets continue
- wall clock time jumps forward
- environment variable updates are not rewritten directly into the restored process state
- Cloud Storage FUSE CSI sidecar is not supported with Pod Snapshots

Compatibility constraints that matter here:

- same machine series and CPU architecture
- same gVisor kernel version
- same GPU driver version for GPU workloads
- `E2` machine types are not supported

## Recommended app design

The app should not try to treat Pod Snapshots as a minor extension of the current lease table.

It should treat them as a first-class session persistence subsystem.

### Core design goal

Persist user session sandboxes natively in Kubernetes so that user-created workspace state survives:

- downloaded files
- installed packages
- root filesystem mutations
- interpreter memory/process state when GKE restore can preserve it

### Recommended architecture

Introduce a dedicated app service, separate from the current lease-only runtime layer:

- `SessionSnapshotService`
- `PersistentSandboxSessionService`

Responsibilities:

- create manual snapshots for a session sandbox
- persist snapshot metadata per app session
- decide whether a session is resumed from an active lease or from a stored snapshot
- create a restorable sandbox for the session
- enforce per-user/per-session quotas on snapshots, active sandboxes, and restore frequency

### Why not rely only on `SandboxClient`

Current limitation:

- `k8s-agent-sandbox` `0.2.1` exposes snapshot creation, but not restore orchestration
- the current `SandboxClient` is centered around `SandboxClaim` lifecycle

That is not enough for precise per-session restore, because forcing a specific snapshot uses Pod annotations on the new Pod.

### Suggested restore strategy for this app

Use one of these approaches.

#### Preferred: session-specific template clone + `SandboxClaim`

For restore of a specific session snapshot:

1. Copy a base `SandboxTemplate` into a session-scoped derived template.
2. Add:
   - the exact snapshot annotation `podsnapshot.gke.io/ps-name`
   - a stable label tying the sandbox back to the app session and user
3. Create a `SandboxClaim` against that derived template.
4. Use the router exactly as today once the sandbox becomes ready.

Why this is the best fit for the current app:

- it preserves compatibility with the current router and `SandboxClaim`-based flow
- it avoids requiring immediate router changes
- it allows exact per-session restore instead of ambiguous “latest compatible snapshot” restore

Operational notes:

- derived templates should be garbage-collected when the session is deleted or re-based
- template names should be deterministic and user/session scoped

#### Alternative: direct `Sandbox` management

Manage `Sandbox` objects directly instead of `SandboxClaim` for persistent sessions.

Pros:

- direct control over `podTemplate.metadata.annotations`
- no template cloning required

Cons:

- higher divergence from the current client/router contract
- likely more app-specific integration work

### Snapshot lifecycle policy

Recommended initial policy:

- `manual` snapshots only
- `postCheckpoint: resume`

Application flows:

1. Active session
   - sandbox is reused through the existing lease model

2. Savepoint / suspend
   - create `PodSnapshotManualTrigger`
   - wait until `status.snapshotCreated.name` resolves
   - persist snapshot metadata in app DB
   - optionally release the live lease after snapshot success

3. Future resume
   - if active lease still exists, reuse it
   - otherwise restore from the latest approved session snapshot
   - create a fresh sandbox only if no usable snapshot exists

### Quotas and usage limits

The app should enforce quotas before creating snapshots or new persistent sessions.

Suggested per-user limits:

- max active sandbox sessions
- max retained snapshots
- max restores per hour/day
- max snapshot age
- max total snapshot storage estimate

Suggested per-session limits:

- latest snapshot only, or latest `N`
- snapshot cooldown interval
- idle timeout before automatic release

Enforcement points:

- before creating a new persistent sandbox
- before creating a manual snapshot
- before restoring from a snapshot

### App persistence model changes

Add durable session-linked snapshot metadata, for example:

- `snapshot_id` / PodSnapshot name
- `trigger_name`
- `snapshot_created_at`
- `snapshot_status`
- `restored_from_snapshot_id`
- `restored_at`
- `persistent_template_name` if using template clones
- `snapshot_error`

### Recommended implementation order

1. Platform/IaC
   - enable GKE Pod Snapshots
   - move gVisor pool off `E2`
   - add bucket + IAM + `PodSnapshotStorageConfig` + `PodSnapshotPolicy`
   - upgrade Agent Sandbox install to `v0.2.1+`

2. Backend model
   - add persistent snapshot/session metadata tables

3. Snapshot service
   - create manual snapshots and persist metadata

4. Restore path
   - implement session-specific template cloning or direct Sandbox creation

5. Quotas and authz
   - enforce per-user and per-session usage controls

6. UI
   - expose snapshot status and resume controls

## Summary

Today the app supports reusable session leases and persistent `/workspace` file state, but not full process-level persistent sandbox sessions.

The main blockers are:

- Agent Sandbox cluster install still on `v0.1.0`
- GKE Pod Snapshot feature not enabled
- no `podsnapshot.gke.io` resources in the cluster
- gVisor pool uses unsupported `E2` machine types
- no snapshot storage bucket, IAM, or policy resources in Terraform
- app has no snapshot metadata or restore orchestration yet

Once those platform changes are made, GKE Pod Snapshots are the most native Kubernetes/GKE path to persist user sandbox workspaces for this app.
