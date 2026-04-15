#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"
PORT_FORWARD_PID_FILE="${SCRIPT_DIR}/.sandbox-router-port-forward.pid"
PORT_FORWARD_LOG_FILE="${SCRIPT_DIR}/.sandbox-router-port-forward.log"

BACKEND_CONFIG_URL="${BACKEND_CONFIG_URL:-http://localhost:8080/api/config}"
BACKEND_HEALTH_URL="${BACKEND_HEALTH_URL:-http://localhost:8080/api/health}"
ROUTER_NAMESPACE="${ROUTER_NAMESPACE:-alt-default}"
ROUTER_SERVICE="${ROUTER_SERVICE:-sandbox-router-svc}"
ROUTER_DEPLOYMENT="${ROUTER_DEPLOYMENT:-sandbox-router-deployment}"
ROUTER_LOCAL_PORT="${ROUTER_LOCAL_PORT:-18080}"
ROUTER_REMOTE_PORT="${ROUTER_REMOTE_PORT:-8080}"
PORT_FORWARD_START_TIMEOUT_SECONDS="${PORT_FORWARD_START_TIMEOUT_SECONDS:-15}"
ROUTER_ENDPOINTS_WAIT_TIMEOUT_SECONDS="${ROUTER_ENDPOINTS_WAIT_TIMEOUT_SECONDS:-60}"
AUTO_SCALE_ROUTER_ON_PORT_FORWARD_START="${AUTO_SCALE_ROUTER_ON_PORT_FORWARD_START:-1}"
ROUTER_SCALE_TARGET_REPLICAS="${ROUTER_SCALE_TARGET_REPLICAS:-1}"
ROUTER_SCALE_ROLLOUT_TIMEOUT="${ROUTER_SCALE_ROLLOUT_TIMEOUT:-240s}"
PORT_FORWARD_BIND_ADDRESSES="${PORT_FORWARD_BIND_ADDRESSES:-0.0.0.0}"

usage() {
  cat <<EOF
Usage: ./dev-sandbox.sh <command> [options]

Commands:
  up local|cluster         Start docker compose using .env.local or .env.cluster
  down                     Stop docker compose
  mode local|cluster       Switch backend sandbox mode via /api/config
  template <name>          Switch backend sandbox template via /api/config
  status                   Show backend health + current runtime config
  logs backend [--follow]  Show local backend logs
  logs backend-k8s [--follow]  Show backend logs from Kubernetes deployment
  logs router-k8s [--follow]   Show sandbox-router logs from Kubernetes deployment
  port-forward start       Start sandbox router kubectl port-forward in background
  port-forward restart     Restart sandbox router port-forward
  port-forward stop        Stop sandbox router port-forward
  port-forward status      Show sandbox router port-forward status
  help                     Show this help

Notes:
  - Local mode runs tools inside backend container.
  - Cluster mode runs tools via Agent Sandbox router.
  - For cluster mode from docker compose, use SANDBOX_API_URL=http://host.docker.internal:18080
  - port-forward start can auto-scale router deployment from 0 replicas.
  - Port-forward binds to ${PORT_FORWARD_BIND_ADDRESSES} by default.
EOF
}

ensure_env_file() {
  local env_file="$1"
  local example_file="$2"
  if [[ ! -f "${env_file}" ]]; then
    echo "Missing ${env_file}."
    echo "Create it from ${example_file} before running."
    exit 1
  fi
}

compose_up() {
  local mode="$1"
  local env_file="${SCRIPT_DIR}/.env.${mode}"
  local example_file="${SCRIPT_DIR}/.env.${mode}.example"
  ensure_env_file "${env_file}" "${example_file}"
  
  if [[ "${mode}" == "cluster" ]]; then
    echo "Cluster mode detected. Ensuring sandbox router port-forward is running..."
    port_forward_start
  fi

  docker compose --project-directory "${PROJECT_DIR}" --env-file "${env_file}" up --build
}

compose_down() {
  docker compose --project-directory "${PROJECT_DIR}" down
}

post_mode() {
  local mode="$1"
  local sandbox_api_url="${2:-}"

  local payload
  if [[ -n "${sandbox_api_url}" ]]; then
    payload=$(python3 -c 'import json,sys; print(json.dumps({"sandbox_mode": sys.argv[1], "sandbox_api_url": sys.argv[2]}))' "${mode}" "${sandbox_api_url}")
  else
    payload=$(python3 -c 'import json,sys; print(json.dumps({"sandbox_mode": sys.argv[1]}))' "${mode}")
  fi

  echo "Switching backend sandbox mode to '${mode}' via ${BACKEND_CONFIG_URL}"
  curl -sS -X POST "${BACKEND_CONFIG_URL}" \
    -H "Content-Type: application/json" \
    --data "${payload}"
  echo
}

