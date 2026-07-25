IaC Model
=========

Reviewed at: 2026-07-25 11:07:04 UTC

Repository Layout
-----------------

The infrastructure code is organized around one primary Terraform stack:

.. code-block:: text

   iac/gke-secure-gpu-cluster/
       main.tf                 GKE cluster and node pools
       variables.tf            Input defaults and feature toggles
       terraform.v3.tfvars     Active environment values
       europe_backend.tf       GCS remote state backend
       identity.tf             Google service accounts and IAM bindings
       secrets.tf              Secret Manager containers
       storage.tf              Sandbox workspace bucket
       outputs.tf              Cluster outputs
       scripts/                Deployment helpers
       k8s/                    Terraform child module for Kubernetes resources

Root Module Responsibilities
----------------------------

The root module owns long-lived GCP and GKE infrastructure:

* Required Google project APIs.
* GKE Standard control plane.
* Explicit node pools.
* Workload Identity Google service accounts and IAM bindings.
* Secret Manager secret containers.
* Shared Cloud Storage bucket for sandbox workspaces.
* Wiring into the Kubernetes child module.

Kubernetes Child Module Responsibilities
----------------------------------------

The ``k8s`` child module owns base Kubernetes resources that require a reachable
cluster API:

* The primary workload namespace.
* Workload Identity Kubernetes service accounts.
* Optional Docker registry pull secret.
* Agent Sandbox controller and extension manifests loaded from the configured
  upstream release.
* Base ``SandboxTemplate`` resources.
* Base ``SandboxWarmPool`` resource.
* Sandbox router ``Service`` and ``Deployment``.
* Sandbox network policies.

Two-Stage Apply Model
---------------------

The preferred lifecycle is a two-stage apply:

1. Apply GCP resources and the GKE cluster.
2. Refresh cluster credentials and optionally upload secret versions.
3. Apply ``module.k8s``.

The helper script is:

.. code-block:: bash

   cd iac/gke-secure-gpu-cluster
   ./scripts/deploy_with_secrets.sh --project gke-gpu-project-473410 --var-file terraform.v3.tfvars
   ./scripts/deploy_with_secrets.sh --execute --project gke-gpu-project-473410 --var-file terraform.v3.tfvars

For fresh Agent Sandbox installs, CRDs must exist before custom resources such as
``SandboxTemplate`` and ``SandboxWarmPool``. The helper supports a two-pass
bootstrap for this case.

State Model
-----------

Terraform state is remote and configured in ``europe_backend.tf``:

.. code-block:: text

   bucket = "gcp-ops-data-tfstate-europe"
   prefix = "terraform/state"

Best practices for this repo:

* Treat remote state as authoritative for Terraform-owned resources.
* Prefer variable/resource changes plus ``terraform plan`` over manual state
  edits.
* Destroy ``module.k8s`` before destroying the cluster when performing teardown.
* Do not store secret values in Terraform variables or committed files.

Feature Toggles
---------------

Important toggles in ``variables.tf`` and ``terraform.v3.tfvars`` include:

.. list-table::
   :header-rows: 1

   * - Variable
     - Meaning
   * - ``enable_gvisor_pool``
     - Creates the dedicated gVisor node pool.
   * - ``enable_agent_sandbox``
     - Installs Agent Sandbox controller and CRDs.
   * - ``enable_agent_sandbox_runtime``
     - Creates runtime custom resources after CRDs exist.
   * - ``enable_agent_sandbox_pydata_template``
     - Creates an additional pydata sandbox template.
   * - ``enable_gcs_fuse_csi_driver``
     - Enables the GCS FUSE CSI driver addon on the GKE cluster.
   * - ``enable_sandbox_workspace_bucket``
     - Creates the shared workspace bucket.

Drift Model
-----------

Not every live Kubernetes object should be forced back to Terraform defaults.
The expected model is:

* Terraform-owned fields should converge after ``terraform plan`` and
  ``terraform apply``.
* App release fields should be managed by Helm or the app's operation scripts.
* Runtime fields such as warm-pool replica counts may be operationally adjusted.
* Controller-created resources such as live ``Sandbox`` objects and user-derived
  ``SandboxTemplate`` objects are runtime state, not Terraform drift.
