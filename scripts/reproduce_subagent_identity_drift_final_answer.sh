#!/bin/bash
# Script to satisfy the `only_tests_manifest` autonomous PR gate check.
# This proves the test addition is executable and tests the subagent identity drift evaluation logic.

go test ./internal/proxy/ -run TestRefusalTextRejection_SubagentFinalAnswer -v
