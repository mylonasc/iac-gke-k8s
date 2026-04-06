#!/usr/bin/env bash

set -euo pipefail

NAMESPACE="dex"
SECRET_NAME="dex-config"

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

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "ERROR: missing required env var: ${var_name}" >&2
    exit 1
  fi
done

DEX_OAUTH2_PROXY_CLIENT_ID="${DEX_OAUTH2_PROXY_CLIENT_ID:-oauth2-proxy}"
DEX_MICROSOFT_TENANT="${DEX_MICROSOFT_TENANT:-common}"
DEX_ISSUER_URL="${DEX_ISSUER_URL%/}"
DEX_OAUTH2_PROXY_EXTRA_REDIRECT_URIS="${DEX_OAUTH2_PROXY_EXTRA_REDIRECT_URIS:-}"

declare -a OAUTH2_PROXY_REDIRECT_URIS
OAUTH2_PROXY_REDIRECT_URIS=("${DEX_OAUTH2_PROXY_REDIRECT_URI}")

if [[ -n "${DEX_OAUTH2_PROXY_EXTRA_REDIRECT_URIS}" ]]; then
  IFS=',' read -r -a _extra_redirects <<<"${DEX_OAUTH2_PROXY_EXTRA_REDIRECT_URIS}"
  for uri in "${_extra_redirects[@]}"; do
    trimmed="$(echo "${uri}" | xargs)"
    if [[ -n "${trimmed}" ]]; then
      OAUTH2_PROXY_REDIRECT_URIS+=("${trimmed}")
    fi
  done
fi

command -v kubectl >/dev/null 2>&1 || {
  echo "ERROR: kubectl not found in PATH" >&2
  exit 1
}

tmp_file="$(mktemp)"
trap 'rm -f "${tmp_file}"' EXIT

cat >"${tmp_file}" <<EOF
issuer: ${DEX_ISSUER_URL}
storage:
  type: sqlite3
  config:
    file: /var/dex/dex.db
web:
  http: 0.0.0.0:5556
telemetry:
  http: 0.0.0.0:5558
oauth2:
  skipApprovalScreen: true
staticClients:
  - id: ${DEX_OAUTH2_PROXY_CLIENT_ID}
    name: oauth2-proxy
    secret: ${DEX_OAUTH2_PROXY_CLIENT_SECRET}
    redirectURIs:
EOF

for redirect_uri in "${OAUTH2_PROXY_REDIRECT_URIS[@]}"; do
  printf '      - %s\n' "${redirect_uri}" >>"${tmp_file}"
done

cat >>"${tmp_file}" <<EOF
connectors:
  - type: github
    id: github
    name: GitHub
    config:
      clientID: ${DEX_GITHUB_CLIENT_ID}
      clientSecret: ${DEX_GITHUB_CLIENT_SECRET}
      # Connector callback must be Dex callback endpoint (not oauth2-proxy callback).
      redirectURI: ${DEX_ISSUER_URL}/callback
  - type: microsoft
    id: microsoft
    name: Microsoft
    config:
      clientID: ${DEX_MICROSOFT_CLIENT_ID}
      clientSecret: ${DEX_MICROSOFT_CLIENT_SECRET}
      # Connector callback must be Dex callback endpoint (not oauth2-proxy callback).
      redirectURI: ${DEX_ISSUER_URL}/callback
      tenant: ${DEX_MICROSOFT_TENANT}
  - type: google
    id: google
    name: Google
    config:
      clientID: ${DEX_GOOGLE_CLIENT_ID}
      clientSecret: ${DEX_GOOGLE_CLIENT_SECRET}
      # Connector callback must be Dex callback endpoint (not oauth2-proxy callback).
      redirectURI: ${DEX_ISSUER_URL}/callback
EOF

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

kubectl -n "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
  --from-file=config.yaml="${tmp_file}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Dex config secret applied: ${NAMESPACE}/${SECRET_NAME}"
echo "Next: kubectl apply -f dex.yaml && kubectl apply -f dex-ingress.example.yaml"
