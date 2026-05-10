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
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone

import requests

from src.config import DASHBOARD_DIR, get_active_properties, get_property_by_id
from src.export_xlsx import comp_report_path, report_workbook_path
from src.storage import db, latest_snapshot_id


RESEND_ENDPOINT = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 30


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

    try:
        err = resp.json()
        log(f"notify: Resend rejected (HTTP {resp.status_code}): "
            f"{err.get('name', '')} — {err.get('message', '')}")
    except Exception:
        log(f"notify: Resend rejected (HTTP {resp.status_code}): {resp.text[:300]}")
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


# --- Digest assembly --------------------------------------------------------

def _build_multi_digest(prop_results: list[dict]) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a multi-property digest."""
    total_props = len(prop_results)
    successes = sum(1 for r in prop_results if r["success"])
    total_changes = sum(len(r["events"]) for r in prop_results)
    total_units = sum(len(r["units"]) for r in prop_results if r["success"])

    if total_props == 1:
        # Single property — use the classic format
        r = prop_results[0]
        name = r["property"]["name"]
        if not r["success"]:
            return _build_failure_digest_single(r)
        return _build_success_digest_single(r)

    # Multi-property subject line
    if successes == total_props:
        subject = f"Rent Comps — {total_props} properties, {total_units} units, {total_changes} changes"
    else:
        subject = f"Rent Comps — {successes}/{total_props} OK, {total_units} units, {total_changes} changes"

    # Pricing insights
    pricing_text, pricing_html = _build_pricing_section()

    # --- TEXT ---
    text = [
        "Rent Comp Tracker — Daily Digest",
        f"Properties: {total_props}  |  Units: {total_units}  |  Changes: {total_changes}",
        "",
        "SUMMARY",
        "-" * 50,
    ]
    for r in prop_results:
        name = r["property"]["name"]
        subject_tag = " [SUBJECT]" if r["property"].get("is_subject") else ""
        if r["success"]:
            n = len(r["units"])
            c = len(r["events"])
            delta = ""
            if r["prev_unit_count"] is not None:
                d = n - r["prev_unit_count"]
                if d != 0:
                    delta = f" ({d:+d})"
            text.append(f"  ✓ {name}{subject_tag}: {n} units{delta}, {c} changes")
        else:
            reason = r["snap"]["fetch_status"].replace("failed:", "") if r["snap"] else "unknown"
            text.append(f"  ✗ {name}{subject_tag}: FAILED — {reason[:60]}")

    text.extend(["", ""])

    # Per-property details for successful properties with changes
    for r in prop_results:
        if r["success"] and r["events"]:
            name = r["property"]["name"]
            text.append(f"CHANGES — {name} ({len(r['events'])})")
            text.append("")
            text.extend(_text_change_lines(r["events"]))
            text.append("")

    if pricing_text:
        text.extend(pricing_text)
        text.append("")

    text.append(f"Dashboard: {_dashboard_url()}")
    text_body = "\n".join(text)

    # --- HTML ---
    html_body = _html_multi_template(prop_results, subject, pricing_html)

    return subject, text_body, html_body


def _build_success_digest_single(r: dict) -> tuple[str, str, str]:
    """Classic single-property success digest."""
    name = r["property"]["name"]
    snap = r["snap"]
    units = r["units"]
    events = r["events"]
    prev_unit_count = r["prev_unit_count"]

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
        subject = f"Rent Comps — {name}: {total} units{delta}, {len(events)} changes"
    else:
        subject = f"Rent Comps — {name}: {total} units, no changes"

    bed_label = lambda b: "Studio" if b == 0 else f"{b} BR"
    mix = " | ".join(f"{bed_label(b)}: {n}" for b, n in sorted(counts_by_bed.items()))
    avg_rent = sum(rents) / len(rents)
    fetched = _fmt_dt(snap["fetched_at"])

    text = [
        f"Rent Comp Tracker — Daily Digest",
        f"Property:  {name}",
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
    text_body = "\n".join(text)

    html_body = _html_template(
        property_name=name,
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
        workbook_attached=False,
    )
    return subject, text_body, html_body


def _build_failure_digest_single(r: dict) -> tuple[str, str, str]:
    """Classic single-property failure digest."""
    name = r["property"]["name"]
    snap = r["snap"]
    subject = f"Rent Comps — {name}: FETCH FAILED"
    fetched = _fmt_dt(snap["fetched_at"]) if snap else "N/A"
    reason = snap["fetch_status"].replace("failed:", "", 1) if snap else "unknown"
    http = snap.get("http_status") or "N/A" if snap else "N/A"

    text_body = "\n".join([
        f"Rent Comp Tracker — Daily Digest",
        f"Property:  {name}",
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
        property_name=name,
        fetched=fetched,
        status_label="FETCH FAILED",
        status_color="#cf222e",
        total="—",
        delta="",
        mix_html=f"<div style='color:#666'>HTTP {_e(http)} — {_e(reason)}</div>",
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


# --- Pricing insights -------------------------------------------------------

def _build_pricing_section() -> tuple[list[str], str]:
    """Build pricing insight text lines and HTML for the email digest.

    Returns (text_lines, html_str). Both empty if no pricing data.
    """
    try:
        from src.pricing import generate_recommendations, signal_label
        report = generate_recommendations()
    except Exception:
        return [], ""

    if report is None or not report.units:
        return [], ""

    s = report.summary
    impact = s["monthly_revenue_impact"]
    impact_sign = "+" if impact >= 0 else ""

    # Text version
    text = [
        "PRICING INSIGHTS",
        "-" * 50,
        f"  Subject: {report.subject_name} (Quality: {s['subject_quality_score']}/10)",
        f"  {s['overpriced_count']} overpriced, {s['market_count']} at market, {s['underpriced_count']} underpriced",
        f"  Avg Listed: ${s['avg_listed']:,}  |  Avg Recommended: ${s['avg_recommended']:,}",
        f"  Revenue impact: {impact_sign}${abs(impact):,}/mo",
        "",
        "  Top opportunities:",
    ]

    # Top 3 largest absolute deltas
    sorted_units = sorted(report.units, key=lambda u: abs(u.delta), reverse=True)[:3]
    for u in sorted_units:
        d_sign = "+" if u.delta >= 0 else ""
        text.append(
            f"    {u.unit_code} ({u.beds}BR, {int(u.sqft)} sf): "
            f"listed ${u.listed_rent:,.0f} → rec ${u.recommended_rent:,.0f} "
            f"({d_sign}${u.delta:,.0f}) — {signal_label(u.signal)}"
        )
    text.append("")

    # HTML version
    signal_colors = {
        "underpriced": "#1a7f37", "market": "#666",
        "overpriced": "#9a6700", "well_above": "#cf222e",
    }

    opp_rows = ""
    for u in sorted_units:
        d_sign = "+" if u.delta >= 0 else ""
        sig_color = signal_colors.get(u.signal, "#666")
        opp_rows += (
            f'<tr>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-family:monospace;font-size:12px;">{_e(u.unit_code)}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;">{u.beds}BR / {int(u.sqft)} sf</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;text-align:right;">${u.listed_rent:,.0f}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;text-align:right;font-weight:600;">${u.recommended_rent:,.0f}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;text-align:right;">{d_sign}${u.delta:,.0f}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;color:{sig_color};font-weight:600;">{_e(signal_label(u.signal))}</td>'
            f'</tr>'
        )

    impact_color = "#1a7f37" if impact >= 0 else "#cf222e"

    html = f"""<tr><td style="padding:0 28px 24px 28px;">
      <h3 style="margin:16px 0 8px 0;font-size:14px;color:#1a1a1a;">Pricing Insights</h3>
      <div style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap;">
        <div style="background:#f6f8fa;padding:8px 12px;border-radius:6px;flex:1;min-width:120px;">
          <div style="font-size:10px;text-transform:uppercase;color:#666;letter-spacing:.05em;">Signals</div>
          <div style="font-size:13px;margin-top:2px;">
            <span style="color:#cf222e;font-weight:600;">{s['overpriced_count']}</span> over
            <span style="margin:0 3px;color:#ccc;">|</span>
            <span style="color:#666;">{s['market_count']}</span> mkt
            <span style="margin:0 3px;color:#ccc;">|</span>
            <span style="color:#1a7f37;font-weight:600;">{s['underpriced_count']}</span> under
          </div>
        </div>
        <div style="background:#f6f8fa;padding:8px 12px;border-radius:6px;flex:1;min-width:120px;">
          <div style="font-size:10px;text-transform:uppercase;color:#666;letter-spacing:.05em;">Revenue Impact</div>
          <div style="font-size:16px;font-weight:600;color:{impact_color};margin-top:2px;">{impact_sign}${abs(impact):,}/mo</div>
        </div>
        <div style="background:#f6f8fa;padding:8px 12px;border-radius:6px;flex:1;min-width:120px;">
          <div style="font-size:10px;text-transform:uppercase;color:#666;letter-spacing:.05em;">Quality Score</div>
          <div style="font-size:16px;font-weight:600;margin-top:2px;">{s['subject_quality_score']}<span style="color:#999;font-size:12px;font-weight:400;">/10</span></div>
        </div>
      </div>
      <div style="font-size:12px;font-weight:600;color:#444;margin-bottom:6px;">Top Opportunities</div>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr>
          <th style="text-align:left;padding:4px 8px;border-bottom:2px solid #e5e7eb;font-size:10px;color:#666;">Unit</th>
          <th style="text-align:left;padding:4px 8px;border-bottom:2px solid #e5e7eb;font-size:10px;color:#666;">Type</th>
          <th style="text-align:right;padding:4px 8px;border-bottom:2px solid #e5e7eb;font-size:10px;color:#666;">Listed</th>
          <th style="text-align:right;padding:4px 8px;border-bottom:2px solid #e5e7eb;font-size:10px;color:#666;">Rec</th>
          <th style="text-align:right;padding:4px 8px;border-bottom:2px solid #e5e7eb;font-size:10px;color:#666;">Delta</th>
          <th style="text-align:left;padding:4px 8px;border-bottom:2px solid #e5e7eb;font-size:10px;color:#666;">Signal</th>
        </tr></thead>
        <tbody>{opp_rows}</tbody>
      </table>
    </td></tr>"""

    return text, html


# --- HTML rendering ---------------------------------------------------------

def _html_multi_template(prop_results: list[dict], subject: str,
                         pricing_html: str = "") -> str:
    """Multi-property email HTML."""
    total_props = len(prop_results)
    successes = sum(1 for r in prop_results if r["success"])
    total_units = sum(len(r["units"]) for r in prop_results if r["success"])
    total_changes = sum(len(r["events"]) for r in prop_results)
    fetched = _fmt_dt(prop_results[0]["snap"]["fetched_at"]) if prop_results[0]["snap"] else "N/A"

    # Summary table rows
    summary_rows = ""
    for r in prop_results:
        name = _e(r["property"]["name"])
        subject_badge = (' <span style="background:#dafbe1;color:#1a7f37;padding:1px 5px;'
                         'border-radius:3px;font-size:10px;font-weight:600;">SUBJECT</span>'
                         if r["property"].get("is_subject") else "")
        if r["success"]:
            n = len(r["units"])
            c = len(r["events"])
            delta = ""
            if r["prev_unit_count"] is not None:
                d = n - r["prev_unit_count"]
                if d != 0:
                    delta = f' <span style="color:#666;">({d:+d})</span>'
            status = '<span style="color:#1a7f37;font-weight:600;">OK</span>'
            summary_rows += (
                f'<tr><td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;">'
                f'{name}{subject_badge}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:center;">{status}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;">{n}{delta}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;">{c}</td></tr>'
            )
        else:
            status = '<span style="color:#cf222e;font-weight:600;">FAILED</span>'
            summary_rows += (
                f'<tr><td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;">'
                f'{name}{subject_badge}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:center;">{status}</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;">—</td>'
                f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;text-align:right;">—</td></tr>'
            )

    # Per-property change details
    change_sections = ""
    for r in prop_results:
        if r["success"] and r["events"]:
            name = _e(r["property"]["name"])
            change_sections += (
                f'<h3 style="margin:16px 0 8px 0;font-size:13px;color:#1a1a1a;">'
                f'{name} — {len(r["events"])} changes</h3>'
                + _html_changes(r["events"])
            )

    no_changes_msg = ""
    if total_changes == 0:
        no_changes_msg = "<p style='color:#666;margin:8px 0;font-size:13px;'>No changes across any property.</p>"

    status_color = "#1a7f37" if successes == total_props else "#d29922"
    status_label = f"{successes}/{total_props} OK"

    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;background:#f6f8fa;color:#1a1a1a;">
  <table role="presentation" width="100%" style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;border-radius:8px;border-collapse:collapse;">
    <tr><td style="padding:24px 28px 12px 28px;border-bottom:1px solid #e5e7eb;">
      <div style="font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:#666;">Rent Comp Tracker</div>
      <div style="font-size:22px;font-weight:600;color:#1f4e78;margin-top:4px;">Daily Digest — {total_props} Properties</div>
      <div style="font-size:13px;color:#666;margin-top:2px;">Snapshot {_e(fetched)}</div>
    </td></tr>
    <tr><td style="padding:20px 28px;">
      <div style="display:inline-block;padding:4px 10px;border-radius:4px;font-size:12px;font-weight:600;color:#fff;background:{status_color};">{_e(status_label)}</div>
      <span style="margin-left:12px;font-size:13px;color:#444;">{total_units} units &middot; {total_changes} changes</span>
    </td></tr>
    <tr><td style="padding:0 28px 16px 28px;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead><tr>
          <th style="text-align:left;padding:6px 8px;border-bottom:2px solid #e5e7eb;font-size:11px;color:#666;">Property</th>
          <th style="text-align:center;padding:6px 8px;border-bottom:2px solid #e5e7eb;font-size:11px;color:#666;">Status</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:2px solid #e5e7eb;font-size:11px;color:#666;">Units</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:2px solid #e5e7eb;font-size:11px;color:#666;">Changes</th>
        </tr></thead>
        <tbody>{summary_rows}</tbody>
      </table>
    </td></tr>
    <tr><td style="padding:8px 28px 20px 28px;text-align:center;">
      <a href="{_e(_dashboard_url())}" style="display:inline-block;background:#7c6bf1;color:#fff;padding:10px 24px;border-radius:5px;font-size:13px;font-weight:600;text-decoration:none;">View Live Dashboard</a>
    </td></tr>
    <tr><td style="padding:0 28px 24px 28px;">
      <h3 style="margin:0 0 10px 0;font-size:14px;color:#1a1a1a;">Changes</h3>
      {change_sections}{no_changes_msg}
    </td></tr>
    {pricing_html}
    <tr><td style="padding:16px 28px;border-top:1px solid #e5e7eb;background:#f6f8fa;border-radius:0 0 8px 8px;">
      <a href="{_e(_dashboard_url())}" style="color:#1f4e78;font-size:13px;text-decoration:none;">View dashboard &rarr;</a>
    </td></tr>
  </table>
</body></html>
"""


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
            sign = "+" if d >= 0 else "-"
            badge = ('<span style="background:#fff8c5;color:#9a6700;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">rent</span>')
            detail = f"${ov:,.0f} -> ${nv:,.0f} ({sign}${abs(d):,.0f})"
        elif et == "date_changed":
            ov = json.loads(e["old_value"]) if e["old_value"] else ""
            nv = json.loads(e["new_value"]) if e["new_value"] else ""
            badge = ('<span style="background:#fff8c5;color:#9a6700;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">date</span>')
            detail = f"{_e((ov or '')[:10])} -> {_e((nv or '')[:10])}"
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
    import html
    return html.escape(str(s), quote=True)


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
