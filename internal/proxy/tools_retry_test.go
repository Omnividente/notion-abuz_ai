package proxy

import (
	"testing"
)

func TestBuildSessionChainContinuationRetryLoop(t *testing.T) {
	// Reset metrics before test
	contextLossMetricsMu.Lock()
	contextLossMetrics = make(map[string]int)
	contextLossMetricsMu.Unlock()

	messages := []ChatMessage{
		{Role: "user", Content: "do something"},
		{Role: "assistant", Content: "working", ToolCalls: []ToolCall{{ID: "call_1", Function: ToolCallFunction{Name: "Bash"}}}},
		{Role: "tool", ToolCallID: "call_1", Content: "exit status 1", Name: "Bash"},
		{Role: "assistant", Content: "working again", ToolCalls: []ToolCall{{ID: "call_2", Function: ToolCallFunction{Name: "Bash"}}}},
		{Role: "tool", ToolCallID: "call_2", Content: "exit status 1", Name: "Bash"},
	}

	buildSessionChainContinuation(messages, "[]", "/tmp")

	metrics := GetContextLossMetrics()
	if metrics["retry_loop_detected"] != 1 {
		t.Errorf("expected retry_loop_detected to be 1, got %d", metrics["retry_loop_detected"])
	}
}
