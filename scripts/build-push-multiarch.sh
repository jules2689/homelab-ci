#!/usr/bin/env bash
# Build and push multi-platform (amd64 + arm64) CI-Lite images.
# Usage: ./scripts/build-push-multiarch.sh [VERSION]
# Example: ./scripts/build-push-multiarch.sh 0.2.0

set -e

VERSION="${VERSION:-0.2.1}"
REGISTRY="${CI_LITE_REGISTRY:-git.hl.jnadeau.ca}"
IMAGE_OWNER="${CI_LITE_IMAGE_OWNER:-homelab}"
PLATFORMS="linux/amd64,linux/arm64"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILDER="${CI_LITE_BUILDX_BUILDER:-ci-lite-multiarch-host}"

# Use host networking so BuildKit can reach registries on private/Tailscale routes.
if ! docker buildx inspect "$BUILDER" &>/dev/null; then
  echo "Creating buildx builder ${BUILDER}..."
  docker buildx create --name "$BUILDER" --use --driver docker-container --driver-opt network=host
fi
docker buildx use "$BUILDER"

echo "Building and pushing homelab-ci:${VERSION} for ${PLATFORMS}..."
docker buildx build \
  --platform "$PLATFORMS" \
  -t "${REGISTRY}/${IMAGE_OWNER}/homelab-ci:${VERSION}" \
  --push \
  -f "${ROOT}/orchestrator/Dockerfile" \
  "${ROOT}/orchestrator"

echo "Building and pushing homelab-ci-web:${VERSION} for ${PLATFORMS}..."
docker buildx build \
  --platform "$PLATFORMS" \
  -t "${REGISTRY}/${IMAGE_OWNER}/homelab-ci-web:${VERSION}" \
  --push \
  -f "${ROOT}/web/Dockerfile" \
  "${ROOT}/web"

echo "Building and pushing homelab-ci-mcp:${VERSION} for ${PLATFORMS}..."
docker buildx build \
  --platform "$PLATFORMS" \
  -t "${REGISTRY}/${IMAGE_OWNER}/homelab-ci-mcp:${VERSION}" \
  --push \
  -f "${ROOT}/mcp_server/Dockerfile" \
  "${ROOT}"

echo "Done. Images pushed:"
echo "  ${REGISTRY}/${IMAGE_OWNER}/homelab-ci:${VERSION}"
echo "  ${REGISTRY}/${IMAGE_OWNER}/homelab-ci-web:${VERSION}"
echo "  ${REGISTRY}/${IMAGE_OWNER}/homelab-ci-mcp:${VERSION}"
