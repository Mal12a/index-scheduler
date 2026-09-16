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

## What runs

| workflow | cadence | asks | red when |
|---|---|---|---|
| `build-check` | nightly | do the tests pass and does it still build | a test or the build fails |
| `link-health` | daily | do the third-party players still play | the checker itself breaks |
| `source-watch` | daily | is each upstream still publishing, or gone dark | an upstream dies or shrinks |
| `storage-check` | daily | do the storage credentials and image domain work | any of them fails |
| `site-up` | every 6h | is the front door open and are pages correct | a page is wrong or leaks an upstream host |
| `site-deep` | daily | the 200-but-broken failures: sitemap host purity, page image/JSON-LD leaks, CSP permits what pages load, versioned asset serves current, uploadDate coverage, soft-404, slug redirects | any of them regresses |
| `capacity` | every 3h | the day's request count against the free cap, and the homepage is not 429 | usage crosses the threshold, or a 429 is already serving |

Three of these are deliberately green on bad news from the outside world and
only red on our own breakage, because a job that goes red for something no
commit caused trains you to ignore red. `link-health` stays green when a player
dies and `source-watch` stays green when an upstream publishes more; both still
email. The alarm is the mail, not the colour.

**`source-watch` detects, it does not crawl.** The catalogue is far too large to
live here and the biggest upstreams refuse a datacenter IP on their content
pages, so a runner cannot grow it. What a runner can do is read the count each
upstream publishes about itself, which is enough to say "there is new work" and
"this one stopped answering". The crawl that acts on that runs where it already
runs. It keeps one small file of counts in the private repo and commits it back,
which is what makes "since yesterday" mean anything.

## Nothing here is identifying, including in the logs

Not a hostname, a path, a brand or an address, and not in a comment either.
Everything specific arrives at run time:

| arrives as | what |
|---|---|
| `vars.PRIVATE_REPO` | the repo to check out |
| `secrets.PIPELINE_DEPLOY_KEY` | reads and writes it |
| `secrets.ALERT_EMAIL`, `secrets.EMAIL_FROM` | who is told when something breaks |
| `secrets.SITE_URL` | the site `site-up`, `site-deep` and `capacity` probe |
| `secrets.R2_*` | endpoint, key, secret, bucket, image bucket and a public image URL |
| `secrets.CLOUDFLARE_API_TOKEN`, `secrets.CF_ZONE_ID` | the request-count read for `capacity` (token needs Analytics: Read) |
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
