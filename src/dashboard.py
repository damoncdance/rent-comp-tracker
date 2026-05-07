"""Render the static HTML dashboard.

Single-file output: dashboard/index.html. Embeds JSON data inline and pulls
Chart.js from a CDN at view time. No build step, no server.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

from src.config import DASHBOARD_DIR, PROPERTY_NAME, PROPERTY_URL
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
    }


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

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_e(ctx['property_name'])} — Availability Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --fg:#1a1a1a; --muted:#5c5c5c; --bg:#f3f4f6; --card:#fff; --line:#e5e7eb;
    --accent:#1f4e78; --accent-soft:rgba(31,78,120,0.08); --shadow:0 1px 2px rgba(0,0,0,.04),0 4px 12px rgba(0,0,0,.06);
  }}
  * {{ box-sizing:border-box; }}
  body {{
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--fg); margin:0;
    padding:clamp(16px,4vw,32px) clamp(16px,3vw,28px) 48px;
    line-height:1.5; -webkit-font-smoothing:antialiased;
  }}
  header {{
    max-width:1120px; margin:0 auto 28px;
    padding-bottom:20px; border-bottom:1px solid var(--line);
  }}
  h1 {{
    margin:0 0 10px; font-size:clamp(1.25rem,2.5vw,1.75rem); font-weight:700;
    color:var(--accent); line-height:1.25; letter-spacing:-0.02em;
  }}
  .meta {{ color:var(--muted); font-size:14px; line-height:1.55; max-width:62ch; }}
  .meta a {{ color:var(--accent); text-decoration:none; border-bottom:1px solid transparent; }}
  .meta a:hover {{ border-bottom-color:var(--accent); }}
  .grid {{
    max-width:1120px; margin:0 auto; display:grid;
    grid-template-columns:repeat(12,minmax(0,1fr)); gap:clamp(12px,2vw,20px);
  }}
  .card {{
    background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:clamp(16px,2.5vw,22px); box-shadow:var(--shadow);
  }}
  .span-3 {{ grid-column:span 3; }} .span-4 {{ grid-column:span 4; }}
  .span-5 {{ grid-column:span 5; }} .span-6 {{ grid-column:span 6; }}
  .span-7 {{ grid-column:span 7; }} .span-8 {{ grid-column:span 8; }}
  .span-12 {{ grid-column:span 12; }}
  @media (max-width:960px) {{
    .span-3,.span-4,.span-6,.span-8 {{ grid-column:span 12; }}
    .span-5,.span-7 {{ grid-column:span 12; }}
  }}
  .stat-card {{ display:flex; flex-direction:column; justify-content:flex-end; min-height:92px; }}
  .stat {{ font-size:clamp(1.5rem,4vw,2rem); font-weight:700; color:var(--accent); line-height:1.1; margin-top:6px; }}
  .label {{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; font-weight:600; }}
  .small {{ font-size:13px; color:var(--muted); margin-top:12px; line-height:1.45; }}
  h2 {{
    margin:0 0 4px; font-size:15px; font-weight:600; color:var(--fg);
    letter-spacing:-0.01em;
  }}
  .card > h2 + .chart-wrap {{ margin-top:12px; }}
  .chart-wrap {{ position:relative; height:min(260px,42vw); width:100%; min-height:200px; }}
  .chart-wrap--tall {{ height:min(280px,48vw); min-height:220px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
  tbody tr:nth-child(even) td {{ background:var(--accent-soft); }}
  th {{
    background:#f9fafb; font-weight:600; font-size:11px;
    text-transform:uppercase; letter-spacing:.05em; color:var(--muted);
    position:sticky; top:0; z-index:1; box-shadow:0 1px 0 var(--line);
  }}
  th.num {{ text-align:right; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
  .muted {{ color:var(--muted); text-align:center; padding:28px !important; font-size:14px; }}
  .scroll {{
    max-height:min(520px,55vh); overflow:auto; margin:0 -4px;
    padding:0 4px; border-radius:8px; border:1px solid var(--line);
    background:var(--card);
  }}
  .scroll table {{ margin:0; }}
  .badge {{ display:inline-block; padding:3px 8px; border-radius:6px; font-size:11px; font-weight:600; white-space:nowrap; }}
  .badge-add {{ background:#d1fae5; color:#065f46; }}
  .badge-remove {{ background:#fee2e2; color:#991b1b; }}
  .badge-change {{ background:#fef3c7; color:#92400e; }}
</style>
</head>
<body>
<header>
  <h1>{_e(ctx['property_name'])} — Availability</h1>
  <div class="meta">
    Snapshot #{snap['id']} fetched {fetched} •
    <a href="{_e(ctx['property_url'])}" target="_blank" rel="noopener">source page</a> •
    Page generated {_fmt_dt(ctx['generated_at'])}
  </div>
</header>

<div class="grid">
  <div class="card span-3 stat-card"><div class="label">Available units</div><div class="stat">{snap['unit_count']}</div></div>
  <div class="card span-3 stat-card"><div class="label">Avg rent</div><div class="stat">${avg_rent:,.0f}</div></div>
  <div class="card span-3 stat-card"><div class="label">Min rent</div><div class="stat">${min_rent:,.0f}</div></div>
  <div class="card span-3 stat-card"><div class="label">Max rent</div><div class="stat">${max_rent:,.0f}</div></div>

  <div class="card span-4">
    <h2>Mix by unit type</h2>
    <div class="chart-wrap"><canvas id="mixChart" aria-label="Unit mix chart"></canvas></div>
  </div>
  <div class="card span-8">
    <h2>Available units over time</h2>
    <div class="chart-wrap"><canvas id="totalChart" aria-label="Units over time chart"></canvas></div>
    <div class="small">One point per snapshot. Build up history by letting the daily run go for a few days.</div>
  </div>

  <div class="card span-12">
    <h2>Average rent over time, by unit type</h2>
    <div class="chart-wrap chart-wrap--tall"><canvas id="rentChart" aria-label="Average rent by type chart"></canvas></div>
  </div>

  <div class="card span-7">
    <h2>Current units ({len(units)})</h2>
    <div class="scroll">
      <table>
        <thead><tr><th>Type</th><th>Tier</th><th>Unit</th><th class="num">Sq ft</th><th class="num">Rent</th><th>Available</th></tr></thead>
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

<script>
const counts = {json.dumps({bed_label(b): n for b, n in sorted(counts_by_bed.items())})};
new Chart(document.getElementById('mixChart'), {{
  type: 'doughnut',
  data: {{
    labels: Object.keys(counts),
    datasets: [{{ data: Object.values(counts), backgroundColor: ['#1f4e78','#2e75b6','#5b9bd5','#9dc3e6'], borderWidth: 0 }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    cutout: '52%',
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ boxWidth: 12, padding: 14, font: {{ size: 12 }} }} }}
    }}
  }}
}});

const timeline = {timeline_json};
new Chart(document.getElementById('totalChart'), {{
  type: 'line',
  data: {{
    labels: timeline.map(p => p.t.slice(0,10)),
    datasets: [{{ label: 'Available units', data: timeline.map(p => p.count),
                  borderColor: '#1f4e78', backgroundColor: 'rgba(31,78,120,0.1)', tension: 0.2, fill: true,
                  borderWidth: 2, pointRadius: 3, pointHoverRadius: 5 }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ intersect: false, mode: 'index' }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, font: {{ size: 11 }} }} }},
      y: {{ beginAtZero: true, ticks: {{ font: {{ size: 11 }} }} }}
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
      {{ label: 'Studio',  data: rentSeries.map(p => p.studio),   borderColor: '#1f4e78', tension: 0.2, borderWidth: 2, pointRadius: 2 }},
      {{ label: '1 BR',    data: rentSeries.map(p => p.one_br),   borderColor: '#2e75b6', tension: 0.2, borderWidth: 2, pointRadius: 2 }},
      {{ label: '2 BR',    data: rentSeries.map(p => p.two_br),   borderColor: '#5b9bd5', tension: 0.2, borderWidth: 2, pointRadius: 2 }},
      {{ label: '3 BR',    data: rentSeries.map(p => p.three_br), borderColor: '#9dc3e6', tension: 0.2, borderWidth: 2, pointRadius: 2 }},
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ intersect: false, mode: 'index' }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, font: {{ size: 11 }} }} }},
      y: {{
        ticks: {{
          callback: v => (v == null || v === '' ? '' : '$' + Number(v).toLocaleString()),
          font: {{ size: 11 }}
        }}
      }}
    }},
    plugins: {{
      legend: {{ position: 'bottom', labels: {{ boxWidth: 12, padding: 16, usePointStyle: true, font: {{ size: 11 }} }} }}
    }}
  }}
}});
</script>
</body>
</html>
"""


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
    return """<!doctype html><html><head><title>Aberdeen Tracker</title>
<style>body{font-family:-apple-system,sans-serif;padding:48px;color:#333;max-width:600px;margin:auto}</style>
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
