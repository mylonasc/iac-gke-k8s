#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: bash benchmarks/scripts/capture_state.sh <run_dir>

Captures repository and cluster state into:
  - <run_dir>/repo_state.txt
  - <run_dir>/cluster_state.txt
EOF
}

if [[ "${1:-}" == "" ]]; then
  usage
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_REPO_ROOT="$(cd "${BENCHMARK_DIR}/../../.." && pwd)"
REPO_ROOT="$(git -C "${BENCHMARK_DIR}" rev-parse --show-toplevel 2>/dev/null || printf "%s" "${DEFAULT_REPO_ROOT}")"

RUN_DIR="$1"
if [[ "${RUN_DIR}" != /* ]]; then
  RUN_DIR="$(cd "$(pwd)" && pwd)/${RUN_DIR}"
fi

mkdir -p "${RUN_DIR}"

NAMESPACE="${BENCHMARK_NAMESPACE:-alt-default}"
SYSTEM_NAMESPACE="${BENCHMARK_SYSTEM_NAMESPACE:-agent-sandbox-system}"
BACKEND_DEPLOYMENT="${BENCHMARK_BACKEND_DEPLOYMENT:-sandboxed-react-agent-backend}"
ROUTER_DEPLOYMENT="${BENCHMARK_ROUTER_DEPLOYMENT:-sandbox-router-deployment}"

write_repo_state() {
  local out_file="$1"
  {
    printf "captured_at_utc: %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    printf "repo_root: %s\n" "${REPO_ROOT}"

    printf "\n== git rev-parse HEAD ==\n"
    git -C "${REPO_ROOT}" rev-parse HEAD || true

    printf "\n== git branch --show-current ==\n"
    git -C "${REPO_ROOT}" branch --show-current || true

    printf "\n== git status --short --branch ==\n"
    git -C "${REPO_ROOT}" status --short --branch || true

    printf "\n== git log -n 12 --oneline ==\n"
    git -C "${REPO_ROOT}" log -n 12 --oneline || true

    printf "\n== git diff --stat ==\n"
    git -C "${REPO_ROOT}" diff --stat || true

    printf "\n== git diff --cached --stat ==\n"
    git -C "${REPO_ROOT}" diff --cached --stat || true

    printf "\n== app-only status (apps/sandboxed-react-agent) ==\n"
    git -C "${REPO_ROOT}" status --short -- "apps/sandboxed-react-agent" || true
  } >"${out_file}"
}

write_cluster_state() {
  local out_file="$1"
  {
    printf "captured_at_utc: %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    printf "namespace: %s\n" "${NAMESPACE}"
    printf "system_namespace: %s\n" "${SYSTEM_NAMESPACE}"
    printf "backend_deployment: %s\n" "${BACKEND_DEPLOYMENT}"
    printf "router_deployment: %s\n" "${ROUTER_DEPLOYMENT}"
  } >"${out_file}"

  if ! command -v kubectl >/dev/null 2>&1; then
    {
      printf "\n== kubectl ==\n"
      printf "kubectl not found on PATH\n"
    } >>"${out_file}"
    return
  fi

  {
    printf "\n== kubectl current-context ==\n"
    kubectl config current-context 2>&1 || true

    printf "\n== kubectl version ==\n"
    kubectl version 2>&1 || true

    printf "\n== kubectl get nodes -o wide ==\n"
    kubectl get nodes -o wide 2>&1 || true

    printf "\n== kubectl -n %s get deployment %s %s ==\n" "${NAMESPACE}" "${BACKEND_DEPLOYMENT}" "${ROUTER_DEPLOYMENT}"
    kubectl -n "${NAMESPACE}" get deployment "${BACKEND_DEPLOYMENT}" "${ROUTER_DEPLOYMENT}" 2>&1 || true

    printf "\n== kubectl -n %s get pods -o wide ==\n" "${NAMESPACE}"
    kubectl -n "${NAMESPACE}" get pods -o wide 2>&1 || true

    printf "\n== kubectl -n %s get svc ==\n" "${NAMESPACE}"
    kubectl -n "${NAMESPACE}" get svc 2>&1 || true

    printf "\n== kubectl -n %s get sandboxtemplate,sandboxwarmpool,sandboxclaim,sandbox ==\n" "${NAMESPACE}"
    kubectl -n "${NAMESPACE}" get sandboxtemplate,sandboxwarmpool,sandboxclaim,sandbox --ignore-not-found 2>&1 || true

    printf "\n== kubectl -n %s get events (Warning, sorted) ==\n" "${NAMESPACE}"
    kubectl -n "${NAMESPACE}" get events --field-selector type=Warning --sort-by=.metadata.creationTimestamp 2>&1 || true

    printf "\n== kubectl -n %s get events (FailedMount) ==\n" "${NAMESPACE}"
    kubectl -n "${NAMESPACE}" get events --field-selector reason=FailedMount --sort-by=.metadata.creationTimestamp 2>&1 || true

    printf "\n== kubectl -n %s get pods ==\n" "${SYSTEM_NAMESPACE}"
    kubectl -n "${SYSTEM_NAMESPACE}" get pods 2>&1 || true
  } >>"${out_file}"
}

write_repo_state "${RUN_DIR}/repo_state.txt"
write_cluster_state "${RUN_DIR}/cluster_state.txt"

printf "Captured repo and cluster state in %s\n" "${RUN_DIR}"
