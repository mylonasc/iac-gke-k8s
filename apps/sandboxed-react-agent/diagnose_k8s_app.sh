#!/usr/bin/env bash
set -u

NAMESPACE="${NAMESPACE:-alt-default}"
APP_BACKEND_DEPLOY="${APP_BACKEND_DEPLOY:-sandboxed-react-agent-backend}"
APP_FRONTEND_DEPLOY="${APP_FRONTEND_DEPLOY:-sandboxed-react-agent-frontend}"
SANDBOX_ROUTER_SVC="${SANDBOX_ROUTER_SVC:-sandbox-router-svc}"
TIMEOUT_ROLLOUT="${TIMEOUT_ROLLOUT:-60s}"
TIMEOUT_WAIT_POD="${TIMEOUT_WAIT_POD:-90s}"
TIMEOUT_CURL="${TIMEOUT_CURL:-60}"
LOG_SINCE="${LOG_SINCE:-20m}"

PASS_COUNT=0
FAIL_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf '[PASS] %s\n' "$1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf '[FAIL] %s\n' "$1"
}

run_curl_probe() {
  local path="$1"
  local method="${2:-GET}"
  local data="${3:-}"
  local pod_name
  local output

  pod_name="diag-probe-$(date +%s)-$RANDOM"

  if [[ -n "${data}" ]]; then
    kubectl -n "${NAMESPACE}" run "${pod_name}" --image=curlimages/curl:8.10.1 --restart=Never --command -- \
      sh -c "curl --max-time ${TIMEOUT_CURL} -sS -X ${method} http://${APP_BACKEND_DEPLOY}${path} -H 'Content-Type: application/json' -d '${data}'" >/dev/null 2>&1
  else
    kubectl -n "${NAMESPACE}" run "${pod_name}" --image=curlimages/curl:8.10.1 --restart=Never --command -- \
      sh -c "curl --max-time ${TIMEOUT_CURL} -sS -X ${method} http://${APP_BACKEND_DEPLOY}${path}" >/dev/null 2>&1
  fi

  if ! kubectl -n "${NAMESPACE}" wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${pod_name}" --timeout="${TIMEOUT_WAIT_POD}" >/dev/null 2>&1; then
    kubectl -n "${NAMESPACE}" logs "pod/${pod_name}" >/tmp/${pod_name}.log 2>/dev/null || true
    kubectl -n "${NAMESPACE}" delete pod "${pod_name}" --ignore-not-found >/dev/null 2>&1 || true
    printf '__PROBE_ERROR__%s' "${pod_name}"
    return 1
  fi

  output="$(kubectl -n "${NAMESPACE}" logs "pod/${pod_name}" 2>/dev/null || true)"
  kubectl -n "${NAMESPACE}" delete pod "${pod_name}" --ignore-not-found >/dev/null 2>&1 || true
  printf '%s' "${output}"
  return 0
}

assert_json_field() {
  local json_payload="$1"
  local py_check="$2"
  python3 -c "import json,sys; data=json.loads(sys.argv[1]); ${py_check}" "${json_payload}" >/dev/null
}

echo "Running diagnostics for sandboxed-react-agent in namespace ${NAMESPACE}"

if kubectl -n "${NAMESPACE}" rollout status "deployment/${APP_BACKEND_DEPLOY}" --timeout="${TIMEOUT_ROLLOUT}" >/dev/null 2>&1; then
  pass "Backend deployment is ready"
else
  fail "Backend deployment is not ready"
fi

if kubectl -n "${NAMESPACE}" rollout status "deployment/${APP_FRONTEND_DEPLOY}" --timeout="${TIMEOUT_ROLLOUT}" >/dev/null 2>&1; then
  pass "Frontend deployment is ready"
else
  fail "Frontend deployment is not ready"
fi

ROUTER_ENDPOINTS="$(kubectl -n "${NAMESPACE}" get endpoints "${SANDBOX_ROUTER_SVC}" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null || true)"
if [[ -n "${ROUTER_ENDPOINTS}" ]]; then
  pass "Sandbox router has ready endpoints (${ROUTER_ENDPOINTS})"
