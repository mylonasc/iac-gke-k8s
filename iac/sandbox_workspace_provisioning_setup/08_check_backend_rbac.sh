#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/common.sh"

require_cmd gcloud
require_cmd kubectl

PROJECT_ID=""
CLUSTER_NAME=""
LOCATION=""
NAMESPACE=""
BACKEND_KSA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --cluster-name) CLUSTER_NAME="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --backend-ksa) BACKEND_KSA="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: 08_check_backend_rbac.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION> --namespace <NAMESPACE> --backend-ksa <KSA_NAME>

Mandatory flags:
  --project-id    GCP project id. Suggested default: active gcloud project.
  --cluster-name  GKE cluster name. Suggested default: your primary sandbox cluster.
  --location      Cluster zone or region. Suggested default: cluster's current location.
  --namespace     Kubernetes namespace. Suggested default: alt-default.
  --backend-ksa   Backend KSA name. Suggested default: default-ksa or sandbox-workspace-admin-ksa.
EOF
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_flag "project-id" "$PROJECT_ID" "$(gcloud config get-value project 2>/dev/null || printf '<ACTIVE_GCLOUD_PROJECT>')"
require_flag "cluster-name" "$CLUSTER_NAME" "<YOUR_CLUSTER_NAME>"
require_flag "location" "$LOCATION" "<YOUR_CLUSTER_LOCATION>"
require_flag "namespace" "$NAMESPACE" "alt-default"
require_flag "backend-ksa" "$BACKEND_KSA" "default-ksa"

note "Fetching cluster credentials"
gcloud container clusters get-credentials "$CLUSTER_NAME" --project="$PROJECT_ID" --location="$LOCATION" >/dev/null

SUBJECT="system:serviceaccount:${NAMESPACE}:${BACKEND_KSA}"
failed=0
checks=(
  "create serviceaccounts"
  "get serviceaccounts"
  "create sandboxtemplates.extensions.agents.x-k8s.io"
  "update sandboxtemplates.extensions.agents.x-k8s.io"
  "delete sandboxtemplates.extensions.agents.x-k8s.io"
  "create sandboxclaims.extensions.agents.x-k8s.io"
  "get sandboxclaims.extensions.agents.x-k8s.io"
  "delete sandboxclaims.extensions.agents.x-k8s.io"
)

for check in "${checks[@]}"; do
  verb=${check%% *}
  resource=${check#* }
  result=$(kubectl auth can-i "$verb" "$resource" -n "$NAMESPACE" --as="$SUBJECT" || true)
  if [[ -z "$result" ]]; then
    result="<unknown>"
  fi
  print_kv "$verb $resource" "$result"
  if [[ "$result" != "yes" ]]; then
    failed=1
  fi
done

exit "$failed"
