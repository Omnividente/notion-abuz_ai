package proxy

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestUploadFileToNotionContextCancellation(t *testing.T) {
	var step int
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		step++
		if strings.Contains(r.URL.Path, "/getUploadFileUrlForAssistantChatTranscriptUpload") {
			w.WriteHeader(http.StatusOK)
			json.NewEncoder(w).Encode(NotionUploadURLResponse{
				URL:                 "https://notion.so/attachment:1234:file.txt",
				SignedUploadPostURL: "http://" + r.Host + "/s3",
			})
			return
		}
		if strings.Contains(r.URL.Path, "/s3") {
			w.WriteHeader(http.StatusOK)
			return
		}
		if strings.Contains(r.URL.Path, "/enqueueTask") {
			// Intentionally sleep long enough so the context will be cancelled during this step.
			time.Sleep(300 * time.Millisecond)
			w.WriteHeader(http.StatusOK)
			w.Write([]byte(`{"taskId": "task-123"}`))
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer ts.Close()

	// temporarily override NotionAPIBase
	origBase := NotionAPIBase
	origGetChromeHTTPClient := getChromeHTTPClient
	getChromeHTTPClient = func(timeout time.Duration) *http.Client {
		return ts.Client()
	}
	NotionAPIBase = ts.URL
	defer func() { NotionAPIBase = origBase; getChromeHTTPClient = origGetChromeHTTPClient }()

	acc := &Account{SpaceID: "space1"}
	file := &FileAttachment{FileName: "file.txt", ContentType: "text/plain", Data: []byte("test")}

	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	_, err := UploadFileToNotion(ctx, acc, file)
	if err == nil {
		t.Fatalf("expected error due to context cancellation, got nil")
	}
	if !strings.Contains(err.Error(), "context deadline exceeded") && !strings.Contains(err.Error(), "context canceled") {
		t.Fatalf("expected context error, got %v", err)
	}
}
