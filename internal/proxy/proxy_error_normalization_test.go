package proxy

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

type AnthropicErrorResponse struct {
	Type  string `json:"type"`
	Error struct {
		Type    string `json:"type"`
		Message string `json:"message"`
	} `json:"error"`
}

func TestOpenAIErrorNormalization_MalformedRequest(t *testing.T) {
	pool := NewAccountPool()
	handler := HandleOpenAIChatCompletions(pool)

	req := httptest.NewRequest("POST", "/v1/chat/completions", bytes.NewBufferString("{ invalid json }"))
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("Expected status 400, got %d", w.Code)
	}

	var errResp OpenAIErrorResponse
	if err := json.Unmarshal(w.Body.Bytes(), &errResp); err != nil {
		t.Fatalf("Failed to parse error response: %v", err)
	}

	if errResp.Error.Type != "invalid_request_error" {
		t.Errorf("Expected error type 'invalid_request_error', got '%s'", errResp.Error.Type)
	}
}

func TestAnthropicErrorNormalization_MalformedRequest(t *testing.T) {
	pool := NewAccountPool()
	handler := HandleAnthropicMessages(pool)

	req := httptest.NewRequest("POST", "/v1/messages", bytes.NewBufferString("{ invalid json }"))
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("Expected status 400, got %d", w.Code)
	}

	var errResp AnthropicErrorResponse
	if err := json.Unmarshal(w.Body.Bytes(), &errResp); err != nil {
		t.Fatalf("Failed to parse error response: %v", err)
	}

	if errResp.Error.Type != "invalid_request_error" {
		t.Errorf("Expected error type 'invalid_request_error', got '%s'", errResp.Error.Type)
	}
}

func TestOpenAIErrorNormalization_MethodNotAllowed(t *testing.T) {
	pool := NewAccountPool()
	handler := HandleOpenAIChatCompletions(pool)

	req := httptest.NewRequest("GET", "/v1/chat/completions", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("Expected status 405, got %d", w.Code)
	}

	var errResp OpenAIErrorResponse
	if err := json.Unmarshal(w.Body.Bytes(), &errResp); err != nil {
		t.Fatalf("Failed to parse error response: %v", err)
	}

	if errResp.Error.Type != "invalid_request_error" {
		t.Errorf("Expected error type 'invalid_request_error', got '%s'", errResp.Error.Type)
	}
}

func TestAnthropicErrorNormalization_MethodNotAllowed(t *testing.T) {
	pool := NewAccountPool()
	handler := HandleAnthropicMessages(pool)

	req := httptest.NewRequest("GET", "/v1/messages", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("Expected status 405, got %d", w.Code)
	}

	var errResp AnthropicErrorResponse
	if err := json.Unmarshal(w.Body.Bytes(), &errResp); err != nil {
		t.Fatalf("Failed to parse error response: %v", err)
	}

	if errResp.Error.Type != "invalid_request_error" {
		t.Errorf("Expected error type 'invalid_request_error', got '%s'", errResp.Error.Type)
	}
}

func TestOpenAIErrorNormalization_EmptyBody(t *testing.T) {
	pool := NewAccountPool()
	handler := HandleOpenAIChatCompletions(pool)

	req := httptest.NewRequest("POST", "/v1/chat/completions", bytes.NewBufferString(""))
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("Expected status 400, got %d", w.Code)
	}

	var errResp OpenAIErrorResponse
	if err := json.Unmarshal(w.Body.Bytes(), &errResp); err != nil {
		t.Fatalf("Failed to parse error response: %v", err)
	}

	if errResp.Error.Type != "invalid_request_error" {
		t.Errorf("Expected error type 'invalid_request_error', got '%s'", errResp.Error.Type)
	}
}
