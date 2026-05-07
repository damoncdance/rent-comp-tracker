"""Email digest after each daily run, sent via the Resend API.

Sends a multipart (text + HTML) summary of the latest snapshot:
status, current availability, changes vs. previous snapshot, a link
to the dashboard, and (when the export exists) the Excel workbook as an
attachment via Resend.

Configured via environment variables (loaded from .env locally; from
GitHub Actions secrets when running in the cloud):

    NOTIFY_ENABLED      "true" to send, anything else skips silently
    RESEND_API_KEY      from https://resend.com/api-keys
    NOTIFY_FROM         e.g. 'Rent Comps <onboarding@resend.dev>'
    NOTIFY_TO           recipient(s), comma-separated for multiple
    DASHBOARD_URL       optional link in the email
                        (defaults to the local file:// path)

Until you verify a domain in Resend, NOTIFY_FROM must use
'onboarding@resend.dev' and NOTIFY_TO must be the email you signed up
with. Both restrictions lift once you verify any domain you own.

Run a test send (no full daily run needed):
    python -m src.notify --test
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone

import requests

from src.config import DASHBOARD_DIR, PROPERTY_NAME
from src.export_xlsx import report_workbook_path
from src.storage import db, latest_snapshot_id


RESEND_ENDPOINT = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 30


# --- Public API -------------------------------------------------------------

def is_enabled() -> bool:
    return os.environ.get("NOTIFY_ENABLED", "").strip().lower() == "true"


def send_digest(snapshot_id: int | None = None, log=print) -> bool:
    """Send the daily digest. Returns True if sent, False if skipped/failed.

    Never raises — email failures should not break the daily run.
    """
    if not is_enabled():
        log("notify: NOTIFY_ENABLED != true, skipping email")
        return False

    missing = _missing_config()
    if missing:
        log(f"notify: missing env vars: {', '.join(missing)} — skipping email")
        return False

    snap_id = snapshot_id if snapshot_id is not None else latest_snapshot_id()
    if snap_id is None:
        log("notify: no snapshot in DB yet — nothing to send")
        return False

    try:
        attachment = _resend_attachment_for_snapshot(snap_id, log)
        subject, text_body, html_body = _build_digest(
            snap_id, workbook_attached=attachment is not None,
        )
    except Exception as e:
        log(f"notify: digest build failed: {type(e).__name__}: {e}")
        return False

    return _send(subject, text_body, html_body, log, attachment=attachment)


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

    try:
        resp = requests.post(
            RESEND_ENDPOINT, headers=headers, json=payload,
            timeout=SEND_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        log(f"notify: network error talking to Resend: {e}")
        return False

    if resp.status_code in (200, 202):
        try:
            email_id = resp.json().get("id", "?")
        except Exception:
            email_id = "?"
        extra = f" + attachment {attachment['filename']}" if attachment else ""
        log(f"notify: sent to {', '.join(recipients)} (Resend id={email_id}){extra}")
        return True

    # Resend returns helpful JSON on errors; surface it.
    try:
        err = resp.json()
        log(f"notify: Resend rejected (HTTP {resp.status_code}): "
            f"{err.get('name', '')} — {err.get('message', '')}")
    except Exception:
        log(f"notify: Resend rejected (HTTP {resp.status_code}): {resp.text[:300]}")
    return False


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
    max_raw = 28 * 1024 * 1024  # under Resend total-email size limits
    if len(raw) > max_raw:
        log(f"notify: workbook too large ({len(raw)} bytes), not attaching")
        return None
    # Resend expects `filename` + base64 `content` only (see resend.com/docs).
    log(f"notify: attaching workbook {path.name} ({len(raw) / 1024:.1f} KB)")
    return {
        "filename": path.name,
        "content": base64.b64encode(raw).decode("ascii"),
    }


# --- Digest assembly --------------------------------------------------------

def _build_digest(
    snapshot_id: int,
    *,
    workbook_attached: bool = False,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body)."""
    with db() as conn:
        snap = dict(conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone())

        units = []
        prev_unit_count = None
        if snap["fetch_status"] == "success":
            units = [dict(r) for r in conn.execute(
                "SELECT * FROM units WHERE snapshot_id = ? "
                "ORDER BY beds, floorplan_name, unit_code",
                (snapshot_id,),
            ).fetchall()]
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

    if snap["fetch_status"] != "success":
        return _build_failure_digest(snap)

    return _build_success_digest(
        snap, units, events, prev_unit_count,
        workbook_attached=workbook_attached,
    )


