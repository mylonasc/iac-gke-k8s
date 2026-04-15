#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Keep defaults aligned with current Kubernetes manifest image name:
# docker.io/mylonasc/magarathea:alt-default-ops-console-0.1.9
DOCKER_REGISTRY="${DOCKER_REGISTRY:-docker.io}"
DOCKERHUB_NAMESPACE="${DOCKERHUB_NAMESPACE:-mylonasc}"
IMAGE_REPO="${IMAGE_REPO:-magarathea}"
TAG="${TAG:-0.1.10}"

IMAGE="${DOCKER_REGISTRY}/${DOCKERHUB_NAMESPACE}/${IMAGE_REPO}:alt-default-ops-console-${TAG}"

echo "Building and pushing image:"
echo "  ${IMAGE}"

echo
echo "[1/2] Building ops console image"
docker build -t "${IMAGE}" "${SCRIPT_DIR}/backend"

echo
echo "[2/2] Pushing ops console image"
docker push "${IMAGE}"

echo
echo "Done."
echo "If TAG changed, update image tag in:"
echo "  ${SCRIPT_DIR}/k8s/deployment.yaml"
