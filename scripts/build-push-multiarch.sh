#!/usr/bin/env bash
# Build and push multi-platform (amd64 + arm64) images for homelab-ci and homelab-ci-web.
# Usage: ./scripts/build-push-multiarch.sh [VERSION]
# Example: ./scripts/build-push-multiarch.sh 0.1.15

set -e

VERSION="${1:-0.1.15}"
REGISTRY="${CI_LITE_REGISTRY:-registry.hl.jnadeau.ca}"
PLATFORMS="linux/amd64,linux/arm64"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Ensure buildx builder exists and supports multi-platform
if ! docker buildx inspect ci-lite-multiarch &>/dev/null; then
  echo "Creating buildx builder ci-lite-multiarch..."
  docker buildx create --name ci-lite-multiarch --use --driver docker-container
fi
docker buildx use ci-lite-multiarch

echo "Building and pushing homelab-ci:${VERSION} for ${PLATFORMS}..."
docker buildx build \
  --platform "$PLATFORMS" \
  -t "${REGISTRY}/homelab-ci:${VERSION}" \
  --push \
  -f "${ROOT}/orchestrator/Dockerfile" \
  "${ROOT}/orchestrator"

echo "Building and pushing homelab-ci-web:${VERSION} for ${PLATFORMS}..."
docker buildx build \
  --platform "$PLATFORMS" \
  -t "${REGISTRY}/homelab-ci-web:${VERSION}" \
  --push \
  -f "${ROOT}/web/Dockerfile" \
  "${ROOT}/web"

echo "Done. Images pushed:"
echo "  ${REGISTRY}/homelab-ci:${VERSION}"
echo "  ${REGISTRY}/homelab-ci-web:${VERSION}"
