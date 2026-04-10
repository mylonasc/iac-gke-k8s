#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

kubectl delete -f "${SCRIPT_DIR}/ingress.magarathea.yaml" --ignore-not-found
kubectl delete -f "${SCRIPT_DIR}/service.yaml" --ignore-not-found
kubectl delete -f "${SCRIPT_DIR}/deployment.yaml" --ignore-not-found