def _build_success_digest(
    snap, units, events, prev_unit_count, *, workbook_attached: bool = False,
):
    counts_by_bed = {}
    for u in units:
        counts_by_bed[u["beds"]] = counts_by_bed.get(u["beds"], 0) + 1
    rents = [u["min_rent"] for u in units] or [0]
    total = len(units)

    delta = ""
    if prev_unit_count is not None:
        d = total - prev_unit_count
        if d != 0:
            delta = f" ({d:+d})"

    if events:
        subject = f"Rent Comps — {PROPERTY_NAME}: {total} units{delta}, {len(events)} changes"
    else:
        subject = f"Rent Comps — {PROPERTY_NAME}: {total} units, no changes"

    bed_label = lambda b: "Studio" if b == 0 else f"{b} BR"
    mix = " | ".join(f"{bed_label(b)}: {n}" for b, n in sorted(counts_by_bed.items()))
    avg_rent = sum(rents) / len(rents)
    fetched = _fmt_dt(snap["fetched_at"])

    # --- TEXT ---
    text = [
        f"Rent Comp Tracker — Daily Digest",
        f"Property:  {PROPERTY_NAME}",
        f"Snapshot:  {fetched}",
        f"Status:    SUCCESS",
        f"",
        f"AVAILABILITY",
        f"  Total available units:  {total}{delta}",
        f"  Mix:                    {mix}",
        f"  Rent range:             ${min(rents):,.0f} - ${max(rents):,.0f}",
        f"  Average rent:           ${avg_rent:,.0f}",
        f"",
    ]
    if events:
        text.append(f"CHANGES SINCE LAST SNAPSHOT ({len(events)})")
        text.append("")
        text.extend(_text_change_lines(events))
        text.append("")
    else:
        text.append("CHANGES: none")
        text.append("")

    text.append(f"Dashboard: {_dashboard_url()}")
    if workbook_attached:
        text.append("")
        text.append(
            "Excel workbook attached: "
            f"{report_workbook_path().name} — Availability Matrix, Tier Summary, Raw Data."
        )
    text_body = "\n".join(text)

    # --- HTML ---
    html_body = _html_template(
        property_name=PROPERTY_NAME,
        fetched=fetched,
        status_label="SUCCESS",
        status_color="#1a7f37",
        total=total,
        delta=delta,
        mix_html=_html_mix(counts_by_bed),
        rent_range=f"${min(rents):,.0f} - ${max(rents):,.0f}",
        avg_rent=f"${avg_rent:,.0f}",
        changes_html=_html_changes(events),
        dashboard_url=_dashboard_url(),
        workbook_attached=workbook_attached,
    )

    return subject, text_body, html_body


def _build_failure_digest(snap):
    subject = f"Rent Comps — {PROPERTY_NAME}: FETCH FAILED"
    fetched = _fmt_dt(snap["fetched_at"])
    reason = snap["fetch_status"].replace("failed:", "", 1)
    http = snap.get("http_status") or "N/A"

    text_body = "\n".join([
        f"Rent Comp Tracker — Daily Digest",
        f"Property:  {PROPERTY_NAME}",
        f"Snapshot:  {fetched}",
        f"Status:    FAILED",
        f"",
        f"The daily snapshot did not succeed.",
        f"  HTTP status: {http}",
        f"  Reason:      {reason}",
        f"",
        f"If failures continue, see the scraper-recovery skill in your project.",
    ])

    html_body = _html_template(
        property_name=PROPERTY_NAME,
        fetched=fetched,
        status_label="FETCH FAILED",
        status_color="#cf222e",
        total="—",
        delta="",
        mix_html=f"<div style='color:#666'>HTTP {http} — {_e(reason)}</div>",
        rent_range="—",
        avg_rent="—",
        changes_html="<p style='color:#666;margin:0'>If failures continue, see the "
                     "<code>scraper-recovery</code> skill in your project.</p>",
        dashboard_url=_dashboard_url(),
        workbook_attached=False,
    )

    return subject, text_body, html_body


