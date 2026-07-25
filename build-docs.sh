#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv-docs"
DOCS_DIR="${SCRIPT_DIR}/docs"
BUILD_DIR="${DOCS_DIR}/_build/html"
PLANTUML_CACHE_DIR="${TMPDIR:-/tmp}/iac-gke-k8s-docs"
PLANTUML_JAR="${PLANTUML_CACHE_DIR}/plantuml.jar"
PLANTUML_URL="https://github.com/plantuml/plantuml/releases/latest/download/plantuml.jar"

resolve_plantuml_cmd() {
  if [[ -n "${PLANTUML_CMD:-}" ]]; then
    printf '%s\n' "${PLANTUML_CMD}"
    return 0
  fi

  if command -v plantuml >/dev/null 2>&1; then
    printf 'plantuml\n'
    return 0
  fi

  if ! command -v java >/dev/null 2>&1; then
    printf 'error: plantuml is not on PATH and java is not available to run plantuml.jar\n' >&2
    return 1
  fi

  mkdir -p "${PLANTUML_CACHE_DIR}"

  if [[ ! -s "${PLANTUML_JAR}" ]]; then
    printf 'PlantUML not found on PATH; downloading %s\n' "${PLANTUML_URL}" >&2
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL "${PLANTUML_URL}" -o "${PLANTUML_JAR}"
    elif command -v wget >/dev/null 2>&1; then
      wget -q "${PLANTUML_URL}" -O "${PLANTUML_JAR}"
    else
      python3 - <<PY
from urllib.request import urlretrieve
urlretrieve("${PLANTUML_URL}", "${PLANTUML_JAR}")
PY
    fi
  fi

  printf 'java -jar %s\n' "${PLANTUML_JAR}"
}

python3 -m venv --clear "${VENV_DIR}"
. "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r "${DOCS_DIR}/requirements.txt"

PLANTUML_CMD="$(resolve_plantuml_cmd)"
export PLANTUML_CMD

PLANTUML_CMD="${PLANTUML_CMD}" sphinx-build -E -W -b html "${DOCS_DIR}" "${BUILD_DIR}"

printf 'Documentation built at %s\n' "${BUILD_DIR}"
