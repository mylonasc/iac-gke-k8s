#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 1 ]]; then
  echo "Usage: $0 <tag>"
  echo "Example: $0 0.1.0"
  echo "Override registry parts with DOCKER_REGISTRY, DOCKERHUB_NAMESPACE, IMAGE_REPO"
  exit 1
fi

TAG="$1"
DOCKER_REGISTRY="${DOCKER_REGISTRY:-docker.io}"
DOCKERHUB_NAMESPACE="${DOCKERHUB_NAMESPACE:-mylonasc}"
IMAGE_REPO="${IMAGE_REPO:-magarathea}"
IMAGE="${DOCKER_REGISTRY}/${DOCKERHUB_NAMESPACE}/${IMAGE_REPO}:telegram-service-${TAG}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Building image: ${IMAGE}"
docker build -t "${IMAGE}" "${SCRIPT_DIR}"

echo "Pushing image: ${IMAGE}"
docker push "${IMAGE}"

echo "Done."
echo "Pushed: ${IMAGE}"
