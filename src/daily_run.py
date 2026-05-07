"""End-to-end daily run: fetch → parse → store → diff → render dashboard.

Run with:
    python -m src.daily_run
    python -m src.daily_run --verbose

Exit codes:
    0 = success (data captured)
    1 = fetch or parse failed (a failure snapshot was still recorded)
    2 = unexpected internal error
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timezone

from src.changes import diff_snapshots
from src.dashboard import render
from src.notify import send_digest
from src.parser import parse_all, ParseError
from src.scraper import fetch_html, FetchError
from src.storage import (
    write_snapshot_failure, write_snapshot_success,
    write_change_events, previous_snapshot_id,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one daily snapshot.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    log = _make_logger(args.verbose)
    log("=" * 60)
    log(f"Daily run started at {datetime.now(timezone.utc).isoformat()}")

    # Step 1: fetch
    try:
        html, http_status = fetch_html(verbose=args.verbose)
        log(f"Fetched {len(html):,} bytes (HTTP {http_status})")
    except FetchError as e:
        log(f"FETCH FAILED: {e}")
        snap_id = write_snapshot_failure(reason=str(e)[:200])
        log(f"Recorded failure snapshot id={snap_id}")
        _safe_render(log)
        send_digest(snapshot_id=snap_id, log=log)
        return 1

    # Step 2: parse
    try:
        units, floorplans = parse_all(html)
        log(f"Parsed {len(units)} units across {len(floorplans)} floorplan tiers")
    except ParseError as e:
        log(f"PARSE FAILED: {e}")
        snap_id = write_snapshot_failure(reason=f"parse:{e}", http_status=http_status)
        log(f"Recorded failure snapshot id={snap_id}")
        _safe_render(log)
        send_digest(snapshot_id=snap_id, log=log)
        return 1

    # Step 3: store snapshot
    snap_id = write_snapshot_success(units, floorplans, http_status=http_status)
    log(f"Snapshot id={snap_id} written")

    # Step 4: diff against previous
    prev_id = previous_snapshot_id(snap_id)
    if prev_id is None:
        log("No prior snapshot — skipping diff")
    else:
        events = diff_snapshots(prev_id, snap_id)
        if events:
            write_change_events(snap_id, events)
            counts: dict[str, int] = {}
            for e in events:
                counts[e["event_type"]] = counts.get(e["event_type"], 0) + 1
            log(f"Diff vs snapshot {prev_id}: " +
                ", ".join(f"{n} {t}" for t, n in sorted(counts.items())))
        else:
            log(f"Diff vs snapshot {prev_id}: no changes")

    # Step 5: render dashboard
    _safe_render(log)

    # Step 6: send email digest (silently skipped if NOTIFY_ENABLED != true)
    send_digest(snapshot_id=snap_id, log=log)

    log("Done.")
    return 0


def _safe_render(log) -> None:
    try:
        path = render()
        log(f"Dashboard written to {path}")
    except Exception as e:
        log(f"DASHBOARD RENDER FAILED: {e}")
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
