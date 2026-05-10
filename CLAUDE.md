# Rent Comp Tracker

Daily snapshot tracker for multifamily rental comp sets. Runs entirely on
GitHub: a scheduled Actions workflow fetches each property, parses the data,
commits an updated SQLite database back to the repo, sends a consolidated
email digest via Resend, and publishes a multi-property dashboard to GitHub Pages.

## Context

The system tracks a comp set anchored on a **subject property** plus
roughly 10–12 competitor properties. It supports multiple platforms
(RentCafe, SecureCafe, AppFolio, etc.) and uses Playwright to bypass
Cloudflare on certain sites.

**Owner:** damoncdance
**Live dashboard:** https://damoncdance.github.io/rent-comp-tracker/
**Repo:** https://github.com/damoncdance/rent-comp-tracker

## Critical data-source insight

The project uses different scraping strategies based on the platform:
- **RentCafe:** Extracts `ysi.unitsList` and `ysi.floorplansList` from static HTML via regex.
- **SecureCafe / RentCafe Optimized:** Uses **Playwright (Chromium)** to bypass Cloudflare and fetch JSON or HTML.
- **AppFolio / Nestio / Others:** Custom parsers in `src/parsers/`.

## Architecture

```
GitHub Actions cron (12:30 UTC daily)
   ↓
checkout repo (gets last committed data/tracker.db)
   ↓
src.daily_run (Orchestrator):
   Loop through active properties in DB:
      fetch (requests OR Playwright/Chromium with xvfb)
         ↓
      parse (platform-specific parser in src/parsers/)
         ↓
      store (SQLite append-only via src.storage)
         ↓
      diff (compare to previous snapshot → log change events)
   ↓
render (regenerate dashboard/index.html + per-property pages)
   ↓
export (generate consolidated Excel comp report + per-property XLSX)
   ↓
notify (Resend HTTP API → consolidated email digest with links)
   ↓
git commit data/tracker.db + dashboard/ → push
   ↓
deploy dashboard/ → GitHub Pages
```

## File map

```
rent-comp-tracker/
├── CLAUDE.md                      ← you are here
├── README.md                      ← human-facing overview
├── SETUP.md                       ← walkthrough
├── requirements.txt               ← pip deps (requests, playwright, openpyxl)
├── schema.sql                     ← SQLite schema
├── migrations/                    ← database migrations
├── src/
│   ├── parsers/                   ← platform-specific parsers
│   ├── config.py                  ← Registry, paths, headers, .env loader
│   ├── scraper.py                 ← fetch logic (Playwright + Requests)
│   ├── storage.py                 ← SQLite persistence layer (The "Source of Truth")
│   ├── changes.py                 ← diffing logic
│   ├── dashboard.py               ← Multi-property HTML generator
│   ├── pricing.py                 ← NER and pricing recommendation logic
│   ├── amenities.py               ← Amenity extraction/normalization
│   ├── export_xlsx.py             ← Excel report generation
│   ├── notify.py                  ← Email digest logic (Resend API)
│   └── daily_run.py               ← Main entry point / orchestrator
├── data/
│   ├── tracker.db                 ← SQLite (TRACKED IN GIT)
│   ├── exports/                   ← Generated Excel reports (GITIGNORED)
│   └── raw/                       ← Raw HTML snapshots (GITIGNORED)
├── dashboard/                     ← Generated HTML files (TRACKED IN GIT)
└── .claude/skills/                ← Specialized agent skills
```

## Important: tracked binary file

`data/tracker.db` and the `dashboard/` directory are intentionally tracked in git. Every Actions run commits
updates back to the repo. This provides a "serverless" persistence layer and history.

## Common commands

```bash
# Local development
pip install -r requirements.txt
python -m playwright install chromium
sqlite3 data/tracker.db < schema.sql

# Run a single snapshot manually (locally)
python -m src.daily_run --verbose

# Run tests (if pytest is installed)
python -m pytest

# Inspect the database
sqlite3 data/tracker.db
> SELECT * FROM properties;
> SELECT fetched_at, unit_count FROM snapshots ORDER BY id DESC LIMIT 10;
```

## Conventions

- **Timestamps:** ISO 8601 in UTC.
- **Money:** REAL in SQLite, formatted as `f"${x:,.0f}"` for display.
- **Database:** Use `src.storage.db()` context manager to ensure `PRAGMA foreign_keys = ON`.
- **Snapshots:** Append-only. Never update existing snapshot data.
- **Failed fetches** still get a snapshot row (`fetch_status = failed:<reason>`) so gaps are visible.
- **Secrets** live in GitHub Actions secrets (`RESEND_API_KEY`, `NOTIFY_FROM`, `NOTIFY_TO`). Locally, `.env` (gitignored).
- **Adding parsers:** Create a new module in `src/parsers/` and register it in `src/parsers/__init__.py`.

## Email notifications (Resend)

One consolidated digest per daily run covering all properties. Fires even on
failures so the inbox doubles as a heartbeat. Includes pricing insights and
an attached Excel comp report. Subject format:

- `Rent Comps — 12 properties, 48 units, 5 changes`
- `Rent Comps — 12 properties, 48 units, no changes`

## When the scraper breaks

See `.claude/skills/scraper-recovery/SKILL.md`. Common failure modes:
403 (header rotation needed), Cloudflare challenge changes (Playwright update),
or the site swapping platforms (new parser needed).
