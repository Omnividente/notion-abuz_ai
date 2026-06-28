package proxy

import (
	"bytes"
	"net/http/httptest"
	"strings"
	"testing"
)

// mockFlusher wraps httptest.ResponseRecorder to implement http.Flusher
type mockFlusher struct {
	*httptest.ResponseRecorder
}

func (m *mockFlusher) Flush() {}

func TestAnthropicStreaming_ToolCallChunks(t *testing.T) {
	rr := httptest.NewRecorder()
	mf := &mockFlusher{rr}

	sendAnthropicSSE(mf, mf, "content_block_delta", map[string]interface{}{
		"type":  "content_block_delta",
		"index": 0,
		"delta": map[string]interface{}{
			"type":         "input_json_delta",
			"partial_json": "{\"f",
		},
	})

	sendAnthropicSSE(mf, mf, "content_block_delta", map[string]interface{}{
		"type":  "content_block_delta",
		"index": 0,
		"delta": map[string]interface{}{
			"type":         "input_json_delta",
			"partial_json": "ile\":\"test.go\"}",
		},
	})

	body := mf.Body.String()
	if !strings.Contains(body, `{"delta":{"partial_json":"{\"f","type":"input_json_delta"}`) || !strings.Contains(body, `{"delta":{"partial_json":"ile\":\"test.go\"}","type":"input_json_delta"}`) {
		t.Fatalf("body missing split JSON chunks: %s", body)
	}
}

func TestAnthropicHandleFrameRobustness(t *testing.T) {
	// Test that parseNDJSONStream handles malformed/unknown NDJSON events gracefully without panicking

	defer func() {
		if r := recover(); r != nil {
			t.Errorf("parseNDJSONStream panicked on unknown event type: %v", r)
		}
	}()

	malformedStream := bytes.NewBufferString(`{"type": "some_random_unsupported_type", "data": "garbage"}
{"type": "agent-inference", "data": {"unexpected": []}}
{"completely_invalid_json"
`)

	var cb StreamCallback = func(delta string, done bool, usage *UsageInfo) {}

	err := parseNDJSONStream(malformedStream, "test-req", cb, nil, nil, nil, nil, nil, nil)
	if err != nil {
		// an error is fine, as long as it doesn't panic and handles it gracefully
		t.Logf("Returned error as expected or handled gracefully: %v", err)
	}
}

func TestAnthropicHandleFrameRobustness_UnexpectedTypes(t *testing.T) {
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("parseNDJSONStream panicked on unexpected JSON types: %v", r)
		}
	}()

	unexpectedStream := bytes.NewBufferString(`123
"string payload"
null
[]
[1, 2, 3]
{"type": "agent-inference", "value": "not_an_array"}
{"type": "agent-tool-result", "toolCallId": 12345}
{"type": "error", "message": {"nested": "object_instead_of_string"}}
`)

	var cb StreamCallback = func(delta string, done bool, usage *UsageInfo) {}

	err := parseNDJSONStream(unexpectedStream, "test-req", cb, nil, nil, nil, nil, nil, nil)
	if err != nil {
		t.Logf("Returned error as expected or handled gracefully: %v", err)
	}
}

func TestAnthropicHandleFrameRobustness_MissingFields(t *testing.T) {
	defer func() {
		if r := recover(); r != nil {
			t.Errorf("parseNDJSONStream panicked on valid JSON missing fields: %v", r)
		}
	}()

	missingFieldsStream := bytes.NewBufferString(`{"type": "agent-inference"}
{"type": "agent-inference", "value": []}
{"type": "patch"}
{"type": "patch", "v": []}
{"type": "patch", "v": [{"o": "a"}]}
{"type": "patch", "v": [{"o": "a", "p": "/value/-"}]}
{"type": "search-status"}
{"type": "error"}
{"type": "agent-tool-result"}
{"type": "call-function"}
`)

	var cb StreamCallback = func(delta string, done bool, usage *UsageInfo) {}

	err := parseNDJSONStream(missingFieldsStream, "test-req", cb, nil, nil, nil, nil, nil, nil)
	if err != nil {
		// an error is fine, as long as it doesn't panic and handles it gracefully
		t.Logf("Returned error as expected or handled gracefully: %v", err)
	}
}
