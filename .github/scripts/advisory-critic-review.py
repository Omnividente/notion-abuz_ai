#!/usr/bin/env python3
"""Produce a non-blocking critic review for autonomous Jules PRs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CRITIC_TOKEN = "AUTONOMOUS_CRITIC_REVIEW_TOKEN"
COMMENT_MARKER = "<!-- AUTONOMOUS_CRITIC_REVIEW -->"
EVIDENCE_BLOCK_RE = re.compile(
    r"<!--\s*AUTONOMOUS_TASK_EVIDENCE\s*(?P<body>.*?)\s*-->",
    re.IGNORECASE | re.DOTALL,
)
FOLLOWUP_COMPROMISE_RE = re.compile(
    r"(?i)(left as follow-up|follow-up task|separate task|не удалось|не получилось|вместо этого|unable to|could not|instead)"
)
SECRET_LINE_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|authorization|bearer\s+[a-z0-9._-]+)"
)


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass
class EvidenceBlock:
    present: bool = False
    raw_count: int = 0
    task_id: str = ""
    status: str = ""
    blocked_reason: str = ""
    micro_pr_justification: str = ""
    acceptance: list[str] = field(default_factory=list)
    evidence_files: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "raw_count": self.raw_count,
            "task_id": self.task_id,
            "status": self.status,
            "blocked_reason": self.blocked_reason,
            "micro_pr_justification": self.micro_pr_justification,
            "acceptance": self.acceptance,
            "evidence_files": self.evidence_files,
            "checks": self.checks,
        }


def read_text(path: str | Path | None) -> str:
    if not path:
        return ""
    value = Path(path)
    if not value.exists():
        return ""
    return value.read_text(encoding="utf-8", errors="replace")


def read_lines(path: str | Path | None) -> list[str]:
    return [line.strip() for line in read_text(path).splitlines() if line.strip()]


def read_json(path: str | Path | None) -> dict[str, Any]:
    text = read_text(path)
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"_parse_error": "invalid JSON"}
    return (
        data
        if isinstance(data, dict)
        else {"_parse_error": "JSON root is not an object"}
    )


def parse_evidence_block(body: str) -> EvidenceBlock:
    matches = list(EVIDENCE_BLOCK_RE.finditer(body or ""))
    evidence = EvidenceBlock(present=bool(matches), raw_count=len(matches))
    if len(matches) != 1:
        return evidence

    current_section = ""
    for raw_line in matches[0].group("body").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith(":") and not line.startswith("-"):
            current_section = line[:-1].strip().lower().replace("-", "_")
            continue
        if ":" in line and not line.startswith("-"):
            key, value = line.split(":", 1)
            key = key.strip().lower().replace("-", "_")
            value = value.strip()
            if key == "task_id":
                evidence.task_id = value
            elif key == "status":
                evidence.status = value.lower()
            elif key == "blocked_reason":
                evidence.blocked_reason = value
            elif key == "micro_pr_justification":
                evidence.micro_pr_justification = value
            else:
                current_section = key
            continue
        if line.startswith("-"):
            item = line[1:].strip()
            if current_section in {"acceptance", "acceptance_criteria", "criteria"}:
                evidence.acceptance.append(item)
            elif current_section in {"evidence_files", "evidence", "files"}:
                evidence.evidence_files.append(item)
            elif current_section in {"checks", "tests", "validation", "validations"}:
                evidence.checks.append(item)
    return evidence


def is_test_file(path: str) -> bool:
    return (
        path.endswith("_test.go")
        or "/__tests__/" in path
        or path.endswith((".spec.ts", ".test.ts", ".spec.tsx", ".test.tsx"))
    )


def is_doc_file(path: str) -> bool:
    return path.startswith("docs/") or path.endswith((".md", ".mdx"))


def is_manifest_file(path: str) -> bool:
    return path == "agent_tasks.json"


def is_test_doc_or_manifest(path: str) -> bool:
    return is_test_file(path) or is_doc_file(path) or is_manifest_file(path)


def has_runtime_or_control_code(files: list[str]) -> bool:
    return any(not is_test_doc_or_manifest(path) for path in files)


def redact_text(text: str, limit: int = 12000) -> str:
    lines: list[str] = []
    for line in (text or "").splitlines():
        if SECRET_LINE_RE.search(line):
            lines.append("[redacted sensitive-looking line]")
        else:
            lines.append(line)
        if sum(len(item) + 1 for item in lines) >= limit:
            lines.append("[truncated]")
            break
    return "\n".join(lines)


def verdict_from_findings(
    findings: list[Finding], changed_files: list[str], evidence: EvidenceBlock
) -> str:
    if any(finding.severity == "high" for finding in findings):
        return "needs_attention"
    if findings:
        return "needs_attention"
    if not changed_files:
        return "unknown"
    if evidence.present and evidence.status in {"done", "blocked"}:
        return "useful"
    return "unknown"


def evaluate(
    *,
    pr_number: str,
    pr_title: str,
    pr_body: str,
    changed_files: list[str],
    diff_text: str = "",
    quality_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    quality_report = quality_report or {}
    evidence = parse_evidence_block(pr_body)
    findings: list[Finding] = []
    warnings: list[str] = []

    if quality_report.get("_parse_error"):
        warnings.append(
            f"Could not parse deterministic quality report: {quality_report['_parse_error']}"
        )
    elif quality_report and quality_report.get("passed") is False:
        findings.append(
            Finding(
                code="deterministic_quality_gate_failed",
                severity="high",
                message="The deterministic autonomous PR quality gate reported a failure.",
                evidence={"reasons": quality_report.get("reasons", [])[:5]},
            )
        )

    if evidence.raw_count == 0:
        findings.append(
            Finding(
                code="missing_evidence_block",
                severity="high",
                message="The PR body does not expose the machine-readable autonomous evidence block.",
            )
        )
    elif evidence.raw_count > 1:
        findings.append(
            Finding(
                code="multiple_evidence_blocks",
                severity="high",
                message="The PR body contains more than one autonomous evidence block.",
                evidence={"count": evidence.raw_count},
            )
        )

    if evidence.present and not evidence.task_id:
        findings.append(
            Finding(
                code="missing_task_id",
                severity="medium",
                message="The evidence block does not identify the completed task id.",
            )
        )

    if evidence.status == "blocked" and not evidence.blocked_reason:
        findings.append(
            Finding(
                code="blocked_without_reason",
                severity="medium",
                message="The PR marks a task blocked without explaining the missing evidence or blocker.",
            )
        )

    if (
        evidence.status == "done"
        and changed_files
        and all(is_test_doc_or_manifest(path) for path in changed_files)
    ):
        findings.append(
            Finding(
                code="test_doc_manifest_only_done_pr",
                severity="medium",
                message="The PR marks work done while changing only tests, docs, or the task manifest.",
                evidence={"changed_files": changed_files},
            )
        )

    body_and_title = f"{pr_title}\n{pr_body}"
    if FOLLOWUP_COMPROMISE_RE.search(body_and_title):
        findings.append(
            Finding(
                code="followup_may_replace_core_work",
                severity="medium",
                message="The PR text suggests core work may have been moved into a follow-up instead of completed.",
            )
        )

    runtime_files = [
        path for path in changed_files if has_runtime_or_control_code([path])
    ]
    test_files = [path for path in changed_files if is_test_file(path)]
    if runtime_files and not test_files and evidence.status == "done":
        warnings.append(
            "Runtime/control code changed without a changed test file; verify checks prove the behavior another way."
        )

    if evidence.acceptance and evidence.evidence_files:
        missing_evidence_files = sorted(
            set(evidence.evidence_files) - set(changed_files)
        )
        if missing_evidence_files:
            findings.append(
                Finding(
                    code="evidence_references_unchanged_files",
                    severity="medium",
                    message="Evidence block references files not changed by this PR.",
                    evidence={"files": missing_evidence_files[:10]},
                )
            )

    if diff_text and SECRET_LINE_RE.search(diff_text):
        warnings.append(
            "Diff contained sensitive-looking lines; critic prompt/report redacted those lines."
        )

    verdict = verdict_from_findings(findings, changed_files, evidence)
    return {
        "version": 1,
        "critic_token": CRITIC_TOKEN,
        "pr": {
            "number": pr_number,
            "title": pr_title,
        },
        "verdict": verdict,
        "non_blocking": True,
        "should_block_merge": False,
        "should_pause_loop": False,
        "changed_files": changed_files,
        "evidence": evidence.to_dict(),
        "quality_report": {
            "present": bool(quality_report),
            "passed": quality_report.get("passed"),
            "reasons": quality_report.get("reasons", [])[:10]
            if isinstance(quality_report.get("reasons"), list)
            else [],
        },
        "findings": [finding.to_dict() for finding in findings],
        "warnings": warnings,
        "llm": {
            "provider": "none",
            "status": "not_requested",
            "verdict": "",
            "summary": "",
            "findings": [],
        },
    }


def build_critic_prompt(report: dict[str, Any], *, pr_body: str, diff_text: str) -> str:
    summary = {
        "pr": report["pr"],
        "deterministic_verdict": report["verdict"],
        "changed_files": report["changed_files"],
        "evidence": report["evidence"],
        "quality_report": report["quality_report"],
        "findings": report["findings"],
        "warnings": report["warnings"],
    }
    return "\n".join(
        [
            f"{CRITIC_TOKEN}",
            "Ты advisory reviewer автономных Jules/Codex PR.",
            "Задача: оценить, дает ли PR реальную пользу проекту, а не просто формально закрывает пункт.",
            "Не создавай PR, не меняй код, не проси остановить петлю, не требуй блокировки merge.",
            "Верни краткий JSON с полями: verdict(useful|needs_attention|unknown), summary, findings[], recommendations[], confidence.",
            "",
            "Deterministic context:",
            json.dumps(summary, ensure_ascii=False, indent=2),
            "",
            "PR body:",
            redact_text(pr_body, limit=6000),
            "",
            "Diff excerpt:",
            redact_text(diff_text, limit=12000),
        ]
    )


def request_json(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: int
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, dict) else {}


def extract_gemini_text(response: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in (
        response.get("candidates", [])
        if isinstance(response.get("candidates"), list)
        else []
    ):
        content = candidate.get("content") if isinstance(candidate, dict) else {}
        for part in (
            content.get("parts", []) if isinstance(content.get("parts"), list) else []
        ):
            text = part.get("text") if isinstance(part, dict) else ""
            if isinstance(text, str) and text:
                texts.append(text)
    return "\n".join(texts).strip()


def parse_json_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def invoke_gemini(
    report: dict[str, Any],
    prompt: str,
    *,
    model: str,
    api_key: str,
    api_base: str,
    timeout: int,
) -> None:
    report["llm"] = {
        "provider": "gemini",
        "status": "unavailable",
        "model": model,
        "verdict": "",
        "summary": "",
        "findings": [],
    }
    if not api_key or not model:
        report["llm"]["status"] = "skipped_missing_key_or_model"
        return

    quoted_model = urllib.parse.quote(model, safe="")
    url = f"{api_base.rstrip('/')}/v1beta/models/{quoted_model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
        },
    }
    try:
        response = request_json(
            url,
            {
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            body,
            timeout,
        )
        text = extract_gemini_text(response)
        parsed = parse_json_from_text(text)
        report["llm"].update(
            {
                "status": "completed",
                "raw_excerpt": text[:1200],
                "verdict": str(parsed.get("verdict") or ""),
                "summary": str(parsed.get("summary") or ""),
                "findings": parsed.get("findings", [])
                if isinstance(parsed.get("findings"), list)
                else [],
                "recommendations": parsed.get("recommendations", [])
                if isinstance(parsed.get("recommendations"), list)
                else [],
                "confidence": parsed.get("confidence", ""),
            }
        )
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        report["llm"]["status"] = "unavailable"
        report["warnings"].append(
            f"Gemini critic unavailable; advisory workflow remains non-blocking: {type(exc).__name__}."
        )


def invoke_jules(
    report: dict[str, Any],
    prompt: str,
    *,
    repo: str,
    starting_branch: str,
    api_base: str,
    timeout: int,
) -> None:
    report["llm"] = {
        "provider": "jules",
        "status": "unavailable",
        "verdict": "",
        "summary": "",
        "findings": [],
    }
    keys = [
        value
        for value in (
            os.environ.get("JULES_API_KEY"),
            os.environ.get("JULES_API_KEY_BACKUP"),
        )
        if value
    ]
    if not keys:
        report["llm"]["status"] = "skipped_missing_key"
        return

    body = {
        "prompt": prompt,
        "sourceContext": {
            "source": f"sources/github/{repo}",
            "githubRepoContext": {"startingBranch": starting_branch or "master"},
        },
        "requirePlanApproval": False,
        "title": f"{CRITIC_TOKEN} PR #{report['pr']['number']} advisory review",
    }
    for key in keys:
        try:
            response = request_json(
                f"{api_base.rstrip('/')}/sessions",
                {
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": key,
                },
                body,
                timeout,
            )
            session_id = (
                response.get("id") or str(response.get("name") or "").rsplit("/", 1)[-1]
            )
            report["llm"].update(
                {
                    "status": "session_created",
                    "session_id": session_id,
                    "session_name": response.get("name", ""),
                    "web_url": response.get("webUrl") or response.get("url") or "",
                    "summary": "Jules advisory critic session was created. Its result is non-blocking.",
                }
            )
            return
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
        ) as exc:
            last_error = type(exc).__name__
    report["warnings"].append(
        f"Jules critic unavailable; advisory workflow remains non-blocking: {last_error}."
    )


def attach_llm_review(
    report: dict[str, Any], prompt: str, args: argparse.Namespace
) -> None:
    provider = args.llm_provider
    if provider == "auto":
        if os.environ.get("GEMINI_API_KEY") and os.environ.get("GEMINI_CRITIC_MODEL"):
            provider = "gemini"
        else:
            provider = "none"

    if provider == "gemini":
        invoke_gemini(
            report,
            prompt,
            model=os.environ.get("GEMINI_CRITIC_MODEL", ""),
            api_key=os.environ.get("GEMINI_API_KEY", ""),
            api_base=args.gemini_api_base,
            timeout=args.api_timeout,
        )
    elif provider == "jules":
        invoke_jules(
            report,
            prompt,
            repo=args.repo,
            starting_branch=args.starting_branch,
            api_base=args.jules_api_base,
            timeout=args.api_timeout,
        )
    else:
        report["llm"] = {
            "provider": "none",
            "status": "skipped",
            "verdict": "",
            "summary": "",
            "findings": [],
        }


def markdown_list(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- none"]


def write_markdown(report: dict[str, Any]) -> str:
    lines = [
        COMMENT_MARKER,
        "## Advisory Critic Review",
        "",
        f"- Verdict: `{report['verdict']}`",
        "- Non-blocking: `true`",
        "- Pauses loop: `false`",
        f"- Task id: `{report['evidence'].get('task_id') or 'unknown'}`",
        f"- Evidence status: `{report['evidence'].get('status') or 'unknown'}`",
        f"- LLM provider: `{report['llm'].get('provider')}`",
        f"- LLM status: `{report['llm'].get('status')}`",
    ]
    if report["llm"].get("session_id"):
        lines.append(f"- Jules critic session: `{report['llm']['session_id']}`")
    if report["llm"].get("web_url"):
        lines.append(f"- Jules URL: {report['llm']['web_url']}")
    if report["llm"].get("summary"):
        lines.extend(["", "### LLM Summary", "", str(report["llm"]["summary"])])

    lines.extend(["", "### Findings"])
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(
                f"- `{finding['severity']}` `{finding['code']}`: {finding['message']}"
            )
    else:
        lines.append("- none")

    if report["llm"].get("findings"):
        lines.extend(["", "### LLM Findings"])
        for finding in report["llm"]["findings"][:8]:
            lines.append(f"- {finding}")

    lines.extend(["", "### Warnings"])
    lines.extend(markdown_list(report["warnings"]))

    lines.extend(
        [
            "",
            "This review is advisory only. It must not block automerge, pause Jules, or change repository state beyond this comment/report.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(path: str, report: dict[str, Any]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as output_file:
        output_file.write(f"verdict={report['verdict']}\n")
        output_file.write("non_blocking=true\n")
        output_file.write("should_block_merge=false\n")
        output_file.write("should_pause_loop=false\n")
        output_file.write(f"llm_provider={report['llm'].get('provider', '')}\n")
        output_file.write(f"llm_status={report['llm'].get('status', '')}\n")
        output_file.write("should_comment=true\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr-number", default="")
    parser.add_argument("--pr-title", default="")
    parser.add_argument("--pr-body-file", default="")
    parser.add_argument("--changed-files-file", default="")
    parser.add_argument("--diff-file", default="")
    parser.add_argument("--quality-report-json", default="")
    parser.add_argument(
        "--output-json", type=Path, default=Path("advisory-critic-review.json")
    )
    parser.add_argument(
        "--output-md", type=Path, default=Path("advisory-critic-review.md")
    )
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    parser.add_argument(
        "--llm-provider",
        choices=["auto", "none", "gemini", "jules"],
        default=os.environ.get("CRITIC_LLM_PROVIDER", "auto"),
    )
    parser.add_argument(
        "--gemini-api-base",
        default=os.environ.get(
            "GEMINI_API_BASE", "https://generativelanguage.googleapis.com"
        ),
    )
    parser.add_argument(
        "--jules-api-base",
        default=os.environ.get(
            "JULES_API_BASE", "https://jules.googleapis.com/v1alpha"
        ),
    )
    parser.add_argument(
        "--starting-branch", default=os.environ.get("PR_HEAD_REF", "master")
    )
    parser.add_argument(
        "--api-timeout",
        type=int,
        default=int(os.environ.get("CRITIC_API_TIMEOUT_SECONDS", "45")),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        pr_body = read_text(args.pr_body_file)
        diff_text = read_text(args.diff_file)
        report = evaluate(
            pr_number=args.pr_number,
            pr_title=args.pr_title,
            pr_body=pr_body,
            changed_files=read_lines(args.changed_files_file),
            diff_text=diff_text,
            quality_report=read_json(args.quality_report_json),
        )
        prompt = build_critic_prompt(report, pr_body=pr_body, diff_text=diff_text)
        attach_llm_review(report, prompt, args)
        markdown = write_markdown(report)
        args.output_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        args.output_md.write_text(markdown, encoding="utf-8")
        write_outputs(args.github_output, report)
        print(
            json.dumps(
                {"verdict": report["verdict"], "llm": report["llm"]}, ensure_ascii=False
            )
        )
    except Exception as exc:  # noqa: BLE001 - advisory tool must fail open.
        fallback = {
            "version": 1,
            "critic_token": CRITIC_TOKEN,
            "verdict": "unknown",
            "non_blocking": True,
            "should_block_merge": False,
            "should_pause_loop": False,
            "findings": [],
            "warnings": [f"Advisory critic failed open: {type(exc).__name__}."],
            "llm": {"provider": "none", "status": "failed_open"},
        }
        args.output_json.write_text(
            json.dumps(fallback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        args.output_md.write_text(
            write_markdown(
                {
                    **fallback,
                    "pr": {"number": args.pr_number, "title": args.pr_title},
                    "changed_files": [],
                    "evidence": EvidenceBlock().to_dict(),
                    "quality_report": {},
                }
            ),
            encoding="utf-8",
        )
        write_outputs(args.github_output, fallback)
        print(
            f"::warning::Advisory critic failed open: {type(exc).__name__}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
