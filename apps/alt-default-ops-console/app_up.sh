#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="${SCRIPT_DIR}/k8s"

kubectl apply -f "${K8S_DIR}/rbac.yaml"
kubectl apply -f "${K8S_DIR}/configmap.yaml"
kubectl apply -f "${K8S_DIR}/deployment.yaml"
kubectl apply -f "${K8S_DIR}/service.yaml"
kubectl apply -f "${K8S_DIR}/ingress.magarathea.yaml"

kubectl -n alt-default rollout status deploy/alt-default-ops-console --timeout=180s
kubectl -n alt-default get deploy,svc,ingress alt-default-ops-console
