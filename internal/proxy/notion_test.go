package proxy

import (
	"strings"

	"reflect"
	"testing"
)

func TestReplaceModelMap(t *testing.T) {
	initial := SnapshotModelMap()
	defer ReplaceModelMap(initial) // Restore after test

	testMap := map[string]string{
		"test-alias": "test-model-id",
		"  spaces  ": "  value  ",
		"empty-val":  "",
		"   ":        "val",
		"":           "empty-key",
	}

	ReplaceModelMap(testMap)

	current := SnapshotModelMap()
	expected := map[string]string{
		"test-alias": "test-model-id",
		"spaces":     "value",
	}

	if !reflect.DeepEqual(current, expected) {
		t.Errorf("Expected map %v, got %v", expected, current)
	}
}

func TestParseNDJSONStream_JSONToolCallLoss(t *testing.T) {
	ndjson := `{"type": "agent-inference", "value": [{"type": "text", "content": "I lost JSON tool-call mode and will write text instead.\n\n` + "```" + `json\n{\n  \"command\": \"ls\"\n}\n` + "```" + `"}], "finishedAt": 123456789}` + "\n"
	r := strings.NewReader(ndjson)

	var foundFallbackText bool
	cb := func(delta string, done bool, usage *UsageInfo) {
		if strings.Contains(delta, "I lost JSON tool-call mode") {
			foundFallbackText = true
		}
	}

	err := parseNDJSONStream(r, "req1", cb, nil, nil, nil, nil, nil, nil)
	if err != nil {
		t.Fatalf("parseNDJSONStream error: %v", err)
	}

	if !foundFallbackText {
		t.Fatalf("failed to parse the conversational fallback text value from NDJSON")
	}
}
