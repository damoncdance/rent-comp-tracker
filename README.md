# Rent Comp Tracker

Daily snapshot tracker for multifamily rental comp sets. Runs entirely on
GitHub: a scheduled Actions workflow fetches each property's availability,
commits the data back to this repo, sends an email digest, and publishes a
static dashboard to GitHub Pages.

**Live dashboard:** https://damoncdance.github.io/rent-comp-tracker/

## What it tracks

The end goal is a comp set anchored on **Inspire West Town** (subject) plus
~10–12 competitor properties. The current implementation tracks one property
— **Aberdeen Crossing** (Chicago) — as the proof-of-concept and reference
parser. Multi-property is a planned expansion.

## What it does

- Fetches each property's floorplans page once per day via GitHub Actions.
- Extracts available units (unit number, rent, sqft, available date) and
  floorplan tiers.
- Appends to `data/tracker.db` (SQLite, tracked in git for history).
- Computes diffs vs. the previous snapshot — units added, units removed
  (presumably leased), rent changes, available-date changes.
- Regenerates `dashboard/index.html` and publishes to GitHub Pages.
- Sends an email digest via Resend.

## How to set up your own copy

See [SETUP.md](SETUP.md) for the full ~25-minute walkthrough: Resend key →
push to GitHub → add three secrets → enable Pages → run.

## Stack

Plain Python 3.11. Single runtime dependency: `requests`. Storage: SQLite.
Dashboard: static HTML with Chart.js from CDN. Hosting: GitHub Pages. Email:
Resend HTTP API. Scheduler: GitHub Actions cron.

No web framework, no JavaScript build, no Docker, no external services
beyond GitHub and Resend (both free at this scale).

## Cost

$0/month at single-property scale. Stays $0 even with 12 properties.

## Status

Baseline implementation. Captures data, renders a dashboard, sends digests.
Multi-property support, deeper analytics, and notification channels beyond
email are deferred until the baseline runs reliably.
