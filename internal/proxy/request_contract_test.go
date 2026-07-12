package proxy

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestResolveRequestMode(t *testing.T) {
	tests := []struct {
		name, model, mode, wantModel string
		defaultAsk, wantAsk, wantErr bool
	}{
		{name: "default chat", model: "opus-4.8", wantModel: "opus-4.8"},
		{name: "suffix ask", model: "opus-4.8-ask", wantModel: "opus-4.8", wantAsk: true},
		{name: "explicit ask", model: "opus-4.8", mode: "ask", wantModel: "opus-4.8", wantAsk: true},
		{name: "configured default", model: "opus-4.8", defaultAsk: true, wantModel: "opus-4.8", wantAsk: true},
		{name: "explicit agent", model: "opus-4.8", mode: "agent", wantModel: "opus-4.8"},
		{name: "conflict", model: "opus-4.8-ask", mode: "agent", wantErr: true},
		{name: "unknown", model: "opus-4.8", mode: "silent-downgrade", wantErr: true},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			model, ask, err := ResolveRequestMode(tc.model, tc.mode, tc.defaultAsk)
			if (err != nil) != tc.wantErr {
				t.Fatalf("err=%v wantErr=%v", err, tc.wantErr)
			}
			if tc.wantErr {
				if err == nil || !strings.Contains(err.Error(), "not downgraded") && tc.name == "conflict" {
					t.Fatalf("diagnostic error=%v", err)
				}
				return
			}
			if model != tc.wantModel || ask != tc.wantAsk {
				t.Fatalf("got model=%q ask=%v, want model=%q ask=%v", model, ask, tc.wantModel, tc.wantAsk)
			}
		})
	}
}

func TestResolveReasoningEffortAliasNoSilentDowngrade(t *testing.T) {
	original := SnapshotModelMap()
	ReplaceModelMap(map[string]string{"opus-4.8-high": "internal-high"})
	t.Cleanup(func() { ReplaceModelMap(original) })

	got, err := ResolveReasoningEffortAlias("opus-4.8", "high")
	if err != nil || got != "opus-4.8-high" {
		t.Fatalf("configured alias got=%q err=%v", got, err)
	}
	if _, err := ResolveReasoningEffortAlias("opus-4.8", "low"); err == nil ||
		!strings.Contains(err.Error(), "request was not downgraded") {
		t.Fatalf("missing explicit diagnostic: %v", err)
	}
}

func TestRoutingContractLanguageMatrix(t *testing.T) {
	cases := []struct {
		name       string
		messages   []ChatMessage
		wantCoding bool
	}{
		{
			name:       "english contract",
			messages:   []ChatMessage{{Role: "system", Content: "You are a coding assistant. Edit repository files and run tests."}},
			wantCoding: true,
		},
		{
			name:       "russian contract",
			messages:   []ChatMessage{{Role: "system", Content: "Ты программный агент: исправляй исходный код репозитория, создавай патчи и запускай тесты."}},
			wantCoding: true,
		},
		{
			name:       "mixed contract",
			messages:   []ChatMessage{{Role: "developer", Content: "Работай с repository, используй инструменты и run tests."}},
			wantCoding: true,
		},
		{
			name:       "russian ordinary request",
			messages:   []ChatMessage{{Role: "user", Content: "Кратко перескажи документ."}},
			wantCoding: false,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := isCodingAssistantRequest(tc.messages); got != tc.wantCoding {
				t.Fatalf("isCodingAssistantRequest=%v want=%v", got, tc.wantCoding)
			}
		})
	}

	// Upstream response language is intentionally not an input to routing.
	if !ShouldDisableAgentFallback(false, true, true, "") {
		t.Fatal("coding/tools contract must stay direct even if Notion later answers in English")
	}
	if ShouldDisableAgentFallback(true, true, true, "agent") {
		t.Fatal("explicit agent mode must be honored")
	}
}


func TestModeModelReasoningSerializedNotionContract(t *testing.T) {
	original := SnapshotModelMap()
	ReplaceModelMap(map[string]string{"opus-4.8-high": "notion-internal-high"})
	t.Cleanup(func() { ReplaceModelMap(original) })

	converted, err := convertOpenAIChatCompletionRequest(&OpenAIChatCompletionRequest{
		Model:           "opus-4.8",
		Mode:            "ask",
		ReasoningEffort: "high",
		Messages:        []OpenAIChatMessage{{Role: "user", Content: "Проверь код"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if converted.Model != "opus-4.8-high" || converted.Mode != "ask" {
		t.Fatalf("converted model=%q mode=%q", converted.Model, converted.Mode)
	}

	model, readOnly, err := ResolveRequestMode(converted.Model, converted.Mode, false)
	if err != nil {
		t.Fatal(err)
	}
	notionModel := ResolveModel(model)
	config := buildConfigValue(notionModel, true, false, nil, readOnly, false, true)
	debug := DebugOverrides{Model: notionModel, EmitAgentSearchExtractedResults: true}
	payload, err := json.Marshal(map[string]interface{}{
		"config": config,
		"debugOverrides": debug,
	})
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]interface{}
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatal(err)
	}
	cfg := decoded["config"].(map[string]interface{})
	overrides := decoded["debugOverrides"].(map[string]interface{})
	if cfg["useReadOnlyMode"] != true {
		t.Fatalf("mode missing from serialized config: %s", payload)
	}
	if cfg["model"] != "notion-internal-high" || overrides["model"] != "notion-internal-high" {
		t.Fatalf("model/reasoning alias missing from serialized payload: %s", payload)
	}
}
