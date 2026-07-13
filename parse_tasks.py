import json
with open('agent_tasks.json', 'r') as f:
    data = json.load(f)
tasks = data.get('tasks', [])
print(f"Total tasks: {len(tasks)}")
todo_tasks = [t for t in tasks if t.get('status') == 'todo']
print(f"Todo tasks: {len(todo_tasks)}")
