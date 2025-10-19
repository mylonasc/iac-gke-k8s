#!/usr/bin/env bash
set -euo pipefail

# deploy_with_secrets.sh
# Automates Phase A -> wait for cluster -> upload secrets -> Phase B for the iac/gke-secure-gpu-cluster repo.
# Dry-run by default. Use --execute to actually run changes. Secrets are read from environment variables and are NOT logged.

usage() {
  cat <<EOF
Usage: $0 [--execute] [--project PROJECT] [--cluster CLUSTER] [--region REGION]

Options:
  --execute           Actually run terraform/gcloud commands. Default is dry-run.
  --project PROJECT   GCP project id (default from var file or env PROJECT_ID)
  --cluster CLUSTER   Cluster name (default: gpu-spot-cluster)
  --region REGION     Cluster region/zone (default: europe-west4-a)

Environment variables used to upload secrets (optional):
  DOCKER_CONFIG_JSON  - docker config JSON (not base64). If set, will be uploaded to Secret Manager secret 'dockerhub-ro-pat' as a new version.
  OPENAI_API_KEY      - openai key string. If set, will be uploaded to Secret Manager secret 'openai-api-key' as a new version.

Examples:
  # Dry-run (no changes)
  $0

  # Execute with required env vars set (in CI, pass secrets via CI secret store)
  DOCKER_CONFIG_JSON='{"auths":{}}' OPENAI_API_KEY='sk-...' $0 --execute

EOF
}

# defaults
EXECUTE=0
PROJECT=""
CLUSTER="gpu-spot-cluster"
REGION="europe-west4-a"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) EXECUTE=1; shift ;;
    --project) PROJECT="$2"; shift 2 ;;
    --cluster) CLUSTER="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$PROJECT" ]]; then
  # try to read project from terraform var file if present
  if [[ -f "terraform.v2.tfvars" ]]; then
    PROJECT=$(grep -E "^project_id\s*=\s*\"?" terraform.v2.tfvars | head -n1 | sed -E 's/.*=\s*"?([^"\n]+)"?/\1/') || true
  fi
  PROJECT=${PROJECT:-}
fi

if [[ -z "$PROJECT" ]]; then
  echo "Project not provided and not found in terraform.v2.tfvars. Provide --project or set it in terraform.v2.tfvars." >&2
  exit 2
fi

echo "Project: $PROJECT"
echo "Cluster: $CLUSTER"
echo "Region: $REGION"

TF_DIR="$(pwd)"

run_or_echo() {
  if [[ $EXECUTE -eq 1 ]]; then
    echo "+ $*"
    eval "$@"
  else
    echo "DRY-RUN: $*"
  fi
}

# Phase A: targeted terraform apply for required Google services, secrets (containers), service account and cluster
echo "\n==> Phase A: create APIs, secret containers, service account and cluster"
run_or_echo "terraform init -input=false"

PHASE_A_TARGETS=(
  "-target=google_project_service.gke_api"
  "-target=google_project_service.compute_api"
  "-target=google_project_service.secretmanager"
  "-target=google_secret_manager_secret.secrets"
  "-target=google_service_account.default_gsa"
  "-target=google_service_account_iam_member.workload_identity_user"
  "-target=google_container_cluster.primary"
  "-target=google_container_node_pool.primary_nodes"
  "-target=google_container_node_pool.general_purpose_pool"
  "-target=google_container_node_pool.gpu_spot_pool_np_a"
  "-target=google_container_node_pool.gpu_spot_pool_np_b"
)

PLAN_CMD=(terraform plan -var-file=terraform.v2.tfvars)
PLAN_CMD+=("${PHASE_A_TARGETS[@]}")

run_or_echo "${PLAN_CMD[@]}"

APPLY_CMD=(terraform apply -var-file=terraform.v2.tfvars -auto-approve)
APPLY_CMD+=("${PHASE_A_TARGETS[@]}")

run_or_echo "${APPLY_CMD[@]}"

# Wait for cluster to be reachable and have nodes (if node pools are already present). We will wait for the control plane first.
echo "\n==> Waiting for cluster control plane to be reachable"

get_credentials_cmd="gcloud container clusters get-credentials $CLUSTER --region $REGION --project $PROJECT"
run_or_echo "$get_credentials_cmd"

wait_seconds=0
max_wait_seconds=900 # 15 minutes
sleep_interval=15

until kubectl version  >/dev/null 2>&1; do
  if [[ $wait_seconds -ge $max_wait_seconds ]]; then
    echo "Timed out waiting for cluster API to be reachable" >&2
    exit 3
  fi
  echo "Waiting for cluster API... ($wait_seconds/$max_wait_seconds)"
  sleep $sleep_interval
  wait_seconds=$((wait_seconds+sleep_interval))
done

echo "Cluster API reachable. Now waiting for at least one Node to be Ready (if node pools exist or are being created)"

wait_seconds=0
max_wait_seconds=900
until kubectl get nodes --no-headers 2>/dev/null | awk '{print $2}' | grep -q "Ready"; do
  if [[ $wait_seconds -ge $max_wait_seconds ]]; then
    echo "Timed out waiting for Ready nodes. Nodes may be provisioning or node pools not created yet." >&2
    break
  fi
  echo "Waiting for Ready nodes... ($wait_seconds/$max_wait_seconds)"
  sleep $sleep_interval
  wait_seconds=$((wait_seconds+sleep_interval))
done

echo "\n==> Secret provisioning (optional)"

# Add secret versions if env vars are present
if [[ -n "${DOCKER_CONFIG_JSON:-}" ]]; then
  echo "Docker config provided in env; uploading to Secret Manager as new version 'dockerhub-ro-pat'"
  if [[ $EXECUTE -eq 1 ]]; then
    echo "Uploading docker config to secret 'dockerhub-ro-pat'"
    echo -n "$DOCKER_CONFIG_JSON" | gcloud secrets versions add dockerhub-ro-pat --data-file=- --project="$PROJECT" >/dev/null
    echo "Uploaded dockerhub-ro-pat"
  else
    echo "DRY-RUN: echo -n "[docker config redacted]" | gcloud secrets versions add dockerhub-ro-pat --data-file=- --project=$PROJECT"
  fi
else
  echo "DOCKER_CONFIG_JSON not provided; skipping dockerhub-ro-pat upload"
fi

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY provided; uploading to Secret Manager as new version 'openai-api-key'"
  if [[ $EXECUTE -eq 1 ]]; then
    echo -n "$OPENAI_API_KEY" | gcloud secrets versions add openai-api-key --data-file=- --project="$PROJECT" >/dev/null
    echo "Uploaded openai-api-key"
  else
    echo "DRY-RUN: echo -n "[openai key redacted]" | gcloud secrets versions add openai-api-key --data-file=- --project=$PROJECT"
  fi
else
  echo "OPENAI_API_KEY not provided; skipping openai-api-key upload"
fi

# Phase B: apply the k8s module only
echo "\n==> Phase B: apply module.k8s"
run_or_echo "terraform apply -target=module.k8s -var-file=terraform.v2.tfvars -auto-approve"

echo "\nFinished. If this was a dry-run, re-run with --execute to perform changes."
