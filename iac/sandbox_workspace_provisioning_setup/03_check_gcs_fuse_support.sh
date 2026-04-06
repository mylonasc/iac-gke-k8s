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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --cluster-name) CLUSTER_NAME="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: 03_check_gcs_fuse_support.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION>

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

note "Fetching cluster credentials"
gcloud container clusters get-credentials "$CLUSTER_NAME" --project="$PROJECT_ID" --location="$LOCATION" >/dev/null

note "Checking cluster-side GCS FUSE support"
CLUSTER_JSON=$(gcloud container clusters describe "$CLUSTER_NAME" --project="$PROJECT_ID" --location="$LOCATION" --format=json)
ADDON_ENABLED=$(printf '%s' "$CLUSTER_JSON" | json_get '.addonsConfig.gcsFuseCsiDriverConfig.enabled')
print_kv "gcsfuse_addon" "${ADDON_ENABLED:-<unknown>}"

if kubectl get csidriver gcsfuse.csi.storage.gke.io >/dev/null 2>&1; then
  print_kv "csi_driver" "present"
else
  print_kv "csi_driver" "missing"
  die "gcsfuse CSI driver not visible in the cluster"
fi
