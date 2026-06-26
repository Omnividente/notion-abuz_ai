"""Find or block duplicate autonomous tasks in agent_tasks.json.

The original Magda-agent script used a project-specific hardcoded duplicate map.
This version is generic for notion-abuz_ai: it compares normalized task titles
and descriptions, then optionally marks duplicate todo tasks as blocked.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


BLOCK_SUFFIX_TEMPLATE = " [blocked: duplicate of task '{task_id}']"
TASK_TEXT_FIELDS = ("title", "description")


@dataclass(frozen=True)
class Duplicate:
    """A duplicate task finding."""

    task_id: str
    duplicate_of: str
    score: float
    reason: str


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a JSON task manifest."""
    with path.open("r", encoding="utf-8") as manifest_file:
        data = json.load(manifest_file)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be an object")
    return data


def normalize_text(value: str) -> str:
    """Normalize text for deterministic duplicate comparison."""
    lowered = value.lower()
    words = re.findall(r"[a-z0-9]+", lowered)
    return " ".join(words)


def task_text(task: dict[str, Any]) -> str:
    """Return the normalized text used for duplicate detection."""
    parts: list[str] = []
    for field in TASK_TEXT_FIELDS:
        value = task.get(field)
        if isinstance(value, str):
            parts.append(value)
    allowed_paths = task.get("allowed_paths")
    if isinstance(allowed_paths, list):
        parts.extend(path for path in allowed_paths if isinstance(path, str))
    return normalize_text(" ".join(parts))


def task_title(task: dict[str, Any]) -> str:
    """Return the normalized title for exact title matching."""
    title = task.get("title")
    return normalize_text(title if isinstance(title, str) else "")


def similarity(left: str, right: str) -> float:
    """Return a stable similarity score in the range 0..1."""
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def find_duplicates(data: dict[str, Any], min_score: float) -> list[Duplicate]:
    """Find duplicate todo tasks against done/blocked tasks and earlier todos."""
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("manifest tasks must be an array")

    canonical: list[tuple[str, str, str, str]] = []
    duplicates: list[Duplicate] = []

    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = task.get("id")
        status = task.get("status")
        if not isinstance(task_id, str) or not isinstance(status, str):
            continue

        title = task_title(task)
        text = task_text(task)

        if status != "todo":
            if status in {"done", "blocked"}:
                canonical.append((task_id, status, title, text))
            continue

        best: Duplicate | None = None
        for other_id, other_status, other_title, other_text in canonical:
            if title and title == other_title:
                candidate = Duplicate(
                    task_id=task_id,
                    duplicate_of=other_id,
                    score=1.0,
                    reason=f"same normalized title as {other_status} task",
                )
            else:
                score = similarity(text, other_text)
                candidate = Duplicate(
                    task_id=task_id,
                    duplicate_of=other_id,
                    score=score,
                    reason=f"similar to {other_status} task",
                )
            if candidate.score >= min_score and (best is None or candidate.score > best.score):
                best = candidate

        if best is not None:
            duplicates.append(best)
        else:
            canonical.append((task_id, status, title, text))

    return duplicates


def block_duplicates(data: dict[str, Any], duplicates: list[Duplicate]) -> int:
    """Mark duplicate todo tasks as blocked and return the number changed."""
    by_id = {duplicate.task_id: duplicate for duplicate in duplicates}
    changed = 0
    tasks = data.get("tasks", [])
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = task.get("id")
        if task.get("status") != "todo" or task_id not in by_id:
            continue

        duplicate = by_id[task_id]
        task["status"] = "blocked"
        suffix = BLOCK_SUFFIX_TEMPLATE.format(task_id=duplicate.duplicate_of)
        description = task.get("description")
        if isinstance(description, str) and suffix not in description:
            task["description"] = description.rstrip() + suffix
        changed += 1
    return changed


def write_manifest(path: Path, data: dict[str, Any]) -> None:
    """Write a manifest with stable JSON formatting."""
    with path.open("w", encoding="utf-8") as manifest_file:
        json.dump(data, manifest_file, indent=2, ensure_ascii=False)
        manifest_file.write("\n")


def main(argv: list[str] | None = None) -> int:
    """Run the duplicate task detector."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", default="agent_tasks.json")
    parser.add_argument("--write", action="store_true", help="write blocked statuses back to the manifest")
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.92,
        help="minimum normalized similarity score for fuzzy duplicates",
    )
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args(argv)

    path = Path(args.manifest)
    data = load_manifest(path)
    duplicates = find_duplicates(data, min_score=args.min_score)

    if args.json:
        print(json.dumps([duplicate.__dict__ for duplicate in duplicates], indent=2))
    else:
        if not duplicates:
            print("No duplicate todo tasks found.")
        for duplicate in duplicates:
            print(
                f"{duplicate.task_id} duplicates {duplicate.duplicate_of} "
                f"(score={duplicate.score:.3f}, reason={duplicate.reason})"
            )

    if args.write:
        changed = block_duplicates(data, duplicates)
        write_manifest(path, data)
        print(f"Blocked {changed} duplicate todo task(s).")
    else:
        print("Dry run only. Re-run with --write to update the manifest.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
