#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v kubectl >/dev/null 2>&1; then
  export TESTER_GATEWAY_URL="${TESTER_GATEWAY_URL:-http://127.0.0.1:8000}"
  export TESTER_DEX_ISSUER="${TESTER_DEX_ISSUER:-https://magarathea.ddns.net/dex}"
  export TESTER_DEX_CLIENT_ID="${TESTER_DEX_CLIENT_ID:-oauth2-proxy}"
  export TESTER_DEX_REDIRECT_URI="${TESTER_DEX_REDIRECT_URI:-http://localhost:8090/dex/callback}"
  export TESTER_DEX_SCOPES="${TESTER_DEX_SCOPES:-openid profile email}"

  if [[ -z "${TESTER_COOKIE_SECRET:-}" ]]; then
    TESTER_COOKIE_SECRET="$(kubectl -n oauth2-proxy get secret oauth2-proxy-secrets -o jsonpath='{.data.cookie-secret}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    export TESTER_COOKIE_SECRET
  fi

  if [[ -z "${TESTER_DEX_CLIENT_SECRET:-}" ]]; then
    TESTER_DEX_CLIENT_SECRET="$(kubectl -n dex get secret dex-config -o jsonpath='{.data.config\.yaml}' 2>/dev/null | base64 -d 2>/dev/null | yq -r '.staticClients[] | select(.id=="oauth2-proxy") | .secret' 2>/dev/null || true)"
    if [[ -z "${TESTER_DEX_CLIENT_SECRET}" ]]; then
      TESTER_DEX_CLIENT_SECRET="$(kubectl -n oauth2-proxy get secret oauth2-proxy-secrets -o jsonpath='{.data.client-secret}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    fi
    export TESTER_DEX_CLIENT_SECRET
  fi

  if [[ -z "${TESTER_ADMIN_USERNAME:-}" ]]; then
    TESTER_ADMIN_USERNAME="$(kubectl -n telegram-gateway get secret telegram-service-secrets -o jsonpath='{.data.ADMIN_USERNAME}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    export TESTER_ADMIN_USERNAME
  fi

  if [[ -z "${TESTER_ADMIN_PASSWORD:-}" ]]; then
    TESTER_ADMIN_PASSWORD="$(kubectl -n telegram-gateway get secret telegram-service-secrets -o jsonpath='{.data.ADMIN_PASSWORD}' 2>/dev/null | base64 -d 2>/dev/null || true)"
    export TESTER_ADMIN_PASSWORD
  fi
fi

python3 -m venv "${SCRIPT_DIR}/.venv"
"${SCRIPT_DIR}/.venv/bin/pip" install --upgrade pip
"${SCRIPT_DIR}/.venv/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt"

exec "${SCRIPT_DIR}/.venv/bin/uvicorn" app:app --host localhost --port 8090 --app-dir "${SCRIPT_DIR}"
