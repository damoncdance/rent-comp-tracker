"""Email digest after each daily run, sent via the Resend API.

Sends a multipart (text + HTML) summary of the latest snapshot for all
properties: status, current availability, changes vs. previous snapshot,
a link to the dashboard, and (when the export exists) the Excel workbook
as an attachment via Resend.

Configured via environment variables (loaded from .env locally; from
GitHub Actions secrets when running in the cloud):

    NOTIFY_ENABLED      "true" to send, anything else skips silently
    RESEND_API_KEY      from https://resend.com/api-keys
    NOTIFY_FROM         e.g. 'Rent Comps <onboarding@resend.dev>'
    NOTIFY_TO           recipient(s), comma-separated for multiple
    DASHBOARD_URL       optional link in the email
                        (defaults to the local file:// path)

Run a test send (no full daily run needed):
    python -m src.notify --test

Modules:
  _helpers  — shared utilities (HTML escape, date formatting, config checks)
  _digest   — digest assembly (subject, text, HTML body builders)
  _html     — HTML email templates
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time

import requests

from src.config import get_property_by_id
from src.export_xlsx import comp_report_path, report_workbook_path
from src.storage import db, latest_snapshot_id

from src.notify._helpers import missing_config as _missing_config
from src.notify._digest import build_multi_digest as _build_multi_digest


RESEND_ENDPOINT = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 30
SEND_MAX_ATTEMPTS = 3
SEND_RETRY_BACKOFF_SECONDS = 3


# --- Public API -------------------------------------------------------------

def is_enabled() -> bool:
    return os.environ.get("NOTIFY_ENABLED", "").strip().lower() == "true"


def send_digest(
    snapshot_ids: dict[int, int | None] | None = None,
    snapshot_id: int | None = None,
    log=print,
) -> bool:
    """Send the daily digest. Returns True if sent, False if skipped/failed.

    snapshot_ids: {property_id: snapshot_id} for multi-property runs.
    snapshot_id: single snapshot id (legacy/backwards compat).
    Never raises — email failures should not break the daily run.
    """
    if not is_enabled():
        log("notify: NOTIFY_ENABLED != true, skipping email")
        return False

    missing = _missing_config()
    if missing:
        log(f"notify: missing env vars: {', '.join(missing)} — skipping email")
        return False

    # Build property results list
    if snapshot_ids:
        prop_results = _gather_multi_property_results(snapshot_ids)
    elif snapshot_id is not None:
        prop_results = _gather_single_snapshot_result(snapshot_id)
    else:
        # Fallback: latest snapshot across all properties
        snap_id = latest_snapshot_id()
        if snap_id is None:
            log("notify: no snapshot in DB yet — nothing to send")
            return False
        prop_results = _gather_single_snapshot_result(snap_id)

    if not prop_results:
        log("notify: no results to report")
        return False

    try:
        subject, text_body, html_body = _build_multi_digest(prop_results)
    except Exception as e:
        log(f"notify: digest build failed: {type(e).__name__}: {e}")
        return False

    # Attach the consolidated comp report if available
    attachment = _resend_comp_report_attachment(log)

    return _send(subject, text_body, html_body, log, attachment=attachment)


# --- Result gathering -------------------------------------------------------

def _gather_multi_property_results(snapshot_ids: dict[int, int | None]) -> list[dict]:
    """Build result dicts for each property from snapshot_ids map."""
    results = []
    with db() as conn:
        for prop_id, snap_id in snapshot_ids.items():
            prop_row = conn.execute(
                "SELECT * FROM properties WHERE id = ?", (prop_id,)
            ).fetchone()
            if not prop_row:
                continue
            prop = dict(prop_row)

            if snap_id is None:
                results.append({
                    "property": prop,
                    "snapshot_id": None,
                    "success": False,
                    "snap": None,
                    "units": [],
                    "events": [],
                    "prev_unit_count": None,
                })
                continue

            snap = dict(conn.execute(
                "SELECT * FROM snapshots WHERE id = ?", (snap_id,)
            ).fetchone())

            success = snap["fetch_status"] == "success"
            units = []
            prev_unit_count = None

            if success:
                units = [dict(r) for r in conn.execute(
                    "SELECT * FROM units WHERE snapshot_id = ? "
                    "ORDER BY beds, floorplan_name, unit_code",
                    (snap_id,),
                ).fetchall()]
                prev = conn.execute(
                    "SELECT unit_count FROM snapshots "
                    "WHERE id < ? AND fetch_status = 'success' AND property_id = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (snap_id, prop_id),
                ).fetchone()
                if prev:
                    prev_unit_count = prev["unit_count"]

            events = [dict(r) for r in conn.execute(
                "SELECT * FROM change_events WHERE snapshot_id = ?", (snap_id,)
            ).fetchall()]

            results.append({
                "property": prop,
                "snapshot_id": snap_id,
                "success": success,
                "snap": snap,
                "units": units,
                "events": events,
                "prev_unit_count": prev_unit_count,
            })
    return results


def _gather_single_snapshot_result(snapshot_id: int) -> list[dict]:
    """Build a single-element result list from a snapshot id."""
    with db() as conn:
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        if not snap:
            return []
        snap = dict(snap)
        prop_id = snap.get("property_id")
        prop = None
        if prop_id:
            prop_row = conn.execute(
                "SELECT * FROM properties WHERE id = ?", (prop_id,)
            ).fetchone()
            prop = dict(prop_row) if prop_row else None

        if prop is None:
            prop = {"id": 0, "name": "Unknown", "slug": "unknown",
                    "is_subject": 0, "url": ""}

        success = snap["fetch_status"] == "success"
        units = []
        prev_unit_count = None
        if success:
            units = [dict(r) for r in conn.execute(
                "SELECT * FROM units WHERE snapshot_id = ? "
                "ORDER BY beds, floorplan_name, unit_code",
                (snapshot_id,),
            ).fetchall()]
            # Scope the "previous" snapshot to the same property so the
            # delta isn't computed against an unrelated property's snapshot.
            if prop_id:
                prev = conn.execute(
                    "SELECT unit_count FROM snapshots "
                    "WHERE id < ? AND fetch_status = 'success' AND property_id = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (snapshot_id, prop_id),
                ).fetchone()
            else:
                prev = conn.execute(
                    "SELECT unit_count FROM snapshots "
                    "WHERE id < ? AND fetch_status = 'success' "
                    "ORDER BY id DESC LIMIT 1",
                    (snapshot_id,),
                ).fetchone()
            if prev:
                prev_unit_count = prev["unit_count"]

        events = [dict(r) for r in conn.execute(
            "SELECT * FROM change_events WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchall()]

    return [{
        "property": prop,
        "snapshot_id": snapshot_id,
        "success": success,
        "snap": snap,
        "units": units,
        "events": events,
        "prev_unit_count": prev_unit_count,
    }]


# --- Resend transport -------------------------------------------------------

def _send(
    subject: str,
    text_body: str,
    html_body: str,
    log,
    *,
    attachment: dict | None = None,
) -> bool:
    """Send via Resend. `attachment` is Resend-shaped: filename, content (base64)."""
    recipients = [r.strip() for r in os.environ["NOTIFY_TO"].split(",") if r.strip()]
    payload = {
        "from":    os.environ["NOTIFY_FROM"],
        "to":      recipients,
        "subject": subject,
        "html":    html_body,
        "text":    text_body,
    }
    if attachment:
        payload["attachments"] = [attachment]
    headers = {
        "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
        "Content-Type":  "application/json",
    }

    # The digest doubles as a daily heartbeat, so retry transient failures
    # (network errors, 429, 5xx). Hard 4xx rejections won't change on retry.
    for attempt in range(1, SEND_MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(
                RESEND_ENDPOINT, headers=headers, json=payload,
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            log(f"notify: network error talking to Resend "
                f"(attempt {attempt}/{SEND_MAX_ATTEMPTS}): {e}")
            if attempt < SEND_MAX_ATTEMPTS:
                time.sleep(SEND_RETRY_BACKOFF_SECONDS * attempt)
                continue
            return False

        if resp.status_code in (200, 202):
            try:
                email_id = resp.json().get("id", "?")
            except Exception:
                email_id = "?"
            extra = f" + attachment {attachment['filename']}" if attachment else ""
            log(f"notify: sent to {', '.join(recipients)} (Resend id={email_id}){extra}")
            return True

        # Retry on transient server-side / rate-limit responses.
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < SEND_MAX_ATTEMPTS:
            log(f"notify: Resend transient HTTP {resp.status_code} "
                f"(attempt {attempt}/{SEND_MAX_ATTEMPTS}), retrying...")
            time.sleep(SEND_RETRY_BACKOFF_SECONDS * attempt)
            continue

        try:
            err = resp.json()
            log(f"notify: Resend rejected (HTTP {resp.status_code}): "
                f"{err.get('name', '')} — {err.get('message', '')}")
        except Exception:
            log(f"notify: Resend rejected (HTTP {resp.status_code}): {resp.text[:300]}")
        return False

    return False


def _resend_comp_report_attachment(log) -> dict | None:
    """Attach the consolidated Rent_Comp_Report.xlsx if it exists."""
    path = comp_report_path()
    if not path.is_file():
        log(f"notify: no comp report at {path}, skipping attachment")
        return None
    raw = path.read_bytes()
    max_raw = 28 * 1024 * 1024
    if len(raw) > max_raw:
        log(f"notify: comp report too large ({len(raw)} bytes), not attaching")
        return None
    log(f"notify: attaching comp report {path.name} ({len(raw) / 1024:.1f} KB)")
    return {
        "filename": path.name,
        "content": base64.b64encode(raw).decode("ascii"),
    }


def _resend_attachment_for_snapshot(snapshot_id: int, log) -> dict | None:
    """Build one Resend `attachments` element, or None if not applicable."""
    with db() as conn:
        row = conn.execute(
            "SELECT fetch_status FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
    if not row or row["fetch_status"] != "success":
        return None
    path = report_workbook_path()
    if not path.is_file():
        log(f"notify: no workbook at {path}, skipping attachment")
        return None
    raw = path.read_bytes()
    max_raw = 28 * 1024 * 1024
    if len(raw) > max_raw:
        log(f"notify: workbook too large ({len(raw)} bytes), not attaching")
        return None
    log(f"notify: attaching workbook {path.name} ({len(raw) / 1024:.1f} KB)")
    return {
        "filename": path.name,
        "content": base64.b64encode(raw).decode("ascii"),
    }


# --- CLI for testing --------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="Email notification module.")
    parser.add_argument("--test", action="store_true",
                        help="Send a digest of the latest snapshot now (skips the daily run).")
    parser.add_argument("--snapshot-id", type=int, default=None,
                        help="Send the digest for a specific snapshot id.")
    args = parser.parse_args()

    if not args.test and args.snapshot_id is None:
        parser.print_help()
        sys.exit(0)

    sent = send_digest(snapshot_id=args.snapshot_id)
    sys.exit(0 if sent else 1)


if __name__ == "__main__":
    _cli()
