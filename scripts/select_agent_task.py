"""Select the highest-value autonomous task from agent_tasks.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SAFE_RISKS = {"low", "medium"}
MICRO_KEYWORDS = (
    "add test",
    "add tests",
    "test coverage",
    "edge case",
    "handleframe",
    "missing metadata",
    "missing field",
    "empty payload",
    "trimcitationcontext",
    "malformed json",
    "follow-up",
    "followup",
)
EVIDENCE_TOKENS = (
    "live smoke",
    "local live smoke",
    "artifact",
    "artifacts",
    "transcript",
    "ci failure",
    "reproduced",
    "runtime failure",
    "failing log",
    "offline reproduction",
)
BLOCK_REASON = (
    "micro/test-only task without concrete live smoke, transcript, CI, "
    "or offline reproduction evidence"
)
EXCLUDED_TASK_REASON = "task is already represented by a stopped autonomous PR awaiting review"


@dataclass(frozen=True)
class Selection:
    selected: bool
    task_id: str = ""
    title: str = ""
    score: int = 0
    reason: str = ""
    reason_code: str = ""
    todo_count: int = 0
    eligible_count: int = 0
    rejected_count: int = 0
    rejected: list[dict[str, str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "task_id": self.task_id,
            "title": self.title,
            "score": self.score,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "todo_count": self.todo_count,
            "eligible_count": self.eligible_count,
            "rejected_count": self.rejected_count,
            "rejected": self.rejected or [],
        }


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as manifest_file:
        data = json.load(manifest_file)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be an object")
    return data


def task_text(task: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in ("id", "title", "description", "area"):
        value = task.get(field)
        if isinstance(value, str):
            parts.append(value)
    for field in ("allowed_paths", "acceptance"):
        value = task.get(field)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return "\n".join(parts).lower()


def allowed_risks(risk_ceiling: str) -> set[str]:
    return {"low"} if risk_ceiling == "low" else SAFE_RISKS


def is_evidence_backed(text: str) -> bool:
    return any(token in text for token in EVIDENCE_TOKENS) or bool(
        re.search(r"\b(?:pr|issue)\s*#\d+\b", text, flags=re.IGNORECASE)
    )


def is_low_impact_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return (
        normalized == "agent_tasks.json"
        or normalized.startswith("docs/")
        or normalized.endswith("_test.go")
        or normalized.endswith("/*_test.go")
        or "*_test.go" in normalized
    )


def is_runtime_proxy_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return (
        normalized.startswith("internal/proxy/")
        and normalized.endswith(".go")
        and not normalized.endswith("_test.go")
        and "*_test.go" not in normalized
    )


def is_micro_test_only(task: dict[str, Any]) -> bool:
    if task.get("risk") != "low":
        return False

    paths = [str(path) for path in task.get("allowed_paths", [])]
    if not paths or any(not is_low_impact_path(path) for path in paths):
        return False

    text = task_text(task)
    if not any(keyword in text for keyword in MICRO_KEYWORDS):
        return False

    return not is_evidence_backed(text)


def score_task(task: dict[str, Any], focus: str) -> tuple[int, str]:
    text = task_text(task)
    paths = [str(path) for path in task.get("allowed_paths", [])]
    has_runtime = any(is_runtime_proxy_path(path) for path in paths)
    has_tests = any(is_low_impact_path(path) and "test" in path.lower() for path in paths)
    has_docs = any(str(path).replace("\\", "/").lower().startswith("docs/") for path in paths)
    has_live_smoke = "live smoke" in text or "rdsh_local_live_smoke" in text
    has_artifacts = "artifact" in text or "transcript" in text
    evidence = is_evidence_backed(text)

    score = 0
    reasons: list[str] = []

    if task.get("area") == focus:
        score += 20
        reasons.append("focus area match")
    elif focus == "proxy" and task.get("area") == "proxy":
        score += 20
        reasons.append("proxy focus")

    if has_live_smoke or has_artifacts:
        score += 90
        reasons.append("live-smoke/artifact theme")
    if has_runtime:
        score += 80
        reasons.append("runtime proxy change")
    if has_runtime and has_tests:
        score += 25
        reasons.append("runtime plus tests")
    if has_runtime and has_docs:
        score += 15
        reasons.append("runtime plus docs")
    if "runtime" in text or "reproduced" in text:
        score += 25
        reasons.append("runtime/reproduced language")
    if evidence and not has_runtime:
        score += 20
        reasons.append("evidence-backed non-runtime task")
    if task.get("risk") == "medium":
        score += 10
        reasons.append("medium-risk operational scope")
    if all(is_low_impact_path(path) for path in paths):
        score -= 20
        reasons.append("low-impact path set")

    return score, ", ".join(reasons) or "eligible task"


def select_task(
    data: dict[str, Any],
    *,
    risk_ceiling: str,
    focus: str,
    task_id: str | None = None,
    exclude_task_ids: set[str] | None = None,
) -> Selection:
    risks = allowed_risks(risk_ceiling)
    excluded = exclude_task_ids or set()
    tasks = [task for task in data.get("tasks", []) if isinstance(task, dict)]
    todo_tasks = [task for task in tasks if task.get("status") == "todo"]
    todo_count = len(todo_tasks)
    rejected: list[dict[str, str]] = []

    if task_id:
        for task in tasks:
            if task.get("id") != task_id:
                continue
            if task_id in excluded:
                raise ValueError(f"task {task_id!r} is excluded: {EXCLUDED_TASK_REASON}")
            if task.get("status") != "todo":
                raise ValueError(f"task {task_id!r} has status {task.get('status')!r}, expected 'todo'")
            if task.get("risk") not in risks:
                raise ValueError(f"task {task_id!r} risk {task.get('risk')!r} exceeds ceiling {risk_ceiling!r}")
            return Selection(
                selected=True,
                task_id=str(task.get("id", "")),
                title=str(task.get("title", "")),
                score=1000,
                reason="exact task id requested",
                reason_code="exact_task_id_requested",
                todo_count=todo_count,
                eligible_count=1,
                rejected_count=0,
                rejected=rejected,
            )
        raise ValueError(f"task {task_id!r} was not found")

    best: tuple[int, int, dict[str, Any], str] | None = None
    eligible_count = 0
    for index, task in enumerate(tasks):
        if task.get("status") != "todo" or task.get("risk") not in risks:
            continue
        current_task_id = str(task.get("id", ""))
        if current_task_id in excluded:
            rejected.append({"task_id": current_task_id, "reason": EXCLUDED_TASK_REASON})
            continue
        if is_micro_test_only(task):
            rejected.append({"task_id": current_task_id, "reason": BLOCK_REASON})
            continue

        score, reason = score_task(task, focus)
        eligible_count += 1
        candidate = (score, -index, task, reason)
        if best is None or candidate > best:
            best = candidate

    if best is None:
        if todo_count == 0:
            reason = "no todo tasks are available"
            reason_code = "no_todo_tasks"
        elif eligible_count == 0:
            reason = "no eligible todo task matched the risk ceiling and micro-task policy"
            reason_code = "no_eligible_autonomous_task"
        else:
            reason = "no eligible todo task selected"
            reason_code = "no_eligible_autonomous_task"
        return Selection(
            selected=False,
            reason=reason,
            reason_code=reason_code,
            todo_count=todo_count,
            eligible_count=eligible_count,
            rejected_count=len(rejected),
            rejected=rejected,
        )

    score, _neg_index, task, reason = best
    return Selection(
        selected=True,
        task_id=str(task.get("id", "")),
        title=str(task.get("title", "")),
        score=score,
        reason=reason,
        reason_code="selected",
        todo_count=todo_count,
        eligible_count=eligible_count,
        rejected_count=len(rejected),
        rejected=rejected,
    )


def print_selection(selection: Selection, json_output: bool) -> None:
    if json_output:
        print(json.dumps(selection.to_dict(), ensure_ascii=False, indent=2))
        return

    if not selection.selected:
        print(f"No task selected: {selection.reason}")
        for item in selection.rejected or []:
            print(f"Rejected {item['task_id']}: {item['reason']}")
        return

    print(f"Selected task: {selection.task_id}")
    print(f"Title: {selection.title}")
    print(f"Score: {selection.score}")
    print(f"Reason: {selection.reason}")
    for item in selection.rejected or []:
        print(f"Rejected {item['task_id']}: {item['reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="agent_tasks.json", type=Path)
    parser.add_argument("--risk-ceiling", choices=["low", "medium"], default="medium")
    parser.add_argument("--focus", default="proxy")
    parser.add_argument("--task-id", default="")
    parser.add_argument(
        "--exclude-task-id",
        action="append",
        default=[],
        help="task id to skip because an existing stopped autonomous PR already represents it",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable selection JSON")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        selection = select_task(
            manifest,
            risk_ceiling=args.risk_ceiling,
            focus=args.focus,
            task_id=args.task_id.strip() or None,
            exclude_task_ids={item.strip() for item in args.exclude_task_id if item.strip()},
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if args.json:
            print(json.dumps({"selected": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print_selection(selection, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
