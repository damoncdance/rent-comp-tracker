# Rent Comp Tracker

Daily snapshot tracker for multifamily rental comp sets. Runs entirely on
GitHub: a scheduled Actions workflow fetches each property, parses the data,
commits an updated SQLite database back to the repo, sends an email digest
via Resend, and publishes a static dashboard to GitHub Pages.

## Context

The end goal is a comp set anchored on **Inspire West Town** (subject) plus
roughly 10–12 competitor properties. The current implementation tracks one
property — **Aberdeen Crossing** (Chicago) — as the proof-of-concept and
reference parser. Multi-property is a clearly-scoped future expansion (see
"Adding properties" below); don't refactor for it preemptively.

**Owner:** damoncdance
**Live dashboard:** https://damoncdance.github.io/rent-comp-tracker/
**Repo:** https://github.com/damoncdance/rent-comp-tracker

## Critical data-source insight (read first)

The current property is on **RentCafe** (Yardi). The floorplans page inlines
two JavaScript variables in `<script>` tags:

- `ysi.floorplansList` — floorplan tiers (summary: bed/bath/sqft/rent range/avail count)
- `ysi.unitsList` — every individual available unit (unit code, exact rent, sqft, available date, FloorplanId)

**Both arrays are present in the static HTML response.** No JavaScript execution
is needed. We extract them with a regex
(`re.search(r'ysi\.unitsList\s*=\s*(\[.*?\]);', html, re.DOTALL)`) and parse
with `json.loads`. This is the entire scraping strategy.

Most apartment sites built on RentCafe follow the same pattern, so this
approach is reusable for many of the eventual comps. Properties on different
platforms (Yardi Voyager, AppFolio, Entrata, MRI) will need their own parsers.

## Architecture

```
GitHub Actions cron (12:30 UTC daily)
   ↓
checkout repo (gets last committed data/tracker.db)
   ↓
src.daily_run:
   fetch (requests + browser-like headers)
      ↓
   parse (regex extract → json.loads on two embedded arrays)
      ↓
   store (SQLite append-only: snapshots, units, floorplans, change_events)
      ↓
   diff (compare to previous snapshot → log change events)
      ↓
   render (regenerate dashboard/index.html with Chart.js)
      ↓
   notify (Resend HTTP API → email digest)
   ↓
git commit data/tracker.db + dashboard/index.html → push
   ↓
deploy dashboard/ → GitHub Pages
```

One end-to-end run = `python -m src.daily_run`. Locally, the same module
runs against a local DB. In the cloud, that's the only command the workflow
executes.

## File map

```
rent-comp-tracker/
├── CLAUDE.md                      ← you are here
├── README.md                      ← human-facing overview
├── SETUP.md                       ← step-by-step cloud setup walkthrough
├── requirements.txt               ← pip deps (requests only)
├── schema.sql                     ← SQLite schema
├── .env.example                   ← copy to .env for local development
├── .gitignore                     ← excludes .env, raw HTML; tracks DB + dashboard
├── .github/
│   └── workflows/
│       └── daily.yml              ← scheduled Actions workflow
├── src/
│   ├── __init__.py
│   ├── config.py                  ← URL, paths, headers, .env loader
│   ├── scraper.py                 ← fetch_html() — handles 403s, retries
│   ├── parser.py                  ← parse_units(), parse_floorplans()
│   ├── storage.py                 ← write_snapshot_*, units_for_snapshot, ...
│   ├── changes.py                 ← diff_snapshots() → list of change events
│   ├── dashboard.py               ← render() — writes dashboard/index.html
│   ├── notify.py                  ← send_digest() — Resend HTTP API
│   └── daily_run.py               ← orchestrator (runs locally and on Actions)
├── data/
│   ├── tracker.db                 ← SQLite (TRACKED IN GIT — committed by Actions)
│   └── raw/                       ← raw HTML snapshots (gitignored)
├── dashboard/
│   └── index.html                 ← TRACKED IN GIT — regenerated each run
└── .claude/skills/
    ├── scraper-recovery/SKILL.md  ← what to do if fetch starts failing
    └── dashboard-customization/SKILL.md  ← how to add charts/sections
```

## Important: tracked binary file

`data/tracker.db` is intentionally tracked in git. Every Actions run commits
the updated database back so the next run can diff against it. This is
unconventional but works fine at this scale (the file grows roughly 10–50 KB
per snapshot; under 20 MB after a year of daily runs for one property).

**Don't optimize this** by moving the DB to S3, an artifact, or a cache.
Those add complexity for no gain at this volume. Revisit only if (a) the file
grows above ~100 MB, or (b) we add so many properties that commit churn
becomes a problem.

