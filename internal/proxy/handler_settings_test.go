package proxy

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestHandleAdminSettings_Validation(t *testing.T) {
	// Create a dummy config
	configPath := filepath.Join(t.TempDir(), "dummy_settings_config.yaml")
	os.WriteFile(configPath, []byte("proxy:\n  enable_web_search: false\n"), 0644)
	defer os.Remove(configPath)

	auth := NewDashboardAuth("", "") // No password, auth bypassed

	handler := HandleAdminSettings(configPath, auth)

	tests := []struct {
		name           string
		payload        string
		expectedStatus int
	}{
		{"valid_bool", `{"enable_web_search": true}`, http.StatusOK},
		{"valid_bool_2", `{"enable_workspace_search": false}`, http.StatusOK},
		{"valid_string", `{"notion_proxy": "http://127.0.0.1:8080"}`, http.StatusOK},
		{"invalid_bool_as_string", `{"enable_web_search": "true"}`, http.StatusBadRequest},
		{"invalid_string_as_int", `{"notion_proxy": 123}`, http.StatusBadRequest},
		{"unknown_field", `{"unknown_field": "value"}`, http.StatusBadRequest},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest("PUT", "/admin/settings", bytes.NewReader([]byte(tt.payload)))
			w := httptest.NewRecorder()
			handler(w, req)

			if w.Result().StatusCode != tt.expectedStatus {
				t.Errorf("expected status %d, got %d. Body: %s", tt.expectedStatus, w.Result().StatusCode, w.Body.String())
			}
		})
	}
}
