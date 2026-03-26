#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Keep defaults aligned with current Kubernetes manifest image names:
# docker.io/mylonasc/magarathea:sandboxed-react-agent-backend-0.1.0
# docker.io/mylonasc/magarathea:sandboxed-react-agent-frontend-0.1.0
DOCKER_REGISTRY="${DOCKER_REGISTRY:-docker.io}"
DOCKERHUB_NAMESPACE="${DOCKERHUB_NAMESPACE:-mylonasc}"
IMAGE_REPO="${IMAGE_REPO:-magarathea}"
TAG="${TAG:-0.4.9}"

BACKEND_IMAGE="${DOCKER_REGISTRY}/${DOCKERHUB_NAMESPACE}/${IMAGE_REPO}:sandboxed-react-agent-backend-${TAG}"
FRONTEND_IMAGE="${DOCKER_REGISTRY}/${DOCKERHUB_NAMESPACE}/${IMAGE_REPO}:sandboxed-react-agent-frontend-${TAG}"

echo "Building and pushing images:"
echo "  ${BACKEND_IMAGE}"
echo "  ${FRONTEND_IMAGE}"

echo
echo "[1/4] Building backend image"
docker build -t "${BACKEND_IMAGE}" "${SCRIPT_DIR}/backend"

echo
echo "[2/4] Pushing backend image"
docker push "${BACKEND_IMAGE}"

echo
echo "[3/4] Building frontend image"
docker build -t "${FRONTEND_IMAGE}" "${SCRIPT_DIR}/frontend"

echo
echo "[4/4] Pushing frontend image"
docker push "${FRONTEND_IMAGE}"

echo
echo "Done."
echo "If TAG changed, update image tags in:"
echo "  ${SCRIPT_DIR}/k8s/backend-deployment.yaml"
echo "  ${SCRIPT_DIR}/k8s/frontend-deployment.yaml"