## Common commands

```bash
# Local development
pip install -r requirements.txt
sqlite3 data/tracker.db < schema.sql        # only if no DB yet
cp .env.example .env                         # then edit .env

# Run a single snapshot manually (locally)
python -m src.daily_run
python -m src.daily_run --verbose

# Test the email digest without doing a full daily run
python -m src.notify --test

# Trigger the cloud workflow on demand (instead of waiting for the schedule)
# Either: GitHub repo → Actions tab → "Daily snapshot" → "Run workflow"
# Or with the gh CLI:
gh workflow run "Daily snapshot"

# Inspect the database
sqlite3 data/tracker.db
> .tables
> SELECT fetched_at, unit_count FROM snapshots ORDER BY id DESC LIMIT 10;
> SELECT unit_code, min_rent FROM units WHERE snapshot_id = (SELECT MAX(id) FROM snapshots);
> SELECT event_type, COUNT(*) FROM change_events GROUP BY event_type;
```

## Conventions

- **Timestamps** are ISO 8601 in UTC (`datetime.now(timezone.utc).isoformat()`).
- **Money** stored as REAL (dollars, no cents on this site). Format with `f"${x:,.0f}"` for display.
- **Unit identity** is the `UnitCode` field (e.g. `"1100-701"`). It's stable across snapshots.
- **Snapshots are append-only.** Never UPDATE rows in `units` or `floorplans`; insert a new snapshot row instead. This keeps history intact for diffs.
- **Failed fetches still get a snapshot row** (with `fetch_status` = `failed:<reason>`) so we can see when the site went dark.
- **Secrets live in GitHub Actions secrets** (RESEND_API_KEY, NOTIFY_FROM, NOTIFY_TO). Locally, `.env` (gitignored) does the same job.

## Email notifications (Resend)

Configured via three repo secrets: `RESEND_API_KEY`, `NOTIFY_FROM`, `NOTIFY_TO`.
The notify module calls Resend's HTTP API directly — no SMTP, no app passwords.

The digest fires after every `daily_run`, including on fetch/parse failures,
so the inbox doubles as a heartbeat. Subject lines summarize state at a glance:

- `Rent Comps — Aberdeen Crossing: 76 units, no changes`
- `Rent Comps — Aberdeen Crossing: 75 units (-1), 3 changes`
- `Rent Comps — Aberdeen Crossing: FETCH FAILED`

Without a verified Resend domain, `NOTIFY_FROM` must be `onboarding@resend.dev`
and `NOTIFY_TO` must match the Resend signup email. Both restrictions lift
once the user verifies a domain.

## Adding properties (future work — don't do this preemptively)

When ready to add Inspire West Town and the 10–12 comps:

1. Add a `properties` table in `schema.sql`:
   `(id, slug, display_name, url, platform, active)`.
2. Add a `property_id` column to `snapshots`. Backfill the existing rows
   with the Aberdeen property id, then enforce NOT NULL.
3. Replace `PROPERTY_URL` and `PROPERTY_NAME` in `config.py` with a list
   pulled from the DB.
4. Loop in `daily_run.py` — one fetch+parse+store+notify cycle per active
   property. Failures on one property shouldn't block others.
5. The dashboard becomes a top-level page listing all comps, with per-property
   detail pages.
6. Per-property parsers: keep `parser.py` for RentCafe; add
   `parser_yardi_voyager.py`, `parser_appfolio.py`, etc. as needed. The
   parser interface is `parse_all(html) -> (units, floorplans)`.
7. The Actions workflow doesn't need structural changes — just runs the
   updated daily_run module.

## When the scraper breaks

See `.claude/skills/scraper-recovery/SKILL.md`. The most common failure modes
are 403 (header rotation needed) and the site swapping platforms (parser
rewrite needed). Failures land in your email inbox via the digest.

## What's intentionally NOT here

- **No analytics yet.** Dashboard shows current availability + a basic
  timeline. Deeper analysis (days-on-market, absorption rate, elasticity)
  is deferred until the baseline runs reliably and we have multiple properties.
- **No SMS / push.** Email-only for now. Twilio for SMS or ntfy.sh for push
  are reasonable additions later if email isn't fast enough.
- **No web framework.** `dashboard/index.html` is a single static file with
  embedded JSON and Chart.js from CDN. Don't introduce Flask/FastAPI unless
  there's a real need (likely once we have 12 properties and want filtering).
- **No multi-property support yet.** See "Adding properties" above for the
  migration path; don't pre-build it.
- **No external state stores.** SQLite-in-git is sufficient at this scale.
  Don't move to Postgres, S3, Turso, etc. without a concrete reason.
