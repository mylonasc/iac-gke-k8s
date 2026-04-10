#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="${TOKEN_INSPECTION_NAMESPACE:-alt-default}"
NAME="fastapi-token-inspection"
HOST="${TOKEN_INSPECTION_HOST:-magarathea.ddns.net}"
PATH_PREFIX="${TOKEN_INSPECTION_PATH_PREFIX:-/token-inspection}"

usage() {
  cat <<EOF
Usage: ./manage.sh <command>

Commands:
  up      Deploy app, service, and host-specific ingress
  down    Remove ingress, service, and deployment
  status  Show workload status in namespace ${NAMESPACE}
  logs    Tail deployment logs
  url     Print the URL to retrieve tokens

Environment overrides:
  TOKEN_INSPECTION_NAMESPACE (default: alt-default)
  TOKEN_INSPECTION_HOST (default: magarathea.ddns.net)
  TOKEN_INSPECTION_PATH_PREFIX (default: /token-inspection)
EOF
}

cmd="${1:-help}"

case "${cmd}" in
  up)
    kubectl apply -f "${SCRIPT_DIR}/deployment.yaml"
    kubectl apply -f "${SCRIPT_DIR}/service.yaml"
    kubectl apply -f "${SCRIPT_DIR}/ingress.magarathea.yaml"
    kubectl -n "${NAMESPACE}" rollout status deployment/"${NAME}" --timeout=120s
    kubectl -n "${NAMESPACE}" get deployment,service,ingress "${NAME}"
    ;;
  down)
    kubectl delete -f "${SCRIPT_DIR}/ingress.magarathea.yaml" --ignore-not-found
    kubectl delete -f "${SCRIPT_DIR}/service.yaml" --ignore-not-found
    kubectl delete -f "${SCRIPT_DIR}/deployment.yaml" --ignore-not-found
    ;;
  status)
    kubectl -n "${NAMESPACE}" get deployment,service,ingress "${NAME}" --ignore-not-found
    ;;
  logs)
    kubectl -n "${NAMESPACE}" logs deployment/"${NAME}" --tail=200
    ;;
  url)
    printf "https://%s%s/raw\n" "${HOST}" "${PATH_PREFIX}"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    usage
    exit 1
    ;;
esac
