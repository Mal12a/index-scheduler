"""Send one failure mail. Standard library only, on purpose.

The alert step may use only what exists before the first step that can fail, so
this imports nothing that a checkout, a setup action or a pip install provides.

    python3 scripts/mail.py --subject "..." --body-file out.log --status failure

Exits non-zero when it could not send, including when a secret is missing: an
alerting path that disables itself quietly is the failure mode this repo is
built to not have.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.resend.com/emails"
# Not cosmetic. The API sits behind a CDN that rejects urllib's default
# signature with a bare 403 whose code says nothing about mail. Any non-default
# agent passes, so this costs one header rather than a dependency.
AGENT = "index-scheduler/1.0"
LIMIT = 60_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body-file", action="append", default=[],
                    help="file to include; may be repeated, missing files are noted")
    ap.add_argument("--note", default="", help="text above the files")
    a = ap.parse_args()

    key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("ALERT_EMAIL")
    sender = os.environ.get("EMAIL_FROM")
    missing = [n for n, v in (("RESEND_API_KEY", key), ("ALERT_EMAIL", to),
                              ("EMAIL_FROM", sender)) if not v]
    if missing:
        print(f"[mail] not sent, missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    parts = [a.note, ""] if a.note else []
    for path in a.body_file:
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError as e:
            # Say so rather than sending a mail that looks complete. A missing
            # report is itself information: the step died before writing one.
            text = f"(could not read {path}: {type(e).__name__})"
        parts += [f"--- {os.path.basename(path)} ---", text[:LIMIT], ""]
    parts.append(f"Run: {os.environ.get('RUN_URL', '(unknown)')}")

    req = urllib.request.Request(
        API,
        data=json.dumps({"from": sender, "to": [to], "subject": a.subject,
                         "text": "\n".join(parts)}).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"[mail] sent, {r.status}")
        return 0
    except urllib.error.HTTPError as e:
        # The provider's own words. A mailer that cannot mail and will not say
        # why is the same dead end as no mailer. The body carries no credential.
        print(f"[mail] refused, {e.code}: {e.read()[:300].decode('utf-8', 'replace')}",
              file=sys.stderr)
        return 1
    except OSError as e:
        print(f"[mail] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
