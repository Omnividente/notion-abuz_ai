package proxy

import (
	"log"
	"sync"
)

var (
	requestContractMetricsMu sync.Mutex
	requestContractMetrics   = make(map[string]int)
	idempotencyMetricsMu     sync.Mutex
	idempotencyMetrics       = make(map[string]int)
)

func RecordRequestContractMetric(reason string) {
	requestContractMetricsMu.Lock()
	requestContractMetrics[reason]++
	count := requestContractMetrics[reason]
	requestContractMetricsMu.Unlock()
	log.Printf("[metrics] request_contract: %s (total: %d)", reason, count)
}

func GetRequestContractMetrics() map[string]int {
	requestContractMetricsMu.Lock()
	defer requestContractMetricsMu.Unlock()

	out := make(map[string]int, len(requestContractMetrics))
	for k, v := range requestContractMetrics {
		out[k] = v
	}
	return out
}

func GetContextLossMetrics() map[string]int {
	contextLossMetricsMu.Lock()
	defer contextLossMetricsMu.Unlock()

	out := make(map[string]int, len(contextLossMetrics))
	for k, v := range contextLossMetrics {
		out[k] = v
	}
	return out
}

func GetToolModeLossMetrics() map[string]int {
	toolModeLossMetricsMu.Lock()
	defer toolModeLossMetricsMu.Unlock()

	out := make(map[string]int, len(toolModeLossMetrics))
	for k, v := range toolModeLossMetrics {
		out[k] = v
	}
	return out
}

func RecordIdempotencyMetric(reason string) {
	idempotencyMetricsMu.Lock()
	idempotencyMetrics[reason]++
	count := idempotencyMetrics[reason]
	idempotencyMetricsMu.Unlock()
	log.Printf("[metrics] idempotency: %s (total: %d)", reason, count)
}

func GetIdempotencyMetrics() map[string]int {
	idempotencyMetricsMu.Lock()
	defer idempotencyMetricsMu.Unlock()

	out := make(map[string]int, len(idempotencyMetrics))
	for k, v := range idempotencyMetrics {
		out[k] = v
	}
	return out
}
