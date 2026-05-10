"""HTML email templates for the notification digest."""
from __future__ import annotations

import json

from src.notify._helpers import e, fmt_dt, dashboard_url


def html_multi_template(prop_results: list[dict], subject: str,
                        pricing_html: str = "") -> str:
    """Multi-property email HTML."""
    total_props = len(prop_results)
    successes = sum(1 for r in prop_results if r["success"])
    total_units = sum(len(r["units"]) for r in prop_results if r["success"])
    total_changes = sum(len(r["events"]) for r in prop_results)
    fetched = fmt_dt(prop_results[0]["snap"]["fetched_at"]) if prop_results[0]["snap"] else "N/A"

    # Summary table rows
    summary_rows = ""
    for r in prop_results:
        name = e(r["property"]["name"])
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
            name = e(r["property"]["name"])
            change_sections += (
                f'<h3 style="margin:16px 0 8px 0;font-size:13px;color:#1a1a1a;">'
                f'{name} — {len(r["events"])} changes</h3>'
                + html_changes(r["events"])
            )

    no_changes_msg = ""
    if total_changes == 0:
        no_changes_msg = "<p style='color:#666;margin:8px 0;font-size:13px;'>No changes across any property.</p>"

    status_color = "#1a7f37" if successes == total_props else "#d29922"
    status_label = f"{successes}/{total_props} OK"

    _dash_url = dashboard_url()

    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;background:#f6f8fa;color:#1a1a1a;">
  <table role="presentation" width="100%" style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;border-radius:8px;border-collapse:collapse;">
    <tr><td style="padding:24px 28px 12px 28px;border-bottom:1px solid #e5e7eb;">
      <div style="font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:#666;">Rent Comp Tracker</div>
      <div style="font-size:22px;font-weight:600;color:#1f4e78;margin-top:4px;">Daily Digest — {total_props} Properties</div>
      <div style="font-size:13px;color:#666;margin-top:2px;">Snapshot {e(fetched)}</div>
    </td></tr>
    <tr><td style="padding:20px 28px;">
      <div style="display:inline-block;padding:4px 10px;border-radius:4px;font-size:12px;font-weight:600;color:#fff;background:{status_color};">{e(status_label)}</div>
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
      <a href="{e(_dash_url)}" style="display:inline-block;background:#7c6bf1;color:#fff;padding:10px 24px;border-radius:5px;font-size:13px;font-weight:600;text-decoration:none;">View Live Dashboard</a>
    </td></tr>
    <tr><td style="padding:0 28px 24px 28px;">
      <h3 style="margin:0 0 10px 0;font-size:14px;color:#1a1a1a;">Changes</h3>
      {change_sections}{no_changes_msg}
    </td></tr>
    {pricing_html}
    <tr><td style="padding:16px 28px;border-top:1px solid #e5e7eb;background:#f6f8fa;border-radius:0 0 8px 8px;">
      <a href="{e(_dash_url)}" style="color:#1f4e78;font-size:13px;text-decoration:none;">View dashboard &rarr;</a>
    </td></tr>
  </table>