else
  fail "Sandbox router has no ready endpoints"
fi

HEALTH_RESPONSE="$(run_curl_probe '/api/health' 'GET' 2>/dev/null || true)"
if [[ "${HEALTH_RESPONSE}" == *'"status":"ok"'* ]]; then
  pass "Backend /api/health responds with status ok"
else
  fail "Backend /api/health failed (${HEALTH_RESPONSE})"
fi

CONFIG_RESPONSE="$(run_curl_probe '/api/config' 'GET' 2>/dev/null || true)"
if assert_json_field "${CONFIG_RESPONSE}" "assert 'model' in data and 'sandbox' in data"; then
  pass "Backend /api/config returns runtime config"
else
  fail "Backend /api/config did not return expected JSON (${CONFIG_RESPONSE})"
fi

SIMPLE_CHAT='{"message":"Reply with exactly: READY"}'
SIMPLE_CHAT_RESPONSE="$(run_curl_probe '/api/chat' 'POST' "${SIMPLE_CHAT}" 2>/dev/null || true)"
if assert_json_field "${SIMPLE_CHAT_RESPONSE}" "assert data.get('reply'); assert not data.get('error')"; then
  pass "Simple /api/chat request succeeds"
else
  fail "Simple /api/chat request failed (${SIMPLE_CHAT_RESPONSE})"
fi

TOOL_CHAT='{"message":"Use sandbox_exec_python once to compute 2+2 and return only the number."}'
TOOL_CHAT_RESPONSE="$(run_curl_probe '/api/chat' 'POST' "${TOOL_CHAT}" 2>/dev/null || true)"
if assert_json_field "${TOOL_CHAT_RESPONSE}" "assert isinstance(data.get('tool_calls'), list); assert len(data.get('tool_calls', [])) >= 1; assert not data.get('error')"; then
  pass "Tool-call /api/chat request succeeded with at least one tool call"
else
  fail "Tool-call /api/chat request failed (${TOOL_CHAT_RESPONSE})"
fi

BACKEND_LOGS="$(kubectl -n "${NAMESPACE}" logs "deployment/${APP_BACKEND_DEPLOY}" --since="${LOG_SINCE}" --tail=300 2>/dev/null || true)"
if [[ "${BACKEND_LOGS}" == *"Read timed out"* ]] || [[ "${BACKEND_LOGS}" == *"Request to gateway router failed"* ]]; then
  fail "Backend logs show sandbox router timeout/errors"
else
  pass "Backend logs show no recent sandbox router timeout/errors"
fi

ROUTER_RESTARTS="$(kubectl -n "${NAMESPACE}" get pods -l app=sandbox-router -o jsonpath='{range .items[*]}{.status.containerStatuses[0].restartCount}{"\n"}{end}' 2>/dev/null || true)"
if [[ "${ROUTER_RESTARTS}" == *$'\n'* ]] || [[ -n "${ROUTER_RESTARTS}" ]]; then
  if printf '%s' "${ROUTER_RESTARTS}" | grep -Eq '^[1-9][0-9]*$'; then
    fail "Sandbox router pod has container restarts (${ROUTER_RESTARTS//$'\n'/, })"
  else
    pass "Sandbox router pod has no container restarts"
  fi
fi

echo
echo "Diagnostics summary: ${PASS_COUNT} passed, ${FAIL_COUNT} failed"

if [[ ${FAIL_COUNT} -gt 0 ]]; then
  echo "Recommendations:"
  echo "- Check router pod health: kubectl -n ${NAMESPACE} get pods -l app=sandbox-router -o wide"
  echo "- Check backend logs: kubectl -n ${NAMESPACE} logs deployment/${APP_BACKEND_DEPLOY} --tail=300"
  echo "- Re-run this script after stabilizing router/backing nodes"
  exit 1
fi

exit 0
