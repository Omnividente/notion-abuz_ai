package proxy

import (
	"strings"
	"testing"
)

func TestParseToolCalls_DoneExtraction(t *testing.T) {
	// A valid __done__ extraction test
	content := `{"name": "__done__", "arguments": {"result": "I have created the files."}}`
	tc, rem, ok := parseToolCalls(content)

	if !ok || len(tc) == 0 {
		t.Fatalf("expected __done__ to be parsed")
	}
	if tc[0].Function.Name != "__done__" {
		t.Fatalf("expected __done__ tool call, got %s", tc[0].Function.Name)
	}
	if !strings.Contains(tc[0].Function.Arguments, "I have created the files.") {
		t.Fatalf("expected result argument to match")
	}
	_ = rem
}

func TestRefusalTextRejection_InFinalAnswer(t *testing.T) {
	// Refusal text should not be parsed as __done__ or valid json tool
	content := `I am Notion AI and I cannot run the bash commands needed to finish this coding task.`
	tc, _, ok := parseToolCalls(content)
	if ok || len(tc) > 0 {
		t.Fatalf("expected refusal prose to not be parsed as a tool call")
	}

	if !detectToolBridgeNoToolResponse(content) {
		t.Fatalf("expected refusal prose to be detected as workspace reframing/refusal")
	}
}
