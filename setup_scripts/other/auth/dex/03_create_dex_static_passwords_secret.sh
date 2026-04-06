#!/usr/bin/env bash

set -euo pipefail

DEX_NAMESPACE="${DEX_NAMESPACE:-dex}"
DEX_STATIC_PASSWORDS_SECRET_NAME="${DEX_STATIC_PASSWORDS_SECRET_NAME:-dex-static-passwords}"
DEX_STATIC_PASSWORDS_FILE="${DEX_STATIC_PASSWORDS_FILE:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Create/update the dedicated Dex static passwords secret.

Usage:
  ./03_create_dex_static_passwords_secret.sh

Optional overrides:
  DEX_NAMESPACE
  DEX_STATIC_PASSWORDS_SECRET_NAME
  DEX_STATIC_PASSWORDS_FILE

If DEX_STATIC_PASSWORDS_FILE is unset, ./static-passwords.yaml is used when present.
EOF
  exit 0
fi

if [[ -z "${DEX_STATIC_PASSWORDS_FILE}" && -f "${SCRIPT_DIR}/static-passwords.yaml" ]]; then
  DEX_STATIC_PASSWORDS_FILE="${SCRIPT_DIR}/static-passwords.yaml"
fi

if [[ -z "${DEX_STATIC_PASSWORDS_FILE}" ]]; then
  echo "ERROR: DEX_STATIC_PASSWORDS_FILE is not set and ./static-passwords.yaml was not found" >&2
  exit 1
fi

if [[ ! -f "${DEX_STATIC_PASSWORDS_FILE}" ]]; then
  echo "ERROR: DEX_STATIC_PASSWORDS_FILE does not exist: ${DEX_STATIC_PASSWORDS_FILE}" >&2
  exit 1
fi

if [[ ! -s "${DEX_STATIC_PASSWORDS_FILE}" ]]; then
  echo "ERROR: DEX_STATIC_PASSWORDS_FILE is empty: ${DEX_STATIC_PASSWORDS_FILE}" >&2
  exit 1
fi

command -v kubectl >/dev/null 2>&1 || {
  echo "ERROR: kubectl not found in PATH" >&2
  exit 1
}

kubectl get namespace "${DEX_NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${DEX_NAMESPACE}"

kubectl -n "${DEX_NAMESPACE}" create secret generic "${DEX_STATIC_PASSWORDS_SECRET_NAME}" \
  --from-file=static-passwords.yaml="${DEX_STATIC_PASSWORDS_FILE}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Dex static passwords secret applied: ${DEX_NAMESPACE}/${DEX_STATIC_PASSWORDS_SECRET_NAME}"