post_template() {
  local template_name="$1"
  if [[ -z "${template_name}" ]]; then
    echo "Usage: ./dev-sandbox.sh template <template-name>"
    exit 1
  fi

  local payload
  payload=$(python3 -c 'import json,sys; print(json.dumps({"sandbox_template_name": sys.argv[1]}))' "${template_name}")

  echo "Switching backend sandbox template to '${template_name}' via ${BACKEND_CONFIG_URL}"
  curl -sS -X POST "${BACKEND_CONFIG_URL}" \
    -H "Content-Type: application/json" \
    --data "${payload}"
  echo
}

show_status() {
  echo "Health (${BACKEND_HEALTH_URL}):"
  curl -sS "${BACKEND_HEALTH_URL}"
  echo
  echo "Config (${BACKEND_CONFIG_URL}):"
  curl -sS "${BACKEND_CONFIG_URL}"
  echo
  port_forward_status
}

show_logs() {
  local target="${1:-backend}"
  local follow_flag="${2:-}"
  local follow_args=()

  if [[ "${follow_flag}" == "--follow" ]]; then
    follow_args+=("-f")
  fi

  case "${target}" in
    backend)
      docker compose --project-directory "${PROJECT_DIR}" logs --tail=300 "${follow_args[@]}" backend
      ;;
    backend-k8s)
      kubectl -n "${ROUTER_NAMESPACE}" logs deployment/sandboxed-react-agent-backend --tail=300 "${follow_args[@]}"
      ;;
    router-k8s)
      kubectl -n "${ROUTER_NAMESPACE}" logs deployment/"${ROUTER_DEPLOYMENT}" --tail=300 "${follow_args[@]}"
      ;;
    *)
      echo "Usage: ./dev-sandbox.sh logs backend|backend-k8s|router-k8s [--follow]"
      exit 1
      ;;
  esac
}

is_pid_running() {
  local pid="$1"
  kill -0 "${pid}" >/dev/null 2>&1
}

is_local_port_open() {
  local host="$1"
  local port="$2"
  python3 -c 'import socket,sys; s=socket.socket(); s.settimeout(0.5); rc=s.connect_ex((sys.argv[1], int(sys.argv[2]))); s.close(); raise SystemExit(0 if rc == 0 else 1)' "${host}" "${port}"
}

router_has_ready_endpoints() {
  local endpoint_ips
  endpoint_ips="$(kubectl -n "${ROUTER_NAMESPACE}" get endpoints "${ROUTER_SERVICE}" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null || true)"
  [[ -n "${endpoint_ips}" ]]
}

