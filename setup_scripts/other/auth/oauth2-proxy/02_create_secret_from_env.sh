#!/usr/bin/env bash

set -euo pipefail

NAMESPACE="oauth2-proxy"
SECRET_NAME="oauth2-proxy-secrets"

if [[ -z "${OAUTH2_PROXY_CLIENT_SECRET:-}" ]]; then
  echo "ERROR: missing required env var OAUTH2_PROXY_CLIENT_SECRET" >&2
  exit 1
fi

OAUTH2_PROXY_CLIENT_ID="${OAUTH2_PROXY_CLIENT_ID:-oauth2-proxy}"

if [[ -z "${OAUTH2_PROXY_COOKIE_SECRET:-}" ]]; then
  command -v python3 >/dev/null 2>&1 || {
    echo "ERROR: python3 is required to auto-generate OAUTH2_PROXY_COOKIE_SECRET" >&2
    exit 1
  }
  OAUTH2_PROXY_COOKIE_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24)[:32])')"
  echo "INFO: generated OAUTH2_PROXY_COOKIE_SECRET automatically"
fi

command -v kubectl >/dev/null 2>&1 || {
  echo "ERROR: kubectl not found in PATH" >&2
  exit 1
}

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

kubectl -n "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
  --from-literal=client-id="${OAUTH2_PROXY_CLIENT_ID}" \
  --from-literal=client-secret="${OAUTH2_PROXY_CLIENT_SECRET}" \
  --from-literal=cookie-secret="${OAUTH2_PROXY_COOKIE_SECRET}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "oauth2-proxy secret applied: ${NAMESPACE}/${SECRET_NAME}"
