package main

import (
	"fmt"
	"strings"
)

type historyEntry struct {
	label   string
	content string
}

func main() {
	trailingReversed := []historyEntry{
		{label: "Tool (test)", content: "line1\nline2"},
		{label: "Assistant", content: "Call test({})"},
	}
	var prompt strings.Builder
	prompt.WriteString("Partial progress since the latest user message:\n")
	for i := len(trailingReversed) - 1; i >= 0; i-- {
		prompt.WriteString(trailingReversed[i].label)
		prompt.WriteString(":\n") // wait, let's see how it currently is
		prompt.WriteString(trailingReversed[i].content)
		if i > 0 {
			prompt.WriteString("\n\n")
		}
	}
	fmt.Println(prompt.String())
}
