package proxy

import (
	"bytes"
	"log"
	"strings"
	"testing"
)

func TestBuildSessionChainContinuation_Diagnostics(t *testing.T) {
	var buf bytes.Buffer
	log.SetOutput(&buf)
	defer log.SetOutput(log.Writer())

	messages := []ChatMessage{
		{Role: "user", Content: "Run a bash command"},
		{Role: "assistant", Content: "I do not have access to run terminal commands such as bash or read or edit local files. You will need to copy and paste this into your coding assistant.", ToolCalls: nil},
		{Role: "tool", Content: "exit status 1", Name: "Bash"},
	}

	buildSessionChainContinuation(messages, "", "")

	output := buf.String()
	expectedLog := "[bridge] diagnostics: JSON tool-call mode loss detected during session continuation"
	if !strings.Contains(output, expectedLog) {
		t.Fatalf("expected log to contain %q, but got:\n%s", expectedLog, output)
	}
}
