package proxy

import (
	"strings"
	"testing"
)

func TestParseToolCalls_DoneExtraction(t *testing.T) {
	tests := []struct {
		name    string
		content string
		wantRes string
	}{
		{
			name:    "clean __done__",
			content: `{"name": "__done__", "arguments": {"result": "I have created the files."}}`,
			wantRes: "I have created the files.",
		},
		{
			name:    "trailing whitespace",
			content: `{"name": "__done__", "arguments": {"result": "I have created the files."}}   `,
			wantRes: "I have created the files.",
		},
		{
			name:    "unusual newlines",
			content: "{\n  \"name\": \"__done__\",\n  \"arguments\": {\n    \"result\": \"I have created the files.\"\n  }\n}\n\n",
			wantRes: "I have created the files.",
		},
		{
			name:    "preamble with newlines and trailing spaces",
			content: "Here is the final result:\n\n\r\n{\"name\": \"__done__\", \"arguments\": {\"result\": \"I have created the files.\"}} \n \r",
			wantRes: "I have created the files.",
		},
		{
			name:    "pretty printed with wrapper format",
			content: "```json\n{\n  \"tool_call\": {\n    \"name\": \"__done__\",\n    \"arguments\": {\n      \"result\": \"I have created the files.\"\n    }\n  }\n}\n```",
			wantRes: "I have created the files.",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tc, _, ok := parseToolCalls(tt.content)

			if !ok || len(tc) == 0 {
				t.Fatalf("expected __done__ to be parsed for %s", tt.name)
			}
			if tc[0].Function.Name != "__done__" {
				t.Fatalf("expected __done__ tool call, got %s", tc[0].Function.Name)
			}
			if !strings.Contains(tc[0].Function.Arguments, tt.wantRes) {
				t.Fatalf("expected result argument to match in %s", tt.name)
			}
		})
	}
}

func TestRefusalTextRejection_InFinalAnswer(t *testing.T) {
	// Refusal text should not be parsed as __done__ or valid json tool
	content := `I am Notion AI and I cannot run the bash commands needed to finish this coding task.`
	tc, _, ok := parseToolCalls(content)
	if ok || len(tc) > 0 {
		t.Fatalf("expected refusal prose to not be parsed as a tool call")
	}

	isNoTool, reason := detectToolBridgeNoToolResponse(content)
	if !isNoTool {
		t.Fatalf("expected refusal prose to be detected as workspace reframing/refusal")
	}
	if reason != "Notion persona leakage" {
		t.Fatalf("expected reason 'Notion persona leakage', got %q", reason)
	}
}
