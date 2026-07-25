iac-gke-k8s Documentation
==========================

Reviewed at: 2026-07-25 11:07:04 UTC

This Sphinx entrypoint documents the infrastructure architecture of this
repository. The existing Markdown documents remain operational references; this
RST section is the architecture-oriented reading path.

Build locally with:

.. code-block:: bash

   python3 -m venv .venv-docs
   . .venv-docs/bin/activate
   pip install -r docs/requirements.txt
   sphinx-build -b html docs docs/_build/html

PlantUML diagrams are rendered during the Sphinx build. The Python dependency is
listed in ``docs/requirements.txt``; the build environment must also provide a
``plantuml`` executable on ``PATH`` or set ``PLANTUML_CMD`` to an equivalent
command such as ``java -jar /opt/plantuml/plantuml.jar``.

Example with a local PlantUML jar:

.. code-block:: bash

   export PLANTUML_CMD="java -jar /opt/plantuml/plantuml.jar"
   sphinx-build -b html docs docs/_build/html

Architecture Reading Path
-------------------------

Start with the overview and boundaries, then use the role-specific sections for
operational detail.

.. toctree::
   :maxdepth: 2
   :caption: Start Here

   architecture/index
   architecture/status-and-boundaries
   architecture/high-level-architecture

.. toctree::
   :maxdepth: 2
   :caption: Platform Models

   architecture/iac-model
   architecture/cluster-models
   architecture/app-specific-customizations
   architecture/diagrams

.. toctree::
   :maxdepth: 2
   :caption: Role Guides

   architecture/infra-engineer-guide
   architecture/admin-guide
   architecture/developer-guide
