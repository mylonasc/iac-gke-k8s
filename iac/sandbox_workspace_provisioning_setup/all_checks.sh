#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/common.sh"

require_cmd gcloud
require_cmd kubectl
require_cmd jq

PROJECT_ID=""
CLUSTER_NAME=""
LOCATION=""
NAMESPACE=""
BUCKET_NAME=""
BACKEND_KSA=""
BACKEND_ADMIN_GSA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --cluster-name) CLUSTER_NAME="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --bucket) BUCKET_NAME="$2"; shift 2 ;;
    --backend-ksa) BACKEND_KSA="$2"; shift 2 ;;
    --backend-admin-gsa) BACKEND_ADMIN_GSA="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: all_checks.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION> [options]

Mandatory flags:
  --project-id          GCP project id. Suggested default: active gcloud project.
  --cluster-name        GKE cluster name. Suggested default: your primary sandbox cluster.
  --location            Cluster zone or region. Suggested default: cluster's current location.

Optional flags:
  --namespace           Kubernetes namespace. Suggested default: alt-default.
  --bucket              Shared workspace bucket. Suggested default: <env>-sandbox-workspaces.
  --backend-ksa         Backend KSA name. Suggested default: default-ksa or sandbox-workspace-admin-ksa.
  --backend-admin-gsa   Backend admin GSA email. Suggested default: sandbox-workspace-admin@<project>.iam.gserviceaccount.com.

Notes:
  - Scripts 01-03 always run.
  - 04 and 09 require --bucket.
  - 05 requires --backend-admin-gsa.
  - 06 requires both --bucket and --backend-admin-gsa.
  - 07 requires --namespace, --backend-ksa, and --backend-admin-gsa.
  - 08 requires --namespace and --backend-ksa.
EOF
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_flag "project-id" "$PROJECT_ID" "$(gcloud config get-value project 2>/dev/null || printf '<ACTIVE_GCLOUD_PROJECT>')"
require_flag "cluster-name" "$CLUSTER_NAME" "<YOUR_CLUSTER_NAME>"
require_flag "location" "$LOCATION" "<YOUR_CLUSTER_LOCATION>"

NAMESPACE=${NAMESPACE:-alt-default}

declare -a failures=()
declare -a skipped=()

CHECK_04_OK=0
CHECK_05_OK=0

run_check() {
  local label="$1"
  shift
  note "Running $label"
  if "$@"; then
    print_kv "$label" "PASS"
  else
    print_kv "$label" "FAIL"
    failures+=("$label")
  fi
}

skip_check() {
  local label="$1"
  local reason="$2"
  print_kv "$label" "SKIP ($reason)"
  skipped+=("$label")
}

run_check "01 required APIs" \
  "$SCRIPT_DIR/01_check_required_apis.sh" \
  --project-id "$PROJECT_ID"

run_check "02 workload identity" \
  "$SCRIPT_DIR/02_check_cluster_workload_identity.sh" \
  --project-id "$PROJECT_ID" \
  --cluster-name "$CLUSTER_NAME" \
  --location "$LOCATION"

run_check "03 GCS FUSE support" \
  "$SCRIPT_DIR/03_check_gcs_fuse_support.sh" \
  --project-id "$PROJECT_ID" \
  --cluster-name "$CLUSTER_NAME" \
  --location "$LOCATION"

if [[ -n "$BUCKET_NAME" ]]; then
  run_check "04 workspace bucket" \
    "$SCRIPT_DIR/04_check_workspace_bucket.sh" \
    --project-id "$PROJECT_ID" \
    --bucket "$BUCKET_NAME"
  if [[ ! " ${failures[*]} " =~ " 04 workspace bucket " ]]; then
    CHECK_04_OK=1
  fi
else
  skip_check "04 workspace bucket" "missing --bucket"
fi

if [[ -n "$BACKEND_ADMIN_GSA" ]]; then
  run_check "05 backend admin GSA" \
    "$SCRIPT_DIR/05_check_backend_admin_gsa.sh" \
    --project-id "$PROJECT_ID" \
    --backend-admin-gsa "$BACKEND_ADMIN_GSA"
  if [[ ! " ${failures[*]} " =~ " 05 backend admin GSA " ]]; then
    CHECK_05_OK=1
  fi
else
  skip_check "05 backend admin GSA" "missing --backend-admin-gsa"
fi

if [[ -n "$BUCKET_NAME" && -n "$BACKEND_ADMIN_GSA" && "$CHECK_04_OK" -eq 1 && "$CHECK_05_OK" -eq 1 ]]; then
  run_check "06 backend admin permissions" \
    "$SCRIPT_DIR/06_check_backend_admin_permissions.sh" \
    --project-id "$PROJECT_ID" \
    --bucket "$BUCKET_NAME" \
    --backend-admin-gsa "$BACKEND_ADMIN_GSA"
else
  skip_check "06 backend admin permissions" "missing flags or unmet 04/05 prerequisites"
fi

if [[ -n "$BACKEND_KSA" && -n "$BACKEND_ADMIN_GSA" && "$CHECK_05_OK" -eq 1 ]]; then
  run_check "07 backend KSA binding" \
    "$SCRIPT_DIR/07_check_backend_ksa_binding.sh" \
    --project-id "$PROJECT_ID" \
    --cluster-name "$CLUSTER_NAME" \
    --location "$LOCATION" \
    --namespace "$NAMESPACE" \
    --backend-ksa "$BACKEND_KSA" \
    --backend-admin-gsa "$BACKEND_ADMIN_GSA"
else
  skip_check "07 backend KSA binding" "missing flags or unmet 05 prerequisite"
fi

if [[ -n "$BACKEND_KSA" ]]; then
  run_check "08 backend RBAC" \
    "$SCRIPT_DIR/08_check_backend_rbac.sh" \
    --project-id "$PROJECT_ID" \
    --cluster-name "$CLUSTER_NAME" \
    --location "$LOCATION" \
    --namespace "$NAMESPACE" \
    --backend-ksa "$BACKEND_KSA"
else
  skip_check "08 backend RBAC" "missing --backend-ksa"
fi

if [[ -n "$BUCKET_NAME" && "$CHECK_04_OK" -eq 1 ]]; then
  run_check "09 deprovisioning constraints" \
    "$SCRIPT_DIR/09_check_deprovisioning_constraints.sh" \
    --project-id "$PROJECT_ID" \
    --bucket "$BUCKET_NAME"
else
  skip_check "09 deprovisioning constraints" "missing --bucket or unmet 04 prerequisite"
fi

printf '\nSummary\n'
print_kv "failed" "${#failures[@]}"
print_kv "skipped" "${#skipped[@]}"

if [[ ${#failures[@]} -gt 0 ]]; then
  printf 'Failed checks:\n'
  for item in "${failures[@]}"; do
    printf '  - %s\n' "$item"
  done
fi

if [[ ${#skipped[@]} -gt 0 ]]; then
  printf 'Skipped checks:\n'
  for item in "${skipped[@]}"; do
    printf '  - %s\n' "$item"
  done
fi

[[ ${#failures[@]} -eq 0 ]]
