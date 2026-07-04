package proxy

import (
	"testing"
)

func TestSanitizeForBridge_DroppedSystemMessageMetric(t *testing.T) {
	// Reset metrics before test
	contextLossMetricsMu.Lock()
	contextLossMetrics = make(map[string]int)
	contextLossMetricsMu.Unlock()

	messages := []ChatMessage{
		{Role: "system", Content: "This is a dummy system prompt."},
		{Role: "system", Content: "This system message should be explicitly dropped."},
		{Role: "user", Content: "Hello world"},
	}

	_ = sanitizeForBridge(messages)

	contextLossMetricsMu.Lock()
	count := contextLossMetrics["system_message_dropped"]
	contextLossMetricsMu.Unlock()

	if count != 1 {
		t.Errorf("expected 1 system_message_dropped metric, got %d", count)
	}
}

func TestInjectToolsIntoMessages_DroppedSystemMessageMetric(t *testing.T) {
	// Reset metrics before test
	contextLossMetricsMu.Lock()
	contextLossMetrics = make(map[string]int)
	contextLossMetricsMu.Unlock()

	messages := []ChatMessage{
		{Role: "system", Content: "Another system prompt that gets dropped in fallback."},
		{Role: "user", Content: "Hello world"},
	}

	// Create a tool to trigger the large tool set logic
	tools := make([]Tool, 20)
	for i := 0; i < 20; i++ {
		tools[i] = Tool{
			Type: "function",
			Function: ToolFunction{
				Name: "test_tool",
			},
		}
	}

	_ = injectToolsIntoMessages(messages, tools, "claude-3-5-sonnet-20241022", nil)

	contextLossMetricsMu.Lock()
	count := contextLossMetrics["system_message_dropped"]
	contextLossMetricsMu.Unlock()

	if count != 1 {
		t.Errorf("expected 1 system_message_dropped metric from fallback transcript builder, got %d", count)
	}
}
