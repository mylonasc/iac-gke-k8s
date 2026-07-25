# Minimal Sphinx configuration for the RST architecture documentation.

project = "iac-gke-k8s"
author = "iac-gke-k8s maintainers"
copyright = "2026, iac-gke-k8s maintainers"

extensions = ["sphinxcontrib.plantuml"]

# Render diagrams as SVG when PlantUML is available in the build environment.
# Install the Python extension from docs/requirements.txt and provide either a
# `plantuml` executable on PATH or set PLANTUML_CMD to an equivalent command,
# for example: java -jar /opt/plantuml/plantuml.jar
import os

plantuml = os.environ.get("PLANTUML_CMD", "plantuml")
plantuml_output_format = "svg_img"

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "alabaster"
