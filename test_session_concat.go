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
	reversed := []historyEntry{
		{label: "Tool (test)", content: "line1\nline2"},
		{label: "Assistant", content: "Call test({})"},
	}
	var history strings.Builder
	for i := len(reversed) - 1; i >= 0; i-- {
		if history.Len() > 0 {
			history.WriteString("\n\n")
		}
		history.WriteString(reversed[i].label)
		history.WriteString(":\n")
		history.WriteString(reversed[i].content)
	}
	fmt.Println(history.String())
}
