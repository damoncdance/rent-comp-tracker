"""Render the static HTML dashboard.

Single-file output: dashboard/index.html. Embeds JSON data inline and pulls
Chart.js from a CDN at view time. No build step, no server.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

from src.config import DASHBOARD_DIR, PROPERTY_NAME, PROPERTY_URL
from src.fees import FEES
from src.storage import (
    db, latest_snapshot_id, snapshot_summary_history, recent_changes,
)


def render() -> str:
    """Build dashboard/index.html from current DB state. Returns the path."""
    snap_id = latest_snapshot_id()
    if snap_id is None:
        html = _empty_state_html()
    else:
        ctx = _build_context(snap_id)
        html = _render_html(ctx)

    out = DASHBOARD_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return str(out)


def _build_context(snap_id: int) -> dict:
    with db() as conn:
        snap = dict(conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snap_id,)
        ).fetchone())
        units = [dict(r) for r in conn.execute(
            "SELECT * FROM units WHERE snapshot_id = ? ORDER BY beds, floorplan_name, unit_code",
            (snap_id,),
        ).fetchall()]

    history_rows = snapshot_summary_history(limit=90)

    # Build per-snapshot timeline: unit_count and avg rent by bed type
    by_snap: dict[int, dict] = {}
    for r in history_rows:
        s = by_snap.setdefault(r["id"], {
            "id": r["id"], "fetched_at": r["fetched_at"], "unit_count": r["unit_count"],
            "avg_rent_by_bed": {},
        })
        s["avg_rent_by_bed"][r["beds"]] = r["avg_rent"]
    timeline = sorted(by_snap.values(), key=lambda x: x["fetched_at"])

    # Bed-type breakdown for current snapshot
    by_bed: dict[int, list[dict]] = defaultdict(list)
    for u in units:
        by_bed[u["beds"]].append(u)

    return {
        "property_name": PROPERTY_NAME,
        "property_url":  PROPERTY_URL,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "snapshot":      snap,
        "units":         units,
        "by_bed":        dict(by_bed),
        "timeline":      timeline,
        "changes":       recent_changes(limit=50),
        "fees":          FEES.get(PROPERTY_NAME),
    }


def _render_fees_tab(fees: dict | None) -> str:
    """Build the Fees tab HTML content."""
    if fees is None:
        return ('<div class="card span-12">'
                '<p class="muted">No fee schedule configured for this property.</p>'
                '</div>')

    sections = []

    # Application & admin fees
    if fees.get("application"):
        rows = ""
        for item in fees["application"]:
            rows += (f"<tr><td>{_e(item['item'])}</td>"
                     f"<td class='num'>{_e(item['cost'])}</td>"
                     f"<td class='note'>{_e(item.get('note', ''))}</td></tr>")
        sections.append(
            '<div class="card span-6">'
            '<h2>Application &amp; admin</h2>'
            '<div class="scroll"><table>'
            '<thead><tr><th>Fee</th><th class="num">Amount</th><th>Note</th></tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table></div></div>'
        )

    # Parking
    if fees.get("parking"):
        rows = ""
        for item in fees["parking"]:
            rows += (f"<tr><td>{_e(item['type'])}</td>"
                     f"<td class='num'>{_e(item['cost'])}</td></tr>")
        sections.append(
            '<div class="card span-6">'
            '<h2>Parking</h2>'
            '<div class="scroll"><table>'
            '<thead><tr><th>Type</th><th class="num">Monthly</th></tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table></div></div>'
        )

    # Bundled services
    if fees.get("bundled"):
        rows = ""
        for item in fees["bundled"]:
            rows += (f"<tr><td>{_e(item['type'])}</td>"
                     f"<td class='num'>{_e(item['cost'])}</td></tr>")
        note_html = ""
        if fees.get("bundled_note"):
            note_html = '<div class="small" style="margin:-2px 0 8px">' + _e(fees["bundled_note"]) + '</div>'
        sections.append(
            '<div class="card span-6">'
            '<h2>Bundled services</h2>'
            + note_html +
            '<div class="scroll"><table>'
            '<thead><tr><th>Unit type</th><th class="num">Monthly</th></tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table></div></div>'
        )

    # Pets
    if fees.get("pets"):
        rows = ""
        for item in fees["pets"]:
            rows += (f"<tr><td>{_e(item['item'])}</td>"
                     f"<td class='num'>{_e(item['cost'])}</td></tr>")
        note_html = ""
        if fees.get("pet_policy"):
            note_html = '<div class="small">' + _e(fees["pet_policy"]) + '</div>'
        sections.append(
            '<div class="card span-6">'
            '<h2>Pets</h2>'
            '<div class="scroll"><table>'
            '<thead><tr><th>Fee</th><th class="num">Amount</th></tr></thead>'
            f'<tbody>{rows}</tbody>'
            '</table></div>'
            + note_html +
            '</div>'
        )

    # Disclaimer
    if fees.get("disclaimer"):
        sections.append(
            '<div class="card span-12">'
            f'<p class="disclaimer">{_e(fees["disclaimer"])}</p>'
            '</div>'
        )

    return "\n".join(sections)


def _render_html(ctx: dict) -> str:
    """Build the HTML string. Plain f-string templating; no Jinja dependency."""
    snap = ctx["snapshot"]
    units = ctx["units"]
    fetched = _fmt_dt(snap["fetched_at"])

    # Headline numbers
    counts_by_bed = {b: len(rows) for b, rows in ctx["by_bed"].items()}
    rents = [u["min_rent"] for u in units]
    avg_rent = sum(rents) / len(rents) if rents else 0
    min_rent = min(rents) if rents else 0
    max_rent = max(rents) if rents else 0

    # Unit table rows
    bed_label = lambda b: "Studio" if b == 0 else f"{b} BR"
    unit_rows_html = "".join(
        f"<tr>"
        f"<td>{bed_label(u['beds'])}</td>"
        f"<td>{_e(u['floorplan_name'])}</td>"
        f"<td class='mono'>{_e(u['unit_code'])}</td>"
        f"<td class='num'>{int(u['sqft']):,}</td>"
        f"<td class='num'>${u['min_rent']:,.0f}</td>"
        f"<td>{_fmt_date(u['available_date'])}</td>"
        f"</tr>"
        for u in units
    )

    # Recent changes rows
    changes_html = "".join(_render_change_row(c) for c in ctx["changes"]) \
                   or "<tr><td colspan='4' class='muted'>No changes recorded yet — need at least 2 snapshots.</td></tr>"

    # Timeline data for Chart.js
    timeline_json = json.dumps([
        {"t": t["fetched_at"], "count": t["unit_count"]}
        for t in ctx["timeline"]
    ])
    avg_rent_series_json = json.dumps([
        {
            "t": t["fetched_at"],
            "studio":  t["avg_rent_by_bed"].get(0),
            "one_br":  t["avg_rent_by_bed"].get(1),
            "two_br":  t["avg_rent_by_bed"].get(2),
            "three_br":t["avg_rent_by_bed"].get(3),
        }
        for t in ctx["timeline"]
    ])

    # Fees tab content
    fees_html = _render_fees_tab(ctx.get("fees"))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_e(ctx['property_name'])} — Availability Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --fg:#e8e8e8; --fg-strong:#fff; --muted:#8a8f98; --bg:#0e1117; --card:#161b22;
    --line:#30363d; --accent:#58a6ff; --accent-soft:rgba(88,166,255,0.08);
    --green:#3fb950; --red:#f85149; --yellow:#d29922;
    --mono:ui-monospace,SFMono-Regular,"Cascadia Mono",Menlo,monospace;
  }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--fg); margin:0;
    padding:0 clamp(12px,3vw,24px) 48px;
    font-size:13px; line-height:1.45; -webkit-font-smoothing:antialiased;
  }}
  header {{
    max-width:1200px; margin:0 auto;
    padding:16px 0 0; display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
  }}
  h1 {{
    font-size:15px; font-weight:700; color:var(--fg-strong);
    letter-spacing:-0.01em; white-space:nowrap;
  }}
  .meta {{
    color:var(--muted); font-size:12px; font-family:var(--mono);
    display:flex; gap:6px; flex-wrap:wrap; align-items:baseline;
  }}
  .meta a {{ color:var(--accent); text-decoration:none; }}
  .meta a:hover {{ text-decoration:underline; }}
  .meta .sep {{ opacity:0.35; }}

  /* Tab bar */
  .tabs {{
    max-width:1200px; margin:0 auto;
    display:flex; gap:0; border-bottom:1px solid var(--line);
    padding-top:10px;
  }}
  .tab {{
    padding:8px 18px; font-size:12px; font-weight:600; color:var(--muted);
    text-transform:uppercase; letter-spacing:.05em; cursor:pointer;
    border:1px solid transparent; border-bottom:none; border-radius:4px 4px 0 0;
    background:none; font-family:inherit; position:relative; bottom:-1px;
  }}
  .tab:hover {{ color:var(--fg); }}
  .tab.active {{
    color:var(--fg-strong); background:var(--bg);
    border-color:var(--line); border-bottom:1px solid var(--bg);
  }}
  .tab-panel {{ display:none; }}
  .tab-panel.active {{ display:block; }}

  .grid {{
    max-width:1200px; margin:12px auto 0; display:grid;
    grid-template-columns:repeat(12,minmax(0,1fr)); gap:10px;
  }}
  .card {{
    background:var(--card); border:1px solid var(--line); border-radius:6px;
    padding:14px 16px;
  }}
  .span-3 {{ grid-column:span 3; }} .span-4 {{ grid-column:span 4; }}
  .span-5 {{ grid-column:span 5; }} .span-6 {{ grid-column:span 6; }}
  .span-7 {{ grid-column:span 7; }} .span-8 {{ grid-column:span 8; }}
  .span-12 {{ grid-column:span 12; }}
  @media (max-width:960px) {{
    .span-3 {{ grid-column:span 6; }}
    .span-4,.span-5,.span-6,.span-7,.span-8 {{ grid-column:span 12; }}
  }}
  @media (max-width:520px) {{
    .span-3 {{ grid-column:span 12; }}
  }}

  /* KPI stat cards */
  .stat-card {{ display:flex; flex-direction:column; gap:2px; min-height:68px; justify-content:center; }}
  .label {{
    font-size:10px; color:var(--muted); text-transform:uppercase;
    letter-spacing:.08em; font-weight:600;
  }}
  .stat {{
    font-size:22px; font-weight:700; color:var(--fg-strong);
    font-family:var(--mono); line-height:1.15;
    font-variant-numeric:tabular-nums;
  }}

  /* Section headings */
  h2 {{
    font-size:12px; font-weight:600; color:var(--muted);
    text-transform:uppercase; letter-spacing:.06em;
    margin:0 0 10px; padding-bottom:8px; border-bottom:1px solid var(--line);
  }}
  .small {{
    font-size:11px; color:var(--muted); margin-top:10px;
    font-family:var(--mono); line-height:1.4;
  }}

  /* Charts */
  .chart-wrap {{ position:relative; height:220px; width:100%; }}

  /* Tables */
  table {{ width:100%; border-collapse:collapse; font-size:12px; font-family:var(--mono); }}
  th,td {{ text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
  tbody tr:hover td {{ background:var(--accent-soft); }}
  th {{
    background:var(--card); font-weight:600; font-size:10px;
    text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
    position:sticky; top:0; z-index:1;
  }}
  th.num {{ text-align:right; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.mono {{ font-size:12px; }}
  td.note {{ color:var(--muted); font-size:11px; }}
  .muted {{ color:var(--muted); text-align:center; padding:24px !important; font-size:12px; }}
  .scroll {{
    max-height:min(540px,58vh); overflow:auto;
    border-radius:4px; border:1px solid var(--line);
    background:var(--card);
  }}
  .scroll table {{ margin:0; }}

  /* Badges */
  .badge {{
    display:inline-block; padding:2px 7px; border-radius:3px;
    font-size:10px; font-weight:700; letter-spacing:.03em;
    text-transform:uppercase; white-space:nowrap; font-family:var(--mono);
  }}
  .badge-add {{ background:rgba(63,185,80,0.15); color:var(--green); }}
  .badge-remove {{ background:rgba(248,81,73,0.15); color:var(--red); }}
  .badge-change {{ background:rgba(210,153,34,0.15); color:var(--yellow); }}

  /* Fees-specific */
  .disclaimer {{
    color:var(--muted); font-size:11px; font-style:italic;
    line-height:1.5; font-family:var(--mono);
  }}
</style>
</head>
<body>
<header>
  <h1>{_e(ctx['property_name'])}</h1>
  <div class="meta">
    <span>snap #{snap['id']}</span><span class="sep">/</span>
    <span>{fetched}</span><span class="sep">/</span>
    <a href="{_e(ctx['property_url'])}" target="_blank" rel="noopener">source</a>
  </div>
</header>

<div class="tabs">
  <button class="tab active" data-tab="availability">Availability</button>
  <button class="tab" data-tab="fees">Fees</button>
</div>

<div id="tab-availability" class="tab-panel active">
<div class="grid">
  <div class="card span-3 stat-card"><div class="label">Units avail</div><div class="stat">{snap['unit_count']}</div></div>
  <div class="card span-3 stat-card"><div class="label">Avg rent</div><div class="stat">${avg_rent:,.0f}</div></div>
  <div class="card span-3 stat-card"><div class="label">Low</div><div class="stat">${min_rent:,.0f}</div></div>
  <div class="card span-3 stat-card"><div class="label">High</div><div class="stat">${max_rent:,.0f}</div></div>

  <div class="card span-4">
    <h2>Unit mix</h2>
    <div class="chart-wrap"><canvas id="mixChart" aria-label="Unit mix chart"></canvas></div>
  </div>
  <div class="card span-8">
    <h2>Availability</h2>
    <div class="chart-wrap"><canvas id="totalChart" aria-label="Units over time chart"></canvas></div>
    <div class="small">daily snapshots — history builds over time</div>
  </div>

  <div class="card span-12">
    <h2>Avg rent by type</h2>
    <div class="chart-wrap"><canvas id="rentChart" aria-label="Average rent by type chart"></canvas></div>
  </div>

  <div class="card span-7">
    <h2>Current units ({len(units)})</h2>
    <div class="scroll">
      <table>
        <thead><tr><th>Type</th><th>Tier</th><th>Unit</th><th class="num">Sqft</th><th class="num">Rent</th><th>Avail</th></tr></thead>
        <tbody>{unit_rows_html}</tbody>
      </table>
    </div>
  </div>

  <div class="card span-5">
    <h2>Recent changes</h2>
    <div class="scroll">
      <table>
        <thead><tr><th>When</th><th>Event</th><th>Unit</th><th>Detail</th></tr></thead>
        <tbody>{changes_html}</tbody>
      </table>
    </div>
  </div>
</div>
</div>

<div id="tab-fees" class="tab-panel">
<div class="grid">
  {fees_html}
</div>
</div>

<script>
/* Tab switching */
document.querySelectorAll('.tab').forEach(function(btn) {{
  btn.addEventListener('click', function() {{
    document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
    document.querySelectorAll('.tab-panel').forEach(function(p) {{ p.classList.remove('active'); }});
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
  }});
}});

Chart.defaults.color = '#8a8f98';
Chart.defaults.borderColor = '#30363d';
Chart.defaults.font.family = "ui-monospace,SFMono-Regular,'Cascadia Mono',Menlo,monospace";
Chart.defaults.font.size = 11;

const counts = {json.dumps({bed_label(b): n for b, n in sorted(counts_by_bed.items())})};
new Chart(document.getElementById('mixChart'), {{
  type: 'doughnut',
  data: {{
    labels: Object.keys(counts),
    datasets: [{{ data: Object.values(counts), backgroundColor: ['#58a6ff','#3fb950','#d29922','#f85149'], borderWidth: 0 }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    cutout: '58%',
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 12, font: {{ size: 11 }}, color: '#8a8f98' }} }}
    }}
  }}
}});

const timeline = {timeline_json};
new Chart(document.getElementById('totalChart'), {{
  type: 'line',
  data: {{
    labels: timeline.map(p => p.t.slice(0,10)),
    datasets: [{{ label: 'Available units', data: timeline.map(p => p.count),
                  borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.08)', tension: 0.25, fill: true,
                  borderWidth: 1.5, pointRadius: 2, pointHoverRadius: 4, pointBackgroundColor: '#58a6ff' }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ intersect: false, mode: 'index' }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, font: {{ size: 10 }} }} }},
      y: {{ beginAtZero: true, ticks: {{ font: {{ size: 10 }}, precision: 0 }}, grid: {{ color: 'rgba(48,54,61,0.6)' }} }}
    }},
    plugins: {{ legend: {{ display: false }} }}
  }}
}});

const rentSeries = {avg_rent_series_json};
new Chart(document.getElementById('rentChart'), {{
  type: 'line',
  data: {{
    labels: rentSeries.map(p => p.t.slice(0,10)),
    datasets: [
      {{ label: 'Studio',  data: rentSeries.map(p => p.studio),   borderColor: '#58a6ff', tension: 0.25, borderWidth: 1.5, pointRadius: 2 }},
      {{ label: '1 BR',    data: rentSeries.map(p => p.one_br),   borderColor: '#3fb950', tension: 0.25, borderWidth: 1.5, pointRadius: 2 }},
      {{ label: '2 BR',    data: rentSeries.map(p => p.two_br),   borderColor: '#d29922', tension: 0.25, borderWidth: 1.5, pointRadius: 2 }},
      {{ label: '3 BR',    data: rentSeries.map(p => p.three_br), borderColor: '#f85149', tension: 0.25, borderWidth: 1.5, pointRadius: 2 }},
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ intersect: false, mode: 'index' }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, font: {{ size: 10 }} }} }},
      y: {{
        ticks: {{
          callback: v => (v == null || v === '' ? '' : '$' + Number(v).toLocaleString()),
          font: {{ size: 10 }}
        }},
        grid: {{ color: 'rgba(48,54,61,0.6)' }}
      }}
    }},
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 14, usePointStyle: true, font: {{ size: 11 }}, color: '#8a8f98' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""


def _render_change_row(c: dict) -> str:
    when = _fmt_dt(c["snapshot_fetched_at"])
    et = c["event_type"]
    unit = _e(c["unit_code"])
    if et == "unit_added":
        nv = json.loads(c["new_value"]) if c["new_value"] else {}
        detail = f"{nv.get('floorplan_name','')} — ${nv.get('min_rent',0):,.0f}"
        badge = "<span class='badge badge-add'>added</span>"
    elif et == "unit_removed":
        ov = json.loads(c["old_value"]) if c["old_value"] else {}
        detail = f"was {ov.get('floorplan_name','')} — ${ov.get('min_rent',0):,.0f}"
        badge = "<span class='badge badge-remove'>removed</span>"
    elif et == "rent_changed":
        ov = json.loads(c["old_value"]) if c["old_value"] else 0
        nv = json.loads(c["new_value"]) if c["new_value"] else 0
        delta = (nv or 0) - (ov or 0)
        sign = "+" if delta >= 0 else "−"
        detail = f"${ov:,.0f} → ${nv:,.0f} ({sign}${abs(delta):,.0f})"
        badge = "<span class='badge badge-change'>rent</span>"
    elif et == "date_changed":
        ov = json.loads(c["old_value"]) if c["old_value"] else ""
        nv = json.loads(c["new_value"]) if c["new_value"] else ""
        detail = f"{(ov or '')[:10]} → {(nv or '')[:10]}"
        badge = "<span class='badge badge-change'>date</span>"
    else:
        detail = ""
        badge = f"<span class='badge'>{_e(et)}</span>"
    return f"<tr><td>{when}</td><td>{badge}</td><td class='mono'>{unit}</td><td>{_e(detail)}</td></tr>"


def _empty_state_html() -> str:
    return """<!doctype html><html><head><title>Rent Comp Tracker</title>
<style>
  body{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
       padding:48px;color:#8a8f98;background:#0e1117;max-width:600px;margin:auto}
  h1{color:#e8e8e8;font-size:16px;font-weight:700}
  code{color:#58a6ff}
</style>
</head><body><h1>No data yet</h1>
<p>Run <code>python -m src.daily_run</code> to capture the first snapshot, then refresh this page.</p>
</body></html>"""


def _fmt_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y %H:%M UTC")
    except Exception:
        return iso


def _fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except Exception:
        return iso[:10] if iso else ""


def _e(s) -> str:
    """Minimal HTML escape."""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                  .replace(">", "&gt;").replace('"', "&quot;"))
