# Rent Comp Tracker

Daily snapshot tracker for multifamily rental comp sets. Runs entirely on
GitHub: a scheduled Actions workflow fetches each property's availability,
commits the data back to this repo, sends an email digest, and publishes a
static dashboard to GitHub Pages.

**Live dashboard:** https://damoncdance.github.io/rent-comp-tracker/

## What it tracks

The system tracks a comp set anchored on a **subject property** plus
~10–12 competitor properties across various platforms (RentCafe, SecureCafe, AppFolio, etc.).

## What it does

- Fetches each property's availability once per day via GitHub Actions (using Playwright for Cloudflare-protected sites).
- Extracts available units and floorplan tiers using platform-specific parsers.
- Appends to `data/tracker.db` (SQLite, tracked in git for history).
- Computes diffs vs. the previous snapshot — units added, units removed, rent changes, etc.
- Regenerates a multi-property dashboard at `dashboard/index.html`.
- Sends a consolidated email digest via Resend.
- Generates Excel comp reports and per-property availability sheets.

## How to set up your own copy

See [SETUP.md](SETUP.md) for the full ~25-minute walkthrough.

## Stack

Plain Python 3.11. Core dependencies: `requests`, `playwright`, `openpyxl`. Storage: SQLite.
Dashboard: static HTML with Chart.js from CDN. Hosting: GitHub Pages. Email:
Resend HTTP API. Scheduler: GitHub Actions cron.

## Status

Active. Multi-property support, automated pricing recommendations, and consolidated reporting are implemented.
