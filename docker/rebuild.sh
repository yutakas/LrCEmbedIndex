#!/usr/bin/env bash
#
# Rebuild and deploy the LrCEmbedIndex Docker container from scratch.
#
# Usage:
#   Local:   ./docker/rebuild.sh
#   Remote:  docker context use <remote-context> && ./docker/rebuild.sh
#
# Environment variables:
#   INDEX_FOLDER  Host path for index/metadata storage (default: ./docker/data)
#   PHOTO_FOLDER  Host path for photo folder to patrol (default: ./docker/photos)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> Stopping and removing existing container..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" down --remove-orphans 2>/dev/null || true

echo "==> Removing old image..."
docker rmi lrcembedindex 2>/dev/null || true
# Also remove the compose-built image (named after the directory)
docker rmi docker-lrcembedindex 2>/dev/null || true

echo "==> Building fresh image..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" build --no-cache

echo "==> Starting container..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d

echo "==> Done. Container status:"
docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps

echo ""
echo "Server is running at http://$(hostname):8600"
echo "Settings UI:  http://$(hostname):8600/settings-ui"
echo ""
echo "Set the Index Folder to /data in the Settings UI."
echo "This maps to \${INDEX_FOLDER:-./docker/data} on the host."
