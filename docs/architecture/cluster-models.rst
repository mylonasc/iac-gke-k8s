Cluster Models
==============

Reviewed at: 2026-07-25 11:07:04 UTC

This page presents several views of the cluster so an infrastructure engineer can
quickly reason about capacity, isolation, identity, routing, and runtime state.

Capacity Model
--------------

The cluster uses explicit node pools for distinct workload classes.

.. list-table::
   :header-rows: 1

   * - Node pool
     - Machine type
     - Workload intent
     - Scheduling controls
   * - ``primary-nodes``
     - ``e2-standard-2``
     - Baseline/system/platform services.
     - Min/max 1 in current config.
   * - ``general-purpose-pool``
     - ``e2-medium``
     - Standard application workloads.
     - Label and taint ``purpose=general-apps``.
   * - ``general-purpose-pool-small``
     - ``e2-small`` spot
     - Cost-focused app capacity.
     - Label and taint ``purpose=general-apps-small``.
   * - ``gpu-spot-pool-a``
     - ``g2-standard-4`` with ``nvidia-l4``
     - L4 GPU workloads.
     - GPU and spot taints.
   * - ``gpu-spot-pool-b``
     - ``n1-standard-4`` with ``nvidia-tesla-t4``
     - T4 GPU workloads.
     - GPU and spot taints.
   * - ``gvisor-sandbox-pool``
     - ``e2-medium`` spot with gVisor sandbox config
     - Isolated sandbox runtime pods.
     - Label ``workload-isolation=gvisor`` and taint ``sandbox.gke.io/runtime=gvisor``.

Scheduling Model
----------------

The platform uses labels, taints, tolerations, and runtime classes together:

* General app workloads tolerate the general-purpose taints when they are
  allowed to run on those pools.
* GPU workloads request ``nvidia.com/gpu`` and tolerate GPU pool taints.
* Sandbox runtime pods set ``runtimeClassName: gvisor``, select
  ``workload-isolation=gvisor``, and tolerate ``sandbox.gke.io/runtime=gvisor``.
* The sandbox router runs outside the gVisor pool so routing/control traffic does
  not consume isolated runtime capacity.

Isolation Model
---------------

Sandbox isolation is layered:

* Dedicated gVisor-capable node pool.
* RuntimeClass ``gvisor`` for sandbox pods.
* Sandbox runtime service account with ``automountServiceAccountToken=false``.
* NetworkPolicy allowing runtime internet egress while blocking private ranges.
* NetworkPolicy allowing router ingress from the expected backend client only.
* Router compatibility mode can allow unauthenticated clients, so network policy
  is an important compensating control.

Identity Model
--------------

Workload Identity maps Kubernetes service accounts to Google service accounts:

.. list-table::
   :header-rows: 1

   * - Kubernetes service account
     - Google service account
     - Purpose
   * - ``default-ksa``
     - ``default-service-account@<project>.iam.gserviceaccount.com``
     - Default workload identity principal.
   * - ``sandbox-workspace-admin-ksa``
     - ``sandbox-workspace-admin@<project>.iam.gserviceaccount.com``
     - Workspace provisioning and admin operations.
   * - ``sandbox-runtime-ksa``
     - No GSA mapping in base Terraform.
     - Runtime sandbox pod identity with service account token disabled.

Secret Model
------------

The repo separates secret containers from secret values:

* Terraform creates Secret Manager secret containers.
* Secret values are added out of band by CI or operators.
* Kubernetes app secrets are expected in the consuming namespace.
* Documentation may list secret names and keys, but must not record secret
  values.

Runtime Model
-------------

Agent Sandbox introduces runtime resources beyond ordinary Deployments:

* ``SandboxTemplate`` defines the pod template for sandbox runtime pods.
* ``SandboxWarmPool`` optionally pre-creates idle sandboxes.
* ``SandboxClaim`` asks the controller for an isolated runtime.
* ``Sandbox`` represents the bound runtime backing a claim.
* The router forwards execution/file requests to the concrete sandbox runtime.

Base templates are Terraform-managed. User-derived templates and live claims are
runtime/application state.

Ingress Model
-------------

The inspected cluster uses ``ingress-nginx`` with host
``magarathea.ddns.net``. Platform support services such as Dex and oauth2-proxy
are present in dedicated namespaces. App-specific Ingress resources should be
managed by their app release mechanism rather than Terraform root infrastructure.
