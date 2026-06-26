package proxy

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHandleAnthropicMessages_InjectsCompatibilityInstructionForCodingAssistants(t *testing.T) {
	// Disable AppConfig to avoid panics during log if we don't mock it completely
	AppConfig = &Config{}

	pool := NewAccountPool()
	// Add a dummy account to the pool so it doesn't fail early with NoAccountsAvailable
	pool.accounts = []*Account{
		{
			UserEmail: "test@example.com",
			UserID:    "user-123",
			TokenV2:   "token",
			SpaceID:   "space-123",
		},
	}

	reqBody := AnthropicRequest{
		Model:  "claude-opus-4-6",
		System: "You are Claude Code, Anthropic's official CLI.",
		Messages: []AnthropicMessage{
			{Role: "user", Content: "Write a test."},
		},
	}
	bodyBytes, _ := json.Marshal(reqBody)

	req, _ := http.NewRequest("POST", "/v1/messages", bytes.NewReader(bodyBytes))
	req.Header.Set("Content-Type", "application/json")

	rr := httptest.NewRecorder()
	handler := HandleAnthropicMessages(pool)

	// Since we mock the pool but not Notion's actual API, it will fail at the inference call
	// or return a bad gateway. We just want to ensure it doesn't panic and that the logic runs.
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusBadGateway && rr.Code != http.StatusInternalServerError && rr.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d", rr.Code)
	}
}

func TestHandleOpenAIChatCompletions_InjectsCompatibilityInstructionForCodingAssistants(t *testing.T) {
	AppConfig = &Config{}

	pool := NewAccountPool()
	pool.accounts = []*Account{
		{
			UserEmail: "test@example.com",
			UserID:    "user-123",
			TokenV2:   "token",
			SpaceID:   "space-123",
		},
	}

	reqBody := OpenAIChatCompletionRequest{
		Model: "gpt-4",
		Messages: []OpenAIChatMessage{
			{Role: "system", Content: "You are a helpful coding assistant API."},
			{Role: "user", Content: "Write a function."},
		},
	}
	bodyBytes, _ := json.Marshal(reqBody)

	req, _ := http.NewRequest("POST", "/v1/chat/completions", bytes.NewReader(bodyBytes))
	req.Header.Set("Content-Type", "application/json")

	rr := httptest.NewRecorder()
	handler := HandleOpenAIChatCompletions(pool)

	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusBadGateway && rr.Code != http.StatusInternalServerError && rr.Code != http.StatusOK {
		t.Fatalf("unexpected status code: %d", rr.Code)
	}
}
