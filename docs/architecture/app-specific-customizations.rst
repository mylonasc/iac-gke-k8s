Application-Specific Customizations
===================================

Reviewed at: 2026-07-25 11:07:04 UTC

Purpose
-------

The core cluster architecture is intentionally application-neutral. Some live
workloads still need platform customizations that are best understood as
app-specific extensions rather than generic cluster behavior.

This page documents those extension patterns so infrastructure engineers can
recognize them without mixing them into the baseline GKE/Terraform model.

Customization Boundary
----------------------

An app-specific customization is acceptable when it satisfies all of these
conditions:

* The cluster exposes a reusable platform primitive.
* The app opts into that primitive through Helm values, manifests, RBAC, or
  runtime configuration.
* The customization does not require every workload in the cluster to behave the
  same way.
* Ownership is clear: Terraform owns the platform primitive; the app release owns
  its own use of that primitive.

Isolated Execution For Agent Workloads
--------------------------------------

The cluster provides Agent Sandbox and a gVisor node pool so applications can
request short-lived isolated runtime containers. This is a platform capability,
not a requirement for every app.

Platform-owned pieces include:

* Agent Sandbox controller and CRDs.
* Base ``SandboxTemplate`` resources.
* Base ``SandboxWarmPool`` resource.
* Sandbox router ``Service`` and ``Deployment``.
* gVisor node pool, runtime class, taints, labels, and base network policies.

App-owned pieces include:

* Whether the app exposes isolated execution to its users.
* RBAC that permits the app backend to create/read sandbox resources.
* Runtime policy such as template selection, session versus ephemeral execution,
  and fallback behavior.
* User-derived templates or workspace-specific templates created at runtime.

Operationally, user-derived ``SandboxTemplate`` resources, ``SandboxClaim``
resources, and ``Sandbox`` resources should be treated as runtime/application
state unless explicitly brought under Terraform management.

On-Prem Or Private Database Connectivity
----------------------------------------

Some applications may need to reach private or on-premises databases. The live
environment has used a WireGuard sidecar/proxy pattern for this type of access.

Platform considerations:

* The cluster must allow the pod networking and security context needed by the
  sidecar.
* Secrets such as WireGuard configuration must be created out of band and must
  not be committed to the repo.
* The database service abstraction may be represented by a Kubernetes ``Service``
  alias even when the actual database is outside the cluster.

App-owned considerations:

* Enabling the sidecar in the app release configuration.
* Choosing database host/port values.
* Mounting the WireGuard configuration secret.
* Owning app-level migration and connection behavior.

This pattern should not be treated as a cluster-wide default. It is an app-level
connectivity strategy that depends on the consuming workload.

Private Images And Pull Secrets
-------------------------------

The cluster can host workloads that pull private images. The platform may provide
or document a namespace-level Docker registry secret, while each app decides
which images and tags it runs.

Recommended ownership:

* Terraform may create secret containers or optional Kubernetes pull secrets.
* Operators or CI provide secret values.
* App releases reference the pull secret through image pull secret configuration.

Admin And Support Workloads
---------------------------

The inspected cluster included admin and support workloads managed by an app-level
Helm release that is not represented as a chart in this checkout. That is an
application/source-control gap, not a change to the core cluster architecture.

Until the chart is added to the repo or the workloads are migrated to another
source of truth, treat those resources as live app-specific state and avoid
folding them into Terraform platform ownership.

Documentation Rule
------------------

When documenting a new customization, record it here if it depends on cluster
primitives but is not required for all workloads. Keep the core pages focused on
the generic platform model.
