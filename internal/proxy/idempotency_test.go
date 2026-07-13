package proxy

import (
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestIdempotencyMiddlewareConcurrentDuplicate(t *testing.T) {
	inferenceIdempotency = sync.Map{}
	idempotencyMetricsMu.Lock()
	idempotencyMetrics = make(map[string]int)
	idempotencyMetricsMu.Unlock()
	var handled atomic.Int32
	start := make(chan struct{})
	handler := IdempotencyMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handled.Add(1)
		<-start
		w.WriteHeader(http.StatusNoContent)
	}))

	const workers = 12
	results := make(chan int, workers)

	// Launch first worker to lock the key
	go func() {
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
		req.Header.Set("Idempotency-Key", "event-42")
		handler.ServeHTTP(rec, req)
		results <- rec.Code
	}()

	for handled.Load() == 0 {
	}

	// First worker is now blocked inside the handler (statusProcessing).
	// Launch remaining workers so they hit statusProcessing.
	var wg sync.WaitGroup
	for i := 1; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
			req.Header.Set("Idempotency-Key", "event-42")
			handler.ServeHTTP(rec, req)
			results <- rec.Code
		}()
	}

	// Wait for all duplicates to finish and get StatusConflict
	wg.Wait()

	// Unblock the first worker
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

	metrics := GetIdempotencyMetrics()
	if metrics["in_flight_conflict"] != workers-1 {
		t.Fatalf("expected in_flight_conflict=%d, got %d", workers-1, metrics["in_flight_conflict"])
	}
	if metrics["first_execution"] != 1 {
		t.Fatalf("expected first_execution=1, got %d", metrics["first_execution"])
	}
	if GetIdempotencyEntryCount() != 1 {
		t.Fatalf("expected 1 entry, got %d", GetIdempotencyEntryCount())
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

func TestIdempotencyMiddlewareReplayNonStreaming(t *testing.T) {
	inferenceIdempotency = sync.Map{}
	var handled atomic.Int32
	handler := IdempotencyMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handled.Add(1)
		w.Header().Set("Set-Cookie", "secret=true")
		w.Header().Set("X-Custom", "value")
		w.WriteHeader(http.StatusCreated)
		w.Write([]byte("response body"))
	}))

	req1 := httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
	req1.Header.Set("Idempotency-Key", "test-replay")
	rec1 := httptest.NewRecorder()
	handler.ServeHTTP(rec1, req1)

	if rec1.Code != http.StatusCreated {
		t.Fatalf("first request code = %d", rec1.Code)
	}
	if rec1.Body.String() != "response body" {
		t.Fatalf("first request body = %s", rec1.Body.String())
	}
	if rec1.Header().Get("Set-Cookie") != "secret=true" {
		t.Fatalf("first request missing cookie")
	}

	// Replay
	req2 := httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
	req2.Header.Set("Idempotency-Key", "test-replay")
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, req2)

	if rec2.Code != http.StatusCreated {
		t.Fatalf("second request code = %d", rec2.Code)
	}
	if rec2.Body.String() != "response body" {
		t.Fatalf("second request body = %s", rec2.Body.String())
	}
	if rec2.Header().Get("X-Idempotency-Status") != "replayed" {
		t.Fatalf("second request missing replayed header")
	}
	if rec2.Header().Get("Set-Cookie") != "" {
		t.Fatalf("second request returned cookie")
	}
	if rec2.Header().Get("X-Custom") != "value" {
		t.Fatalf("second request missing custom header")
	}

	if handled.Load() != 1 {
		t.Fatalf("handled = %d, expected 1", handled.Load())
	}

	metrics := GetIdempotencyMetrics()
	// Count may be higher if previous tests ran, just ensure > 0
	if metrics["completed_replay"] == 0 {
		t.Fatalf("expected completed_replay to be incremented")
	}
}

func TestIdempotencyMiddlewareStreaming(t *testing.T) {
	inferenceIdempotency = sync.Map{}
	var handled atomic.Int32
	handler := IdempotencyMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handled.Add(1)
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("chunk 1"))
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
		w.Write([]byte("chunk 2"))
	}))

	req1 := httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
	req1.Header.Set("Idempotency-Key", "test-stream")
	rec1 := httptest.NewRecorder()
	handler.ServeHTTP(rec1, req1)

	if rec1.Code != http.StatusOK {
		t.Fatalf("first request code = %d", rec1.Code)
	}
	if rec1.Body.String() != "chunk 1chunk 2" {
		t.Fatalf("first request body = %s", rec1.Body.String())
	}

	// Duplicate
	req2 := httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
	req2.Header.Set("Idempotency-Key", "test-stream")
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, req2)

	if rec2.Code != http.StatusConflict {
		t.Fatalf("second request code = %d", rec2.Code)
	}
	if rec2.Header().Get("X-Idempotency-Status") != "duplicate" {
		t.Fatalf("second request missing duplicate header")
	}

	if handled.Load() != 1 {
		t.Fatalf("handled = %d, expected 1", handled.Load())
	}

	metrics := GetIdempotencyMetrics()
	// Count may be higher if previous tests ran, just ensure > 0
	if metrics["completed_replay"] == 0 {
		t.Fatalf("expected completed_replay to be incremented")
	}
}

func TestIdempotencyMiddlewareExpiry(t *testing.T) {
	inferenceIdempotency = sync.Map{}
	idempotencyMetricsMu.Lock()
	idempotencyMetrics = make(map[string]int)
	idempotencyMetricsMu.Unlock()

	var handled atomic.Int32
	handler := IdempotencyMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		handled.Add(1)
		w.WriteHeader(http.StatusCreated)
	}))

	// First execution
	req1 := httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
	req1.Header.Set("Idempotency-Key", "test-expiry")
	rec1 := httptest.NewRecorder()
	handler.ServeHTTP(rec1, req1)

	if rec1.Code != http.StatusCreated {
		t.Fatalf("first request code = %d", rec1.Code)
	}

	metrics := GetIdempotencyMetrics()
	if metrics["first_execution"] != 1 {
		t.Fatalf("expected first_execution=1, got %d", metrics["first_execution"])
	}

	// Manually expire the entry
	scoped := "/v1/messages:test-expiry"
	actual, loaded := inferenceIdempotency.Load(scoped)
	if !loaded {
		t.Fatalf("expected entry to be loaded")
	}
	entry := actual.(*idempotencyEntry)
	entry.mu.Lock()
	entry.expires = time.Now().Add(-1 * time.Minute)
	entry.mu.Unlock()

	// Second execution, should trigger expiry and re-execute
	req2 := httptest.NewRequest(http.MethodPost, "/v1/messages", nil)
	req2.Header.Set("Idempotency-Key", "test-expiry")
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, req2)

	if rec2.Code != http.StatusCreated {
		t.Fatalf("second request code = %d", rec2.Code)
	}

	if handled.Load() != 2 {
		t.Fatalf("handled = %d, expected 2", handled.Load())
	}

	metrics = GetIdempotencyMetrics()
	if metrics["expiry"] != 1 {
		t.Fatalf("expected expiry=1, got %d", metrics["expiry"])
	}
	if metrics["first_execution"] != 2 {
		t.Fatalf("expected first_execution=2, got %d", metrics["first_execution"])
	}
}
