Status And Boundaries
=====================

Reviewed at: 2026-07-25 11:07:04 UTC

Purpose
-------

This page states what this architecture documentation considers current, what is
managed by which tool, and where the repo currently differs from the live
cluster.

Source Of Truth
---------------

The current infrastructure source of truth is:

.. list-table::
   :header-rows: 1

   * - Area
     - Source
     - Notes
   * - GCP and GKE infrastructure
     - ``iac/gke-secure-gpu-cluster``
     - Terraform root module.
   * - Terraform variables for the active environment
     - ``iac/gke-secure-gpu-cluster/terraform.v3.tfvars``
     - Active checked-in var file for the inspected cluster.
   * - Terraform remote state backend
     - ``iac/gke-secure-gpu-cluster/europe_backend.tf``
     - GCS backend bucket and prefix.
   * - Kubernetes platform resources
     - ``iac/gke-secure-gpu-cluster/k8s``
     - Terraform child module using the Kubernetes provider.
   * - Agent Sandbox platform/runtime base resources
     - ``iac/gke-secure-gpu-cluster/k8s/agent_sandbox.tf``
     - Controller install, CRDs, base templates, router, network policies.
   * - Application deployment mechanisms
     - App-owned directories under ``apps/``
     - App details are out of scope for the core cluster architecture.
   * - Operational runbook
     - ``docs/runbooks/full-stack-lifecycle.md``
     - Canonical lifecycle commands.

Management Boundaries
---------------------

Use these boundaries when changing the platform:

.. list-table::
   :header-rows: 1

   * - Managed by
     - Owns
     - Does not own
   * - Terraform root module
     - GKE cluster, node pools, project APIs, IAM, Secret Manager containers, workspace bucket.
     - Application Deployments, app release versions, live SandboxClaims.
   * - Terraform ``module.k8s``
     - Base namespace/service accounts, Agent Sandbox install, base SandboxTemplates, base warm pool, router, network policies.
     - Per-user workspace templates, live SandboxClaims, app Helm releases.
   * - Helm app releases
     - Application Deployments, Services, Ingresses, PVCs for app stacks.
     - GKE node pools, Workload Identity IAM, Agent Sandbox CRDs.
   * - Operators/admin tools
     - Runtime scaling, emergency rollouts, secret values, user/runtime state.
     - Long-term Terraform-owned desired state.

Current Corrections To Older Docs
---------------------------------

Some older documents still use names that are no longer the current repo layout:

.. list-table::
   :header-rows: 1

   * - Older reference
     - Current interpretation
   * - Former primary-app source path references
     - Current app-specific source paths and release mechanisms should be verified under ``apps/`` before changing app workloads.
   * - Raw manifests for apps that also have Helm operational paths
     - Treat the documented app operation entrypoint as current and raw manifests as legacy unless that app states otherwise.
   * - ``cluster-user-secrets-broker`` directory references
     - Current repo directory is ``apps/cluster-user-secrets-manager``; live resource names still use ``cluster-user-secrets-broker-*``.
   * - Multiple authz-related app directories
     - Check the live app configuration before assuming which app owns authorization policy.

Live Cluster Notes
------------------

The live cluster check found these relevant differences from the checked-in repo:

* Only the ``primary-nodes`` pool had a running node during inspection; the other
  autoscaled pools existed but were idle at zero nodes.
* The primary app backend matched the repo Helm values at version ``0.6.32``.
* The primary app frontend live image was version ``0.6.29`` while the repo Helm
  values referenced a git-based frontend tag.
* The live cluster included a Helm release named ``alt-default-admin-apps`` for
  admin/authz/user-secrets support workloads. No matching chart was found in this
  checkout.
* Agent Sandbox warm pools were live-scaled to ``0`` even though the Terraform
  var file declares ``agent_sandbox_warm_pool_replicas = 2``. Terraform marks the
  warm-pool replica field as computed, so this is an operational setting rather
  than a normal Terraform drift concern.
* Many user-derived ``SandboxTemplate`` resources existed. These are expected
  runtime/application artifacts and are not base Terraform objects.

Secrets Policy
--------------

This documentation never records secret values. Secret names and expected key
names may be documented. Values are managed out of band by operators or CI.
