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
