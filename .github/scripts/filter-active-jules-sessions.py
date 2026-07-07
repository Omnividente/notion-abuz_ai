#!/usr/bin/env python3
"""Filter Jules sessions that should actually block next-task dispatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_ACTIVE_STATES = {
    "QUEUED",
    "PLANNING",
    "IN_PROGRESS",
    "AWAITING_PLAN_APPROVAL",
    "AWAITING_USER_FEEDBACK",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as data_file:
        return json.load(data_file)


def load_manifest_statuses(path: Path) -> dict[str, str]:
    data = load_json(path)
    statuses: dict[str, str] = {}
    for task in data.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = task.get("id")
        if isinstance(task_id, str) and task_id:
            statuses[task_id] = str(task.get("status") or "")
    return statuses


def parse_recent_map_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def load_recent_map(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    data = load_json(path)
    if isinstance(data, dict) and "value" in data:
        return parse_recent_map_value(data.get("value"))
    return parse_recent_map_value(data)


def session_id(session: dict[str, Any]) -> str:
    raw = session.get("id")
    if isinstance(raw, str) and raw:
        return raw.split("/")[-1]
    raw = session.get("name")
    if isinstance(raw, str) and raw:
        return raw.split("/")[-1]
    return ""


def session_name(session: dict[str, Any]) -> str:
    raw = session.get("name")
    if isinstance(raw, str) and raw:
        return raw
    raw = session.get("id")
    if isinstance(raw, str) and raw:
        return raw
    return ""


def task_id_for_session(session: dict[str, Any], recent_map: dict[str, Any]) -> str:
    sid = session_id(session)
    entry = recent_map.get(sid)
    if isinstance(entry, dict):
        value = entry.get("task_id")
        return str(value or "")
    if isinstance(entry, str):
        return entry
    return ""


def stopped_task_ids(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def filter_sessions(
    sessions_data: dict[str, Any],
    *,
    source: str,
    active_states: set[str],
    task_statuses: dict[str, str],
    recent_map: dict[str, Any],
    stopped_tasks: set[str],
) -> dict[str, Any]:
    blocking: list[dict[str, str]] = []
    ignored: list[dict[str, str]] = []
    active_total = 0

    for session in sessions_data.get("sessions", []):
        if not isinstance(session, dict):
            continue
        if str((session.get("sourceContext") or {}).get("source") or "") != source:
            continue
        state = str(session.get("state") or "")
        if state not in active_states:
            continue

        active_total += 1
        sid = session_id(session)
        task_id = task_id_for_session(session, recent_map)
        item = {
            "session_id": sid,
            "session_name": session_name(session),
            "state": state,
            "task_id": task_id,
        }

        if task_id:
            status = task_statuses.get(task_id, "")
            if status in {"done", "blocked"}:
                item["reason"] = f"manifest_status:{status}"
                ignored.append(item)
                continue
            if task_id in stopped_tasks:
                item["reason"] = "stopped_autonomous_pr"
                ignored.append(item)
                continue
            item["reason"] = "active_task"
            blocking.append(item)
            continue

        item["reason"] = "unknown_task_id"
        blocking.append(item)

    return {
        "active_total": active_total,
        "blocking_count": len(blocking),
        "ignored_count": len(ignored),
        "blocking_sessions": blocking,
        "ignored_sessions": ignored,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("agent_tasks.json"))
    parser.add_argument("--recent-map", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--stopped-task-ids", default="")
    parser.add_argument(
        "--active-state",
        action="append",
        default=[],
        help="Active Jules state. Defaults to the known active states.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    active_states = set(args.active_state or DEFAULT_ACTIVE_STATES)
    result = filter_sessions(
        load_json(args.sessions),
        source=args.source,
        active_states=active_states,
        task_statuses=load_manifest_statuses(args.manifest),
        recent_map=load_recent_map(args.recent_map),
        stopped_tasks=stopped_task_ids(args.stopped_task_ids),
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["blocking_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
