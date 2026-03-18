#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Keep defaults aligned with current Kubernetes manifest image names:
# docker.io/mylonasc/magarathea:sandboxed-react-agent-backend-0.1.0
# docker.io/mylonasc/magarathea:sandboxed-react-agent-frontend-0.1.0
DOCKER_REGISTRY="${DOCKER_REGISTRY:-docker.io}"
DOCKERHUB_NAMESPACE="${DOCKERHUB_NAMESPACE:-mylonasc}"
IMAGE_REPO="${IMAGE_REPO:-magarathea}"
TAG="${TAG:-0.1.0}"

SANDBOX_IMAGE="${DOCKER_REGISTRY}/${DOCKERHUB_NAMESPACE}/${IMAGE_REPO}:pydata-sandbox-template-${TAG}"

echo "Building and pushing images:"
echo "  ${SANDBOX_IMAGE}"

echo
echo "[1/4] Building backend image"
docker build -t "${SANDBOX_IMAGE}" "."

echo
echo "[2/4] Pushing backend image"
docker push "${SANDBOX_IMAGE}"

