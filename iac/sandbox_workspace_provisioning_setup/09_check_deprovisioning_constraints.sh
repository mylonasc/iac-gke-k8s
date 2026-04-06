#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/common.sh"

require_cmd gcloud
require_cmd jq

PROJECT_ID=""
BUCKET_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id) PROJECT_ID="$2"; shift 2 ;;
    --bucket) BUCKET_NAME="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: 09_check_deprovisioning_constraints.sh --project-id <PROJECT_ID> --bucket <BUCKET_NAME>

Mandatory flags:
  --project-id   GCP project id. Suggested default: active gcloud project.
  --bucket       Shared workspace bucket name. Suggested default: <env>-sandbox-workspaces.
EOF
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_flag "project-id" "$PROJECT_ID" "$(gcloud config get-value project 2>/dev/null || printf '<ACTIVE_GCLOUD_PROJECT>')"
require_flag "bucket" "$BUCKET_NAME" "<ENV>-sandbox-workspaces"

note "Checking bucket properties that affect user deprovisioning"
BUCKET_JSON=$(gcloud storage buckets describe "gs://$BUCKET_NAME" --project="$PROJECT_ID" --format=json)

print_kv "versioning" "$(printf '%s' "$BUCKET_JSON" | jq -r '.versioning.enabled // empty')"
print_kv "retention_period" "$(printf '%s' "$BUCKET_JSON" | jq -r '.retention_policy.retentionPeriod // .retentionPolicy.retentionPeriod // empty')"
print_kv "retention_locked" "$(printf '%s' "$BUCKET_JSON" | jq -r '.retention_policy.isLocked // .retentionPolicy.isLocked // empty')"
print_kv "soft_delete" "$(printf '%s' "$BUCKET_JSON" | jq -r '.soft_delete_policy.retentionDurationSeconds // .softDeletePolicy.retentionDurationSeconds // empty')"

note "If retention, soft-delete, or lock settings are non-empty, deprovisioning must archive or delay deletion accordingly"
