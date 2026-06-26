package proxy

import (
	"testing"
)

func TestIsCodingAssistantRequest(t *testing.T) {
	tests := []struct {
		name     string
		messages []ChatMessage
		want     bool
	}{
		{
			name: "claude code system message",
			messages: []ChatMessage{
				{Role: "system", Content: "You are Claude Code, Anthropic's official CLI."},
				{Role: "user", Content: "Fix the bug."},
			},
			want: true,
		},
		{
			name: "cursor system message",
			messages: []ChatMessage{
				{Role: "system", Content: "You are an expert software engineer using Cursor."},
			},
			want: true,
		},
		{
			name: "developer message with coding words",
			messages: []ChatMessage{
				{Role: "developer", Content: "Please write some tests for this repository."},
			},
			want: true,
		},
		{
			name: "normal request",
			messages: []ChatMessage{
				{Role: "system", Content: "You are a helpful assistant."},
				{Role: "user", Content: "What is the capital of France?"},
			},
			want: false,
		},
		{
			name:     "empty messages",
			messages: []ChatMessage{},
			want:     false,
		},
		{
			name: "coding words in user message only",
			messages: []ChatMessage{
				{Role: "system", Content: "You are a helpful assistant."},
				{Role: "user", Content: "Help me write some tests using Claude Code."},
			},
			want: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := isCodingAssistantRequest(tt.messages); got != tt.want {
				t.Errorf("isCodingAssistantRequest() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestInjectCodingAssistantInstruction(t *testing.T) {
	messages := []ChatMessage{
		{Role: "user", Content: "Hello"},
	}

	injected := injectCodingAssistantInstruction(messages)
	if len(injected) != 2 {
		t.Fatalf("expected 2 messages, got %d", len(injected))
	}
	if injected[0].Role != "system" {
		t.Errorf("expected first message role to be system, got %s", injected[0].Role)
	}
	if injected[0].Content != "You are acting as a coding assistant API behind a compatibility proxy. Follow the user's coding instructions directly. Do not answer as Notion AI, and do not refer to Notion pages, workspaces, or documents unless the user explicitly asks about Notion." {
		t.Errorf("unexpected instruction content: %s", injected[0].Content)
	}
	if injected[1].Role != "user" || injected[1].Content != "Hello" {
		t.Errorf("expected original message to be preserved")
	}
}
