"""Select the highest-value autonomous task from agent_tasks.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RISK_ORDER = ("low", "medium", "high")
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
    "rdsh local live smoke",
    "rdsh_local_live_smoke",
    "artifact",
    "artifacts",
    "transcript",
    "ci failure",
    "reproduced",
    "runtime failure",
    "failing log",
    "offline reproduction",
    "claude code",
    "tool-call",
    "tool call",
    "notion persona",
    "notion ai",
    "session recovery",
    "json tool-call",
    "api failure",
    "search failure",
    "incomplete context",
)
NEGATED_EVIDENCE_PATTERNS = (
    "without reproduced",
    "without a reproduced",
    "without concrete evidence",
    "without live smoke",
    "without transcript",
    "without ci failure",
    "without offline reproduction",
    "no reproduced",
    "no concrete evidence",
    "no live smoke",
    "no transcript",
    "no ci failure",
    "no offline reproduction",
    "not evidence-backed",
)
BLOCK_REASON = (
    "micro/test-only task without concrete live smoke, transcript, CI, "
    "or offline reproduction evidence"
)
HIGH_RISK_EVIDENCE_REASON = (
    "high-risk task without concrete live smoke, transcript, CI, offline reproduction, "
    "or Claude Code bridge evidence"
)
HIGH_RISK_SCOPE_REASON = (
    "high-risk task is not bounded to implementation paths plus focused tests/docs/manifest"
)
HIGH_RISK_SENSITIVE_PATH_REASON = (
    "high-risk task touches secrets, account data, deployment/runtime data, local config, or token files"
)
SENSITIVE_HIGH_PATH_PARTS = (
    "/secrets/",
    "/accounts/",
    "/data/",
    "/deploy/",
    "/deployment/",
)
SENSITIVE_HIGH_PATH_NAMES = {
    ".env",
    "config.yaml",
    "token.txt",
    "pass.txt",
}


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
    if risk_ceiling not in RISK_ORDER:
        raise ValueError(f"unknown risk ceiling {risk_ceiling!r}")
    ceiling_index = RISK_ORDER.index(risk_ceiling)
    return set(RISK_ORDER[: ceiling_index + 1])


def is_evidence_backed(text: str) -> bool:
    if any(pattern in text for pattern in NEGATED_EVIDENCE_PATTERNS):
        return False
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


def is_script_or_workflow_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return (
        normalized.startswith("scripts/")
        or normalized.startswith(".github/scripts/")
        or normalized.startswith(".github/workflows/")
        or normalized.endswith(".sh")
        or normalized.endswith(".py")
        or normalized.endswith(".yml")
        or normalized.endswith(".yaml")
    )


def is_implementation_path(path: str) -> bool:
    return (
        is_runtime_proxy_path(path)
        or is_script_or_workflow_path(path)
        or (
            not is_low_impact_path(path)
            and path.replace("\\", "/").lower() != "agent_tasks.json"
        )
    )


def is_sensitive_high_risk_path(path: str) -> bool:
    normalized = "/" + path.replace("\\", "/").lower().lstrip("/")
    basename = normalized.rsplit("/", 1)[-1]
    if basename in SENSITIVE_HIGH_PATH_NAMES or basename.endswith(".log"):
        return True
    return any(part in normalized for part in SENSITIVE_HIGH_PATH_PARTS)


def high_risk_guard_reason(task: dict[str, Any]) -> str:
    if task.get("risk") != "high":
        return ""

    paths = [str(path) for path in task.get("allowed_paths", [])]
    if not paths or not any(is_implementation_path(path) for path in paths):
        return HIGH_RISK_SCOPE_REASON
    if any(is_sensitive_high_risk_path(path) for path in paths):
        return HIGH_RISK_SENSITIVE_PATH_REASON
    if not is_evidence_backed(task_text(task)):
        return HIGH_RISK_EVIDENCE_REASON
    return ""


def task_rejection_reason(task: dict[str, Any], risk_ceiling: str) -> str:
    risk = str(task.get("risk") or "")
    risks = allowed_risks(risk_ceiling)
    if risk not in risks:
        return f"task {task.get('id')!r} risk {risk!r} exceeds ceiling {risk_ceiling!r}"
    return high_risk_guard_reason(task)


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
    if task.get("risk") == "high":
        score += 15
        reasons.append("guarded high-risk evidence-backed scope")
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
) -> Selection:
    risks = allowed_risks(risk_ceiling)
    tasks = [task for task in data.get("tasks", []) if isinstance(task, dict)]
    todo_tasks = [task for task in tasks if task.get("status") == "todo"]
    todo_count = len(todo_tasks)
    rejected: list[dict[str, str]] = []

    if task_id:
        for task in tasks:
            if task.get("id") != task_id:
                continue
            if task.get("status") != "todo":
                raise ValueError(f"task {task_id!r} has status {task.get('status')!r}, expected 'todo'")
            rejection_reason = task_rejection_reason(task, risk_ceiling)
            if rejection_reason:
                raise ValueError(rejection_reason)
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
        high_rejection_reason = high_risk_guard_reason(task)
        if high_rejection_reason:
            rejected.append({"task_id": str(task.get("id", "")), "reason": high_rejection_reason})
            continue
        if is_micro_test_only(task):
            rejected.append({"task_id": str(task.get("id", "")), "reason": BLOCK_REASON})
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
            reason = "no eligible todo task matched the risk ceiling, guarded-high policy, and micro-task policy"
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
    parser.add_argument("--risk-ceiling", choices=list(RISK_ORDER), default="medium")
    parser.add_argument("--focus", default="proxy")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--json", action="store_true", help="print machine-readable selection JSON")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        selection = select_task(
            manifest,
            risk_ceiling=args.risk_ceiling,
            focus=args.focus,
            task_id=args.task_id.strip() or None,
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
