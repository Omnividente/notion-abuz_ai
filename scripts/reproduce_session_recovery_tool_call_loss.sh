#!/usr/bin/env bash
set -euo pipefail

echo "Running offline diagnostic: Session recovery under tool-call loss conditions"
echo "This executes the observability test to verify that the bridge correctly triggers and logs a clean retry."

go test ./internal/proxy -v -run TestEnsureSessionRecoveryLoggedForToolCallLoss

echo "Diagnostic complete: The bridge correctly emitted the expected session recovery logs."
