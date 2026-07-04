import json

def update_tasks():
    with open('agent_tasks.json', 'r') as f:
        data = json.load(f)

    data['tasks'].append({
      "id": "proxy-observability-detect-system-message-dropped-regex-match2",
      "status": "todo",
      "area": "proxy",
      "risk": "low",
      "title": "Add test for regex-based system message extraction",
      "description": "Ensure that if a system message has a specific CWD regex match, the extraction works and CWD is captured properly.",
      "allowed_paths": [
        "internal/proxy/tools_test.go",
        "agent_tasks.json"
      ],
      "acceptance": [
        "A test asserts that CWD is correctly extracted from a system message matching the <cwd> regex."
      ]
    })

    with open('agent_tasks.json', 'w') as f:
        json.dump(data, f, indent=2)

if __name__ == '__main__':
    update_tasks()
