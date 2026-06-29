package proxy

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestCoerceToolArguments(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected string
	}{

		{
			name:     "string to boolean",
			input:    `{"dry_run": "true", "force": "false"}`,
			expected: `{"dry_run":true,"force":false}`,
		},

		{
			name:     "mixed types",
			input:    `{"path": "/tmp/test", "timeout": "100", "recursive": "true"}`,
			expected: `{"path":"/tmp/test","recursive":true,"timeout":"100"}`,
		},
		{
			name:     "no coercion needed",
			input:    `{"timeout": 123, "force": true}`,
			expected: `{"timeout":123,"force":true}`,
		},
		{
			name:     "nested object and array",
			input:    `{"config": {"dry_run": "true"}, "flags": ["false", "true", "test"]}`,
			expected: `{"config":{"dry_run":true},"flags":[false,true,"test"]}`,
		},
		{
			name:     "invalid json",
			input:    `{"timeout": "123`,
			expected: `{"timeout": "123`,
		},
		{
			name:     "empty object",
			input:    `{}`,
			expected: `{}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := string(coerceToolArguments([]byte(tt.input)))

			// Use generic unmarshaling for comparison to ignore key order in JSON
			if got != tt.expected && tt.name != "invalid json" {
				var gotObj, expObj map[string]interface{}
				err1 := json.Unmarshal([]byte(got), &gotObj)
				err2 := json.Unmarshal([]byte(tt.expected), &expObj)

				if err1 == nil && err2 == nil {
					if reflect.DeepEqual(gotObj, expObj) {
						return // Match, ignoring order
					}
				}

				t.Errorf("coerceToolArguments() = %v, want %v", got, tt.expected)
			} else if tt.name == "invalid json" && got != tt.expected {
				t.Errorf("coerceToolArguments() = %v, want %v", got, tt.expected)
			}
		})
	}
}