def _text_change_lines(events):
    grouped = {"unit_added": [], "unit_removed": [], "rent_changed": [], "date_changed": []}
    for e in events:
        grouped.setdefault(e["event_type"], []).append(e)

    lines = []
    if grouped["unit_added"]:
        lines.append(f"  ADDED ({len(grouped['unit_added'])}):")
        for e in grouped["unit_added"]:
            nv = json.loads(e["new_value"]) if e["new_value"] else {}
            lines.append(f"    {e['unit_code']} - {nv.get('floorplan_name','')} "
                         f"({int(nv.get('sqft') or 0)} sf) - ${nv.get('min_rent',0):,.0f}")
        lines.append("")
    if grouped["unit_removed"]:
        lines.append(f"  REMOVED ({len(grouped['unit_removed'])}):")
        for e in grouped["unit_removed"]:
            ov = json.loads(e["old_value"]) if e["old_value"] else {}
            lines.append(f"    {e['unit_code']} - {ov.get('floorplan_name','')} "
                         f"({int(ov.get('sqft') or 0)} sf) - was ${ov.get('min_rent',0):,.0f}")
        lines.append("")
    if grouped["rent_changed"]:
        lines.append(f"  RENT CHANGES ({len(grouped['rent_changed'])}):")
        for e in grouped["rent_changed"]:
            ov = json.loads(e["old_value"]) if e["old_value"] else 0
            nv = json.loads(e["new_value"]) if e["new_value"] else 0
            d = (nv or 0) - (ov or 0)
            sign = "+" if d >= 0 else "-"
            lines.append(f"    {e['unit_code']} - ${ov:,.0f} -> ${nv:,.0f} "
                         f"({sign}${abs(d):,.0f})")
        lines.append("")
    if grouped["date_changed"]:
        lines.append(f"  AVAILABLE DATE CHANGES ({len(grouped['date_changed'])}):")
        for e in grouped["date_changed"]:
            ov = json.loads(e["old_value"]) if e["old_value"] else ""
            nv = json.loads(e["new_value"]) if e["new_value"] else ""
            lines.append(f"    {e['unit_code']} - {(ov or '')[:10]} -> {(nv or '')[:10]}")
        lines.append("")
    return lines


# --- HTML rendering ---------------------------------------------------------

def _html_template(*, property_name, fetched, status_label, status_color,
                   total, delta, mix_html, rent_range, avg_rent,
                   changes_html, dashboard_url, workbook_attached: bool = False) -> str:
    attach_row = ""
    if workbook_attached:
        attach_row = (
            "<tr><td style=\"padding:0 28px 16px 28px;border-top:1px solid #e5e7eb;\">"
            "<p style=\"margin:0;font-size:13px;color:#444;\">"
            "<strong>Excel workbook attached</strong> — Availability Matrix, "
            "Tier Summary, and Raw Data (same file as the repo export).</p>"
            "</td></tr>"
        )
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;background:#f6f8fa;color:#1a1a1a;">
  <table role="presentation" width="100%" style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;border-radius:8px;border-collapse:collapse;">
    <tr><td style="padding:24px 28px 12px 28px;border-bottom:1px solid #e5e7eb;">
      <div style="font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:#666;">Rent Comp Tracker</div>
      <div style="font-size:22px;font-weight:600;color:#1f4e78;margin-top:4px;">{_e(property_name)}</div>
      <div style="font-size:13px;color:#666;margin-top:2px;">Snapshot {_e(fetched)}</div>
    </td></tr>
    <tr><td style="padding:20px 28px;">
      <div style="display:inline-block;padding:4px 10px;border-radius:4px;font-size:12px;font-weight:600;color:#fff;background:{status_color};">{_e(status_label)}</div>
    </td></tr>
    <tr><td style="padding:0 28px 16px 28px;">
      <table width="100%" style="border-collapse:collapse;">
        <tr>
          <td style="padding:12px;background:#f6f8fa;border-radius:6px;width:50%;">
            <div style="font-size:11px;text-transform:uppercase;color:#666;letter-spacing:.05em;">Total available units</div>
            <div style="font-size:28px;font-weight:600;color:#1f4e78;margin-top:2px;">{_e(total)}<span style="font-size:14px;color:#666;font-weight:400;"> {_e(delta)}</span></div>
          </td>
          <td style="width:12px;"></td>
          <td style="padding:12px;background:#f6f8fa;border-radius:6px;width:50%;">
            <div style="font-size:11px;text-transform:uppercase;color:#666;letter-spacing:.05em;">Average rent</div>
            <div style="font-size:28px;font-weight:600;color:#1f4e78;margin-top:2px;">{_e(avg_rent)}</div>
          </td>
        </tr>
      </table>
      <div style="margin-top:16px;font-size:13px;color:#444;">
        <div><strong>Mix:</strong> {mix_html}</div>
        <div style="margin-top:4px;"><strong>Rent range:</strong> {_e(rent_range)}</div>
      </div>
    </td></tr>
    <tr><td style="padding:0 28px 24px 28px;">
      <h3 style="margin:0 0 10px 0;font-size:14px;color:#1a1a1a;">Changes</h3>
      {changes_html}
    </td></tr>
    {attach_row}
    <tr><td style="padding:16px 28px;border-top:1px solid #e5e7eb;background:#f6f8fa;border-radius:0 0 8px 8px;">
      <a href="{_e(dashboard_url)}" style="color:#1f4e78;font-size:13px;text-decoration:none;">View dashboard &rarr;</a>
    </td></tr>
  </table>
