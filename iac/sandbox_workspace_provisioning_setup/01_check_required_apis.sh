#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/common.sh"

require_cmd gcloud

PROJECT_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      PROJECT_ID="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage: 01_check_required_apis.sh --project-id <PROJECT_ID>

Mandatory flags:
  --project-id   GCP project id. Suggested default: your active gcloud project.
EOF
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

require_flag "project-id" "$PROJECT_ID" "$(gcloud config get-value project 2>/dev/null || printf '<ACTIVE_GCLOUD_PROJECT>')"

note "Checking required APIs"
ENABLED=$(gcloud services list --enabled --project="$PROJECT_ID" --format='value(config.name)')

required=(
  container.googleapis.com
  iam.googleapis.com
  cloudresourcemanager.googleapis.com
  storage.googleapis.com
)

missing=0
for api in "${required[@]}"; do
  if grep -Fxq "$api" <<<"$ENABLED"; then
    print_kv "$api" "ENABLED"
  else
    print_kv "$api" "MISSING"
    missing=1
  fi
done

exit "$missing"
