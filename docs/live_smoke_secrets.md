# Live smoke secrets

This repository can run real Notion-account smoke tests against the PR code
without committing account files. The workflow is
`.github/workflows/rdsh_local_live_smoke.yml`.

## What It Tests

The workflow:

1. Checks out the PR code.
2. Decodes live account JSON files from `LIVE_NOTION_ACCOUNTS_B64`.
3. Writes a temporary local `config.yaml`.
4. Builds and starts `./notion-manager` on `127.0.0.1`.
5. Sends real OpenAI-compatible and Anthropic-compatible Claude Code style
   requests to the local server.
6. Fails if the response does not contain the expected token or leaks
   Notion/workspace/page/document persona text.

It tests the code in the PR, not the already deployed RDSH server.

## Recommended GitHub Setup

Create a protected environment:

```text
GitHub -> Settings -> Environments -> New environment -> live-rdsh
```

Recommended environment settings:

- Add required reviewers.
- Allow only trusted maintainers to approve deployments to this environment.
- Store live account material as environment secrets, not repository files.

Required environment secret:

```text
LIVE_NOTION_ACCOUNTS_B64
```

Optional environment variable:

```text
LIVE_SMOKE_MODEL=opus-4.8
```

## Creating LIVE_NOTION_ACCOUNTS_B64

From Windows PowerShell:

```powershell
Compress-Archive -Path D:\notion-abuz_ai-master\accounts\*.json -DestinationPath $env:TEMP\notion-live-accounts.zip -Force
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:TEMP\notion-live-accounts.zip")) | Set-Clipboard
```

Paste the clipboard value into the `LIVE_NOTION_ACCOUNTS_B64` environment
secret.

The workflow also accepts base64 for:

- one account JSON object
- a JSON array of account objects
- a JSON object whose values are account objects

The zip format is preferred because it preserves multiple account files cleanly.

## Running It

Manual run:

```text
Actions -> RDSH Local Live Smoke -> Run workflow
```

PR run:

- PR must target `master`.
- PR must be from this repository, not a fork.
- PR must have label `jules` or `live-smoke`.
- The `live-rdsh` environment approval must be granted before secrets are
  released to the job.

## Visibility Model

The account JSON files are not committed to the repository. GitHub only exposes
the secret value to the approved workflow job. Maintainers can see secret names
and workflow logs, but GitHub does not show the secret value in the UI.

The workflow writes account files only into the temporary runner workspace and
does not upload them as artifacts.
