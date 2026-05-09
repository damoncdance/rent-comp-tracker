"""End-to-end daily run: fetch → parse → store → diff → render dashboard.

Run with:
    python -m src.daily_run
    python -m src.daily_run --verbose

Exit codes:
    0 = all properties succeeded
    1 = at least one property failed (failures were recorded)
    2 = unexpected internal error
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime, timezone

from src.changes import diff_snapshots
from src.config import get_active_properties
from src.dashboard import render
from src.export_xlsx import export as export_xlsx, export_comp_report
from src.notify import send_digest
from src.parsers import get_parser, UnsupportedPlatformError
from src.scraper import fetch_html, fetch_securecafe, fetch_rentcafe_optimized, FetchError
from src.storage import (
    write_snapshot_failure, write_snapshot_success,
    write_change_events, previous_snapshot_id,
)

INTER_FETCH_DELAY = 5  # seconds between property fetches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one daily snapshot.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    log = _make_logger(args.verbose)
    log("=" * 60)
    log(f"Daily run started at {datetime.now(timezone.utc).isoformat()}")

    properties = get_active_properties()
    if not properties:
        log("No active properties found — nothing to do.")
        return 0

    log(f"Processing {len(properties)} active properties")

    results = []  # list of (property, snapshot_id, success)

    for i, prop in enumerate(properties):
        if i > 0:
            log(f"  waiting {INTER_FETCH_DELAY}s between fetches...")
            time.sleep(INTER_FETCH_DELAY)

        snap_id, ok = _run_one_property(prop, log, verbose=args.verbose)
        results.append((prop, snap_id, ok))

    # Render multi-property dashboard
    _safe_render(log)

    # Export xlsx — consolidated comp report + per-property
    snapshot_ids = {prop["id"]: snap_id for prop, snap_id, _ in results}
    _safe_comp_report(snapshot_ids, log)
    for prop, snap_id, ok in results:
        if ok and snap_id:
            _safe_export(prop, snap_id, log)

    # Send consolidated email digest
    send_digest(snapshot_ids=snapshot_ids, log=log)

    successes = sum(1 for _, _, ok in results if ok)
    failures = len(results) - successes
    log(f"Done. {successes} succeeded, {failures} failed.")

    return 1 if failures > 0 else 0


def _run_one_property(prop: dict, log, verbose: bool = False) -> tuple[int | None, bool]:
    """Run fetch→parse→store→diff for one property. Returns (snapshot_id, success)."""
    name = prop["name"]
    slug = prop["slug"]
    url = prop["url"]
    platform = prop["platform"]
    prop_id = prop["id"]

    log(f"--- {name} ({slug}) [{platform}] ---")

    # Get parser
    try:
        parser_mod = get_parser(platform)
    except UnsupportedPlatformError as e:
        log(f"  SKIPPED: {e}")
        snap_id = write_snapshot_failure(prop_id, reason=f"no_parser:{platform}")
        return snap_id, False

    # Fetch — SecureCafe and RentCafe optimized need Playwright for Cloudflare
    try:
        if platform == "securecafe":
            html, http_status = fetch_securecafe(url=url, slug=slug, verbose=verbose)
        elif platform == "rentcafe_optimized":
            html, http_status = fetch_rentcafe_optimized(url=url, slug=slug, verbose=verbose)
        else:
            html, http_status = fetch_html(url=url, slug=slug, verbose=verbose)
        log(f"  Fetched {len(html):,} bytes (HTTP {http_status})")
    except FetchError as e:
        log(f"  FETCH FAILED: {e}")
        snap_id = write_snapshot_failure(prop_id, reason=str(e)[:200])
        return snap_id, False

    # Parse
    try:
        units, floorplans = parser_mod.parse_all(html)
        log(f"  Parsed {len(units)} units across {len(floorplans)} floorplan tiers")
    except parser_mod.ParseError as e:
        log(f"  PARSE FAILED: {e}")
        snap_id = write_snapshot_failure(prop_id, reason=f"parse:{e}", http_status=http_status)
        return snap_id, False

    # Store
    snap_id = write_snapshot_success(prop_id, units, floorplans, http_status=http_status)
    log(f"  Snapshot id={snap_id} written")

    # Diff
    prev_id = previous_snapshot_id(snap_id, property_id=prop_id)
    if prev_id is None:
        log("  No prior snapshot — skipping diff")
    else:
        events = diff_snapshots(prev_id, snap_id)
        if events:
            write_change_events(snap_id, events)
            counts: dict[str, int] = {}
            for e in events:
                counts[e["event_type"]] = counts.get(e["event_type"], 0) + 1
            log(f"  Diff vs snapshot {prev_id}: " +
                ", ".join(f"{n} {t}" for t, n in sorted(counts.items())))
        else:
            log(f"  Diff vs snapshot {prev_id}: no changes")

    return snap_id, True


def _safe_render(log) -> None:
    try:
        path = render()
        log(f"Dashboard written to {path}")
    except Exception as e:
        log(f"DASHBOARD RENDER FAILED: {e}")
        if "--verbose" in sys.argv:
            traceback.print_exc()


def _safe_comp_report(snapshot_ids: dict, log) -> None:
    try:
        path = export_comp_report(snapshot_ids)
        if path:
            log(f"Comp report written to {path}")
        else:
            log("Comp report skipped (no data)")
    except Exception as e:
        log(f"COMP REPORT FAILED: {e}")
        if "--verbose" in sys.argv:
            traceback.print_exc()


def _safe_export(prop: dict, snapshot_id: int, log) -> None:
    try:
        path = export_xlsx(snapshot_id, prop=prop)
        if path:
            log(f"  Excel export written to {path}")
        else:
            log(f"  Excel export skipped for {prop['name']} (no data)")
    except Exception as e:
        log(f"  EXCEL EXPORT FAILED for {prop['name']}: {e}")
        if "--verbose" in sys.argv:
            traceback.print_exc()


def _make_logger(verbose: bool):
    def log(msg: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)
    return log


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
