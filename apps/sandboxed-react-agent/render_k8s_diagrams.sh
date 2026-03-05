#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv-kubediagrams"
KUBE_DIAGRAMS_BIN="${VENV_DIR}/bin/kube-diagrams"

OUT_DIR="${SCRIPT_DIR}/docs/diagrams"
CUSTOM_CONFIG="${OUT_DIR}/kubediagrams.custom.yaml"
SUPPORT_RESOURCES="${OUT_DIR}/diagram-support-resources.yaml"
INTERACTION_RESOURCES="${OUT_DIR}/interaction-resources.yaml"

if [[ ! -x "${KUBE_DIAGRAMS_BIN}" ]]; then
  echo "Setting up KubeDiagrams virtualenv in ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install KubeDiagrams
fi

mkdir -p "${OUT_DIR}"

echo "Rendering deployment diagram with KubeDiagrams..."
"${KUBE_DIAGRAMS_BIN}" \
  -f svg \
  --embed-all-icons \
  -c "${CUSTOM_CONFIG}" \
  -o "${OUT_DIR}/deployment-kubediagrams" \
  "${SUPPORT_RESOURCES}" \
  "${SCRIPT_DIR}/k8s/backend-deployment.yaml" \
  "${SCRIPT_DIR}/k8s/backend-service.yaml" \
  "${SCRIPT_DIR}/k8s/backend-sandbox-rbac.yaml" \
  "${SCRIPT_DIR}/k8s/frontend-deployment.yaml" \
  "${SCRIPT_DIR}/k8s/frontend-service.yaml" \
  "${SCRIPT_DIR}/k8s/ingress.magarathea.yaml" \
  "${REPO_ROOT}/iac/gke-secure-gpu-cluster/k8s/agent-sandbox-router.yaml" \
  "${REPO_ROOT}/iac/gke-secure-gpu-cluster/k8s/agent-sandbox-template-and-pool.yaml"

echo "Rendering interaction diagram with KubeDiagrams..."
"${KUBE_DIAGRAMS_BIN}" \
  -f svg \
  --embed-all-icons \
  -c "${CUSTOM_CONFIG}" \
  -o "${OUT_DIR}/interaction-kubediagrams" \
  "${SUPPORT_RESOURCES}" \
  "${INTERACTION_RESOURCES}" \
  "${SCRIPT_DIR}/k8s/backend-deployment.yaml" \
  "${SCRIPT_DIR}/k8s/backend-service.yaml" \
  "${SCRIPT_DIR}/k8s/frontend-deployment.yaml" \
  "${SCRIPT_DIR}/k8s/frontend-service.yaml" \
  "${SCRIPT_DIR}/k8s/ingress.magarathea.yaml" \
  "${REPO_ROOT}/iac/gke-secure-gpu-cluster/k8s/agent-sandbox-router.yaml" \
  "${REPO_ROOT}/iac/gke-secure-gpu-cluster/k8s/agent-sandbox-template-and-pool.yaml" \
  "${REPO_ROOT}/iac/gke-secure-gpu-cluster/k8s/agent-sandbox-claim-example.yaml"

echo "Diagrams generated:"
echo "- ${OUT_DIR}/deployment-kubediagrams.svg"
echo "- ${OUT_DIR}/interaction-kubediagrams.svg"

echo "Localizing remote icon URLs into local files..."
python3 "${SCRIPT_DIR}/localize_diagram_icons.py"
