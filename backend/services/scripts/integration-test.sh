#!/usr/bin/env bash
# Run the Go integration tests against throwaway infrastructure.
#
# The integration-tagged tests (internal/email, internal/chat) need a real
# Redis: they exercise the Redis Stream consumer-group / PEL / XAUTOCLAIM
# paths and the pub/sub -> WebSocket fan-out, none of which can be faked
# without testing the fake instead of the code.
#
# This script starts a disposable Redis on a non-default port (6399, so it
# cannot collide with a dev redis on 6379 or the compose mapping on 6380),
# runs the tests, and removes the container on exit — including on failure or
# Ctrl-C, so a failed run never leaves a container behind.
#
# Usage:
#   ./scripts/integration-test.sh                 # all integration tests
#   ./scripts/integration-test.sh ./internal/chat # one package
#
# Without this script:  REDIS_TEST_URL=... go test -tags integration ./...
# The tests SKIP (loudly) when REDIS_TEST_URL is unset, so a plain
# `go test -tags integration ./...` never silently reports success.
set -euo pipefail

CONTAINER="shiptrip-it-redis"
PORT="${IT_REDIS_PORT:-6399}"
REDIS_IMAGE="${IT_REDIS_IMAGE:-redis:7-alpine}"
TARGET="${*:-./...}"

cd "$(dirname "$0")/.."

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

cleanup # clear any container left by a previously killed run

echo "==> starting throwaway redis ($REDIS_IMAGE) on :$PORT"
docker run -d --name "$CONTAINER" -p "$PORT:6379" "$REDIS_IMAGE" >/dev/null

# Wait for readiness rather than sleeping a fixed amount: on a cold image pull
# the container can take a while, and a fixed sleep would either flake or waste
# time on every run.
echo -n "==> waiting for redis"
for _ in $(seq 1 50); do
  if docker exec "$CONTAINER" redis-cli PING 2>/dev/null | grep -q PONG; then
    echo " — ready"
    break
  fi
  echo -n "."
  sleep 0.2
done
if ! docker exec "$CONTAINER" redis-cli PING 2>/dev/null | grep -q PONG; then
  echo
  echo "redis did not become ready; aborting" >&2
  exit 1
fi

echo "==> go test -tags integration -race $TARGET"
REDIS_TEST_URL="redis://localhost:$PORT/0" \
  go test -tags integration -race -count=1 "$TARGET"
