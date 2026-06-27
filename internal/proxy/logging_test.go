package proxy

import (
	"log"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDebugLoggingToggle(t *testing.T) {
	tmpDir := t.TempDir()
	logPath := filepath.Join(tmpDir, "test.log")

	err := ConfigureLogOutput(logPath)
	if err != nil {
		t.Fatalf("ConfigureLogOutput failed: %v", err)
	}
	defer ConfigureLogOutput("") // reset

	// Test 1: Debug enabled
	SetDebugLoggingEnabled(true)
	log.Println("[debug] this should be logged")
	log.Println("[bridge] this bridge log should be logged")
	log.Println("normal log should always be logged")

	b, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("failed to read log: %v", err)
	}
	out := string(b)
	if !strings.Contains(out, "[debug] this should be logged") {
		t.Errorf("expected [debug] log, got: %s", out)
	}
	if !strings.Contains(out, "[bridge] this bridge log should be logged") {
		t.Errorf("expected [bridge] log, got: %s", out)
	}
	if !strings.Contains(out, "normal log should always be logged") {
		t.Errorf("expected normal log, got: %s", out)
	}

	// Clear log file for Test 2
	os.Remove(logPath)
	ConfigureLogOutput(logPath)

	// Test 2: Debug disabled
	SetDebugLoggingEnabled(false)
	log.Println("[debug] this should NOT be logged")
	log.Println("[thinking] this thinking log should NOT be logged")
	log.Println("another normal log should be logged")

	b, err = os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("failed to read log: %v", err)
	}
	out = string(b)
	if strings.Contains(out, "[debug] this should NOT be logged") {
		t.Errorf("did not expect [debug] log, got: %s", out)
	}
	if strings.Contains(out, "[thinking] this thinking log should NOT be logged") {
		t.Errorf("did not expect [thinking] log, got: %s", out)
	}
	if !strings.Contains(out, "another normal log should be logged") {
		t.Errorf("expected normal log, got: %s", out)
	}
}
