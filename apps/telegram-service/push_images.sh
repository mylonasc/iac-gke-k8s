#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 || $# -gt 1 ]]; then
  echo "Usage: $0 <tag>"
  echo "Example: $0 0.1.1"
  exit 1
fi

TAG="$1"

"${SCRIPT_DIR}/build_and_push_image.sh" "${TAG}"

echo
echo "If TAG changed, update image tag in:"
echo "  ${SCRIPT_DIR}/k8s/deployment.yaml"
