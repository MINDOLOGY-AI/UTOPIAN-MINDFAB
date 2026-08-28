#!/usr/bin/env bash
# build the dockeruse agent docker image and keep retrying until it succeeds.
# run this in a tmux session and leave it alone.

set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

IMAGE_NAME="fab_sandbox"
BUILD_CONTEXT="$SCRIPT_DIR/docker_build"
LOG_FILE="$BUILD_CONTEXT/build.log"

mkdir -p "$(dirname "$LOG_FILE")"

# tee all output to the log file so you can tail it later
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== starting docker build for $IMAGE_NAME ==="
echo "context: $BUILD_CONTEXT"
echo "log: $LOG_FILE"
echo ""

attempt=0
while true; do
  attempt=$((attempt + 1))
  echo "=== attempt $attempt at $(date -Iseconds) ==="

  if docker build -t "$IMAGE_NAME" "$BUILD_CONTEXT"; then
    cp "$BUILD_CONTEXT/Dockerfile" "$BUILD_CONTEXT/last_build"
    echo "=== build succeeded on attempt $attempt at $(date -Iseconds) ==="
    exit 0
  fi

  echo "=== build failed on attempt $attempt, retrying in 10s... ==="
  echo ""
  sleep 10
done
