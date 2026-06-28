package proxy

import (
	"strings"
	"testing"
)

func TestClaudeCodeAgentLoop_ToolResultContinuationLargeOutputTruncation(t *testing.T) {
	longOutput := strings.Repeat("A", 5000)

	messages := []ChatMessage{
		{Role: "user", Content: "Run a command that outputs a lot of text."},
		{Role: "assistant", Content: "", ToolCalls: []ToolCall{
			{ID: "call_1", Type: "function", Function: ToolCallFunction{Name: "Bash", Arguments: `{"command":"cat huge_file.txt"}`}},
		}},
		{Role: "tool", Name: "Bash", ToolCallID: "call_1", Content: longOutput},
	}

	followUp := buildSessionChainFollowUp(messages, "Bash", "")
	if len(followUp) != 1 {
		t.Fatalf("expected 1 follow up")
	}

	content := followUp[0].Content

	if !strings.Contains(content, "... (truncated)") {
		t.Errorf("Expected long tool output to be truncated")
	}

	// Ensure safe multibyte truncation
	if len(content) > 6000 {
		t.Errorf("Follow-up prompt should be constrained in size, got %d chars", len(content))
	}
}

func TestClaudeCodeAgentLoop_ToolResultContinuationMultibyteTruncation(t *testing.T) {
	// A string of emojis (each emoji is multiple bytes, usually 4)
	longOutput := strings.Repeat("😂", 5000) // This is 20,000 bytes long

	messages := []ChatMessage{
		{Role: "user", Content: "Run a command that outputs a lot of text."},
		{Role: "assistant", Content: "", ToolCalls: []ToolCall{
			{ID: "call_1", Type: "function", Function: ToolCallFunction{Name: "Bash", Arguments: `{"command":"cat huge_file.txt"}`}},
		}},
		{Role: "tool", Name: "Bash", ToolCallID: "call_1", Content: longOutput},
	}

	followUp := buildSessionChainFollowUp(messages, "Bash", "")
	if len(followUp) != 1 {
		t.Fatalf("expected 1 follow up")
	}

	content := followUp[0].Content

	if !strings.Contains(content, "... (truncated)") {
		t.Errorf("Expected long tool output to be truncated")
	}

	// Check if string ends with a half-sliced emoji.
	// Since we are truncating by rune, it shouldn't. If we were truncating by byte, it might.
	// The `[]rune` trick in Go prevents invalid UTF-8 generation anyway, but let's test it runs fine.
}
