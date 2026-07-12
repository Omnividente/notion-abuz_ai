package proxy

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"
)

type idempotencyEntry struct {
	expires time.Time
}

var inferenceIdempotency sync.Map

// IdempotencyMiddleware ensures a client-supplied inference event is processed
// at most once. Duplicates are explicit and diagnosable instead of reaching
// Notion twice. Keys are scoped by endpoint and expire automatically.
func IdempotencyMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || !strings.HasPrefix(r.URL.Path, "/v1/") {
			next.ServeHTTP(w, r)
			return
		}
		key := strings.TrimSpace(r.Header.Get("Idempotency-Key"))
		if key == "" {
			next.ServeHTTP(w, r)
			return
		}
		scoped := r.URL.Path + ":" + key
		entry := &idempotencyEntry{expires: time.Now().Add(30 * time.Minute)}
		actual, loaded := inferenceIdempotency.LoadOrStore(scoped, entry)
		if loaded {
			existing, ok := actual.(*idempotencyEntry)
			if ok && time.Now().After(existing.expires) &&
				inferenceIdempotency.CompareAndSwap(scoped, existing, entry) {
				loaded = false
			}
		}
		if loaded {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("X-Idempotency-Status", "duplicate")
			w.WriteHeader(http.StatusConflict)
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"error": map[string]string{
					"type":    "duplicate_request",
					"message": "this Idempotency-Key was already processed; upstream inference was not repeated",
				},
			})
			return
		}
		next.ServeHTTP(w, r)
	})
}
