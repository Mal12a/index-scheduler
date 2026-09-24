"""Did the scheduled checks actually run, and reach their code?

    python3 scripts/watchdog.py --repo Mal12a/index-scheduler
    python3 scripts/watchdog.py --selfcheck

Every check in this repo assumes it ran. Three ways that assumption fails
silently, each seen on this repo or a sibling one:

  - GitHub turns a public repo's schedules off after 60 days with no pushes.
    The workflows here commit their baselines to the PRIVATE repo, so their
    own runs never count as activity here. A disabled workflow has no runs at
    all, so it cannot fail; only the age of its last run shows it.
  - GitHub delivers roughly half the scheduled runs it is asked for, and has
    left runs QUEUED for hours. A green last run says nothing about whether
    there has been a run since.
  - A run can die before the code is checked out (every run here did, for ten
    days, on a missing secret). "Failed" then means "never measured", which is
    a different problem from a check finding something.

So this reads the Actions API and asserts, per repo and per workflow:

  pushed     the repo's last push is under PUSH_WARN_DAYS old. Whether a push
             by a workflow's own token counts as activity is not documented, so
             this measures the one clock that decides it rather than trusting a
             heartbeat to have reset it.
  state      every workflow is active, not disabled_inactivity or disabled_*.
  recent     every scheduled workflow ran within MAX_RUN_AGE_H.
  succeeded  every scheduled workflow has succeeded at least once.
  reached    the latest run got past setup; if not, names the step it died at.

Standard library only, like mail.py, so it cannot share fate with an install.
It must NOT run only in the repo it watches: a disabled repo disables its
watchdog on the same day. Exits 1 on any finding, 2 when the API cannot be
read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

PUSH_WARN_DAYS = 45      # the cliff is 60; this leaves two weeks of warning
MAX_RUN_AGE_H = 48       # every workflow here runs daily or more often
SETUP_STEPS = ("Set up job", "Refuse to start without the deploy key",
               "Run actions/checkout@v4", "actions/checkout@v4")


def api(path: str) -> dict:
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "ci-watchdog/1.0"})
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def age_h(stamp: str | None, now: datetime) -> float | None:
    if not stamp:
        return None
    t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return (now - t).total_seconds() / 3600


def died_at(jobs: dict) -> str | None:
    """The first failed step of the latest run, if it failed during setup.
    None when the run reached its own code (whatever it then found)."""
    for job in jobs.get("jobs", []):
        for step in job.get("steps", []):
            if step.get("conclusion") == "failure":
                name = step.get("name", "")
                return name if any(s in name for s in SETUP_STEPS) else None
    return None


def judge(repo: dict, workflows: list[dict], now: datetime) -> list[str]:
    """Pure: every finding for one repo, from already-fetched API data. Each
    workflow dict carries 'wf', 'last', 'last_ok' and 'jobs'."""
    f = []
    pushed = age_h(repo.get("pushed_at"), now)
    if pushed is None:
        f.append("repo: no pushed_at, so the inactivity clock cannot be read")
    elif pushed / 24 >= PUSH_WARN_DAYS:
        left = 60 - pushed / 24
        f.append(f"repo: last push {pushed / 24:.0f} days ago; GitHub disables its "
                 f"schedules at 60 days ({left:.0f} left). Push anything to reset it")
    if not workflows:
        f.append("repo: no workflows listed, so nothing here is being watched")
    for w in workflows:
        name, state = w["wf"]["name"], w["wf"].get("state", "?")
        if state != "active":
            f.append(f"{name}: state {state}, so it is not being scheduled at all")
            continue
        last = w.get("last")
        if last is None:
            f.append(f"{name}: has never run")
            continue
        a = age_h(last.get("created_at"), now)
        if a is not None and a > MAX_RUN_AGE_H:
            f.append(f"{name}: last run {a:.0f}h ago, over {MAX_RUN_AGE_H}h; the "
                     f"schedule is not being delivered")
        if w.get("last_ok") is None:
            f.append(f"{name}: has never succeeded")
        step = died_at(w.get("jobs") or {})
        if step:
            f.append(f"{name}: latest run died at setup step {step!r}, before any "
                     f"check ran, so it measured nothing")
    return f


def fetch(repo_name: str) -> tuple[dict, list[dict]]:
    repo = api(f"repos/{repo_name}")
    out = []
    for wf in api(f"repos/{repo_name}/actions/workflows").get("workflows", []):
        runs = api(f"repos/{repo_name}/actions/workflows/{wf['id']}/runs?per_page=1")
        last = (runs.get("workflow_runs") or [None])[0]
        ok = api(f"repos/{repo_name}/actions/workflows/{wf['id']}/runs"
                 f"?status=success&per_page=1")
        jobs = api(f"repos/{repo_name}/actions/runs/{last['id']}/jobs") if last else {}
        out.append({"wf": wf, "last": last, "jobs": jobs,
                    "last_ok": (ok.get("workflow_runs") or [None])[0]})
    return repo, out


def selfcheck() -> None:
    """The judge must fire on each failure it exists for, and pass a healthy
    repo. Fixtures, no network."""
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    ok_run = {"created_at": "2026-10-31T10:00:00Z"}
    healthy = {"wf": {"name": "w", "state": "active"}, "last": ok_run,
               "last_ok": ok_run, "jobs": {"jobs": [{"steps": [
                   {"name": "Run actions/checkout@v4", "conclusion": "success"},
                   {"name": "Probe", "conclusion": "failure"}]}]}}
    assert judge({"pushed_at": "2026-10-20T00:00:00Z"}, [healthy], now) == [], \
        "a healthy repo whose check found something must not be reported"
    stale = judge({"pushed_at": "2026-09-14T15:05:59Z"}, [healthy], now)
    assert any("disables its schedules" in s for s in stale), stale
    dead = dict(healthy, jobs={"jobs": [{"steps": [
        {"name": "Refuse to start without the deploy key", "conclusion": "failure"}]}]})
    assert any("died at setup" in s for s in judge({"pushed_at": "2026-10-20T00:00:00Z"},
                                                    [dead], now))
    off = dict(healthy, wf={"name": "w", "state": "disabled_inactivity"})
    assert any("not being scheduled" in s for s in judge({"pushed_at": "2026-10-20T00:00:00Z"},
                                                         [off], now))
    old = dict(healthy, last={"created_at": "2026-10-25T00:00:00Z"})
    assert any("not being delivered" in s for s in judge({"pushed_at": "2026-10-20T00:00:00Z"},
                                                         [old], now))
    never = dict(healthy, last_ok=None)
    assert any("never succeeded" in s for s in judge({"pushed_at": "2026-10-20T00:00:00Z"},
                                                     [never], now))
    assert judge({"pushed_at": "2026-10-20T00:00:00Z"}, [], now), "no workflows is a finding"
    print("selfcheck ok: fires on each failure, passes a healthy repo")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", action="append", default=[])
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    if a.selfcheck:
        selfcheck()
        return 0
    if not a.repo:
        print("NOT CHECKED: no --repo given")
        return 2
    now = datetime.now(timezone.utc)
    findings = []
    for name in a.repo:
        try:
            repo, wfs = fetch(name)
        except (urllib.error.URLError, KeyError, ValueError) as e:
            print(f"NOT CHECKED: {name}: {type(e).__name__}: {str(e)[:100]}")
            return 2
        pushed = age_h(repo.get("pushed_at"), now)
        print(f"{name}: {len(wfs)} workflow(s), last push "
              f"{'?' if pushed is None else f'{pushed / 24:.0f}d'} ago")
        findings += [f"{name}: {s}" for s in judge(repo, wfs, now)]
    for s in findings:
        print(f"  FAIL {s}")
    if not findings:
        print("  every workflow is scheduled, recent, has succeeded, and reached its code")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
