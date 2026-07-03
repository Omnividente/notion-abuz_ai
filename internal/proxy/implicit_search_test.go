package proxy

import (
	"testing"
)

func TestDetectImplicitSearch(t *testing.T) {
	tests := []struct {
		name          string
		messages      []ChatMessage
		wantWeb       bool
		wantWorkspace bool
	}{
		{
			name: "explicit web search",
			messages: []ChatMessage{
				{Role: "user", Content: "Could you search the web for latest AI news?"},
			},
			wantWeb:       true,
			wantWorkspace: false,
		},
		{
			name: "explicit workspace search",
			messages: []ChatMessage{
				{Role: "user", Content: "Please search my workspace for Q3 planning"},
			},
			wantWeb:       false,
			wantWorkspace: true,
		},
		{
			name: "both",
			messages: []ChatMessage{
				{Role: "user", Content: "Search Notion for the project, and also google for the competitor."},
			},
			wantWeb:       true,
			wantWorkspace: true,
		},
		{
			name: "neither",
			messages: []ChatMessage{
				{Role: "user", Content: "Just write a bash script for me."},
			},
			wantWeb:       false,
			wantWorkspace: false,
		},
		{
			name: "meaningful message skips wrappers",
			messages: []ChatMessage{
				{Role: "user", Content: "Can you search online?"},
				{Role: "assistant", Content: "Sure!"},
				{Role: "user", Content: "Results from executed function(s):\n<some result>"},
			},
			wantWeb:       true,
			wantWorkspace: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotWeb, gotWorkspace := detectImplicitSearch(tt.messages)
			if gotWeb != tt.wantWeb {
				t.Errorf("detectImplicitSearch() gotWeb = %v, want %v", gotWeb, tt.wantWeb)
			}
			if gotWorkspace != tt.wantWorkspace {
				t.Errorf("detectImplicitSearch() gotWorkspace = %v, want %v", gotWorkspace, tt.wantWorkspace)
			}
		})
	}
}