wait_for_router_endpoints_ready() {
  local elapsed=0
  while (( elapsed < ROUTER_ENDPOINTS_WAIT_TIMEOUT_SECONDS )); do
    if router_has_ready_endpoints; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

maybe_scale_router_for_port_forward() {
  if [[ "${AUTO_SCALE_ROUTER_ON_PORT_FORWARD_START}" != "1" ]]; then
    return 0
  fi

  if ! kubectl -n "${ROUTER_NAMESPACE}" get deployment "${ROUTER_DEPLOYMENT}" >/dev/null 2>&1; then
    return 0
  fi

  local current_replicas
  current_replicas="$(kubectl -n "${ROUTER_NAMESPACE}" get deployment "${ROUTER_DEPLOYMENT}" -o jsonpath='{.spec.replicas}' 2>/dev/null || true)"
  current_replicas="${current_replicas:-0}"

  if [[ "${current_replicas}" != "0" ]]; then
    return 0
  fi

  echo "Router deployment ${ROUTER_DEPLOYMENT} is scaled to 0; scaling to ${ROUTER_SCALE_TARGET_REPLICAS} for interactive testing."
  kubectl -n "${ROUTER_NAMESPACE}" scale deployment/"${ROUTER_DEPLOYMENT}" --replicas="${ROUTER_SCALE_TARGET_REPLICAS}" >/dev/null
  kubectl -n "${ROUTER_NAMESPACE}" rollout status deployment/"${ROUTER_DEPLOYMENT}" --timeout="${ROUTER_SCALE_ROLLOUT_TIMEOUT}" >/dev/null
}

wait_for_port_forward_ready() {
  local pid="$1"
  local elapsed=0
  while (( elapsed < PORT_FORWARD_START_TIMEOUT_SECONDS )); do
    if ! is_pid_running "${pid}"; then
      return 1
    fi
    if is_local_port_open "127.0.0.1" "${ROUTER_LOCAL_PORT}"; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  return 1
}

port_forward_start() {
  if [[ -f "${PORT_FORWARD_PID_FILE}" ]]; then
    local existing_pid
    existing_pid="$(cat "${PORT_FORWARD_PID_FILE}")"
    if [[ -n "${existing_pid}" ]] && is_pid_running "${existing_pid}"; then
      echo "Port-forward already running (pid ${existing_pid})."
      echo "Log: ${PORT_FORWARD_LOG_FILE}"
      return 0
    fi
    rm -f "${PORT_FORWARD_PID_FILE}"
  fi

  maybe_scale_router_for_port_forward

  if ! wait_for_router_endpoints_ready; then
    echo "Sandbox router service has no ready endpoints: ${ROUTER_SERVICE} (ns=${ROUTER_NAMESPACE})."
    echo "If runtime is intentionally idle, scale router deployment for interactive testing:"
    echo "  kubectl -n ${ROUTER_NAMESPACE} scale deployment/${ROUTER_DEPLOYMENT} --replicas=1"
    exit 1
  fi

  echo "Starting port-forward: svc/${ROUTER_SERVICE} ${ROUTER_LOCAL_PORT}:${ROUTER_REMOTE_PORT} (ns=${ROUTER_NAMESPACE}, addresses=${PORT_FORWARD_BIND_ADDRESSES})"
  nohup kubectl -n "${ROUTER_NAMESPACE}" port-forward --address "${PORT_FORWARD_BIND_ADDRESSES}" "svc/${ROUTER_SERVICE}" "${ROUTER_LOCAL_PORT}:${ROUTER_REMOTE_PORT}" >"${PORT_FORWARD_LOG_FILE}" 2>&1 &
  local pf_pid=$!
  echo "${pf_pid}" >"${PORT_FORWARD_PID_FILE}"

  if wait_for_port_forward_ready "${pf_pid}"; then
    echo "Port-forward started (pid ${pf_pid})."
    echo "Router should be reachable at http://127.0.0.1:${ROUTER_LOCAL_PORT}"
    echo "Log: ${PORT_FORWARD_LOG_FILE}"
  else
    echo "Failed to start port-forward or local port did not open in time."
    echo "Check log: ${PORT_FORWARD_LOG_FILE}"
    rm -f "${PORT_FORWARD_PID_FILE}"
    exit 1
  fi
}

port_forward_stop() {
  if [[ ! -f "${PORT_FORWARD_PID_FILE}" ]]; then
    echo "No tracked port-forward process found."
    return 0
  fi

  local pf_pid
  pf_pid="$(cat "${PORT_FORWARD_PID_FILE}")"
  if [[ -n "${pf_pid}" ]] && is_pid_running "${pf_pid}"; then
    kill "${pf_pid}"
    sleep 1
    if is_pid_running "${pf_pid}"; then
      kill -9 "${pf_pid}" >/dev/null 2>&1 || true
    fi
    echo "Stopped port-forward (pid ${pf_pid})."
  else
    echo "Tracked port-forward pid is not running."
  fi

  rm -f "${PORT_FORWARD_PID_FILE}"
}

port_forward_status() {
  if [[ ! -f "${PORT_FORWARD_PID_FILE}" ]]; then
    echo "Port-forward: stopped"
    return 0
  fi

  local pf_pid
  pf_pid="$(cat "${PORT_FORWARD_PID_FILE}")"
  if [[ -n "${pf_pid}" ]] && is_pid_running "${pf_pid}"; then
    echo "Port-forward: running (pid ${pf_pid})"
    echo "Router URL: http://127.0.0.1:${ROUTER_LOCAL_PORT}"
    echo "Log: ${PORT_FORWARD_LOG_FILE}"
  else
    echo "Port-forward: stopped (stale pid file)"
    rm -f "${PORT_FORWARD_PID_FILE}"
  fi
}

main() {
  local command="${1:-help}"
  case "${command}" in
    up)
      local mode="${2:-}"
      case "${mode}" in
        local|cluster) compose_up "${mode}" ;;
        *)
          echo "Usage: ./dev-sandbox.sh up local|cluster"
          exit 1
          ;;
      esac
      ;;
    down)
      compose_down
      ;;
    mode)
      local mode_value="${2:-}"
      local api_url="${3:-}"
      case "${mode_value}" in
        local|cluster) post_mode "${mode_value}" "${api_url}" ;;
        *)
          echo "Usage: ./dev-sandbox.sh mode local|cluster [sandbox_api_url]"
          exit 1
          ;;
      esac
      ;;
    template)
      post_template "${2:-}"
      ;;
    status)
      show_status
      ;;
    logs)
      show_logs "${2:-backend}" "${3:-}"
      ;;
    port-forward)
      local subcommand="${2:-status}"
      case "${subcommand}" in
        start) port_forward_start ;;
        restart)
          port_forward_stop
          port_forward_start
          ;;
        stop) port_forward_stop ;;
        status) port_forward_status ;;
        *)
          echo "Usage: ./dev-sandbox.sh port-forward start|restart|stop|status"
          exit 1
          ;;
      esac
      ;;
    help|-h|--help)
      usage
      ;;
    *)
      echo "Unknown command: ${command}"
      usage
      exit 1
      ;;
  esac
}

main "$@"
