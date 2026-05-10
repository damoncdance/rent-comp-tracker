"""Digest assembly — builds (subject, text_body, html_body) tuples."""
from __future__ import annotations

import json

from src.notify._helpers import e, fmt_dt, dashboard_url
from src.notify._html import (
    html_multi_template,
    html_template,
    html_mix,
    html_changes,
)


def build_multi_digest(prop_results: list[dict]) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a multi-property digest."""
    total_props = len(prop_results)
    successes = sum(1 for r in prop_results if r["success"])
    total_changes = sum(len(r["events"]) for r in prop_results)
    total_units = sum(len(r["units"]) for r in prop_results if r["success"])

    if total_props == 1:
        r = prop_results[0]
        if not r["success"]:
            return build_failure_digest_single(r)
        return build_success_digest_single(r)

    # Multi-property subject line
    if successes == total_props:
        subject = f"Rent Comps — {total_props} properties, {total_units} units, {total_changes} changes"
    else:
        subject = f"Rent Comps — {successes}/{total_props} OK, {total_units} units, {total_changes} changes"

    # Pricing insights
    pricing_text, pricing_html = build_pricing_section()

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

    for r in prop_results:
        if r["success"] and r["events"]:
            name = r["property"]["name"]
            text.append(f"CHANGES — {name} ({len(r['events'])})")
            text.append("")
            text.extend(text_change_lines(r["events"]))
            text.append("")

    if pricing_text:
        text.extend(pricing_text)
        text.append("")

    text.append(f"Dashboard: {dashboard_url()}")
    text_body = "\n".join(text)

    # --- HTML ---
    html_body = html_multi_template(prop_results, subject, pricing_html)

    return subject, text_body, html_body


def build_success_digest_single(r: dict) -> tuple[str, str, str]:
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
    fetched = fmt_dt(snap["fetched_at"])

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
        text.extend(text_change_lines(events))
        text.append("")
    else:
        text.append("CHANGES: none")
        text.append("")

    text.append(f"Dashboard: {dashboard_url()}")
    text_body = "\n".join(text)

    html_body = html_template(
        property_name=name,
        fetched=fetched,
        status_label="SUCCESS",
        status_color="#1a7f37",
        total=total,
        delta=delta,
        mix_html=html_mix(counts_by_bed),
        rent_range=f"${min(rents):,.0f} - ${max(rents):,.0f}",
        avg_rent=f"${avg_rent:,.0f}",
        changes_html=html_changes(events),
        dashboard_url=dashboard_url(),
        workbook_attached=False,
    )
    return subject, text_body, html_body


def build_failure_digest_single(r: dict) -> tuple[str, str, str]:
    """Classic single-property failure digest."""
    name = r["property"]["name"]
    snap = r["snap"]
    subject = f"Rent Comps — {name}: FETCH FAILED"
    fetched = fmt_dt(snap["fetched_at"]) if snap else "N/A"
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

    html_body = html_template(
        property_name=name,
        fetched=fetched,
        status_label="FETCH FAILED",
        status_color="#cf222e",
        total="—",
        delta="",
        mix_html=f"<div style='color:#666'>HTTP {e(http)} — {e(reason)}</div>",
        rent_range="—",
        avg_rent="—",
        changes_html="<p style='color:#666;margin:0'>If failures continue, see the "
                     "<code>scraper-recovery</code> skill in your project.</p>",
        dashboard_url=dashboard_url(),
        workbook_attached=False,
    )
    return subject, text_body, html_body


def text_change_lines(events):
    grouped = {"unit_added": [], "unit_removed": [], "rent_changed": [], "date_changed": []}
    for ev in events:
        grouped.setdefault(ev["event_type"], []).append(ev)

    lines = []
    if grouped["unit_added"]:
        lines.append(f"  ADDED ({len(grouped['unit_added'])}):")
        for ev in grouped["unit_added"]:
            nv = json.loads(ev["new_value"]) if ev["new_value"] else {}
            lines.append(f"    {ev['unit_code']} - {nv.get('floorplan_name','')} "
                         f"({int(nv.get('sqft') or 0)} sf) - ${nv.get('min_rent',0):,.0f}")
        lines.append("")
    if grouped["unit_removed"]:
        lines.append(f"  REMOVED ({len(grouped['unit_removed'])}):")
        for ev in grouped["unit_removed"]:
            ov = json.loads(ev["old_value"]) if ev["old_value"] else {}
            lines.append(f"    {ev['unit_code']} - {ov.get('floorplan_name','')} "
                         f"({int(ov.get('sqft') or 0)} sf) - was ${ov.get('min_rent',0):,.0f}")
        lines.append("")
    if grouped["rent_changed"]:
        lines.append(f"  RENT CHANGES ({len(grouped['rent_changed'])}):")
        for ev in grouped["rent_changed"]:
            ov = json.loads(ev["old_value"]) if ev["old_value"] else 0
            nv = json.loads(ev["new_value"]) if ev["new_value"] else 0
            d = (nv or 0) - (ov or 0)
            sign = "+" if d >= 0 else "-"
            lines.append(f"    {ev['unit_code']} - ${ov:,.0f} -> ${nv:,.0f} "
                         f"({sign}${abs(d):,.0f})")
        lines.append("")
    if grouped["date_changed"]:
        lines.append(f"  AVAILABLE DATE CHANGES ({len(grouped['date_changed'])}):")
        for ev in grouped["date_changed"]:
            ov = json.loads(ev["old_value"]) if ev["old_value"] else ""
            nv = json.loads(ev["new_value"]) if ev["new_value"] else ""
            lines.append(f"    {ev['unit_code']} - {(ov or '')[:10]} -> {(nv or '')[:10]}")
        lines.append("")
    return lines


def build_pricing_section() -> tuple[list[str], str]:
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
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-family:monospace;font-size:12px;">{e(u.unit_code)}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;">{u.beds}BR / {int(u.sqft)} sf</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;text-align:right;">${u.listed_rent:,.0f}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;text-align:right;font-weight:600;">${u.recommended_rent:,.0f}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;text-align:right;">{d_sign}${u.delta:,.0f}</td>'
            f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:12px;color:{sig_color};font-weight:600;">{e(signal_label(u.signal))}</td>'
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
