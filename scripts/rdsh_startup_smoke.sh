#!/bin/bash
set -e

cleanup() {
    if [ -n "$SERVER_PID" ]; then
        kill -9 $SERVER_PID 2>/dev/null || true
        wait $SERVER_PID 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "Building..."
go build -ldflags="-s -w" -o notion-manager ./cmd/notion-manager
echo "Starting server..."
./notion-manager > server.log 2>&1 &
SERVER_PID=$!

echo "Waiting for server to start..."
for i in {1..10}; do
    if curl -s http://localhost:8081/health >/dev/null; then
        break
    fi
    sleep 1
done

echo "Checking health endpoint..."
curl -s -f http://localhost:8081/health >/dev/null || { echo "Health failed"; false; }

echo "Checking ready endpoint..."
READY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/ready)
if [ "$READY_STATUS" != "503" ] && [ "$READY_STATUS" != "200" ]; then
    echo "Ready endpoint returned unexpected status: $READY_STATUS"
    false
fi

echo "Checking dashboard..."
curl -s -f http://localhost:8081/dashboard/ >/dev/null || { echo "Dashboard failed"; false; }

echo "Checking models API authentication..."
MODELS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/v1/models)
if [ "$MODELS_STATUS" != "401" ]; then
    echo "Models API should require authentication but returned $MODELS_STATUS"
    false
fi

cat << JSON > /tmp/local-live-smoke-summary.json
{
    "commit_sha": "$(git rev-parse HEAD)",
    "status": "success",
    "endpoints": {
        "health": "ok",
        "ready": "$READY_STATUS",
        "dashboard": "ok",
        "api_unauth": "$MODELS_STATUS"
    }
}
JSON

echo "Smoke test passed!"
