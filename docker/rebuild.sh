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

# Load environment variables from .env if present
ENV_FILE=""
if [ -f "$PROJECT_DIR/.env" ]; then
  ENV_FILE="$PROJECT_DIR/.env"
  echo "==> Loading environment from $ENV_FILE"
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
fi

# Auto-detect host timezone so patrol time windows use local time
if [ -z "${TZ:-}" ]; then
  if [ -L /etc/localtime ]; then
    TZ=$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')
  elif command -v timedatectl >/dev/null 2>&1; then
    TZ=$(timedatectl show -p Timezone --value 2>/dev/null || true)
  fi
  if [ -n "${TZ:-}" ]; then
    export TZ
    echo "==> Detected host timezone: $TZ"
  fi
fi

echo "==> Stopping and removing existing container..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" ${ENV_FILE:+--env-file "$ENV_FILE"} down 2>/dev/null || true

echo "==> Removing old image..."
docker rmi lrcembedindex 2>/dev/null || true
# Also remove the compose-built image (named after the directory)
docker rmi docker-lrcembedindex 2>/dev/null || true

echo "==> Building fresh image..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" ${ENV_FILE:+--env-file "$ENV_FILE"} build --no-cache

echo "==> Starting container..."
docker compose -f "$SCRIPT_DIR/docker-compose.yml" ${ENV_FILE:+--env-file "$ENV_FILE"} up -d

echo "==> Done. Container status:"
docker compose -f "$SCRIPT_DIR/docker-compose.yml" ${ENV_FILE:+--env-file "$ENV_FILE"} ps

echo ""
echo "Server is running at http://$(hostname):8600"
echo "Settings UI:  http://$(hostname):8600/settings-ui"
echo ""
echo "Set the Index Folder to /data in the Settings UI."
echo "This maps to \${INDEX_FOLDER:-./docker/data} on the host."
