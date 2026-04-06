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
Usage: 04_check_workspace_bucket.sh --project-id <PROJECT_ID> --bucket <BUCKET_NAME>

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

note "Describing bucket"
BUCKET_JSON=$(gcloud storage buckets describe "gs://$BUCKET_NAME" --project="$PROJECT_ID" --format=json)

uniform_access=$(printf '%s' "$BUCKET_JSON" | jq -r '.uniform_bucket_level_access // .iamConfiguration.uniformBucketLevelAccess.enabled // empty')
public_access_prevention=$(printf '%s' "$BUCKET_JSON" | jq -r '.public_access_prevention // .iamConfiguration.publicAccessPrevention // empty')
hierarchical_namespace=$(printf '%s' "$BUCKET_JSON" | jq -r '.hierarchical_namespace.enabled // .hierarchicalNamespace.enabled // empty')
storage_class=$(printf '%s' "$BUCKET_JSON" | jq -r '.default_storage_class // .storageClass // empty')
versioning=$(printf '%s' "$BUCKET_JSON" | jq -r '.versioning.enabled // empty')
retention_period=$(printf '%s' "$BUCKET_JSON" | jq -r '.retention_policy.retentionPeriod // .retentionPolicy.retentionPeriod // empty')

print_kv "bucket" "$BUCKET_NAME"
print_kv "location" "$(printf '%s' "$BUCKET_JSON" | json_get '.location')"
print_kv "storage_class" "${storage_class:-<unknown>}"
print_kv "uniform_access" "${uniform_access:-<unknown>}"
print_kv "public_access_prevention" "${public_access_prevention:-<unknown>}"
print_kv "hierarchical_namespace" "${hierarchical_namespace:-<unknown>}"
print_kv "versioning" "${versioning:-<unset>}"
print_kv "retention_period" "${retention_period:-<unset>}"

[[ "$uniform_access" == "true" ]] || die "Uniform bucket-level access must be enabled"

if [[ -n "$hierarchical_namespace" && "$hierarchical_namespace" != "true" ]]; then
  die "Hierarchical namespace must be enabled"
fi

if [[ -z "$hierarchical_namespace" ]]; then
  note "Hierarchical namespace not surfaced by current gcloud output; verify separately if needed"
fi
