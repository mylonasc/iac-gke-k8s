Infrastructure Engineer Guide
=============================

Reviewed at: 2026-07-25 11:07:04 UTC

Audience
--------

This page is for engineers changing Terraform, GKE node pools, IAM, Secret
Manager containers, storage, or Agent Sandbox platform resources.

Start Here
----------

Use these files first:

.. code-block:: text

   iac/gke-secure-gpu-cluster/main.tf
   iac/gke-secure-gpu-cluster/variables.tf
   iac/gke-secure-gpu-cluster/terraform.v3.tfvars
   iac/gke-secure-gpu-cluster/identity.tf
   iac/gke-secure-gpu-cluster/storage.tf
   iac/gke-secure-gpu-cluster/secrets.tf
   iac/gke-secure-gpu-cluster/k8s/agent_sandbox.tf

Safe Change Workflow
--------------------

1. Identify whether the change is Terraform-owned, Helm-owned, or runtime-owned.
2. Change the smallest Terraform input/resource needed.
3. Run a plan from ``iac/gke-secure-gpu-cluster``.
4. Review whether the plan touches only intended resources.
5. Apply in the documented two-stage model if cluster/provider ordering is
   involved.
6. Verify with ``kubectl`` and, when applicable, a runtime smoke check.

Useful commands:

.. code-block:: bash

   cd iac/gke-secure-gpu-cluster
   terraform plan -var-file=terraform.v3.tfvars
   terraform plan -refresh-only -var-file=terraform.v3.tfvars

Provider Ordering
-----------------

Do not assume Terraform can create the cluster and immediately use the
Kubernetes provider in a single clean pass. The reliable model is:

* Phase A: create GCP APIs, IAM, cluster, and node pools.
* Refresh credentials and verify API reachability.
* Phase B: apply ``module.k8s``.

Node Pool Changes
-----------------

When changing node pools, check all of the following:

* Machine type and accelerator availability in ``europe-west4-a``.
* Quota for GPUs and machine families.
* Taints and tolerations used by live workloads.
* Labels used by ``nodeSelector``.
* Autoscaling minimums and expected idle cost.

The live cluster can legitimately show only ``primary-nodes`` as active if other
autoscaled pools are idle at zero nodes.

Agent Sandbox Changes
---------------------

When changing Agent Sandbox:

* Install or upgrade controller/CRDs before applying custom resources.
* Keep base templates generic and stable.
* Do not treat user-derived templates as Terraform objects.
* Keep router scheduling separate from sandbox runtime scheduling.
* Check whether the client supports router authentication before disabling
  compatibility mode.

Recommended checks:

.. code-block:: bash

   kubectl get pods -n agent-sandbox-system
   kubectl -n alt-default get sandboxtemplate,sandboxwarmpool
   kubectl -n alt-default get deploy,svc | grep sandbox-router
   kubectl -n alt-default get sandboxclaim,sandbox

Destroy Order
-------------

Destroy app workloads before destroying the cluster. Then destroy Terraform
Kubernetes resources while the API server still exists:

.. code-block:: bash

   cd iac/gke-secure-gpu-cluster
   terraform destroy -target=module.k8s -var-file=terraform.v3.tfvars
   terraform destroy -var-file=terraform.v3.tfvars

Risk Areas
----------

The main infrastructure risks are:

* Replacing a node pool that still has workload-specific scheduling assumptions.
* Applying ``module.k8s`` before the cluster API is reachable.
* Accidental cluster deletion when deletion protection is disabled.
* Recording secret values in Terraform state or committed files.
* Treating runtime/controller-created Sandbox resources as Terraform drift.
