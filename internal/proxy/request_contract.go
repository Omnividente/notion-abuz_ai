package proxy

import (
	"fmt"
	"strings"
)

// ResolveRequestMode maps the public mode contract to Notion's read-only flag.
// Unknown or conflicting values fail explicitly instead of being silently dropped.
func ResolveRequestMode(model, mode string, defaultAsk bool) (string, bool, error) {
	cleanModel, suffixAsk := StripAskModeSuffix(strings.TrimSpace(model))
	cleanMode := strings.ToLower(strings.TrimSpace(mode))
	switch cleanMode {
	case "", "auto":
		return cleanModel, suffixAsk || defaultAsk, nil
	case "ask", "read_only", "readonly":
		return cleanModel, true, nil
	case "chat", "agent":
		if suffixAsk {
			return "", false, fmt.Errorf(
				"mode %q conflicts with model suffix -ask; request was not downgraded",
				mode,
			)
		}
		return cleanModel, false, nil
	default:
		return "", false, fmt.Errorf(
			"unsupported mode %q; supported values are auto, ask, read_only, chat, agent",
			mode,
		)
	}
}

// ResolveReasoningEffortAlias requires an explicit configured alias whenever a
// client requests reasoning effort. This prevents invisible loss of the option.
func ResolveReasoningEffortAlias(model, effort string) (string, error) {
	cleanModel := strings.TrimSpace(model)
	cleanEffort := strings.ToLower(strings.TrimSpace(effort))
	if cleanEffort == "" {
		return cleanModel, nil
	}
	switch cleanEffort {
	case "none", "low", "medium", "high", "xhigh":
	default:
		return "", fmt.Errorf(
			"unsupported reasoning_effort %q; request was not downgraded",
			effort,
		)
	}
	alias := cleanModel + "-" + cleanEffort
	if _, ok := SnapshotModelMap()[alias]; !ok {
		return "", fmt.Errorf(
			"reasoning_effort %q is not configured for model %q: add model_map alias %q; request was not downgraded",
			effort,
			cleanModel,
			alias,
		)
	}
	return alias, nil
}

// ShouldDisableAgentFallback resolves the transport route from the request
// contract. Language and response text are intentionally absent from inputs.
func ShouldDisableAgentFallback(
	configDefault bool,
	isCodingAssistant bool,
	hasClientTools bool,
	mode string,
) bool {
	if isCodingAssistant {
		RecordRequestContractMetric("coding_assistant")
	} else {
		RecordRequestContractMetric("normal")
	}
	switch strings.ToLower(strings.TrimSpace(mode)) {
	case "agent":
		return false
	case "ask", "read_only", "readonly", "chat":
		return true
	}
	return configDefault || isCodingAssistant || hasClientTools
}
