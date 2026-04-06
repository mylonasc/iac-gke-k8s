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
BACKEND_KSA=""
BACKEND_ADMIN_GSA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --cluster-name) CLUSTER_NAME="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --backend-ksa) BACKEND_KSA="$2"; shift 2 ;;
    --backend-admin-gsa) BACKEND_ADMIN_GSA="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: 07_check_backend_ksa_binding.sh --project-id <PROJECT_ID> --cluster-name <CLUSTER_NAME> --location <LOCATION> --namespace <NAMESPACE> --backend-ksa <KSA_NAME> --backend-admin-gsa <GSA_EMAIL>

Mandatory flags:
  --project-id          GCP project id. Suggested default: active gcloud project.
  --cluster-name        GKE cluster name. Suggested default: your primary sandbox cluster.
  --location            Cluster zone or region. Suggested default: cluster's current location.
  --namespace           Kubernetes namespace. Suggested default: alt-default.
  --backend-ksa         Backend KSA name. Suggested default: default-ksa or sandbox-workspace-admin-ksa.
  --backend-admin-gsa   Backend admin GSA email. Suggested default: sandbox-workspace-admin@<project>.iam.gserviceaccount.com.
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
require_flag "backend-admin-gsa" "$BACKEND_ADMIN_GSA" "sandbox-workspace-admin@<PROJECT_ID>.iam.gserviceaccount.com"

note "Fetching cluster credentials"
gcloud container clusters get-credentials "$CLUSTER_NAME" --project="$PROJECT_ID" --location="$LOCATION" >/dev/null

note "Checking KSA annotation"
ANNOTATION=$(kubectl get serviceaccount "$BACKEND_KSA" -n "$NAMESPACE" -o jsonpath='{.metadata.annotations.iam\.gke\.io/gcp-service-account}' 2>/dev/null || true)
print_kv "ksa_annotation" "${ANNOTATION:-<missing>}"

note "Checking Workload Identity binding on GSA"
POLICY=$(gcloud iam service-accounts get-iam-policy "$BACKEND_ADMIN_GSA" --project="$PROJECT_ID" --format=json)
MEMBER="serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/${BACKEND_KSA}]"
MATCH=$(printf '%s' "$POLICY" | jq -r --arg member "$MEMBER" '.bindings[] | select(.role == "roles/iam.workloadIdentityUser") | select(.members[]? == $member) | .role')
print_kv "wi_member" "$MEMBER"
print_kv "wi_binding" "${MATCH:-<missing>}"

[[ "$ANNOTATION" == "$BACKEND_ADMIN_GSA" ]] || die "KSA annotation does not point to the backend admin GSA"
[[ -n "$MATCH" ]] || die "roles/iam.workloadIdentityUser binding missing on backend admin GSA"