</body></html>
"""


def _html_mix(counts_by_bed) -> str:
    bed_label = lambda b: "Studio" if b == 0 else f"{b} BR"
    parts = [f"{bed_label(b)}: <strong>{n}</strong>"
             for b, n in sorted(counts_by_bed.items())]
    return " &nbsp;|&nbsp; ".join(parts)


def _html_changes(events) -> str:
    if not events:
        return "<p style='color:#666;margin:0;font-size:13px;'>No changes since last snapshot.</p>"

    rows = []
    for e in events:
        et = e["event_type"]
        unit = _e(e["unit_code"])
        if et == "unit_added":
            nv = json.loads(e["new_value"]) if e["new_value"] else {}
            badge = ('<span style="background:#dafbe1;color:#1a7f37;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">added</span>')
            detail = (f"{_e(nv.get('floorplan_name',''))} — "
                      f"${nv.get('min_rent',0):,.0f}")
        elif et == "unit_removed":
            ov = json.loads(e["old_value"]) if e["old_value"] else {}
            badge = ('<span style="background:#ffebe9;color:#cf222e;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">removed</span>')
            detail = (f"was {_e(ov.get('floorplan_name',''))} — "
                      f"${ov.get('min_rent',0):,.0f}")
        elif et == "rent_changed":
            ov = json.loads(e["old_value"]) if e["old_value"] else 0
            nv = json.loads(e["new_value"]) if e["new_value"] else 0
            d = (nv or 0) - (ov or 0)
            sign = "+" if d >= 0 else "−"
            badge = ('<span style="background:#fff8c5;color:#9a6700;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">rent</span>')
            detail = f"${ov:,.0f} → ${nv:,.0f} ({sign}${abs(d):,.0f})"
        elif et == "date_changed":
            ov = json.loads(e["old_value"]) if e["old_value"] else ""
            nv = json.loads(e["new_value"]) if e["new_value"] else ""
            badge = ('<span style="background:#fff8c5;color:#9a6700;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">date</span>')
            detail = f"{(ov or '')[:10]} → {(nv or '')[:10]}"
        else:
            badge = f'<span style="font-size:11px;">{_e(et)}</span>'
            detail = ""
        rows.append(
            f'<tr><td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;width:80px;vertical-align:top;">{badge}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;font-family:ui-monospace,Menlo,monospace;font-size:12px;width:90px;">{unit}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#444;">{detail}</td></tr>'
        )
    return ('<table style="width:100%;border-collapse:collapse;">'
            + "".join(rows) + '</table>')


# --- Helpers ----------------------------------------------------------------

def _missing_config() -> list[str]:
    required = ["RESEND_API_KEY", "NOTIFY_FROM", "NOTIFY_TO"]
    return [k for k in required if not os.environ.get(k)]


def _dashboard_url() -> str:
    """DASHBOARD_URL env var if set; otherwise local file:// path."""
    explicit = os.environ.get("DASHBOARD_URL", "").strip()
    if explicit:
        return explicit
    return (DASHBOARD_DIR / "index.html").as_uri()


def _fmt_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return iso


def _e(s) -> str:
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                  .replace(">", "&gt;").replace('"', "&quot;"))


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
