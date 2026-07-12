package proxy

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHandleHealth(t *testing.T) {
	// Create a minimal AccountPool setup for testing
	pool := &AccountPool{}

	handler := HandleHealth(pool)
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()

	handler(w, req)

	res := w.Result()
	defer res.Body.Close()

	if res.StatusCode != http.StatusOK {
		t.Errorf("expected status OK, got %v", res.StatusCode)
	}

	var response map[string]interface{}
	err := json.NewDecoder(res.Body).Decode(&response)
	if err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	if response["status"] != "ok" {
		t.Errorf("expected status 'ok', got %v", response["status"])
	}

	// Verify that expected keys are present in the response
	expectedKeys := []string{"accounts", "available", "quota"}
	for _, key := range expectedKeys {
		if _, ok := response[key]; !ok {
			t.Errorf("expected key %q in response, but it was missing", key)
		}
	}
}

func TestHandleReadiness_NoUsableAccounts(t *testing.T) {
	pool := NewAccountPool()
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/ready", nil)

	HandleReadiness(pool).ServeHTTP(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if rec.Header().Get("Retry-After") == "" {
		t.Fatal("expected Retry-After for deferred readiness")
	}
	var response map[string]interface{}
	if err := json.NewDecoder(rec.Body).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if response["status"] != "not_ready" || response["reason"] != "no usable accounts" {
		t.Fatalf("response=%#v", response)
	}
}
