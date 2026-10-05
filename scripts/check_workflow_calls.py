"""Every flag a workflow passes must be one the script accepts.

    python3 scripts/check_workflow_calls.py --code code
    python3 scripts/check_workflow_calls.py --selfcheck

A workflow calling a Python script is a caller that no import graph, type
checker or test suite can see. Rename a flag and nothing anywhere fails until
the schedule fires.

It happened twice in one rename. `--cap` became `--included` when the capacity
check moved from a daily free cap to a monthly paid allowance:

  - the workflow kept passing --cap, so argparse rejected it, the script exited
    before writing any output, and the job failed every three hours with
    "status: unknown" rather than anything about capacity
  - the script's own GITHUB_OUTPUT block kept a stale a.cap, which only runs
    where GITHUB_OUTPUT is set, so every local run passed and every CI run
    crashed after printing a clean status

This reads each workflow, finds every `python ... scripts/....py --flag` call,
and asks the script's own parser whether it knows that flag. No execution: the
module is parsed, not imported, so a script needing credentials or a browser is
checked the same as any other.

Exits 1 on an unknown flag or a missing script, 2 when it cannot judge.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys

# Relative to THIS FILE, never the working directory. The nightly runs its
# steps from code/, the private checkout, which has a .github/workflows of its
# own: a CWD-relative path read that one instead, found 4 calls in 1 workflow,
# and printed a clean green having never looked at the 10 workflows it exists
# to guard. Checking the wrong population is the failure this whole file is
# about, so the directory it read is printed on every run.
WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"
# `python scripts/x.py --a --b`. Continuations are joined BEFORE matching
# rather than matched across: a pattern like (?:[^\n]|\\\n)* succeeds on the
# first line and never backtracks into the continuation, so it captured exactly
# " \\" and found no flags at all, while reporting 30 calls checked.
CALL = re.compile(r"python3?\s+((?:scripts|code/scripts)/[A-Za-z0-9_/]+\.py)([^\n]*)")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")


def flags_a_script_accepts(path: pathlib.Path) -> set[str] | None:
    """Option strings from the script's own add_argument calls, by parsing it.

    Parsed rather than imported: importing runs module-level code, and several
    of these open a network client or read a credential at import time.
    """
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return None
    out: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("--"):
                    out.add(arg.value)
    return out


def calls_in(text: str) -> list[tuple[str, set[str]]]:
    """(script path, flags passed) for every script call in one workflow."""
    found = []
    text = text.replace("\\\n", " ")      # join shell line continuations first
    for m in CALL.finditer(text):
        script, rest = m.group(1), m.group(2)
        # Stop at the shell operator that ends the command, so the next line's
        # `|| rc=$?` or a following command cannot donate flags to this call.
        rest = re.split(r"[|;&>]|\n\s*\n", rest)[0]
        found.append((script, set(FLAG.findall(rest))))
    return found


def selfcheck() -> None:
    """It must spot an unknown flag and accept a known one, or it is decoration."""
    src = "import argparse\np=argparse.ArgumentParser()\np.add_argument('--included')\n"
    tmp = pathlib.Path("/tmp/_cwc_fixture.py")
    tmp.write_text(src)
    accepts = flags_a_script_accepts(tmp)
    assert accepts == {"--included"}, accepts
    assert calls_in("run: python scripts/x.py --cap 100 --report r\n")[0][1] == {"--cap", "--report"}
    # The real shape: a YAML block with shell continuations. A single-line
    # fixture passed while every real call captured nothing.
    multi = ("          python scripts/x.py \\\n"
             "            --cap \"${{ github.event.inputs.included || 10 }}\" \\\n"
             "            --report ../cap.txt > ../cap.log 2>&1 || rc=$?\n")
    got = calls_in(multi)[0][1]
    assert "--cap" in got, got
    # The real regression: --cap passed, --included accepted.
    assert "--cap" not in accepts
    # A flag after a shell operator belongs to another command.
    got = calls_in("python scripts/x.py --included 5 || echo --oops\n")[0][1]
    assert got == {"--included"}, got
    tmp.unlink()
    print("selfcheck ok: catches an unknown flag, accepts a known one")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="code",
                    help="path the private repo is checked out at")
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    if a.selfcheck:
        selfcheck()
        return 0

    if not WORKFLOWS.is_dir():
        print(f"NOT CHECKED: no {WORKFLOWS}")
        return 2
    code = pathlib.Path(a.code)
    fails, checked = [], 0
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        for script, flags in calls_in(wf.read_text()):
            # A call may name the script relative to the private checkout or to
            # this repo; try both rather than assume one layout.
            rel = script[len("code/"):] if script.startswith("code/") else script
            # The private checkout for code/… paths, and the repo holding the
            # workflows for its own scripts. Neither is the working directory:
            # the nightly runs from code/, where the public repo's mail.py does
            # not exist, and a cwd-relative guess reported 11 missing scripts.
            for base in (code, WORKFLOWS.parents[1]):
                p = base / rel
                if p.exists():
                    break
            else:
                fails.append(f"{wf.name}: {script} does not exist")
                continue
            accepts = flags_a_script_accepts(p)
            if accepts is None:
                fails.append(f"{wf.name}: {script} could not be parsed")
                continue
            checked += 1
            for f in sorted(flags - accepts):
                fails.append(f"{wf.name}: passes {f} to {script}, which does not accept it")
    if not checked:
        # Matching nothing is the same confident green this is built to prevent.
        print("NOT CHECKED: found no script calls in any workflow")
        return 2
    print(f"  {checked} script call(s) across "
          f"{len(list(WORKFLOWS.glob('*.yml')))} workflow(s) in {WORKFLOWS}")
    for f in fails:
        print(f"  FAIL {f}")
    if fails:
        return 1
    print("  every flag a workflow passes is one the script accepts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
