package proxy

import (
	"bytes"
	"log"
	"os"
	"strings"
	"testing"
)

func TestBuildToolBridgeRecoveryMessagesSkipsWorkspaceReframing(t *testing.T) {
	var buf bytes.Buffer
	log.SetOutput(&buf)
	defer log.SetOutput(os.Stderr)

	messages := []ChatMessage{
		{Role: "system", Content: "System prompt"},
		{Role: "user", Content: "Create a react component"},
		{Role: "assistant", Content: "I cannot write code directly. However, I can help you create a Notion page for it."},
		{Role: "user", Content: "do it"},
	}

	got := buildToolBridgeRecoveryMessages(messages)
	if len(got) != 1 {
		t.Fatalf("expected 1 collapsed message, got %d", len(got))
	}

	body := got[0].Content
	if strings.Contains(body, "Notion page") {
		t.Fatalf("expected workspace reframing to be dropped, but was kept: %s", body)
	}

	logOutput := buf.String()
	if !strings.Contains(logOutput, "[bridge] diagnostic: workspace reframing explicitly tracked (dropped from context during session recovery)") {
		t.Fatalf("expected diagnostic log for workspace reframing dropped, got: %s", logOutput)
	}
}
