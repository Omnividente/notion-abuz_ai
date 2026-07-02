import json

with open("agent_tasks.json", "r") as f:
    data = json.load(f)

for t in data["tasks"]:
    if t["id"] == "proxy-behavior-anthropic-tool-result-continuation-preservation":
        t["status"] = "done"

new_task = {
  "id": "proxy-behavior-anthropic-multi-turn-tool-results-flattening",
  "title": "Prevent duplicated tool results in Anthropic multi-turn flattened transcript",
  "description": "During legacy collapse mode, if tool results are merged into the previous assistant message AND a continuation message is appended, the LLM receives duplicated tool output. Investigate and fix this duplication in injectToolsIntoMessages.",
  "status": "todo",
  "area": "proxy",
  "risk": "medium",
  "allowed_paths": [
    "internal/proxy/tools.go",
    "internal/proxy/tools_test.go",
    "agent_tasks.json"
  ],
  "acceptance": [
    "The flattening behavior correctly assigns tool results to the prompt without generating identical duplicate text blocks in both user and assistant roles."
  ]
}

data["tasks"].append(new_task)

with open("agent_tasks.json", "w") as f:
    json.dump(data, f, indent=2)
