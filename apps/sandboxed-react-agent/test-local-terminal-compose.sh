#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Checking local compose health..."
if ! curl -fsS "http://127.0.0.1:8080/api/health" >/dev/null; then
  echo "Local app is not reachable at http://127.0.0.1:8080"
  echo "Start compose first: ./apps/sandboxed-react-agent/dev-sandbox.sh up local"
  exit 1
fi

echo "Ensuring router port-forward is available..."
pf_status="$("${SCRIPT_DIR}/dev-sandbox.sh" port-forward status || true)"
if [[ "${pf_status}" != *"Port-forward: running"* ]]; then
  "${SCRIPT_DIR}/dev-sandbox.sh" port-forward start
else
  printf '%s\n' "${pf_status}"
fi

echo "Switching backend runtime to cluster mode for interactive terminal..."
"${SCRIPT_DIR}/dev-sandbox.sh" mode cluster "http://host.docker.internal:18080" >/dev/null

echo "Running compose terminal e2e test..."
npm --prefix "${SCRIPT_DIR}/frontend" run test:e2e:terminal:compose

echo "Done. Terminal open path is verified against local docker compose."
