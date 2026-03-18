#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="${SCRIPT_DIR}/k8s"

echo "Deploying LiteLLM gateway + vLLM stack"

kubectl apply -f "${K8S_DIR}/namespace.yaml"
kubectl apply -f "${K8S_DIR}/vllm-l4-service.yaml"
kubectl apply -f "${K8S_DIR}/vllm-t4-service.yaml"
kubectl apply -f "${K8S_DIR}/vllm-l4-deployment.yaml"
kubectl apply -f "${K8S_DIR}/vllm-t4-deployment.yaml"
kubectl apply -f "${K8S_DIR}/litellm-configmap.yaml"
kubectl apply -f "${K8S_DIR}/litellm-service.yaml"
kubectl apply -f "${K8S_DIR}/litellm-deployment.yaml"
kubectl apply -f "${K8S_DIR}/litellm-ingress.yaml"

echo
echo "Done. If secrets are not created yet, apply them now:"
echo "  kubectl apply -f ${K8S_DIR}/secrets.example.yaml"
