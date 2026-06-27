# Jules Autonomous Improvement Loop

This document defines the autonomous improvement loop for notion-abuz_ai.
The goal is to improve Claude and Claude Code compatibility through the
RDSH/notion-abuz_ai proxy without touching secrets, runtime account data,
deployment state, or broad unrelated code.

## Loop

```text
manual dispatch or pull_request.closed
  -> trigger Jules API session
  -> scheduled unattended monitor continues waiting sessions when needed
  -> Jules reads project rules
  -> Jules selects one safe task
  -> Jules implements a bounded change
  -> Jules updates tests and docs
  -> Jules marks the task done
  -> Jules opens one PR
  -> CI and automerge validate/merge
  -> pull_request.closed starts the next task
```

This is an event-driven loop. The GitHub workflow does not run forever; it
starts a Jules session and exits. The loop continues when Jules opens a PR and
the PR is merged.

`AUTO_CREATE_PR` only tells Jules to create a PR when a patch is ready. It does
not guarantee that Jules will never enter `AWAITING_USER_FEEDBACK`. The
scheduled `Jules Unattended Monitor` workflow handles that state by sending a
standard autonomous continuation message. It also approves unexpected plan
approval waits and can dispatch a new task when the loop is idle.

The monitor runs every five minutes. In scheduled mode it waits at least
15 minutes after the last Jules trigger before starting a replacement session,
so a fast terminal failure does not leave the loop idle overnight.
Open same-repository PR branches named `jules-*` or `jules/*` are treated as
autonomous work even if Jules failed to add the `jules` label itself.
If Jules pushes a ready `jules-*` or `jules/*` branch but does not open a PR, the
monitor opens the PR and labels it `jules`.
If Jules says the work is ready for review/finalization, the monitor replies
with an autonomous continuation instruction instead of waiting for a human.

Set repository variable `JULES_LOOP_ENABLED=false` to stop both new Jules task
dispatches and unattended monitor continuations. If the variable is absent or
set to any other value, the loop is enabled.

## Main Rule

Do not ask the user what to do next when a safe `todo` task exists.
Ask for human review only when the change requires secrets, production access,
deployment changes, workflow permission changes, or high/critical-risk work.

For low/medium-risk tasks, do not ask the user to choose between implementation
approaches. If multiple safe approaches exist, choose the smallest reversible
change that satisfies the selected task's acceptance criteria. If unsure, add
focused tests first and then implement the smallest passing fix.

In unattended mode, ordinary engineering uncertainty must be resolved by the
agent. If a possible step belongs to a separate task, leave it out of the
current PR, keep or add a follow-up task, and finish the selected task.

## Communication Contract

Jules should explain its work in Russian unless quoting code, command output,
API names, task ids, file paths, or external error text. This applies to session
messages, plan summaries, PR titles/bodies, and final summaries.

Every useful progress update should answer:

1. `Этап плана`: where the task is now, for example исследование, тесты,
   реализация, валидация, PR, or ожидание.
2. `Что сделано`: what changed or what evidence was gathered.
3. `Что дальше`: the next concrete action.
4. `Зачем`: why this helps Claude Code work through the Notion-backed proxy.
5. `Почему так`: why this approach is the smallest safe step.
6. `Проверки/риски`: validation status, remaining risk, or exact blocker.

Do not replace engineering work with long status narration. Keep updates short,
but make the project state understandable to a Russian-speaking maintainer.

## Research And Discovery

Some tasks are investigative rather than narrowly prescriptive. For those tasks,
Jules should not limit itself to literal user-provided bullet points. It should
inspect the relevant code, tests, docs, and recent failures, then convert new
findings into durable work items.

Research and test tasks may add new `todo` tasks even when the queue is not
below `replenishment_policy.minimum_todo_tasks`, provided that:

1. The finding is grounded in code, docs, tests, CI logs, or a captured live
   smoke result.
2. The new task is low/medium risk and fits in one PR.
3. The task has concrete `allowed_paths` and acceptance criteria.
4. The task does not require secrets, production data, deployment changes, or
   workflow permission changes.
5. The task is not a duplicate of an existing `todo` or `done` task.
6. The manifest stays below `replenishment_policy.max_todo_tasks`.

If a discovered fix is required to complete the selected task and stays inside
the selected task's `allowed_paths`, Jules may implement it in the current PR.
If it is useful but outside the selected scope, Jules must create a follow-up
task and finish the selected task.

For Claude Code compatibility research, prefer behavior-level findings over
single phrase matching. Useful findings include missing transcript fixtures,
new Notion persona leakage signals, broken tool-result continuations, session
recovery gaps, or loss of coding intent from `CLAUDE.md`, hooks, slash commands,
MCP, or subagent-style prompts.

## Product Goal

Make the original project promise true: Claude Code should operate as a
reliable autonomous coding agent through notion-abuz_ai, while pooled Notion AI
accounts provide the upstream model capacity.

