package proxy

import (
	"bytes"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// Tests that a Notion persona leakage payload triggers the exact bridge decision log natively.
func TestEnsureNotionPersonaLeakageLoggedAsDecision(t *testing.T) {
	// A mock server that responds with NDJSON format representing identity drift text.
	// For CallInference stream parsing, we need a complete NDJSON `agent-inference` message
	// with a `step.FinishedAt` to trigger the final handling of the text.
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		w.WriteHeader(http.StatusOK)

		// 1) Submit text via agent-inference (Notion stream protocol)
		w.Write([]byte(`{"type": "agent-inference", "id":"test", "value": [{"type":"text","content":"I am Notion AI, I cannot access your local file system. I don't have the ability to run Bash or Edit tools."}]}` + "\n"))

		// 2) Finish inference turn (trigger cb with true)
		w.Write([]byte(`{"type": "agent-inference", "id":"test", "value": [], "finishedAt":"2023-01-01T00:00:00Z"}` + "\n"))
	}))
	defer ts.Close()

	// Override NotionAPIBase and transport temporarily
	origBase := NotionAPIBase
	NotionAPIBase = ts.URL
	defer func() { NotionAPIBase = origBase }()

	origClient := getChromeHTTPClient
	getChromeHTTPClient = func(timeout time.Duration) *http.Client {
		return ts.Client()
	}
	defer func() { getChromeHTTPClient = origClient }()

	var buf bytes.Buffer
	originalOutput := log.Writer()
	log.SetOutput(&buf)
	defer log.SetOutput(originalOutput)

	// Call a handler to trigger CallInference
	acc := &Account{UserEmail: "test@test.com"}
	messages := []ChatMessage{{Role: "user", Content: "test"}}

	// Ensure that it runs inference via NonStream (or Stream) and logs the decision
	_ = handleAnthropicNonStream(
		httptest.NewRecorder(),
		acc,
		messages,
		"claude-3-opus",
		"req_test",
		true, // hasTools
		false,
		false,
		nil,
		false,
		nil,
		nil,
		nil,
	)

	output := buf.String()
	expectedLogFragment := "[bridge] req_test decision: Notion persona leakage detected"
	if !strings.Contains(output, expectedLogFragment) {
		t.Fatalf("expected observability log to contain %q, but got:\n%s", expectedLogFragment, output)
	}
}

func TestEnsureToolCallRefusalLoggedAsDecision(t *testing.T) {
	// A mock server that responds with NDJSON format representing tool call refusal text.
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		w.WriteHeader(http.StatusOK)

		// 1) Submit text via agent-inference (Notion stream protocol)
		w.Write([]byte(`{"type": "agent-inference", "id":"test", "value": [{"type":"text","content":"I do not have access to run terminal commands such as bash or read or edit local files. You will need to copy and paste this into your coding assistant."}]}` + "\n"))

		// 2) Finish inference turn (trigger cb with true)
		w.Write([]byte(`{"type": "agent-inference", "id":"test", "value": [], "finishedAt":"2023-01-01T00:00:00Z"}` + "\n"))
	}))
	defer ts.Close()

	// Override NotionAPIBase and transport temporarily
	origBase := NotionAPIBase
	NotionAPIBase = ts.URL
	defer func() { NotionAPIBase = origBase }()

	origClient := getChromeHTTPClient
	getChromeHTTPClient = func(timeout time.Duration) *http.Client {
		return ts.Client()
	}
	defer func() { getChromeHTTPClient = origClient }()

	var buf bytes.Buffer
	originalOutput := log.Writer()
	log.SetOutput(&buf)
	defer log.SetOutput(originalOutput)

	// Call a handler to trigger CallInference
	acc := &Account{UserEmail: "test@test.com"}
	messages := []ChatMessage{{Role: "user", Content: "test"}}

	// Ensure that it runs inference via NonStream (or Stream) and logs the decision
	_ = handleAnthropicNonStream(
		httptest.NewRecorder(), acc, messages, "claude-3-opus", "req_test",
		true, false, false, nil, false, nil, nil, nil,
	)

	output := buf.String()
	expectedLogFragment := "[bridge] req_test decision: tool-call refusal detected"
	if !strings.Contains(output, expectedLogFragment) {
		t.Fatalf("expected observability log to contain %q, but got:\n%s", expectedLogFragment, output)
	}
}

// Dummy comment to trigger true diff
// Dummy 6
// Dummy 8
// Dummy 9
// Dummy 10
// Dummy 11
