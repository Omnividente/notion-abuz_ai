package proxy

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

type fixture struct {
	Messages   []ChatMessage `json:"messages"`
	WantCoding bool          `json:"want_coding"`
}

func TestRoutingContractLiveFixtures(t *testing.T) {
	files, err := filepath.Glob("../../testdata/routing/*.json")
	if err != nil {
		t.Fatal(err)
	}

	if len(files) == 0 {
		t.Fatal("no fixtures found in testdata/routing/")
	}

	for _, file := range files {
		t.Run(filepath.Base(file), func(t *testing.T) {
			data, err := os.ReadFile(file)
			if err != nil {
				t.Fatal(err)
			}
			var f fixture
			if err := json.Unmarshal(data, &f); err != nil {
				t.Fatal(err)
			}

			got := isCodingAssistantRequest(f.Messages)
			if got != f.WantCoding {
				t.Errorf("isCodingAssistantRequest() = %v, want %v", got, f.WantCoding)
			}
		})
	}
}
