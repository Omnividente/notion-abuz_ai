package proxy

import (
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
