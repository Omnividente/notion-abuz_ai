#!/usr/bin/env python3
import json
import os
import sys


if len(sys.argv) != 2:
    print("usage: count-autonomous-prs.py <open-prs.json>", file=sys.stderr)
    sys.exit(2)

with open("agent_tasks.json", "r", encoding="utf-8") as f:
    task_ids = [task["id"] for task in json.load(f).get("tasks", [])]

with open(sys.argv[1], "r", encoding="utf-8") as f:
    pulls = json.load(f)

repo = os.environ["GITHUB_REPOSITORY"]
count = 0
stop_labels = {"human-review", "no-automerge", "stop-loop"}
for pr in pulls:
    labels = {
        str(label.get("name", ""))
        for label in pr.get("labels", [])
        if isinstance(label, dict) and label.get("name")
    }
    if labels & stop_labels:
        continue

    head = pr.get("head", {})
    head_ref = head.get("ref", "")
    head_repo = (head.get("repo") or {}).get("full_name", "")
    user = str((pr.get("user") or {}).get("login") or "")
    body = pr.get("body") or ""
    user_lower = user.lower()
    if user == "google-jules[bot]" or ("jules" in user_lower and user_lower.endswith("[bot]")):
        count += 1
        continue
    if "PR created automatically by Jules" in body or "jules.google.com/task" in body:
        count += 1
        continue
    if head_repo != repo:
        continue
    if head_ref.startswith(("jules-", "jules/")):
        count += 1
        continue
    if any(head_ref == task_id or head_ref.startswith(f"{task_id}-") for task_id in task_ids):
        count += 1

print(count)
