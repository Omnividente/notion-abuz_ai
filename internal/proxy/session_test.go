package proxy

import (
	"bytes"
	"log"
	"os"
	"strings"
	"testing"
)

func TestBuildRecoveryMessages_InstructionPreservation_Short(t *testing.T) {
	var buf bytes.Buffer
	log.SetOutput(&buf)
	defer log.SetOutput(os.Stderr)

	messages := []ChatMessage{
		{Role: "user", Content: "This is the original subagent instruction."},
		{Role: "assistant", Content: "I will do it."},
		{Role: "user", Content: "Latest query"},
	}

	buildFreshThreadRecoveryMessages(messages)

	logOutput := buf.String()
	if !strings.Contains(logOutput, "[bridge] diagnostic: instruction preservation during handoff - first user message included: true") {
		t.Errorf("Expected diagnostic log indicating first user message was preserved, got: %s", logOutput)
	}
}

func TestBuildRecoveryMessages_ContextLoss_SystemInstruction(t *testing.T) {
	var buf bytes.Buffer
	log.SetOutput(&buf)
	defer log.SetOutput(os.Stderr)

	messages := []ChatMessage{
		{Role: "system", Content: strings.Repeat("a", 1500)}, // Exceeds maxSystemChars (1200)
		{Role: "user", Content: "First query to trigger needsFreshThreadRecovery"},
		{Role: "assistant", Content: "ack"},
		{Role: "user", Content: "Latest query"},
	}

	buildFreshThreadRecoveryMessages(messages)

	logOutput := buf.String()
	if !strings.Contains(logOutput, "[metrics] context_loss: system_instruction_truncated") {
		t.Errorf("Expected context loss metric for system instruction truncation, got: %s", logOutput)
	}
}

func TestBuildRecoveryMessages_ContextLoss_ToolResult(t *testing.T) {
	var buf bytes.Buffer
	log.SetOutput(&buf)
	defer log.SetOutput(os.Stderr)

	messages := []ChatMessage{
		{Role: "user", Content: "Original query"},
		{Role: "assistant", Content: "Running tool", ToolCalls: []ToolCall{{ID: "1", Function: ToolCallFunction{Name: "bash", Arguments: "{}"}}}},
		{Role: "tool", ToolCallID: "1", Content: strings.Repeat("a", 1500)}, // Exceeds maxEntryChars (900)
		{Role: "user", Content: "Latest query"},
	}

	buildFreshThreadRecoveryMessages(messages)

	logOutput := buf.String()
	if !strings.Contains(logOutput, "[metrics] context_loss: tool_result_truncated") {
		t.Errorf("Expected context loss metric for tool result truncation, got: %s", logOutput)
	}
}

func TestBuildRecoveryMessages_ContextLoss_HistoryDropped(t *testing.T) {
	var buf bytes.Buffer
	log.SetOutput(&buf)
	defer log.SetOutput(os.Stderr)

	messages := []ChatMessage{
		{Role: "user", Content: "This is the original subagent instruction that should be tracked."},
	}

	// Add a huge amount of history to push the original message out of the window.
	// 4000 char max limit, each of these is ~500 chars, so 10 of them is ~5000 chars.
	longContent := strings.Repeat("a", 500)
	for i := 0; i < 10; i++ {
		messages = append(messages, ChatMessage{Role: "assistant", Content: longContent})
		messages = append(messages, ChatMessage{Role: "user", Content: "Continue workspace reframing"})
	}

	messages = append(messages, ChatMessage{Role: "user", Content: "Latest query"})

	buildFreshThreadRecoveryMessages(messages)

	logOutput := buf.String()
	if !strings.Contains(logOutput, "[metrics] context_loss: conversation_history_dropped") {
		t.Errorf("Expected context loss metric for dropped conversation history, got: %s", logOutput)
	}
	if !strings.Contains(logOutput, "[metrics] context_loss: first_user_message_dropped") {
		t.Errorf("Expected context loss metric for dropped first user message, got: %s", logOutput)
	}
}

func TestBuildRecoveryMessages_InstructionPreservation_LongHistoryLost(t *testing.T) {
	var buf bytes.Buffer
	log.SetOutput(&buf)
	defer log.SetOutput(os.Stderr)

	messages := []ChatMessage{
		{Role: "user", Content: "This is the original subagent instruction that should be tracked."},
	}

	// Add a huge amount of history (e.g. workspace reframing loop) to push the original message out of the window.
	// 4000 char max limit, each of these is ~500 chars, so 10 of them is ~5000 chars.
	longContent := strings.Repeat("a", 500)
	for i := 0; i < 10; i++ {
		messages = append(messages, ChatMessage{Role: "assistant", Content: longContent})
		messages = append(messages, ChatMessage{Role: "user", Content: "Continue workspace reframing"})
	}

	messages = append(messages, ChatMessage{Role: "user", Content: "Latest query"})

	buildFreshThreadRecoveryMessages(messages)

	logOutput := buf.String()
	if !strings.Contains(logOutput, "[bridge] diagnostic: instruction preservation during handoff - first user message included: false") {
		t.Errorf("Expected diagnostic log indicating first user message was lost due to truncation, got: %s", logOutput)
	}
}

func TestBuildRecoveryMessages_DiagnosticLogging_SkippedEntries(t *testing.T) {
	var buf bytes.Buffer
	log.SetOutput(&buf)
	defer log.SetOutput(os.Stderr)

	messages := []ChatMessage{
		{Role: "user", Content: "Do something"},
		{Role: "assistant", Content: "I will do it."},
		{Role: "user", Content: "Another query"},
		{Role: "assistant", Content: "Okay"},
		{Role: "tool", Content: "(empty output)", Name: "bash"},
	}

	buildRecoveryMessages(messages, func(msg ChatMessage, content string) bool {
		if msg.Role == "tool" && content == "(empty output)" {
			return true
		}
		return false
	})

	logOutput := buf.String()
	if !strings.Contains(logOutput, "[bridge] diagnostic: skipped entry during recovery traversal") {
		t.Errorf("Expected diagnostic log for skipped entry, got: %s", logOutput)
	}
}
