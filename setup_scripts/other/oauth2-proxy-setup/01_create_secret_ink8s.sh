#!/usr/bin/env bash
# Create Kubernetes Secret for oauth2-proxy from a Google OAuth client JSON file.
#
# Usage:
#   ./create_oauth2_proxy_secret.sh /path/to/google-oauth-client.json
#
# Requirements:
#   - kubectl configured for your cluster
#   - jq installed
#   - python (or python3) installed (for generating cookie secret)

set -euo pipefail

# ----- Pretty, colored output helpers -----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

die() {
  # Print an error message in red and exit non-zero.
  echo -e "${RED}ERROR:${NC} $*" >&2
  exit 1
}

warn() {
  # Print a warning message in yellow.
  echo -e "${YELLOW}WARN:${NC} $*" >&2
}

info() {
  # Print an info message in green.
  echo -e "${GREEN}INFO:${NC} $*"
}

# ----- Input validation -----
if [[ $# -ne 1 ]]; then
  die "Missing required argument. Provide the path to your Google OAuth client JSON.\nUsage: $0 /path/to/google-oauth-client.json"
fi

OAUTH_JSON="$1"

if [[ ! -f "$OAUTH_JSON" ]]; then
  die "File not found: '$OAUTH_JSON'"
fi

if [[ ! -r "$OAUTH_JSON" ]]; then
  die "File is not readable: '$OAUTH_JSON'"
fi

# ----- Dependency checks -----
command -v kubectl >/dev/null 2>&1 || die "kubectl not found in PATH. Install/configure kubectl first."
command -v jq >/dev/null 2>&1 || die "jq not found in PATH. Install jq (e.g., 'sudo apt-get install -y jq' or 'brew install jq')."

# Use python if available, otherwise try python3.
PYTHON_BIN=""
if command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  die "Neither 'python' nor 'python3' found in PATH. Install Python to generate the cookie secret."
fi

# ----- Extract credentials from JSON -----
# Your downloaded file usually looks like:
# { "web": { "client_id": "...", "client_secret": "...", ... } }
CLIENT_ID="$(jq -er '.web.client_id // empty' "$OAUTH_JSON")" \
  || die "Could not read '.web.client_id' from '$OAUTH_JSON'. Is this the correct Google OAuth client JSON file?"
CLIENT_SECRET="$(jq -er '.web.client_secret // empty' "$OAUTH_JSON")" \
  || die "Could not read '.web.client_secret' from '$OAUTH_JSON'. Is this the correct Google OAuth client JSON file?"

# Guard against empty values (jq -e should already help, but keep explicit checks)
[[ -n "$CLIENT_ID" ]] || die "Extracted client_id is empty. Check '.web.client_id' in '$OAUTH_JSON'."
[[ -n "$CLIENT_SECRET" ]] || die "Extracted client_secret is empty. Check '.web.client_secret' in '$OAUTH_JSON'."

# ----- Generate cookie secret -----
# 32 random bytes base64-encoded is a common choice for oauth2-proxy cookie secret.
COOKIE_SECRET="$("$PYTHON_BIN" -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')" \
  || die "Failed to generate cookie secret with $PYTHON_BIN."

# ----- Create namespace and secret -----
NAMESPACE="oauth2-proxy"
SECRET_NAME="oauth2-proxy-secrets"

# Create namespace if it doesn't exist.
if kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
  info "Namespace '$NAMESPACE' already exists."
else
  info "Creating namespace '$NAMESPACE'..."
  kubectl create namespace "$NAMESPACE" >/dev/null
fi

# If secret already exists, fail (safer than silently replacing).
if kubectl -n "$NAMESPACE" get secret "$SECRET_NAME" >/dev/null 2>&1; then
  die "Secret '$SECRET_NAME' already exists in namespace '$NAMESPACE'. Delete it first or choose a different name."
fi

info "Creating secret '$SECRET_NAME' in namespace '$NAMESPACE' from '$OAUTH_JSON'..."
kubectl -n "$NAMESPACE" create secret generic "$SECRET_NAME" \
  --from-literal=client-id="$CLIENT_ID" \
  --from-literal=client-secret="$CLIENT_SECRET" \
  --from-literal=cookie-secret="$COOKIE_SECRET" \
  >/dev/null

info "Done. Secret '$SECRET_NAME' created successfully."

# ----- Helpful reminder about redirect URIs -----
# Some Google OAuth client downloads include redirect URIs with trailing slashes.
# Make sure oauth2-proxy --redirect-url matches EXACTLY what you registered in Google.
warn "Reminder: ensure your oauth2-proxy --redirect-url matches an authorized redirect URI in Google EXACTLY (including trailing slashes if present)."
