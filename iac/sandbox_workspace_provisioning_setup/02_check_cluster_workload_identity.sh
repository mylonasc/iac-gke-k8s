#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/common.sh"

require_cmd gcloud
require_cmd jq

PROJECT_ID=""
CLUSTER_NAME=""
LOCATION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --cluster-name) CLUSTER_NAME="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: 02_check_cluster_workload_identity.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION>

Mandatory flags:
  --project-id    GCP project id. Suggested default: active gcloud project.
  --cluster-name  GKE cluster name. Suggested default: your primary sandbox cluster.
  --location      Cluster zone or region. Suggested default: cluster's current location.
EOF
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_flag "project-id" "$PROJECT_ID" "$(gcloud config get-value project 2>/dev/null || printf '<ACTIVE_GCLOUD_PROJECT>')"
require_flag "cluster-name" "$CLUSTER_NAME" "<YOUR_CLUSTER_NAME>"
require_flag "location" "$LOCATION" "<YOUR_CLUSTER_LOCATION>"

note "Describing cluster"
CLUSTER_JSON=$(gcloud container clusters describe "$CLUSTER_NAME" --project="$PROJECT_ID" --location="$LOCATION" --format=json)

WORKLOAD_POOL=$(printf '%s' "$CLUSTER_JSON" | json_get '.workloadIdentityConfig.workloadPool')
MODE=$(printf '%s' "$CLUSTER_JSON" | json_get '.autopilot.enabled')

print_kv "cluster" "$CLUSTER_NAME"
print_kv "location" "$LOCATION"
print_kv "workload_pool" "${WORKLOAD_POOL:-<missing>}"
print_kv "autopilot" "${MODE:-false}"

[[ -n "$WORKLOAD_POOL" ]] || die "Workload Identity is not enabled on this cluster"
