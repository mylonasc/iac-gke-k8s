#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="${SCRIPT_DIR}/k8s"

echo "Deploying telegram-service stack"

kubectl apply -f "${K8S_DIR}/namespace.yaml"
kubectl apply -f "${K8S_DIR}/configmap.yaml"
kubectl apply -f "${K8S_DIR}/serviceaccount.yaml"
kubectl apply -f "${K8S_DIR}/pvc.yaml"
kubectl apply -f "${K8S_DIR}/service.yaml"
kubectl apply -f "${K8S_DIR}/deployment.yaml"
kubectl apply -f "${K8S_DIR}/networkpolicy.yaml"

kubectl -n telegram-gateway rollout status deploy/telegram-service --timeout=300s
kubectl -n telegram-gateway get deploy/telegram-service svc/telegram-service pvc/telegram-service-data

echo
echo "Done. Apply secrets after replacing placeholders if needed:"
echo "  kubectl apply -f ${K8S_DIR}/secrets.example.yaml"
echo "  kubectl apply -f ${K8S_DIR}/externalsecret.example.yaml"
