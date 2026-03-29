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
DEX_STATIC_PASSWORDS_FILE="${DEX_STATIC_PASSWORDS_FILE:-}"

if [[ -n "${DEX_STATIC_PASSWORDS_FILE}" ]]; then
  if [[ ! -f "${DEX_STATIC_PASSWORDS_FILE}" ]]; then
    echo "ERROR: DEX_STATIC_PASSWORDS_FILE does not exist: ${DEX_STATIC_PASSWORDS_FILE}" >&2
    exit 1
  fi
  if [[ ! -s "${DEX_STATIC_PASSWORDS_FILE}" ]]; then
    echo "ERROR: DEX_STATIC_PASSWORDS_FILE is empty: ${DEX_STATIC_PASSWORDS_FILE}" >&2
    exit 1
  fi
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
      - ${DEX_OAUTH2_PROXY_REDIRECT_URI}
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

if [[ -n "${DEX_STATIC_PASSWORDS_FILE}" ]]; then
  {
    printf '\nenablePasswordDB: true\n'
    printf 'staticPasswords:\n'
    while IFS= read -r line || [[ -n "${line}" ]]; do
      if [[ -n "${line}" ]]; then
        printf '  %s\n' "${line}"
      else
        printf '\n'
      fi
    done <"${DEX_STATIC_PASSWORDS_FILE}"
  } >>"${tmp_file}"
fi

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

kubectl -n "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
  --from-file=config.yaml="${tmp_file}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Dex config secret applied: ${NAMESPACE}/${SECRET_NAME}"
echo "Next: kubectl apply -f dex.yaml && kubectl apply -f dex-ingress.example.yaml"
