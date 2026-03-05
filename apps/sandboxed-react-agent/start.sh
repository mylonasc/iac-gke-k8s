#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="${SCRIPT_DIR}/k8s"
NAMESPACE="${NAMESPACE:-alt-default}"
INGRESS_FILE="${INGRESS_FILE:-ingress.magarathea.yaml}"

echo "Deploying sandboxed-react-agent into namespace: ${NAMESPACE}"

if ! kubectl -n "${NAMESPACE}" get secret sandboxed-react-agent-secrets >/dev/null 2>&1; then
  echo "WARNING: secret 'sandboxed-react-agent-secrets' is missing in namespace '${NAMESPACE}'."
  echo "         Backend pods will not start until it exists."
fi

if ! kubectl -n "${NAMESPACE}" get secret dockerhub-regcred >/dev/null 2>&1; then
  echo "WARNING: secret 'dockerhub-regcred' is missing in namespace '${NAMESPACE}'."
  echo "         Image pulls may fail for private DockerHub images."
fi

kubectl apply -f "${K8S_DIR}/backend-deployment.yaml"
kubectl apply -f "${K8S_DIR}/backend-service.yaml"
kubectl apply -f "${K8S_DIR}/frontend-deployment.yaml"
kubectl apply -f "${K8S_DIR}/frontend-service.yaml"
kubectl apply -f "${K8S_DIR}/${INGRESS_FILE}"

echo "Waiting for deployments to become ready..."
kubectl -n "${NAMESPACE}" rollout status deployment/sandboxed-react-agent-backend --timeout=180s
kubectl -n "${NAMESPACE}" rollout status deployment/sandboxed-react-agent-frontend --timeout=180s

echo "Sandboxed React Agent is deployed."
kubectl -n "${NAMESPACE}" get deploy,svc,ingress | grep sandboxed-react-agent || true
