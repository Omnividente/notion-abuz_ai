import json
import sys

def update_tasks():
    with open('agent_tasks.json', 'r') as f:
        data = json.load(f)

    for task in data['tasks']:
        if task['id'] == 'proxy-observability-detect-system-message-dropped-followup':
            task['status'] = 'done'
            break

    with open('agent_tasks.json', 'w') as f:
        json.dump(data, f, indent=2)

if __name__ == '__main__':
    update_tasks()
