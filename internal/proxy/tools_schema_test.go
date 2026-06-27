package proxy

import (
	"encoding/json"
	"testing"
)

func TestFilterCoreTools(t *testing.T) {
	tools := []Tool{
		{Function: ToolFunction{Name: "Bash"}},
		{Function: ToolFunction{Name: "NonCoreTool"}},
		{Function: ToolFunction{Name: "Read"}},
		{Function: ToolFunction{Name: "WebSearch"}},
	}
	core := filterCoreTools(tools)
	if len(core) != 3 {
		t.Fatalf("Expected 3 core tools, got %d", len(core))
	}
	if core[0].Function.Name != "Bash" || core[1].Function.Name != "Read" || core[2].Function.Name != "WebSearch" {
		t.Errorf("Unexpected tools: %v", core)
	}

	// Test fallback
	toolsFallback := []Tool{
		{Function: ToolFunction{Name: "NonCoreTool1"}},
		{Function: ToolFunction{Name: "NonCoreTool2"}},
	}
	fallback := filterCoreTools(toolsFallback)
	if len(fallback) != 2 {
		t.Fatalf("Expected fallback to keep all tools, got %d", len(fallback))
	}
}

func TestExtractParamSignature(t *testing.T) {
	schemaStr := `{"type":"object","properties":{"command":{"type":"string"},"timeout":{"type":"integer"}},"required":["command"]}`
	var schema interface{}
	json.Unmarshal([]byte(schemaStr), &schema)
	sig := extractParamSignature(schema)
	if sig != "command: str, timeout?: int" {
		t.Errorf("Unexpected signature: %q", sig)
	}
}

func TestBuildCompactToolList(t *testing.T) {
	schemaStr := `{"type":"object","properties":{"command":{"type":"string"},"timeout":{"type":"integer"}},"required":["command"]}`
	var schema interface{}
	json.Unmarshal([]byte(schemaStr), &schema)

	tools := []Tool{
		{Function: ToolFunction{Name: "Bash", Description: "Execute bash command", Parameters: schema}},
	}
	res := buildCompactToolList(tools)
	expected := "- Bash(command: str, timeout?: int) — Execute bash command\n"
	if res != expected {
		t.Errorf("Expected %q, got %q", expected, res)
	}
}

func TestFilterCoreTools_OversizedClaudeCodeList(t *testing.T) {
	schemaStr := `{"type":"object","properties":{"command":{"type":"string"},"timeout":{"type":"integer"}},"required":["command"]}`
	var schema interface{}
	json.Unmarshal([]byte(schemaStr), &schema)

	// An oversized tool list similar to what Claude Code might send
	tools := []Tool{
		{Function: ToolFunction{Name: "Bash", Description: "Execute bash command", Parameters: schema}},
		{Function: ToolFunction{Name: "Read", Description: "Read file contents", Parameters: schema}},
		{Function: ToolFunction{Name: "Edit", Description: "Edit a file", Parameters: schema}},
		{Function: ToolFunction{Name: "Write", Description: "Write to a file", Parameters: schema}},
		{Function: ToolFunction{Name: "Glob", Description: "Search for files", Parameters: schema}},
		{Function: ToolFunction{Name: "Grep", Description: "Search within files", Parameters: schema}},
		{Function: ToolFunction{Name: "Agent", Description: "Delegate to another agent", Parameters: schema}},
		{Function: ToolFunction{Name: "TaskCreate", Description: "Create a task", Parameters: schema}},
		{Function: ToolFunction{Name: "TaskComplete", Description: "Complete a task", Parameters: schema}},
		{Function: ToolFunction{Name: "TodoWrite", Description: "Write to a todo list", Parameters: schema}},
		{Function: ToolFunction{Name: "LSP", Description: "Use language server", Parameters: schema}},
		{Function: ToolFunction{Name: "ViewWebsite", Description: "View website", Parameters: schema}},
		{Function: ToolFunction{Name: "SearchWebsite", Description: "Search website", Parameters: schema}},
		{Function: ToolFunction{Name: "MemoryWrite", Description: "Write memory", Parameters: schema}},
		{Function: ToolFunction{Name: "MemoryRead", Description: "Read memory", Parameters: schema}},
	}

	// Ensure we can filter
	coreTools := filterCoreTools(tools)
	if len(coreTools) != 6 {
		t.Fatalf("Expected 6 core tools from list, got %d", len(coreTools))
	}

	for _, coreTool := range coreTools {
		name := coreTool.Function.Name
		if name != "Bash" && name != "Read" && name != "Edit" && name != "Write" && name != "Glob" && name != "Grep" {
			t.Errorf("Unexpected tool in core set: %s", name)
		}
	}
}
