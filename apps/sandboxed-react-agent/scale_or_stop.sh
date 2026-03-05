#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-alt-default}"
TARGET_REPLICAS="1"

DEPLOYMENTS=(
  "sandboxed-react-agent-backend"
  "sandboxed-react-agent-frontend"
  "sandbox-router-deployment"
)

usage() {
  cat <<'EOF'
Usage: scale_or_stop.sh [--start] [--stop|--scale-zero] [--replicas N] [--namespace NAME] [--only NAME]

Defaults:
  - action: --start
  - replicas for --start: 1
  - namespace: alt-default
  - deployments: backend, frontend, sandbox-router

Examples:
  ./apps/sandboxed-react-agent/scale_or_stop.sh
  ./apps/sandboxed-react-agent/scale_or_stop.sh --stop
  ./apps/sandboxed-react-agent/scale_or_stop.sh --scale-zero
  ./apps/sandboxed-react-agent/scale_or_stop.sh --only sandbox-router-deployment --stop
  ./apps/sandboxed-react-agent/scale_or_stop.sh --only sandbox-router-deployment --scale-zero
  ./apps/sandboxed-react-agent/scale_or_stop.sh --replicas 2
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start)
      TARGET_REPLICAS="1"
      ;;
    --stop|--scale-zero)
      TARGET_REPLICAS="0"
      ;;
    --replicas)
      shift
      TARGET_REPLICAS="${1:-}"
      ;;
    --namespace|-n)
      shift
      NAMESPACE="${1:-}"
      ;;
    --only)
      shift
      DEPLOYMENTS=("${1:-}")
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

if ! [[ "${TARGET_REPLICAS}" =~ ^[0-9]+$ ]]; then
  echo "Error: replicas must be a non-negative integer." >&2
  exit 1
fi

echo "Scaling deployments in namespace '${NAMESPACE}' to replicas=${TARGET_REPLICAS}"

for deploy in "${DEPLOYMENTS[@]}"; do
  if kubectl -n "${NAMESPACE}" get deployment "${deploy}" >/dev/null 2>&1; then
    echo "- scaling ${deploy}"
    kubectl -n "${NAMESPACE}" scale deployment "${deploy}" --replicas="${TARGET_REPLICAS}"
  else
    echo "- skipping ${deploy} (not found)"
  fi
done

echo
kubectl -n "${NAMESPACE}" get deployments \
  "${DEPLOYMENTS[@]}" \
  --ignore-not-found \
  -o custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas
