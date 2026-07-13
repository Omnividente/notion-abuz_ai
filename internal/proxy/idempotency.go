package proxy

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"
)

type idempotencyStatus int

const (
	statusProcessing idempotencyStatus = iota
	statusCompleted
	statusStreaming
)

type idempotencyEntry struct {
	expires    time.Time
	status     idempotencyStatus
	mu         sync.RWMutex
	statusCode int
	headers    http.Header
	body       []byte
}

var inferenceIdempotency sync.Map

type responseCapturer struct {
	http.ResponseWriter
	statusCode  int
	body        []byte
	isStreaming bool
	wroteHeader bool
}

func (c *responseCapturer) WriteHeader(statusCode int) {
	if c.wroteHeader {
		return
	}
	c.statusCode = statusCode
	c.wroteHeader = true
	c.ResponseWriter.WriteHeader(statusCode)
}

func (c *responseCapturer) Write(b []byte) (int, error) {
	if !c.wroteHeader {
		c.WriteHeader(http.StatusOK)
	}
	if !c.isStreaming {
		c.body = append(c.body, b...)
	}
	return c.ResponseWriter.Write(b)
}

func (c *responseCapturer) Flush() {
	c.isStreaming = true
	c.body = nil
	if f, ok := c.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

// IdempotencyMiddleware ensures a client-supplied inference event is processed
// at most once. Duplicates are explicit and diagnosable instead of reaching
// Notion twice. Keys are scoped by endpoint and expire automatically.
// Completed non-streaming requests replay their sanitized response without reinference.
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
		entry := &idempotencyEntry{
			expires: time.Now().Add(30 * time.Minute),
			status:  statusProcessing,
		}
		actual, loaded := inferenceIdempotency.LoadOrStore(scoped, entry)
		if loaded {
			existing, ok := actual.(*idempotencyEntry)
			if ok {
				existing.mu.RLock()
				expired := time.Now().After(existing.expires)
				existing.mu.RUnlock()

				if expired && inferenceIdempotency.CompareAndSwap(scoped, existing, entry) {
					RecordIdempotencyMetric("expiry")
					loaded = false
				} else {
					existing.mu.RLock()
					st := existing.status
					statusCode := existing.statusCode
					headers := existing.headers
					body := existing.body
					existing.mu.RUnlock()

					if st == statusCompleted {
						RecordIdempotencyMetric("completed_replay")
						for k, v := range headers {
							for _, val := range v {
								w.Header().Add(k, val)
							}
						}
						w.Header().Set("X-Idempotency-Status", "replayed")
						w.WriteHeader(statusCode)
						w.Write(body)
						return
					}

					if st == statusStreaming {
						RecordIdempotencyMetric("streaming_non_replay")
					} else {
						RecordIdempotencyMetric("in_flight_conflict")
					}

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
			}
		}

		if loaded {
			RecordIdempotencyMetric("in_flight_conflict")
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

		RecordIdempotencyMetric("first_execution")

		capturer := &responseCapturer{ResponseWriter: w}
		next.ServeHTTP(capturer, r)

		entry.mu.Lock()
		if capturer.isStreaming {
			entry.status = statusStreaming
		} else {
			entry.status = statusCompleted
			if capturer.statusCode == 0 {
				capturer.statusCode = http.StatusOK
			}
			entry.statusCode = capturer.statusCode
			entry.body = capturer.body

			sanitizedHeaders := make(http.Header)
			for k, v := range capturer.Header() {
				lk := strings.ToLower(k)
				if lk == "set-cookie" || lk == "authorization" {
					continue
				}
				sanitizedHeaders[k] = v
			}
			entry.headers = sanitizedHeaders
		}
		entry.mu.Unlock()
	})
}

func GetIdempotencyEntryCount() int {
	count := 0
	inferenceIdempotency.Range(func(key, value interface{}) bool {
		count++
		return true
	})
	return count
}
