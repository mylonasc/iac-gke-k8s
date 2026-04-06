#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/common.sh"

require_cmd gcloud
require_cmd jq

PROJECT_ID=""
BACKEND_ADMIN_GSA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --backend-admin-gsa) BACKEND_ADMIN_GSA="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: 05_check_backend_admin_gsa.sh --project-id <PROJECT_ID> --backend-admin-gsa <GSA_EMAIL>

Mandatory flags:
  --project-id          GCP project id. Suggested default: active gcloud project.
  --backend-admin-gsa   Backend admin GSA email. Suggested default: sandbox-workspace-admin@<project>.iam.gserviceaccount.com.
EOF
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_flag "project-id" "$PROJECT_ID" "$(gcloud config get-value project 2>/dev/null || printf '<ACTIVE_GCLOUD_PROJECT>')"
require_flag "backend-admin-gsa" "$BACKEND_ADMIN_GSA" "sandbox-workspace-admin@<PROJECT_ID>.iam.gserviceaccount.com"

note "Checking backend admin GSA"
GSA_JSON=$(gcloud iam service-accounts describe "$BACKEND_ADMIN_GSA" --project="$PROJECT_ID" --format=json)
print_kv "email" "$(printf '%s' "$GSA_JSON" | json_get '.email')"
print_kv "unique_id" "$(printf '%s' "$GSA_JSON" | json_get '.uniqueId')"
print_kv "disabled" "$(printf '%s' "$GSA_JSON" | json_get '.disabled')"