The account pool, quota routing, dashboard, and Notion transport are not the
current investigation target unless a concrete failing test or live smoke result
points there. The current target is the three-layer Claude Code compatibility
bridge and its session-based multi-turn handling.

Treat these as compatibility bugs:

- Notion persona leakage.
- Notion workspace/page/document refusals in coding-assistant requests.
- Claude-style coding prompts answered as if the user is inside Notion.
- Tool calls replaced by prose refusals when coding tools are available.
- Tool results ignored or interpreted as Notion content.
- Multi-turn Claude Code loops that lose JSON tool-call mode, session context,
  or final-answer mode.
- Model drift caused by lossy Anthropic-compatible request translation.

## Task Sources

Priority:

1. `agent_tasks.json`
2. Failing CI from the current PR
3. `AGENTS.md`
4. `README.md`
5. `docs/api.md`
6. `docs/configuration.md`
7. TODO/FIXME comments
8. Repeated runtime or test failures visible in the repository

## Local Helper Scripts

Two helper scripts are available for local agent work:

```bash
python3 scripts/rool_cognitive_loop.py --validation manifest
python3 scripts/dedupe_agent_tasks.py agent_tasks.json
```

`rool_cognitive_loop.py` implements a small Observe-Orient-Decide-Act cycle for
selecting the first safe todo task, printing its allowed paths, and optionally
running validation. It does not call Jules or any external API.

`dedupe_agent_tasks.py` detects duplicate todo tasks. It is dry-run by default.
Use `--write` only when the selected task allows manifest cleanup.

## Replenishment Policy

Keep at least `replenishment_policy.minimum_todo_tasks` tasks with status
`todo`.

When the queue is low or research discovers new bounded follow-up work:

1. Prefer Claude Code bridge stabilization, transcript fixtures, and regression
   coverage over feature expansion.
2. Generate low/medium-risk tasks only.
3. Each new task must include:
   - stable `id`
   - `area`
   - `risk`
   - `title`
   - `description`
   - `allowed_paths`
   - `acceptance`
4. Do not duplicate done or existing todo tasks.
5. Keep each task small enough for one PR.
6. Do not add speculative tasks without a concrete finding or a documented gap.

## Proxy Priorities

Prefer improvements in this order:

1. Reproducing and classifying Claude Code bridge failures.
2. Notion persona leakage prevention in Claude Code requests.
3. Anthropic Messages tool-call generation, parsing, streaming, and
   continuation.
4. Multi-turn session fingerprinting, retry, recovery, and final-answer mode.
5. Golden transcript fixtures for realistic read/edit/test/finalize loops.
6. Account pool, quota, and failover behavior only when a Claude Code bridge
   failure proves it is involved.
7. OpenAI/OpenCode compatibility only when it supports Claude Code reliability
   or shares the same bridge defect.
8. Dashboard, registration, generic config, and workflow automation only when
   needed for observability or safe operation of the Claude Code bridge work.

For `claude-code-notion-persona-leakage-regression`, prefer a narrow
coding-assistant detection helper plus a short proxy compatibility instruction.
Do not preserve the full Claude Code system prompt in tool-heavy requests.

## Protected Files

Autonomous PRs must not edit:

- `.github/workflows/**`
- `data/**`
- `accounts/**`
- `config.yaml`
- `token.txt`
- `pass.txt`
- `*.log`
- built binaries
- real account/session dumps

Workflow changes must be performed manually or through a dedicated human-reviewed
task.

## Validation Contract

Before opening a PR, run or reason through:

```bash
python3 scripts/validate_agent_tasks.py agent_tasks.json
test -z "$(gofmt -l .)"
cd web && npm ci && npm run build
rm -rf internal/web/dist && cp -r web/dist internal/web/dist
go vet ./...
go test ./...
go build -ldflags="-s -w" -o notion-manager ./cmd/notion-manager
```

If validation fails, fix the failure inside the current task scope when possible.
If the failure is unrelated, add a follow-up task and explain it in the PR body.

## Live RDSH Smoke Tests

The repository may define `RDSH_API_KEY` as a GitHub secret. Live checks must use
that secret only through GitHub Actions environment variables and must not print
or store it. Live network checks belong in `.github/workflows/rdsh_live_smoke.yml`;
unit tests must stay offline and deterministic.

## Local Live Account Smoke Tests

Real account checks can be run against the code from a PR through
`.github/workflows/rdsh_local_live_smoke.yml`. That workflow decodes
`LIVE_NOTION_ACCOUNTS_B64` from the protected `live-rdsh` GitHub environment,
starts `notion-manager` locally, and verifies OpenAI-compatible and Anthropic
Claude Code style requests against `127.0.0.1`.

Use this workflow for integration validation only. Do not add live Notion calls
to Go unit tests, and do not commit account files or generated runtime configs.
See `docs/live_smoke_secrets.md` for setup and operating details.

For a fully unattended overnight loop, the `live-rdsh` environment must not have
required reviewers. Required reviewers are useful for manual protection, but
they intentionally pause jobs before environment secrets are released.
