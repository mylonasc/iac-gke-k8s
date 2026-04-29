#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DOCKER_REGISTRY="${DOCKER_REGISTRY:-docker.io}"
DOCKERHUB_NAMESPACE="${DOCKERHUB_NAMESPACE:-mylonasc}"
IMAGE_REPO="${IMAGE_REPO:-magarathea}"
BACKEND_TAG="${TAG:-0.1.8}"
FRONTEND_TAG="${TAG:-0.1.7}"

TARGET="${1:-all}"

BACKEND_IMAGE="${DOCKER_REGISTRY}/${DOCKERHUB_NAMESPACE}/${IMAGE_REPO}:cluster-authz-manager-backend-${BACKEND_TAG}"
FRONTEND_IMAGE="${DOCKER_REGISTRY}/${DOCKERHUB_NAMESPACE}/${IMAGE_REPO}:cluster-authz-manager-frontend-${FRONTEND_TAG}"

usage() {
  cat <<EOF
Usage: $0 [all|backend|frontend]

Build and push cluster-authz-manager images.

Examples:
  $0           # build/push both images
  $0 backend   # build/push backend only
  $0 frontend  # build/push frontend only
  TAG=0.1.8 $0 all
EOF
}

build_push_backend() {
  echo "[backend 1/2] Building backend image"
  docker build -t "${BACKEND_IMAGE}" "${SCRIPT_DIR}/backend"
  echo "[backend 2/2] Pushing backend image"
  docker push "${BACKEND_IMAGE}"
}

build_push_frontend() {
  echo "[frontend 1/2] Building frontend image"
  docker build -t "${FRONTEND_IMAGE}" "${SCRIPT_DIR}/frontend"
  echo "[frontend 2/2] Pushing frontend image"
  docker push "${FRONTEND_IMAGE}"
}

echo "Target: ${TARGET}"
echo "Backend image:  ${BACKEND_IMAGE}"
echo "Frontend image: ${FRONTEND_IMAGE}"

case "${TARGET}" in
  all)
    build_push_backend
    build_push_frontend
    ;;
  backend)
    build_push_backend
    ;;
  frontend)
    build_push_frontend
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown target: ${TARGET}" >&2
    usage
    exit 1
    ;;
esac

echo "Done."
echo "If TAG changed, keep manifests aligned:"
echo "  ${SCRIPT_DIR}/k8s/backend-deployment.yaml"
echo "  ${SCRIPT_DIR}/k8s/frontend-deployment.yaml"
