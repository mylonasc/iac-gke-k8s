Administrator Guide
===================

Reviewed at: 2026-07-25 11:07:04 UTC

Audience
--------

This page is for cluster administrators operating the live platform, checking
health, handling access, and distinguishing normal runtime state from incidents.

Health Model
------------

A healthy idle cluster should have:

* The GKE API reachable from ``kubectl``.
* At least the ``primary-nodes`` node Ready.
* System namespaces healthy.
* ``agent-sandbox-controller`` Running.
* Base ``SandboxTemplate`` resources present.
* ``sandbox-router-deployment`` rolled out when runtime is enabled.
* No unexpected Pending pods.

Baseline Checks
---------------

.. code-block:: bash

   kubectl config current-context
   kubectl get nodes -o wide -L cloud.google.com/gke-nodepool,workload-isolation,purpose
   kubectl get pods -A
   kubectl get pods -A --field-selector=status.phase=Pending
   kubectl -n agent-sandbox-system get pods
   kubectl -n alt-default get sandboxtemplate,sandboxwarmpool,sandboxclaim,sandbox
   kubectl -n alt-default rollout status deploy/sandbox-router-deployment

Secrets Checks
--------------

Check names and keys only. Do not decode or print values.

.. code-block:: bash

   kubectl -n alt-default get secret <app-runtime-secret> dockerhub-regcred
   kubectl -n alt-default describe secret <app-runtime-secret>
   kubectl -n alt-default describe secret dockerhub-regcred

Common platform/app support secret patterns include:

* An app runtime secret containing API/auth configuration for a specific app.
* ``dockerhub-regcred``
* A database credentials secret when Postgres mode is enabled for an app.
* A WireGuard configuration secret when private database access is enabled for an app.

The live cluster may include additional app-specific keys used by support
services. Record expected key names in the secret inventory, but never record
secret values.

Normal Runtime State
--------------------

These conditions are not automatically incidents:

* GPU and gVisor node pools are listed by GKE but have zero active nodes.
* ``SandboxWarmPool`` replicas are scaled to zero for cost control.
* No ``SandboxClaim`` or ``Sandbox`` resources exist while no sessions are
  active.
* User-derived ``SandboxTemplate`` resources remain after workspace provisioning.

Incident Signals
----------------

Investigate when you see:

* Pending sandbox pods with unsatisfied gVisor taints/selectors.
* ``sandbox-router-deployment`` unavailable while cluster-mode execution is
  expected.
* Image pull failures for private images.
* Missing Workload Identity annotations on expected service accounts.
* Secret key absence for a workload that previously started successfully.
* GPU pods pending with quota or accelerator errors.

Admin Boundaries
----------------

Admins may scale or inspect runtime objects during operations, but should avoid
making long-term changes directly to Terraform-owned resources. If an emergency
change is made with ``kubectl`` or ``gcloud``, record it and reconcile it back
into Terraform or Helm.

Live Helm Caveat
----------------

The inspected cluster included a Helm release named ``alt-default-admin-apps``
that manages admin/authz/user-secrets support resources. No chart for that
release was found in this checkout. Treat that as a documentation/source-control
gap until the chart is added or the live resources are moved to an in-repo
source of truth.
