package proxy

import "strings"

// Helper function to extract context loss metric key for labels
func resolveClipContextLossReason(label string) string {
	if label == "system" {
		return "system_instruction_truncated"
	} else if label == "User (latest)" {
		return "latest_user_message_truncated"
	} else if strings.HasPrefix(label, "Tool") {
		return "tool_result_truncated"
	}
	return "history_entry_truncated"
}
