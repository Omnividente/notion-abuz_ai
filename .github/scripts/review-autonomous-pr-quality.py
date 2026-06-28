#!/usr/bin/env python3
"""Review autonomous Jules PRs for result quality before automerge."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


OPERATIONAL_KEYWORDS = (
    "runtime",
    "bridge decision",
    "observability",
    "logging",
    "log ",
    "logs ",
    "logged",
    "live smoke",
    "diagnostic",
    "diagnostics",
    "artifact",
    "artifacts",
    "compatibility",
    "notion persona",
    "tool-call",
    "workspace reframing",
    "transcript",
    "session",
    "final-answer",
    "json tool-call",
)

OBSERVABILITY_KEYWORDS = (
    "bridge decision",
    "observability",
    "logging",
    "logged",
    "diagnostic",
    "diagnostics",
    "workspace reframing",
    "notion persona",
    "tool-call refusal",
)

DIRECT_OBSERVABILITY_DIFF_MARKERS = (
    "[bridge] decision",
    "decision:",
    "bridge decision",
    "logger",
    "logf",
    "slog",
    "zap.",
    "bytes.buffer",
    "capture",
    "captured",
    "stderr",
    "stdout",
)

COMPROMISE_PHRASES = (
    "сложно мок",
    "вместо этого",
    "не удалось",
    "не получилось",
    "requires complex mocking",
    "complex mocking",
    "instead",
    "unable to",
    "could not",
    "not possible",
    "left as follow-up",
    "follow-up task",
    "separate task",
)


@dataclass
class ChangedTask:
    task_id: str
    before_status: str
    after_status: str
    task: dict[str, Any]


@dataclass
class QualityDecision:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    blocked_task_ids: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    new_task_ids: list[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "task_ids": self.task_ids,
            "blocked_task_ids": self.blocked_task_ids,
            "changed_files": self.changed_files,
            "new_task_ids": self.new_task_ids,
            "recommendation": self.recommendation,
        }


class QualityInputError(RuntimeError):
    """Raised when the quality gate cannot inspect the PR."""


def run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        command = "git " + " ".join(args)
        raise QualityInputError(f"{command} failed: {stderr}") from exc
    return result.stdout


def load_manifest_from_ref(ref: str, path: str) -> dict[str, Any]:
    raw = run_git(["show", f"{ref}:{path}"])
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise QualityInputError(f"{path} at {ref} is not a JSON object")
    return data


def changed_files_between(base: str, head: str) -> list[str]:
    raw = run_git(["diff", "--name-only", base, head])
    return [line.strip() for line in raw.splitlines() if line.strip()]


def diff_text_between(base: str, head: str) -> str:
    return run_git(["diff", "--unified=0", base, head])


def diff_numstat_between(base: str, head: str) -> dict[str, tuple[int, int]]:
    raw = run_git(["diff", "--numstat", base, head])
    result: dict[str, tuple[int, int]] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw, path = parts[0], parts[1], parts[2]
        if added_raw == "-" or deleted_raw == "-":
            result[path] = (0, 0)
            continue
        result[path] = (int(added_raw), int(deleted_raw))
    return result


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").lower()


def is_manifest_path(path: str) -> bool:
    return normalize_path(path) == "agent_tasks.json"


def is_test_path(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized.endswith("_test.go") or normalized.endswith(".test.ts") or normalized.endswith(".test.tsx")


def is_doc_path(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized.startswith("docs/") or normalized in {"readme.md", "agents.md"} or normalized.endswith(".md")


def is_runtime_or_script_path(path: str) -> bool:
    normalized = normalize_path(path)
    if is_manifest_path(normalized) or is_test_path(normalized) or is_doc_path(normalized):
        return False
    return (
        normalized.endswith(".go")
        or normalized.startswith(".github/scripts/")
        or normalized.startswith("scripts/")
        or normalized.startswith("web/")
        or normalized.endswith(".sh")
        or normalized.endswith(".py")
    )


def only_tests_docs_manifest(changed_files: list[str]) -> bool:
    return bool(changed_files) and all(
        is_manifest_path(path) or is_test_path(path) or is_doc_path(path)
        for path in changed_files
    )


def only_tests_manifest(changed_files: list[str]) -> bool:
    return bool(changed_files) and all(is_manifest_path(path) or is_test_path(path) for path in changed_files)


def non_manifest_files(changed_files: list[str]) -> list[str]:
    return [path for path in changed_files if not is_manifest_path(path)]


def task_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = manifest.get("tasks", [])
    if not isinstance(tasks, list):
        raise QualityInputError("agent_tasks.json tasks must be an array")
    result: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if isinstance(task, dict) and isinstance(task.get("id"), str):
            result[task["id"]] = task
    return result


def task_goal_text(task: dict[str, Any]) -> str:
    parts: list[str] = []
    for field_name in ("title", "description"):
        value = task.get(field_name)
        if isinstance(value, str):
            parts.append(value)
    acceptance = task.get("acceptance")
    if isinstance(acceptance, list):
        parts.extend(str(item) for item in acceptance)
    return "\n".join(parts).lower()


def status_changes(
    before_manifest: dict[str, Any],
    after_manifest: dict[str, Any],
    target_status: str,
) -> list[ChangedTask]:
    before = task_map(before_manifest)
    after = task_map(after_manifest)
    changes: list[ChangedTask] = []
    for task_id, after_task in after.items():
        before_status = str((before.get(task_id) or {}).get("status", "missing"))
        after_status = str(after_task.get("status", ""))
        if before_status != target_status and after_status == target_status:
            changes.append(
                ChangedTask(
                    task_id=task_id,
                    before_status=before_status,
                    after_status=after_status,
                    task=after_task,
                )
            )
    return changes


def new_task_ids(before_manifest: dict[str, Any], after_manifest: dict[str, Any]) -> list[str]:
    before_ids = set(task_map(before_manifest))
    after_ids = set(task_map(after_manifest))
    return sorted(after_ids - before_ids)


def is_operational_task(task: dict[str, Any]) -> bool:
    text = task_goal_text(task)
    return any(keyword in text for keyword in OPERATIONAL_KEYWORDS)


def requires_observability_proof(task: dict[str, Any]) -> bool:
    text = task_goal_text(task)
    return any(keyword in text for keyword in OBSERVABILITY_KEYWORDS)


def diff_has_direct_observability_assertion(diff_text: str) -> bool:
    lower = diff_text.lower()
    return any(marker in lower for marker in DIRECT_OBSERVABILITY_DIFF_MARKERS)


def body_has_compromise(pr_title: str, pr_body: str) -> bool:
    text = f"{pr_title}\n{pr_body}".lower()
    return any(phrase in text for phrase in COMPROMISE_PHRASES)


def changed_line_count(numstat: dict[str, tuple[int, int]], changed_files: list[str]) -> int:
    total = 0
    for path in changed_files:
        if is_manifest_path(path):
            continue
        added, deleted = numstat.get(path, (0, 0))
        total += added + deleted
    return total


def evaluate_quality(
    *,
    before_manifest: dict[str, Any],
    after_manifest: dict[str, Any],
    changed_files: list[str],
    diff_text: str,
    numstat: dict[str, tuple[int, int]],
    pr_title: str,
    pr_body: str,
) -> QualityDecision:
    done_changes = status_changes(before_manifest, after_manifest, "done")
    blocked_changes = status_changes(before_manifest, after_manifest, "blocked")
    added_tasks = new_task_ids(before_manifest, after_manifest)

    reasons: list[str] = []
    warnings: list[str] = []
    done_ids = [change.task_id for change in done_changes]
    blocked_ids = [change.task_id for change in blocked_changes]
    non_manifest = non_manifest_files(changed_files)
    has_runtime_or_script = any(is_runtime_or_script_path(path) for path in non_manifest)
    has_direct_observability_assertion = diff_has_direct_observability_assertion(diff_text)
    compromise = body_has_compromise(pr_title, pr_body)
    changed_lines = changed_line_count(numstat, changed_files)

    if len(done_changes) > 1:
        reasons.append(
            "More than one task was marked done; autonomous PRs must complete one task id per PR."
        )

    if not done_changes and not blocked_changes:
        reasons.append(
            "No task moved to done or blocked in agent_tasks.json; autonomous PR has no durable task state update."
        )

    for change in blocked_changes:
        blocked_reason = str(change.task.get("blocked_reason", "")).strip()
        if not blocked_reason:
            reasons.append(f"Task {change.task_id} moved to blocked without blocked_reason.")

    for change in done_changes:
        task = change.task
        operational = is_operational_task(task)
        observability = requires_observability_proof(task)

        if operational and only_tests_manifest(changed_files):
            reasons.append(
                f"Task {change.task_id} is operational/diagnostic but the PR changed only tests and agent_tasks.json."
            )

        if observability and not has_runtime_or_script and not has_direct_observability_assertion:
            reasons.append(
                f"Task {change.task_id} requires observability/logging proof, but the diff has no runtime/script change and no direct log-capture assertion."
            )

        if operational and compromise and only_tests_docs_manifest(changed_files) and not has_runtime_or_script:
            reasons.append(
                f"Task {change.task_id} was marked done while the PR text describes a compromise or moved core work into a follow-up."
            )

        if operational and added_tasks and only_tests_docs_manifest(changed_files) and not has_runtime_or_script:
            reasons.append(
                f"Task {change.task_id} was marked done while adding follow-up tasks, but the PR only changed tests/docs/manifest."
            )

        if operational and changed_lines <= 6 and not has_runtime_or_script:
            warnings.append(
                f"Task {change.task_id} has a very small non-manifest diff ({changed_lines} changed lines); verify this is not a formal-only completion."
            )

    passed = not reasons
    if passed:
        if blocked_changes and not done_changes:
            recommendation = "Manifest-only block update is acceptable; no merge-quality blocker found."
        else:
            recommendation = "Autonomous PR quality gate passed."
    else:
        recommendation = (
            "Do not merge automatically. Ask Jules/Codex to update the same PR with direct evidence "
            "for the selected task, or block the task with a concrete reason instead of marking it done."
        )

    return QualityDecision(
        passed=passed,
        reasons=reasons,
        warnings=warnings,
        task_ids=done_ids,
        blocked_task_ids=blocked_ids,
        changed_files=changed_files,
        new_task_ids=added_tasks,
        recommendation=recommendation,
    )


def write_github_outputs(path: Path, decision: QualityDecision) -> None:
    summary = "; ".join(decision.reasons or decision.warnings or [decision.recommendation])
    with path.open("a", encoding="utf-8") as output:
        output.write(f"passed={'true' if decision.passed else 'false'}\n")
        output.write(f"summary={summary}\n")


def write_report(path: Path, decision: QualityDecision) -> None:
    lines = [
        "# Autonomous PR quality gate",
        "",
        f"Status: {'passed' if decision.passed else 'failed'}",
        "",
    ]
    if decision.task_ids:
        lines.append("Done task ids:")
        lines.extend(f"- `{task_id}`" for task_id in decision.task_ids)
        lines.append("")
    if decision.blocked_task_ids:
        lines.append("Blocked task ids:")
        lines.extend(f"- `{task_id}`" for task_id in decision.blocked_task_ids)
        lines.append("")
    if decision.reasons:
        lines.append("Blocking reasons:")
        lines.extend(f"- {reason}" for reason in decision.reasons)
        lines.append("")
    if decision.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in decision.warnings)
        lines.append("")
    if decision.new_task_ids:
        lines.append("New task ids:")
        lines.extend(f"- `{task_id}`" for task_id in decision.new_task_ids)
        lines.append("")
    lines.append("Recommendation:")
    lines.append(decision.recommendation)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def read_pr_body(args: argparse.Namespace) -> str:
    if args.pr_body_file:
        return Path(args.pr_body_file).read_text(encoding="utf-8")
    return args.pr_body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base git ref/sha for PR diff")
    parser.add_argument("--head", required=True, help="Head git ref/sha for PR diff")
    parser.add_argument("--manifest", default="agent_tasks.json")
    parser.add_argument("--pr-title", default="")
    parser.add_argument("--pr-body", default="")
    parser.add_argument("--pr-body-file", default="")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        before_manifest = load_manifest_from_ref(args.base, args.manifest)
        after_manifest = load_manifest_from_ref(args.head, args.manifest)
        changed_files = changed_files_between(args.base, args.head)
        diff_text = diff_text_between(args.base, args.head)
        numstat = diff_numstat_between(args.base, args.head)
        decision = evaluate_quality(
            before_manifest=before_manifest,
            after_manifest=after_manifest,
            changed_files=changed_files,
            diff_text=diff_text,
            numstat=numstat,
            pr_title=args.pr_title,
            pr_body=read_pr_body(args),
        )
    except (QualityInputError, json.JSONDecodeError, OSError) as exc:
        decision = QualityDecision(
            passed=False,
            reasons=[f"Quality gate could not inspect this PR: {exc}"],
            recommendation="Do not merge automatically until the quality gate can inspect the PR.",
        )

    if args.report:
        write_report(args.report, decision)

    if args.github_output:
        write_github_outputs(Path(args.github_output), decision)

    if args.json:
        print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    elif decision.passed:
        print(decision.recommendation)
    else:
        for reason in decision.reasons:
            print(f"ERROR: {reason}", file=sys.stderr)
        print(decision.recommendation, file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
