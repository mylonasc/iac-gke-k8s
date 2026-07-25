High-Level Architecture
=======================

Reviewed at: 2026-07-25 11:07:04 UTC

Summary
-------

This repository provisions and operates a GKE Standard cluster for isolated agent
execution workloads. The platform combines conventional application node pools,
GPU-capable node pools, and a dedicated gVisor sandbox pool. Terraform owns the
stable cloud and base Kubernetes platform; Helm and operators manage application
rollouts and live runtime state.

The cluster is designed around three core needs:

* Reliable baseline capacity for system and always-on platform services.
* Specialized capacity for GPU workloads and isolated sandbox execution.
* Clear separation between infrastructure desired state and runtime/application
  state.

Default Environment
-------------------

.. list-table::
   :header-rows: 1

   * - Item
     - Value
   * - GCP project
     - ``gke-gpu-project-473410``
   * - Cluster name
     - ``gpu-spot-cluster``
   * - Location
     - ``europe-west4-a``
   * - Primary namespace
     - ``alt-default``
   * - Terraform backend
     - GCS bucket ``gcp-ops-data-tfstate-europe``, prefix ``terraform/state``

Architecture At A Glance
------------------------

The main infrastructure flow is:

.. code-block:: text

   Terraform root module
       -> GCP APIs, IAM, Secret Manager containers, GCS bucket
       -> GKE Standard cluster
       -> node pools
       -> Kubernetes child module
       -> namespace, service accounts, Agent Sandbox platform/runtime

Applications are deployed after the platform exists. They should consume the
platform through stable Kubernetes APIs and Services rather than re-creating
platform primitives.

Major Platform Layers
---------------------

.. list-table::
   :header-rows: 1

   * - Layer
     - Responsibility
     - Source
   * - Cloud foundation
     - APIs, cluster, node pools, IAM, storage, Secret Manager containers.
     - Terraform root module.
   * - Kubernetes platform
     - Namespace, Workload Identity KSAs, Agent Sandbox install/runtime.
     - Terraform ``module.k8s``.
   * - Runtime isolation
     - gVisor runtime class, sandbox templates, warm pool, router, network policy.
     - Terraform plus runtime controllers.
   * - Application operations
     - Helm releases, app rollouts, app PVCs, route exposure.
     - App-specific Helm/scripts.
   * - Live runtime state
     - SandboxClaims, Sandboxes, user-derived templates, operational scale changes.
     - Controllers and operators.

Key Design Choices
------------------

The cluster uses GKE Standard rather than Autopilot because the platform needs
explicit control over node pools, GPU pools, taints, and gVisor isolation.

Node pools are specialized by workload class. This avoids mixing long-running
system services, app workloads, GPU workloads, and untrusted sandbox execution on
the same capacity class.

The Kubernetes provider is applied after the cluster exists. This two-stage model
avoids common Terraform provider-ordering failures where the provider attempts to
connect to a cluster endpoint that does not exist yet.

Secret Manager containers are Terraform-managed, but secret values are not stored
in Terraform code. Values are added out of band by operators or CI.

Runtime resources that change frequently, such as warm-pool replica counts, may
be intentionally left for live operations rather than strict Terraform ownership.
