package proxy

import (
	"testing"
)

func TestInjectToolsIntoMessages_MissingUserMessageMetric(t *testing.T) {
	contextLossMetricsMu.Lock()
	contextLossMetrics = make(map[string]int)
	contextLossMetricsMu.Unlock()

	messages := []ChatMessage{
		{Role: "user", Content: "Here is the result of the tool run:\n{}"},
		{Role: "tool", Content: "tool results..."},
	}

	largeTools := []Tool{
		{Type: "function", Function: ToolFunction{Name: "t1"}},
		{Type: "function", Function: ToolFunction{Name: "t2"}},
		{Type: "function", Function: ToolFunction{Name: "t3"}},
		{Type: "function", Function: ToolFunction{Name: "t4"}},
		{Type: "function", Function: ToolFunction{Name: "t5"}},
		{Type: "function", Function: ToolFunction{Name: "t6"}},
	}

	injectToolsIntoMessages(messages, largeTools, "claude-3-5-sonnet-20241022", nil)

	contextLossMetricsMu.Lock()
	count := contextLossMetrics["missing_user_message_in_fallback"]
	contextLossMetricsMu.Unlock()

	if count != 1 {
		t.Errorf("expected missing_user_message_in_fallback metric to be 1, got %d", count)
	}
}
