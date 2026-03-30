#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="${SCRIPT_DIR}/k8s"

echo "Removing telegram-service stack"

kubectl delete -f "${K8S_DIR}/networkpolicy.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/deployment.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/service.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/pvc.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/serviceaccount.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/configmap.yaml" --ignore-not-found

echo "Done. Namespace and secrets kept intentionally."
