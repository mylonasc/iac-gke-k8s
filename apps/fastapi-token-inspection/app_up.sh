#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

kubectl apply -f "${SCRIPT_DIR}/deployment.yaml"
kubectl apply -f "${SCRIPT_DIR}/service.yaml"
kubectl apply -f "${SCRIPT_DIR}/ingress.magarathea.yaml"

kubectl -n alt-default rollout status deployment/fastapi-token-inspection --timeout=120s
kubectl -n alt-default get deployment,service,ingress fastapi-token-inspection
