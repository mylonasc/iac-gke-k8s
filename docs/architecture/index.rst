Infrastructure Architecture
===========================

Reviewed at: 2026-07-25 11:07:04 UTC

This section explains the infrastructure-as-code and Kubernetes architecture of
the repository. It focuses on cluster structure, ownership boundaries,
operational models, and platform primitives. Application-specific behavior is
kept separate in :doc:`app-specific-customizations`.

Read this section in order if you are new to the platform. Each page has a
timestamp so future readers can quickly judge whether the documentation is still
likely to match the repository and live cluster.

Current Baseline
----------------

The documentation reflects the repository and a live-cluster check performed on
2026-07-25 at 11:07:04 UTC.

The live context inspected was:

.. code-block:: text

   gke_gke-gpu-project-473410_europe-west4-a_gpu-spot-cluster

The live cluster matched the main Terraform defaults and most platform objects.
Known mismatches are captured in :doc:`status-and-boundaries`.

Start Here
----------

* :doc:`status-and-boundaries`
* :doc:`high-level-architecture`

Platform Models
---------------

* :doc:`iac-model`
* :doc:`cluster-models`
* :doc:`app-specific-customizations`
* :doc:`diagrams`

Role Guides
-----------

* :doc:`infra-engineer-guide`
* :doc:`admin-guide`
* :doc:`developer-guide`
