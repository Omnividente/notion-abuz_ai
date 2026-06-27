package proxy

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadConfig_MissingFile(t *testing.T) {
	cfg, err := LoadConfig("non-existent-file.yaml")
	if err != nil {
		t.Fatalf("LoadConfig failed for missing file: %v", err)
	}
	if cfg.Server.Port != "8081" {
		t.Errorf("Expected default port 8081, got %s", cfg.Server.Port)
	}
}

func TestLoadConfig_ValidFile(t *testing.T) {
	content := []byte(`
server:
  port: "9000"
proxy:
  default_model: "custom-model"
`)
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.yaml")
	if err := os.WriteFile(configPath, content, 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := LoadConfig(configPath)
	if err != nil {
		t.Fatalf("LoadConfig failed: %v", err)
	}
	if cfg.Server.Port != "9000" {
		t.Errorf("Expected port 9000, got %s", cfg.Server.Port)
	}
	if cfg.Proxy.DefaultModel != "custom-model" {
		t.Errorf("Expected default_model custom-model, got %s", cfg.Proxy.DefaultModel)
	}
	if cfg.Server.AccountsDir != "accounts" {
		t.Errorf("Expected default accounts_dir 'accounts', got %s", cfg.Server.AccountsDir)
	}
}

func TestLoadConfig_EnvOverrides(t *testing.T) {
	os.Setenv("PORT", "9999")
	defer os.Unsetenv("PORT")

	cfg, err := LoadConfig("")
	if err != nil {
		t.Fatalf("LoadConfig failed: %v", err)
	}

	if cfg.Server.Port != "9999" {
		t.Errorf("Expected port 9999, got %s", cfg.Server.Port)
	}
}

func TestLoadConfig_InvalidFile(t *testing.T) {
	content := []byte(`
server:
  port: "9000
  invalid_yaml
`)
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.yaml")
	if err := os.WriteFile(configPath, content, 0644); err != nil {
		t.Fatal(err)
	}

	_, err := LoadConfig(configPath)
	if err == nil {
		t.Fatal("Expected LoadConfig to fail on invalid YAML")
	}
}

func TestLoadConfig_ModelMapDefaults(t *testing.T) {
	// Tests that ModelMap remains set if config.yaml is parsed but has no model_map
	content := []byte(`
server:
  port: "9000"
`)
	tmpDir := t.TempDir()
	configPath := filepath.Join(tmpDir, "config.yaml")
	if err := os.WriteFile(configPath, content, 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := LoadConfig(configPath)
	if err != nil {
		t.Fatalf("LoadConfig failed: %v", err)
	}

	if cfg.ModelMap == nil {
		t.Fatal("Expected ModelMap to not be nil")
	}
	if len(cfg.ModelMap) == 0 {
		t.Fatal("Expected ModelMap to have default values")
	}
}
