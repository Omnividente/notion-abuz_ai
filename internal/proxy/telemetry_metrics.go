package proxy

func GetContextLossMetrics() map[string]int {
	contextLossMetricsMu.Lock()
	defer contextLossMetricsMu.Unlock()

	out := make(map[string]int, len(contextLossMetrics))
	for k, v := range contextLossMetrics {
		out[k] = v
	}
	return out
}
