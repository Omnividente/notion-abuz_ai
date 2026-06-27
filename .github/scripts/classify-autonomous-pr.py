#!/usr/bin/env python3
import json
import os


with open("agent_tasks.json", "r", encoding="utf-8") as f:
    task_ids = [task["id"] for task in json.load(f).get("tasks", [])]

labels = set(json.loads(os.environ.get("PR_LABELS_JSON", "[]")))
head_ref = os.environ.get("PR_HEAD_REF", "")
head_repo = os.environ.get("PR_HEAD_REPO", "")
user = os.environ.get("PR_USER", "")
repo = os.environ.get("GITHUB_REPOSITORY", "")
title = os.environ.get("PR_TITLE", "")
body = os.environ.get("PR_BODY", "")
jules_body_markers = (
    "PR created automatically by Jules",
    "jules.google.com/task",
)

is_autonomous = (
    user == "google-jules[bot]"
    or "jules" in labels
    or any(marker in body for marker in jules_body_markers)
    or (
        head_repo == repo
        and (
            head_ref.startswith(("jules-", "jules/"))
            or any(
                head_ref == task_id
                or head_ref.startswith(f"{task_id}-")
                or task_id in title
                or task_id in body
                for task_id in task_ids
            )
        )
    )
)

print("true" if is_autonomous else "false")
