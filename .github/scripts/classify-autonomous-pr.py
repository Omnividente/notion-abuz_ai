#!/usr/bin/env python3
import json
import os


with open("agent_tasks.json", "r", encoding="utf-8") as f:
    task_ids = [task["id"] for task in json.load(f).get("tasks", [])]

head_ref = os.environ.get("PR_HEAD_REF", "")
head_repo = os.environ.get("PR_HEAD_REPO", "")
user = os.environ.get("PR_USER", "")
repo = os.environ.get("GITHUB_REPOSITORY", "")
body = os.environ.get("PR_BODY", "")
jules_body_markers = (
    "PR created automatically by Jules",
    "jules.google.com/task",
)

user_lower = user.lower()
is_jules_user = user == "google-jules[bot]" or (
    "jules" in user_lower and user_lower.endswith("[bot]")
)
has_jules_body_marker = any(marker in body for marker in jules_body_markers)
head_matches_task = any(
    head_ref == task_id or head_ref.startswith(f"{task_id}-")
    for task_id in task_ids
)
has_jules_head = (
    head_repo == repo
    and (
        head_ref.startswith(("jules-", "jules/"))
        or head_matches_task
    )
)

is_autonomous = (
    is_jules_user
    or has_jules_body_marker
    or has_jules_head
)

print("true" if is_autonomous else "false")
