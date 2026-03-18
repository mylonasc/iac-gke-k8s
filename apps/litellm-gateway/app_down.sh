#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="${SCRIPT_DIR}/k8s"

echo "Removing LiteLLM gateway + vLLM stack"

kubectl delete -f "${K8S_DIR}/litellm-ingress.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/litellm-deployment.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/litellm-service.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/litellm-configmap.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/vllm-l4-deployment.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/vllm-t4-deployment.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/vllm-l4-service.yaml" --ignore-not-found
kubectl delete -f "${K8S_DIR}/vllm-t4-service.yaml" --ignore-not-found

echo "Done. Namespace and secrets were kept intentionally."
