Developer Guide
===============

Reviewed at: 2026-07-25 11:07:04 UTC

Audience
--------

This page is for application developers who need to understand how their code
uses the cluster platform without owning the cluster infrastructure.

What Developers Need To Know
----------------------------

The platform provides:

* A primary namespace, currently ``alt-default``.
* Workload Identity service accounts for workloads that need GCP access.
* Secret conventions for app runtime values.
* Ingress-nginx and auth support services.
* Agent Sandbox for isolated Python/shell execution.
* Specialized node pools for general, GPU, and sandbox workloads.

Application Naming Model
------------------------

Application source paths, Helm release names, Kubernetes workload names, and
public route names are app-owned compatibility decisions. Do not infer cluster
architecture from an app's historical name or route. Verify the current app
operation entrypoint under ``apps/`` before changing app workloads.

Consuming Agent Sandbox
-----------------------

Developers should treat Agent Sandbox as a platform API:

* Choose an approved base template such as ``python-runtime-template-small``.
* Let the backend/client create ``SandboxClaim`` resources as needed.
* Send execution/file traffic through ``sandbox-router-svc`` when in cluster
  mode.
* Do not schedule application code directly onto the gVisor pool unless that is
  the intended platform change.
* Do not manually create user-derived templates unless you are working on the
  workspace provisioning system.

Scheduling Guidance
-------------------

Application workloads should not assume they can run anywhere:

* General workloads may need tolerations for ``purpose=general-apps`` or
  ``purpose=general-apps-small``.
* GPU workloads must request ``nvidia.com/gpu`` and tolerate GPU taints.
* Sandbox runtime pods are created from templates and are expected to use the
  gVisor runtime class.

Secret Guidance
---------------

Application code should consume secrets from Kubernetes secret references or a
supported broker/service path. Do not commit real secret values. Do not add
secret values to Terraform variables.

When documenting a new secret, record only:

* Secret name.
* Expected key names.
* Producer and consumer.
* Whether it is required or optional.

Local Versus Cluster Mode
-------------------------

Developers may run code locally with local execution modes, but cluster mode has
additional dependencies:

* Agent Sandbox controller and CRDs.
* Router service availability.
* Namespace RBAC for creating and reading sandbox resources.
* Template and warm-pool availability.
* Image pull access for private runtime images.

Before blaming application code, verify the platform path:

.. code-block:: bash

   kubectl -n alt-default get sandboxtemplate,sandboxwarmpool
   kubectl -n alt-default get deploy,svc | grep sandbox-router
   kubectl -n alt-default get sandboxclaim,sandbox

Developer Safety Rules
----------------------

* Do not patch Terraform-owned resources directly unless it is an emergency.
* Do not rely on legacy raw manifests when the app has a Helm operational path.
* Keep workload names stable unless there is a coordinated migration plan.
* Treat runtime ``SandboxClaim`` and ``Sandbox`` objects as ephemeral.
* Keep app-level diagrams and docs aligned with that app's current source path,
  release mechanism, and deployed compatibility names.
