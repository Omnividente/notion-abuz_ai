# notion-abuz_ai Autonomous Agent Guide

This repository can be improved by Jules/Codex-style autonomous PR agents.
Use `agent_tasks.json` as the machine-readable source of truth.

## Primary Objective

Make the original Claude Code promise reliable: Claude Code must work as an
autonomous coding agent through the RDSH/notion-abuz_ai proxy, using pooled
Notion AI accounts as the upstream capacity layer.

The account pool, quota routing, dashboard, and Notion transport are assumed to
work unless a concrete failing test or live smoke result proves otherwise. The
current focus is the three-layer Claude Code compatibility bridge, because it
can drift into Notion workspace/page/document behavior, refuse tool use, lose
JSON tool-call mode, or fail multi-turn continuation.

Treat these as primary proxy compatibility bugs:

- Notion persona leakage in Claude Code requests.
- Notion workspace/page/document refusals in coding-agent requests.
- Tool calls replaced by prose refusals when Claude Code tools are available.
- Tool results interpreted as Notion content instead of coding-tool output.
- Multi-turn Claude Code loops losing session context or final-answer mode.

## Source Priority

Before changing code, read these files in order:

1. `agent_tasks.json`
2. `docs/jules_autonomous_loop.md`
3. `README.md`
4. `docs/api.md`
5. `docs/configuration.md`
6. Relevant package manifests and local tests

## Project Map

- `cmd/notion-manager/`: server entrypoint.
- `internal/proxy/`: proxy core, API compatibility, accounts, uploads, model mapping, stats.
- `internal/regjob/`: bulk registration jobs.
- `internal/msalogin/`: Microsoft SSO onboarding flow.
- `internal/netutil/`: proxy and network helpers.
- `internal/web/`: embedded dashboard assets.
- `web/`: React + TypeScript + Vite dashboard source.
- `docs/`: API and operating documentation.

## Task Selection

Pick exactly one task per PR.

Default selection rule:

1. Pick the exact requested `task_id` when provided.
2. Otherwise pick the first `todo` task in `agent_tasks.json`.
3. Implement only tasks with risk `low` or `medium` autonomously.
4. For `high` or `critical` tasks, create or refine a human-review task instead of implementing it.

If the todo queue is below `replenishment_policy.minimum_todo_tasks`, add a small batch of low/medium-risk tasks with concrete `allowed_paths` and `acceptance` criteria.

Research and compatibility tasks may add new follow-up `todo` tasks even when
the queue is not below the replenishment threshold. Only do this for concrete
findings from code inspection, offline tests, CI logs, docs gaps, or captured
live smoke results. New tasks must be low/medium risk, non-duplicative,
bounded to one PR, and below `replenishment_policy.max_todo_tasks`.

When selecting or generating new work, prefer Claude Code bridge investigation
and regression coverage. Dashboard, registration, generic config, OpenCode,
OpenAI-compatible, and GitHub workflow tasks are secondary unless they directly
support a reproduced Claude Code bridge failure.

Do not ask the user to choose between implementation approaches for low/medium
tasks. If multiple safe approaches exist, choose the smallest reversible change
that satisfies the selected task's acceptance criteria. If unsure, write focused
tests first and then implement the smallest passing fix.

In unattended mode, do not stop for ordinary implementation, scope, test, docs,
or CI-fix questions. If a possible change belongs to a separate task, exclude it
from the current PR, keep or add a follow-up task, and finish the selected task.
When work is ready for review or finalization, open/finalize the PR instead of
asking whether anything else should be reviewed.
For Claude Code compatibility work, prefer behavior-level research and
regression coverage over matching one observed phrase. If a new class of Notion
persona leakage, tool-loop breakage, or coding-intent loss is found, add a
follow-up task with fixtures/tests/docs acceptance criteria.
Repository variable `JULES_LOOP_ENABLED=false` disables new task dispatches and
unattended monitor continuations.

## Communication Policy

All user-facing Jules communication must be in Russian by default. This includes
session updates, plan explanations, PR titles/bodies, review/final summaries,
and messages sent while waiting or finalizing. Keep file paths, task ids,
commands, API names, code identifiers, and quoted error output in their original
language.

Every substantive Jules update should clearly state:

- `Этап плана`: current phase, such as исследование, тесты, реализация,
  валидация, PR, or ожидание.
- `Что сделано`: concrete completed work.
- `Что дальше`: next planned step.
- `Зачем`: why this work matters for Claude Code bridge reliability.
- `Почему так`: why this approach was chosen.
- `Проверки/риски`: validation run, remaining risk, or exact blocker.

If a task is blocked, explain the blocker in Russian, include the exact failing
command or missing permission when relevant, and propose the smallest safe next
step.

Local helper scripts:

```bash
python3 scripts/rool_cognitive_loop.py --validation manifest
python3 scripts/dedupe_agent_tasks.py agent_tasks.json
```

`rool_cognitive_loop.py` is an Observe-Orient-Decide-Act helper for selecting
and validating one local task. `dedupe_agent_tasks.py` is dry-run by default;
use `--write` only in a task that explicitly permits manifest cleanup.

## Safety Rules

Do not modify or commit:

- Real account JSON files
- `data/**`
- `accounts/**`
- `config.yaml` with local secrets
- `token.txt`
- `pass.txt`
- Logs
- Built binaries
- `.github/workflows/**`, unless the selected task explicitly allows workflow work
- Deployment files, unless the selected task explicitly allows deployment work

Unit tests must not call real Notion, Google, OpenAI, Anthropic, GitHub, or
Microsoft APIs. Use local fakes, fixtures, and mocks.

Live RDSH checks belong in `.github/workflows/rdsh_live_smoke.yml` and may use
the repository secret `RDSH_API_KEY`. Do not print, persist, or copy that secret.

Real-account local integration checks belong only in
`.github/workflows/rdsh_local_live_smoke.yml`. That workflow may use the
protected `live-rdsh` environment secret `LIVE_NOTION_ACCOUNTS_B64` to start the
PR code locally and test it through `127.0.0.1`. Do not move those live checks
into regular Go tests.

## Validation

Run the relevant subset first, then full validation before opening a PR:

```bash
python3 scripts/validate_agent_tasks.py agent_tasks.json
test -z "$(gofmt -l .)"
cd web && npm ci && npm run build
rm -rf internal/web/dist && cp -r web/dist internal/web/dist
go vet ./...
go test ./...
go build -ldflags="-s -w" -o notion-manager ./cmd/notion-manager
```

## PR Rules

- One task id per PR.
- Keep changes inside the task's `allowed_paths`.
- Update `agent_tasks.json` to mark the selected task as `done`.
- Add follow-up tasks for newly discovered bugs or improvements.
- Label autonomous PRs with `jules`.
- Use Russian commit/PR descriptions when practical. Mention the completed task
  id, current plan stage, why the change matters, and validation run.
- Do not include temporary scratch files such as `*.orig`, `*.rej`, `*.diff`,
  `*.patch`, `my_script.go`, `my_test*.go`, or `run_test.go`.
