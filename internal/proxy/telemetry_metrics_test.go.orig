package proxy

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHandleAdminMetrics(t *testing.T) {
	// Reset metrics before test
	contextLossMetricsMu.Lock()
	contextLossMetrics = make(map[string]int)
	contextLossMetricsMu.Unlock()

	recordContextLossMetric("tool_schema_simplification_recursion_limit")

	auth := NewDashboardAuth("", "")

	req, _ := http.NewRequest("GET", "/admin/metrics", nil)
	rr := httptest.NewRecorder()

	handler := HandleAdminMetrics(auth)
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Errorf("expected 200 OK, got %d", rr.Code)
	}

	var res map[string]map[string]int
	if err := json.NewDecoder(rr.Body).Decode(&res); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	metrics := res["context_loss"]
	if metrics["tool_schema_simplification_recursion_limit"] != 1 {
		t.Errorf("expected tool_schema_simplification_recursion_limit to be 1, got %d", metrics["tool_schema_simplification_recursion_limit"])
	}
}
