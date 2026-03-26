#!/usr/bin/env bash
set -euo pipefail

# --- Configuration ---
NAMESPACE="${NAMESPACE:-alt-default}"
ROLLOUT_TIMEOUT="120s"
MANIFEST_DIR="./k8s" # Default directory to look for YAMLs

usage() {
  cat <<'EOF'
Usage: update_app.sh --name DEPLOYMENT_NAME [--file PATH_TO_YAML] [--namespace NAME]

Options:
  --name NAME       The name of the deployment in Kubernetes
  --file FILE       Path to the YAML manifest (defaults to ./k8s/NAME.yaml)
  --namespace -n    Kubernetes namespace (default: alt-default)
  --help -h         Show this help

Example:
  ./update_app.sh --name sandboxed-react-agent-backend --file ./deploy/backend-prod.yaml
EOF
}

# --- Parse Arguments ---
DEPLOY_NAME=""
YAML_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) shift; DEPLOY_NAME="${1:-}" ;;
    --file) shift; YAML_FILE="${1:-}" ;;
    --namespace|-n) shift; NAMESPACE="${1:-}" ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

# Validation
if [[ -z "$DEPLOY_NAME" ]]; then
  echo "Error: --name is required." >&2
  exit 1
fi

# If no file is provided, guess it based on deployment name
if [[ -z "$YAML_FILE" ]]; then
  YAML_FILE="${MANIFEST_DIR}/${DEPLOY_NAME}.yaml"
fi

if [[ ! -f "$YAML_FILE" ]]; then
  echo "Error: Manifest file not found at $YAML_FILE" >&2
  exit 1
fi

# --- Execution ---
echo "🚀 Starting Zero-Downtime Update..."
echo "📍 Deployment: $DEPLOY_NAME"
echo "📄 Manifest:   $YAML_FILE"
echo "🌐 Namespace:  $NAMESPACE"

# 1. Apply the new configuration
if kubectl apply -f "$YAML_FILE" -n "$NAMESPACE"; then
  echo "  ⏳ Waiting for rollout to finish (Timeout: $ROLLOUT_TIMEOUT)..."
  
  # 2. Monitor the rollout
  if kubectl rollout status deployment/"$DEPLOY_NAME" -n "$NAMESPACE" --timeout="$ROLLOUT_TIMEOUT"; then
    echo "✅ Success! $DEPLOY_NAME is updated and stable."
  else
    echo "❌ UPDATE FAILED! The new pods are not healthy."
    echo "🔙 Triggering automatic rollback to previous version..."
    kubectl rollout undo deployment/"$DEPLOY_NAME" -n "$NAMESPACE"
    kubectl rollout status deployment/"$DEPLOY_NAME" -n "$NAMESPACE"
    exit 1
  fi
else
  echo "❌ Error: Failed to apply the YAML manifest."
  exit 1
fi

echo "---"
kubectl get deployment "$DEPLOY_NAME" -n "$NAMESPACE" -o wide
