#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
repo = os.environ["GITHUB_REPOSITORY"]
token = os.environ.get("GITHUB_API_TOKEN", "")
session_ids = {
    value.strip()
    for value in os.environ.get("JULES_SESSION_IDS", "").split(",")
    if value.strip()
}

if not token:
    print("No GitHub API token available; cannot open ready Jules PRs.")
    sys.exit(0)


def request(method, path, body=None, ok=(200, 201, 204)):
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(f"{api_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status not in ok:
                raise RuntimeError(f"{method} {path} returned HTTP {resp.status}")
            content = resp.read()
            if not content:
                return None
            return json.loads(content.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc


def safe_ref(ref):
    return urllib.parse.quote(ref, safe="")


def is_jules_branch(branch):
    if branch.startswith(("jules-", "jules/")):
        return True
    return any(session_id in branch for session_id in session_ids)


refs = request("GET", f"/repos/{repo}/git/matching-refs/heads") or []
pulls = request("GET", f"/repos/{repo}/pulls?state=all&per_page=100") or []


def is_autonomous_pr(pr):
    labels = {label["name"] for label in pr.get("labels", [])}
    if labels & {"human-review", "no-automerge", "stop-loop"}:
        return False
    head_ref = (pr.get("head") or {}).get("ref", "")
    return "jules" in labels or is_jules_branch(head_ref)


open_autonomous = [
    pr for pr in pulls
    if pr.get("state") == "open" and is_autonomous_pr(pr)
]
if open_autonomous:
    numbers = ", ".join(f"#{pr['number']}" for pr in open_autonomous)
    print(f"Open autonomous PR already exists ({numbers}); not opening another ready PR.")
    sys.exit(0)

open_heads = {pr["head"]["ref"] for pr in pulls if pr.get("state") == "open"}
closed_head_shas = {
    (pr["head"]["ref"], pr["head"]["sha"])
    for pr in pulls
    if pr.get("state") == "closed"
}

created = 0
for ref in refs:
    full_ref = ref.get("ref", "")
    branch = full_ref.removeprefix("refs/heads/")
    sha = (ref.get("object") or {}).get("sha", "")

    if not is_jules_branch(branch):
        continue
    if branch in open_heads:
        print(f"Open PR already exists for {branch}; skipping.")
        continue
    if (branch, sha) in closed_head_shas:
        print(f"Closed PR already exists for current {branch}@{sha}; skipping.")
        continue

    compare = request("GET", f"/repos/{repo}/compare/master...{safe_ref(branch)}")
    if int(compare.get("behind_by", 0)) > 0:
        print(
            f"{branch} is behind master by {compare.get('behind_by')} commit(s); "
            "skipping stale ready branch."
        )
        continue
    if int(compare.get("ahead_by", 0)) <= 0:
        print(f"{branch} is not ahead of master; skipping.")
        continue

    commits = compare.get("commits", [])
    title = f"Jules: автономное обновление {branch}"
    if commits:
        title = f"Jules: готовые изменения из {branch}"[:120]

    body = (
        "Открыто автоматически через Jules Unattended Monitor из готовой "
        f"ветки Jules.\n\nЭтап плана: PR\nЧто сделано: Jules подготовила изменения в ветке `{branch}`.\n"
        "Что дальше: CI и automerge workflow должны проверить и смержить PR, если проверки пройдут.\n"
        "Зачем: сохранить автономный цикл улучшения Claude Code bridge без ручного открытия PR.\n"
        "Почему так: ветка уже опережает `master`, а открытого PR для нее нет.\n"
        f"Проверки/риски: требуется CI на PR.\n\nBranch: `{branch}`\nCommit: `{sha}`"
    )
    pr = request(
        "POST",
        f"/repos/{repo}/pulls",
        {
            "title": title,
            "head": branch,
            "base": "master",
            "body": body,
        },
    )
    number = pr["number"]
    created += 1
    print(f"Opened PR #{number} for {branch}.")

    try:
        request(
            "POST",
            f"/repos/{repo}/issues/{number}/labels",
            {"labels": ["jules"]},
        )
        print(f"Labeled PR #{number} as jules.")
    except RuntimeError as exc:
        print(f"Could not label PR #{number}: {exc}")

    break

print(f"Ready Jules PRs opened: {created}")
