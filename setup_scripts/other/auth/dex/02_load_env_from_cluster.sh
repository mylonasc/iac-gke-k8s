#!/usr/bin/env bash

set -euo pipefail

DEX_NAMESPACE="${DEX_NAMESPACE:-dex}"
DEX_SECRET_NAME="${DEX_SECRET_NAME:-dex-config}"
OAUTH2_PROXY_NAMESPACE="${OAUTH2_PROXY_NAMESPACE:-oauth2-proxy}"
OAUTH2_PROXY_SECRET_NAME="${OAUTH2_PROXY_SECRET_NAME:-oauth2-proxy-secrets}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Load Dex env vars from deployed Kubernetes secrets.

Usage:
  eval "$(./02_load_env_from_cluster.sh)"

Optional overrides:
  DEX_NAMESPACE
  DEX_SECRET_NAME
  OAUTH2_PROXY_NAMESPACE
  OAUTH2_PROXY_SECRET_NAME
EOF
  exit 0
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

require_cmd kubectl
require_cmd yq
require_cmd base64

DEX_CONFIG_B64="$(kubectl get secret "${DEX_SECRET_NAME}" -n "${DEX_NAMESPACE}" -o jsonpath='{.data.config\.yaml}')"
if [[ -z "${DEX_CONFIG_B64}" ]]; then
  echo "ERROR: secret ${DEX_NAMESPACE}/${DEX_SECRET_NAME} missing .data.config.yaml" >&2
  exit 1
fi
DEX_CONFIG_YAML="$(printf '%s' "${DEX_CONFIG_B64}" | base64 -d)"

yaml_get() {
  local expr="$1"
  yq -r "${expr} // \"\"" <<<"${DEX_CONFIG_YAML}"
}

DEX_ISSUER_URL="$(yaml_get '.issuer')"
DEX_OAUTH2_PROXY_CLIENT_ID="$(yaml_get '(.staticClients // [] | map(select(.id == "oauth2-proxy")) | .[0].id)')"
DEX_OAUTH2_PROXY_REDIRECT_URI="$(yaml_get '(.staticClients // [] | map(select(.id == "oauth2-proxy")) | .[0].redirectURIs[0])')"
DEX_OAUTH2_PROXY_CLIENT_SECRET="$(yaml_get '(.staticClients // [] | map(select(.id == "oauth2-proxy")) | .[0].secret)')"

DEX_GITHUB_CLIENT_ID="$(yaml_get '(.connectors // [] | map(select(.id == "github")) | .[0].config.clientID)')"
DEX_GITHUB_CLIENT_SECRET="$(yaml_get '(.connectors // [] | map(select(.id == "github")) | .[0].config.clientSecret)')"

DEX_MICROSOFT_CLIENT_ID="$(yaml_get '(.connectors // [] | map(select(.id == "microsoft")) | .[0].config.clientID)')"
DEX_MICROSOFT_CLIENT_SECRET="$(yaml_get '(.connectors // [] | map(select(.id == "microsoft")) | .[0].config.clientSecret)')"
DEX_MICROSOFT_TENANT="$(yaml_get '(.connectors // [] | map(select(.id == "microsoft")) | .[0].config.tenant)')"

DEX_GOOGLE_CLIENT_ID="$(yaml_get '(.connectors // [] | map(select(.id == "google")) | .[0].config.clientID)')"
DEX_GOOGLE_CLIENT_SECRET="$(yaml_get '(.connectors // [] | map(select(.id == "google")) | .[0].config.clientSecret)')"

if [[ -z "${DEX_OAUTH2_PROXY_CLIENT_SECRET}" ]]; then
  OAUTH_SECRET_B64="$(kubectl get secret "${OAUTH2_PROXY_SECRET_NAME}" -n "${OAUTH2_PROXY_NAMESPACE}" -o jsonpath='{.data.client-secret}' 2>/dev/null || true)"
  if [[ -n "${OAUTH_SECRET_B64}" ]]; then
    DEX_OAUTH2_PROXY_CLIENT_SECRET="$(printf '%s' "${OAUTH_SECRET_B64}" | base64 -d)"
  fi
fi

required_vars=(
  DEX_ISSUER_URL
  DEX_OAUTH2_PROXY_REDIRECT_URI
  DEX_OAUTH2_PROXY_CLIENT_SECRET
  DEX_GITHUB_CLIENT_ID
  DEX_GITHUB_CLIENT_SECRET
  DEX_MICROSOFT_CLIENT_ID
  DEX_MICROSOFT_CLIENT_SECRET
  DEX_GOOGLE_CLIENT_ID
  DEX_GOOGLE_CLIENT_SECRET
)

missing=()
for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    missing+=("${var_name}")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "ERROR: missing required values from deployed config:" >&2
  for var_name in "${missing[@]}"; do
    echo "  - ${var_name}" >&2
  done
  exit 1
fi

if [[ -z "${DEX_OAUTH2_PROXY_CLIENT_ID}" ]]; then
  DEX_OAUTH2_PROXY_CLIENT_ID="oauth2-proxy"
fi
if [[ -z "${DEX_MICROSOFT_TENANT}" ]]; then
  DEX_MICROSOFT_TENANT="common"
fi

export_vars=(
  DEX_ISSUER_URL
  DEX_OAUTH2_PROXY_REDIRECT_URI
  DEX_OAUTH2_PROXY_CLIENT_ID
  DEX_OAUTH2_PROXY_CLIENT_SECRET
  DEX_GITHUB_CLIENT_ID
  DEX_GITHUB_CLIENT_SECRET
  DEX_MICROSOFT_CLIENT_ID
  DEX_MICROSOFT_CLIENT_SECRET
  DEX_MICROSOFT_TENANT
  DEX_GOOGLE_CLIENT_ID
  DEX_GOOGLE_CLIENT_SECRET
)

for var_name in "${export_vars[@]}"; do
  printf 'export %s=%q\n' "${var_name}" "${!var_name}"
done
