#!/usr/bin/env python3
"""Render the repository-owned Jules next-task prompt without GitHub expressions."""

from __future__ import annotations

import argparse
from pathlib import Path


def render(template: str, values: dict[str, str]) -> str:
    rendered = template
    for name, value in values.items():
        rendered = rendered.replace("{{" + name + "}}", value)
    unresolved = sorted(
        part.split("}}", 1)[0]
        for part in rendered.split("{{")[1:]
        if "}}" in part
    )
    if unresolved:
        raise ValueError("unresolved prompt placeholders: " + ", ".join(unresolved))
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    for name in (
        "repository",
        "focus",
        "task-id",
        "selected-task-title",
        "selected-task-score",
        "selected-task-reason",
        "recovery-session-id",
        "recovery-reason",
        "risk-ceiling",
    ):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    values = {
        "REPOSITORY": args.repository,
        "FOCUS": args.focus,
        "TASK_ID": args.task_id,
        "SELECTED_TASK_TITLE": args.selected_task_title,
        "SELECTED_TASK_SCORE": args.selected_task_score,
        "SELECTED_TASK_REASON": args.selected_task_reason,
        "RECOVERY_SESSION_ID": args.recovery_session_id,
        "RECOVERY_REASON": args.recovery_reason,
        "RISK_CEILING": args.risk_ceiling,
    }
    print(render(args.template.read_text(encoding="utf-8"), values), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
