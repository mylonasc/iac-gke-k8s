#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/common.sh"

require_cmd kubectl
require_cmd python3

NAMESPACE=""
BACKEND_LABEL=""
USER_ID=""
SESSION_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --backend-label) BACKEND_LABEL="$2"; shift 2 ;;
    --user-id) USER_ID="$2"; shift 2 ;;
    --session-id) SESSION_ID="$2"; shift 2 ;;
    -h|--help)
      cat <<'EOF'
Usage: 10_smoke_test_workspace_flow.sh --namespace <NAMESPACE> --user-id <USER_ID> [options]

Mandatory flags:
  --namespace      Kubernetes namespace. Suggested default: alt-default.
  --user-id        Test user id for workspace provisioning. Suggested default: smoke-test-user.

Optional flags:
  --backend-label  Pod label selector for backend. Suggested default: app=sandboxed-react-agent-backend.
  --session-id     Session id to reuse. Suggested default: smoke-workspace-session.

This script:
  1. locates a running backend pod
  2. synchronously provisions the workspace for the given user
  3. creates a session for that user
  4. executes a shell command through SandboxLifecycleService that writes into /workspace
  5. prints the resulting workspace status and execution result
EOF
      exit 0
      ;;
    *) die "Unknown argument: $1" ;;
  esac
done

NAMESPACE=${NAMESPACE:-alt-default}
BACKEND_LABEL=${BACKEND_LABEL:-app=sandboxed-react-agent-backend}
SESSION_ID=${SESSION_ID:-smoke-workspace-session}

require_flag "namespace" "$NAMESPACE" "alt-default"
require_flag "user-id" "$USER_ID" "smoke-test-user"

note "Locating backend pod"
BACKEND_POD=$(kubectl get pods -n "$NAMESPACE" -l "$BACKEND_LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
[[ -n "$BACKEND_POD" ]] || die "Could not find a backend pod with label '$BACKEND_LABEL' in namespace '$NAMESPACE'"

TMP_SCRIPT=$(mktemp)
trap 'rm -f "$TMP_SCRIPT"' EXIT

cat > "$TMP_SCRIPT" <<'PY'
import json
import os

from app.main import agent

user_id = os.environ["SMOKE_USER_ID"]
session_id = os.environ["SMOKE_SESSION_ID"]

workspace = agent.ensure_workspace(user_id)
session = agent.get_or_create_session(session_id, user_id)
result = agent.sandbox_lifecycle.exec_shell(
    session.session_id,
    'printf "workspace smoke ok\n" > smoke-workspace.txt && pwd && ls -1',
    runtime_config=agent.get_runtime_config(user_id),
)
status = agent.get_workspace_status(user_id)

print(json.dumps({
    "workspace": workspace,
    "session_id": session.session_id,
    "result": result.as_tool_payload(),
    "status": status,
}, ensure_ascii=True))
PY

note "Running workspace smoke test inside backend pod"
kubectl cp "$TMP_SCRIPT" "$NAMESPACE/$BACKEND_POD:/tmp/workspace_smoke.py" >/dev/null
kubectl exec -n "$NAMESPACE" "$BACKEND_POD" -- env \
  PYTHONPATH="/app" \
  SMOKE_USER_ID="$USER_ID" \
  SMOKE_SESSION_ID="$SESSION_ID" \
  python3 /tmp/workspace_smoke.py
