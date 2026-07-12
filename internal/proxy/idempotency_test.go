package proxy

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
)

func TestIdempotencyMiddlewareConcurrentDuplicate(t *testing.T) {
	inferenceIdempotency = sync.Map{}
	var handled atomic.Int32
	start := make(chan struct{})
	handler := IdempotencyMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handled.Add(1)
		<-start
		w.WriteHeader(http.StatusNoContent)
	}))

	const workers = 12
	results := make(chan int, workers)
	for i := 0; i < workers; i++ {
		go func() {
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
			req.Header.Set("Idempotency-Key", "event-42")
			handler.ServeHTTP(rec, req)
			results <- rec.Code
		}()
	}
	for handled.Load() == 0 {
	}
	close(start)

	success, duplicates := 0, 0
	for i := 0; i < workers; i++ {
		switch code := <-results; code {
		case http.StatusNoContent:
			success++
		case http.StatusConflict:
			duplicates++
		default:
			t.Fatalf("unexpected status %d", code)
		}
	}
	if success != 1 || duplicates != workers-1 || handled.Load() != 1 {
		t.Fatalf("success=%d duplicates=%d handled=%d", success, duplicates, handled.Load())
	}
}

func TestIdempotencyMiddlewarePassesRequestsWithoutKey(t *testing.T) {
	inferenceIdempotency = sync.Map{}
	var handled atomic.Int32
	handler := IdempotencyMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handled.Add(1)
		w.WriteHeader(http.StatusNoContent)
	}))
	for i := 0; i < 2; i++ {
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/v1/responses", nil))
		if rec.Code != http.StatusNoContent {
			t.Fatalf("status=%d", rec.Code)
		}
	}
	if handled.Load() != 2 {
		t.Fatalf("handled=%d", handled.Load())
	}
}
