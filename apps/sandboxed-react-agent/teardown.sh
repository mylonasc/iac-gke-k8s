#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="${SCRIPT_DIR}/k8s"
NAMESPACE="${NAMESPACE:-alt-default}"
INGRESS_FILE="${INGRESS_FILE:-ingress.magarathea.yaml}"
DELETE_PULL_SECRET=0

if [[ "${1:-}" == "--delete-pull-secret" ]]; then
  DELETE_PULL_SECRET=1
fi

echo "Tearing down sandboxed-react-agent from namespace: ${NAMESPACE}"

kubectl delete -f "${K8S_DIR}/${INGRESS_FILE}" --ignore-not-found
kubectl delete -f "${K8S_DIR}/ingress.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/ingress.magarathea.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/frontend-service.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/frontend-deployment.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/backend-sandbox-rbac.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/backend-service.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/backend-deployment.yaml" --ignore-not-found

kubectl -n "${NAMESPACE}" delete secret sandboxed-react-agent-secrets --ignore-not-found

if [[ "${DELETE_PULL_SECRET}" -eq 1 ]]; then
  kubectl -n "${NAMESPACE}" delete secret dockerhub-regcred --ignore-not-found
fi

echo "Sandboxed React Agent resources removed."
kubectl -n "${NAMESPACE}" get deploy,svc,ingress,role,rolebinding,secret | grep sandboxed-react-agent || true
