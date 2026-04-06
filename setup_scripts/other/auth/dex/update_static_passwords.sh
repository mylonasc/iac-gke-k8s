#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEX_NAMESPACE="${DEX_NAMESPACE:-dex}"
STATIC_PASSWORDS_FILE="${DEX_STATIC_PASSWORDS_FILE:-${SCRIPT_DIR}/static-passwords.yaml}"
RESTART_DEX="true"

usage() {
  cat <<EOF
Update Dex static passwords from a local YAML file.

Usage:
  ./update_static_passwords.sh [--file /path/to/static-passwords.yaml] [--no-restart]

Options:
  --file PATH    Use a specific static passwords file.
  --no-restart   Update the dex-config secret without restarting Dex.
  -h, --help     Show this help message.

Environment overrides:
  DEX_NAMESPACE
  DEX_STATIC_PASSWORDS_FILE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --file requires a path argument" >&2
        exit 1
      fi
      STATIC_PASSWORDS_FILE="$2"
      shift 2
      ;;
    --no-restart)
      RESTART_DEX="false"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -f "${STATIC_PASSWORDS_FILE}" ]]; then
  echo "ERROR: static passwords file not found: ${STATIC_PASSWORDS_FILE}" >&2
  exit 1
fi

if [[ ! -s "${STATIC_PASSWORDS_FILE}" ]]; then
  echo "ERROR: static passwords file is empty: ${STATIC_PASSWORDS_FILE}" >&2
  exit 1
fi

export DEX_STATIC_PASSWORDS_FILE="${STATIC_PASSWORDS_FILE}"
"${SCRIPT_DIR}/03_create_dex_static_passwords_secret.sh"

if [[ "${RESTART_DEX}" == "true" ]]; then
  kubectl rollout restart deployment/dex -n "${DEX_NAMESPACE}"
  kubectl rollout status deployment/dex -n "${DEX_NAMESPACE}"
fi

echo "Static passwords updated from: ${DEX_STATIC_PASSWORDS_FILE}"