</body></html>
"""


def html_template(*, property_name, fetched, status_label, status_color,
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
      <div style="font-size:22px;font-weight:600;color:#1f4e78;margin-top:4px;">{e(property_name)}</div>
      <div style="font-size:13px;color:#666;margin-top:2px;">Snapshot {e(fetched)}</div>
    </td></tr>
    <tr><td style="padding:20px 28px;">
      <div style="display:inline-block;padding:4px 10px;border-radius:4px;font-size:12px;font-weight:600;color:#fff;background:{status_color};">{e(status_label)}</div>
    </td></tr>
    <tr><td style="padding:0 28px 16px 28px;">
      <table width="100%" style="border-collapse:collapse;">
        <tr>
          <td style="padding:12px;background:#f6f8fa;border-radius:6px;width:50%;">
            <div style="font-size:11px;text-transform:uppercase;color:#666;letter-spacing:.05em;">Total available units</div>
            <div style="font-size:28px;font-weight:600;color:#1f4e78;margin-top:2px;">{e(total)}<span style="font-size:14px;color:#666;font-weight:400;"> {e(delta)}</span></div>
          </td>
          <td style="width:12px;"></td>
          <td style="padding:12px;background:#f6f8fa;border-radius:6px;width:50%;">
            <div style="font-size:11px;text-transform:uppercase;color:#666;letter-spacing:.05em;">Average rent</div>
            <div style="font-size:28px;font-weight:600;color:#1f4e78;margin-top:2px;">{e(avg_rent)}</div>
          </td>
        </tr>
      </table>
      <div style="margin-top:16px;font-size:13px;color:#444;">
        <div><strong>Mix:</strong> {mix_html}</div>
        <div style="margin-top:4px;"><strong>Rent range:</strong> {e(rent_range)}</div>
      </div>
    </td></tr>
    <tr><td style="padding:0 28px 24px 28px;">
      <h3 style="margin:0 0 10px 0;font-size:14px;color:#1a1a1a;">Changes</h3>
      {changes_html}
    </td></tr>
    {attach_row}
    <tr><td style="padding:16px 28px;border-top:1px solid #e5e7eb;background:#f6f8fa;border-radius:0 0 8px 8px;">
      <a href="{e(dashboard_url)}" style="color:#1f4e78;font-size:13px;text-decoration:none;">View dashboard &rarr;</a>
    </td></tr>
  </table>
</body></html>
"""


def html_mix(counts_by_bed) -> str:
    bed_label = lambda b: "Studio" if b == 0 else f"{b} BR"
    parts = [f"{bed_label(b)}: <strong>{n}</strong>"
             for b, n in sorted(counts_by_bed.items())]
    return " &nbsp;|&nbsp; ".join(parts)


def html_changes(events) -> str:
    if not events:
        return "<p style='color:#666;margin:0;font-size:13px;'>No changes since last snapshot.</p>"

    rows = []
    for ev in events:
        et = ev["event_type"]
        unit = e(ev["unit_code"])
        if et == "unit_added":
            nv = json.loads(ev["new_value"]) if ev["new_value"] else {}
            badge = ('<span style="background:#dafbe1;color:#1a7f37;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">added</span>')
            detail = (f"{e(nv.get('floorplan_name',''))} — "
                      f"${nv.get('min_rent',0):,.0f}")
        elif et == "unit_removed":
            ov = json.loads(ev["old_value"]) if ev["old_value"] else {}
            badge = ('<span style="background:#ffebe9;color:#cf222e;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">removed</span>')
            detail = (f"was {e(ov.get('floorplan_name',''))} — "
                      f"${ov.get('min_rent',0):,.0f}")
        elif et == "rent_changed":
            ov = json.loads(ev["old_value"]) if ev["old_value"] else 0
            nv = json.loads(ev["new_value"]) if ev["new_value"] else 0
            d = (nv or 0) - (ov or 0)
            sign = "+" if d >= 0 else "-"
            badge = ('<span style="background:#fff8c5;color:#9a6700;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">rent</span>')
            detail = f"${ov:,.0f} -> ${nv:,.0f} ({sign}${abs(d):,.0f})"
        elif et == "date_changed":
            ov = json.loads(ev["old_value"]) if ev["old_value"] else ""
            nv = json.loads(ev["new_value"]) if ev["new_value"] else ""
            badge = ('<span style="background:#fff8c5;color:#9a6700;padding:2px 6px;'
                     'border-radius:3px;font-size:11px;font-weight:600;">date</span>')
            detail = f"{e((ov or '')[:10])} -> {e((nv or '')[:10])}"
        else:
            badge = f'<span style="font-size:11px;">{e(et)}</span>'
            detail = ""
        rows.append(
            f'<tr><td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;width:80px;vertical-align:top;">{badge}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;font-family:ui-monospace,Menlo,monospace;font-size:12px;width:90px;">{unit}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#444;">{detail}</td></tr>'
        )
    return ('<table style="width:100%;border-collapse:collapse;">'
            + "".join(rows) + '</table>')
