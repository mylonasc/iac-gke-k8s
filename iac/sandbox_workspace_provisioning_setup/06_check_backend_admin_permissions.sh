#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/common.sh"

require_cmd gcloud
require_cmd jq

PROJECT_ID=""
BUCKET_NAME=""
BACKEND_ADMIN_GSA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --bucket) BUCKET_NAME="$2"; shift 2 ;;
    --backend-admin-gsa) BACKEND_ADMIN_GSA="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: 06_check_backend_admin_permissions.sh --project-id <PROJECT_ID> --bucket <BUCKET_NAME> --backend-admin-gsa <GSA_EMAIL>

Mandatory flags:
  --project-id          GCP project id. Suggested default: active gcloud project.
  --bucket              Shared workspace bucket. Suggested default: <env>-sandbox-workspaces.
  --backend-admin-gsa   Backend admin GSA email. Suggested default: sandbox-workspace-admin@<project>.iam.gserviceaccount.com.
EOF
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_flag "project-id" "$PROJECT_ID" "$(gcloud config get-value project 2>/dev/null || printf '<ACTIVE_GCLOUD_PROJECT>')"
require_flag "bucket" "$BUCKET_NAME" "<ENV>-sandbox-workspaces"
require_flag "backend-admin-gsa" "$BACKEND_ADMIN_GSA" "sandbox-workspace-admin@<PROJECT_ID>.iam.gserviceaccount.com"

note "Inspecting project-level IAM roles for backend admin GSA"
PROJECT_POLICY=$(gcloud projects get-iam-policy "$PROJECT_ID" --format=json)
PROJECT_ROLES=$(printf '%s' "$PROJECT_POLICY" | jq -r --arg member "serviceAccount:$BACKEND_ADMIN_GSA" '.bindings[] | select(.members[]? == $member) | .role' | sort -u)
printf '%s\n' "$PROJECT_ROLES"

note "Inspecting bucket-level IAM roles for backend admin GSA"
BUCKET_POLICY=$(gcloud storage buckets get-iam-policy "gs://$BUCKET_NAME" --format=json)
BUCKET_ROLES=$(printf '%s' "$BUCKET_POLICY" | jq -r --arg member "serviceAccount:$BACKEND_ADMIN_GSA" '.bindings[] | select(.members[]? == $member) | .role' | sort -u)
printf '%s\n' "$BUCKET_ROLES"

grep -Eq '^roles/iam.serviceAccountAdmin$' <<<"$PROJECT_ROLES" || note "Missing expected project role: roles/iam.serviceAccountAdmin"
grep -Eq '^(roles/storage.folderAdmin|roles/storage.admin)$' <<<"$BUCKET_ROLES" || note "Missing expected bucket role: roles/storage.folderAdmin or roles/storage.admin"
