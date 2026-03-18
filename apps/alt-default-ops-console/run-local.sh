#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "${SCRIPT_DIR}/.env.local" ]]; then
  echo "Missing ${SCRIPT_DIR}/.env.local"
  echo "Create it from .env.local.example and set OAUTH_CLIENT_SECRET."
  exit 1
fi

docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up --build -d
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" ps

echo
echo "Open: http://localhost (or http://localhost:8080)"
