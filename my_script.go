package main

import (
	"fmt"
	"strings"
	"regexp"
)

type ChatMessage struct {
	Role    string
	Content string
}

func main() {
	var cwdRe = regexp.MustCompile(`<cwd>([^<]+)</cwd>`)
	messages := []ChatMessage{
		{Role: "system", Content: "You are acting as a coding assistant API behind a compatibility proxy."},
		{Role: "system", Content: "<cwd>/home</cwd>You are Claude Code."},
	}
	var filtered []ChatMessage
	var extractedCwd string
	for _, m := range messages {
		if m.Role == "system" {
			// Preserve our own coding assistant instruction
			if strings.Contains(m.Content, "You are acting as a coding assistant API behind a compatibility proxy.") {
				filtered = append(filtered, m)
			} else {
				if match := cwdRe.FindStringSubmatch(m.Content); len(match) >= 2 {
					extractedCwd = match[1]
					fmt.Printf("[bridge] extracted CWD from system prompt: %s\n", extractedCwd)
				}
				fmt.Printf("[bridge] dropped system message (%d chars)\n", len(m.Content))
			}
		} else {
			filtered = append(filtered, m)
		}
	}
	fmt.Printf("filtered length: %d\n", len(filtered))
	for _, f := range filtered {
		fmt.Printf("filtered: %s\n", f.Content)
	}
}
