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

	toolModeLossMetricsMu.Lock()
	toolModeLossMetrics = make(map[string]int)
	toolModeLossMetricsMu.Unlock()

	recordToolModeLossMetric("unparseable_json_candidate_blocks")
	auth := NewDashboardAuth("", "")

	req, _ := http.NewRequest("GET", "/admin/metrics", nil)
	rr := httptest.NewRecorder()

	handler := HandleAdminMetrics(auth)
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Errorf("expected 200 OK, got %d", rr.Code)
	}

	var res map[string]interface{}
	if err := json.NewDecoder(rr.Body).Decode(&res); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	metrics := res["context_loss"].(map[string]interface{})
	if metrics["tool_schema_simplification_recursion_limit"].(float64) != 1 {
		t.Errorf("expected tool_schema_simplification_recursion_limit to be 1, got %v", metrics["tool_schema_simplification_recursion_limit"])
	}

	toolModeLossMetrics := res["tool_mode_loss"].(map[string]interface{})
	if toolModeLossMetrics["unparseable_json_candidate_blocks"].(float64) != 1 {
		t.Errorf("expected unparseable_json_candidate_blocks to be 1, got %v", toolModeLossMetrics["unparseable_json_candidate_blocks"])
	}

	requestContractMetrics := res["request_contract"]
	if requestContractMetrics == nil {
		t.Errorf("expected request_contract to be present in response")
	}

	idempotencyMetrics := res["idempotency"]
	if idempotencyMetrics == nil {
		t.Errorf("expected idempotency to be present in response")
	}

	idempotencyEntries := res["idempotency_entries"]
	if idempotencyEntries == nil {
		t.Errorf("expected idempotency_entries to be present in response")
	}
}
