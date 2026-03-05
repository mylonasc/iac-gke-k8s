#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.cluster"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}."
  echo "Create it from ${SCRIPT_DIR}/.env.cluster.example before running."
  exit 1
fi

docker compose --project-directory "${SCRIPT_DIR}" --env-file "${ENV_FILE}" up --build
