#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"

usage() {
  echo "Usage: $0 [command]"
  echo
  echo "Commands:"
  echo "  up        Start the Authz Manager stack"
  echo "  down      Stop the Authz Manager stack"
  echo "  logs      Follow logs"
  echo "  restart   Restart the stack"
}

ensure_env() {
  if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo "Creating .env from .env.example..."
    cp "${SCRIPT_DIR}/.env.example" "${SCRIPT_DIR}/.env"
  fi
}

case "${1:-}" in
  up)
    ensure_env
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up --build -d
    echo "Authz Manager is starting..."
    echo "Access the UI at: http://localhost:8081"
    ;;
  down)
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" down
    ;;
  logs)
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" logs -f
    ;;
  restart)
    $0 down
    $0 up
    ;;
  *)
    usage
    exit 1
    ;;
esac
