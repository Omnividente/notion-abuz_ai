#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone


TOKEN = "AUTONOMOUS_CONTINUE_TOKEN"


def parse_epoch(value):
    if not value:
        return 0
    try:
        normalized = value.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp())
    except ValueError:
        return 0


if len(sys.argv) != 2:
    print("usage: summarize-jules-activities.py <activities.json>", file=sys.stderr)
    sys.exit(2)

with open(sys.argv[1], "r", encoding="utf-8") as f:
    activities = json.load(f).get("activities", [])

latest_agent_epoch = 0
latest_user_epoch = 0
latest_token_epoch = 0

for activity in activities:
    originator = str(activity.get("originator", "")).lower()
    is_user = "user" in originator
    epoch = parse_epoch(activity.get("createTime"))
    blob = json.dumps(activity, ensure_ascii=False)

    if is_user:
        latest_user_epoch = max(latest_user_epoch, epoch)
        if TOKEN in blob:
            latest_token_epoch = max(latest_token_epoch, epoch)
    else:
        latest_agent_epoch = max(latest_agent_epoch, epoch)

print(f"{latest_agent_epoch}\t{latest_user_epoch}\t{latest_token_epoch}")
