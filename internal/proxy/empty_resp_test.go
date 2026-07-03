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

func TestEnsureEmptyResponseLoggedAsMetric(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "getAIUsageEligibilityV2") {
			w.Write([]byte(`{"premiumCredits": {"hasPremium": true, "premiumBalance": 100}}`))
			return
		}
		if strings.Contains(r.URL.Path, "getAIUsageEligibility") {
			w.Write([]byte(`{"isEligible": true}`))
			return
		}
		if strings.Contains(r.URL.Path, "getUserAnalyticsSettings") {
			w.Write([]byte(`{"isIntercomEnabled": true}`))
			return
		}

		w.Header().Set("Content-Type", "application/x-ndjson")
		w.WriteHeader(http.StatusOK)

		// Simulate an empty response by just completing the stream with no text blocks
		w.Write([]byte(`{"type": "agent-inference", "id":"test", "step": {"finishedAt": 123456}}` + "\n"))
	}))
	defer ts.Close()

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

	req := httptest.NewRequest("POST", "/v1/messages", bytes.NewReader([]byte(`{
		"model": "claude-3-5-sonnet-20241022",
		"messages": [{"role":"user", "content":"hello"}]
	}`)))
	req.Header.Set("Authorization", "Bearer test-token")
	w := httptest.NewRecorder()

	pool := NewAccountPool()
	acc := &Account{UserEmail: "test-empty@test.com", TokenV2: "tok", SpaceID: "spc"}
	acc.QuotaInfo = &QuotaInfo{IsEligible: true, HasPremium: true}
	acc.SpaceCount = 1
	pool.AddAccount(acc)

	handler := HandleAnthropicMessages(pool)
	handler.ServeHTTP(w, req)

	output := buf.String()
	expectedLogFragment := "[metrics] empty_response:"

	if !strings.Contains(output, expectedLogFragment) {
		t.Fatalf("expected observability metric log to contain %q, but got:\n%s", expectedLogFragment, output)
	}
}
