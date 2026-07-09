package proxy

import (
	"net/http/httptest"
	"testing"
)

func TestSetSSEHeaders(t *testing.T) {
	w := httptest.NewRecorder()
	SetSSEHeaders(w)

	if ct := w.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("Expected Content-Type to be text/event-stream, got %s", ct)
	}
	if cc := w.Header().Get("Cache-Control"); cc != "no-cache" {
		t.Errorf("Expected Cache-Control to be no-cache, got %s", cc)
	}
	if conn := w.Header().Get("Connection"); conn != "keep-alive" {
		t.Errorf("Expected Connection to be keep-alive, got %s", conn)
	}
	if xAccel := w.Header().Get("X-Accel-Buffering"); xAccel != "no" {
		t.Errorf("Expected X-Accel-Buffering to be no, got %s", xAccel)
	}
}
