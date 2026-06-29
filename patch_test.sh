echo "// Dummy comment to trigger true diff" >> internal/proxy/anthropic_observability_test.go
git add internal/proxy/anthropic_observability_test.go
git commit -m "chore: dummy comment to force pr update"
