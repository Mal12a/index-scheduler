# index-scheduler

Scheduled workflows. No application code, no data, and nothing that identifies
what they run against.

## Why this is a separate repo

Actions minutes bill to the account that **owns the repository**, and standard
runners are free and unmetered on **public** repositories. The code has to stay
private: it carries upstream targets, a catalogue and credentials. One repo
cannot be both, so there are two.

| repo | visibility | holds |
|---|---|---|
| this one | public | workflows, and the mailer they alert with |
| the code repo | private | code, catalogue, targets, deploy secrets |

Each workflow checks this repo out at the root, mounts the private repo at
`code/`, and calls into it.

## Nothing here is identifying, including in the logs

Not a hostname, a path, a brand or an address, and not in a comment either.
Everything specific arrives at run time:

| arrives as | what |
|---|---|
| `vars.PRIVATE_REPO` | the repo to check out |
| `secrets.PIPELINE_DEPLOY_KEY` | reads and writes it |
| `secrets.ALERT_EMAIL`, `secrets.EMAIL_FROM` | who is told when something breaks |
| the private repo | every upstream host, the catalogue, the site |

Two rules follow from the repo being public, and both are load-bearing:

- **No artifacts.** An artifact on a public repository is world-downloadable,
  and these runs record every host they touch.
- **No detail in the log.** Job output goes to a file, and only counts and a
  status reach `stdout`. The detail is emailed. A step that pipes a report into
  the log or the run summary defeats the split as surely as committing a key.

## No fallbacks

A step that fails goes red and emails. Nothing here retries quietly, swallows an
error, or substitutes a default for a value it could not compute: a run that
half worked and said nothing is the failure these workflows exist to prevent.
The one deliberate exception is the link check itself, which stays green when a
third-party player dies, because that is the internet failing and not this code.
It still emails.

`scripts/mail.py` is the only code here. It uses the standard library alone, so
nothing an earlier step installs can break the one step whose job is to say that
an earlier step broke.
