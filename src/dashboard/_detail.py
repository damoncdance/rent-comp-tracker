from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.config import DASHBOARD_DIR
from src.fees import FEES
from src.storage import db, latest_snapshot_id, snapshot_summary_history, recent_changes
from src.dashboard._constants import BED_COLORS
from src.dashboard._helpers import e, fmt_dt, fmt_date, is_vacant, safe_slug, json_safe
from src.dashboard._css import css


def render_property_detail(prop: dict) -> Path:
    """Generate dashboard/{slug}/index.html for a single property."""
    slug = prop["slug"]
    prop_id = prop["id"]
    prop_name = prop["name"]

    snap_id = latest_snapshot_id(property_id=prop_id)
    if snap_id is None:
        html = _detail_empty_html(prop)
    else:
        html = _detail_full_html(prop, snap_id)

    out_dir = DASHBOARD_DIR / safe_slug(slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


def _detail_full_html(prop: dict, snap_id: int) -> str:
    """Build a full detail page for a property with data."""
    prop_name = prop["name"]
    prop_id = prop["id"]

    with db() as conn:
        snap = dict(conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snap_id,)
        ).fetchone())
        units = [dict(r) for r in conn.execute(
            "SELECT * FROM units WHERE snapshot_id = ? ORDER BY beds, floorplan_name, unit_code",
            (snap_id,),
        ).fetchall()]

    fetched = fmt_dt(snap["fetched_at"])
    total = prop.get("unit_count_total") or 0
    avail = snap.get("unit_count") or 0
    exposure = round(avail / total * 100, 1) if total else 0

    # Leased %: vacant = units available within 7 days (likely unoccupied)
    today = datetime.now(timezone.utc).date()
    vacant_count = sum(1 for u in units if is_vacant(u.get("available_date", ""), today))
    leased_pct = round((total - vacant_count) / total * 100, 1) if total else 0

    # Bed type breakdown
    by_bed: dict[int, list] = defaultdict(list)
    for u in units:
        by_bed[u["beds"]].append(u)

    rents = [u["min_rent"] for u in units]
    avg_rent = sum(rents) / len(rents) if rents else 0
    psf_pairs = [(u["min_rent"], u["sqft"]) for u in units if u["sqft"] and u["min_rent"]]
    avg_psf = sum(r / s for r, s in psf_pairs) / len(psf_pairs) if psf_pairs else 0

    # Unit table
    bed_label = lambda b: "Studio" if b == 0 else f"{b} BR"
    unit_rows = "".join(
        f"<tr>"
        f"<td>{bed_label(u['beds'])}</td>"
        f"<td>{e(u['floorplan_name'])}</td>"
        f"<td class='mono'>{e(u['unit_code'])}</td>"
        f"<td class='num'>{int(u['sqft']):,}</td>"
        f"<td class='num'>${u['min_rent']:,.0f}</td>"
        f"<td>{fmt_date(u['available_date'])}</td>"
        f"<td class='concession-cell'>{e(u.get('concession_text') or '')}</td>"
        f"</tr>"
        for u in units
    )

    # Changes
    changes = recent_changes(limit=50, property_id=prop_id)
    changes_html = "".join(_render_change_row(c) for c in changes) \
                   or "<tr><td colspan='4' class='muted'>No changes recorded yet.</td></tr>"

    # History data
    history = snapshot_summary_history(limit=90, property_id=prop_id)
    by_snap: dict[int, dict] = {}
    for r in history:
        s = by_snap.setdefault(r["id"], {
            "id": r["id"], "fetched_at": r["fetched_at"], "unit_count": r["unit_count"],
            "avg_rent_by_bed": {},
        })
        s["avg_rent_by_bed"][r["beds"]] = r["avg_rent"]
    timeline = sorted(by_snap.values(), key=lambda x: x["fetched_at"])

    timeline_json = json_safe([
        {"t": t["fetched_at"], "count": t["unit_count"]}
        for t in timeline
    ])
    rent_series_json = json_safe([
        {
            "t": t["fetched_at"],
            "studio": t["avg_rent_by_bed"].get(0),
            "one_br": t["avg_rent_by_bed"].get(1),
            "two_br": t["avg_rent_by_bed"].get(2),
            "three_br": t["avg_rent_by_bed"].get(3),
        }
        for t in timeline
    ])

    # Bed type summary stats
    counts_by_bed = {b: len(rows) for b, rows in by_bed.items()}

    # Fees
    fees = FEES.get(prop_name)
    fees_html = _render_fees_section(fees)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{e(prop_name)} — Availability Detail</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js" integrity="sha384-9nhczxUqK87bcKHh20fSQcTGD4qq5GhayNYSYWqwBkINBhOfQLg/P5HG5lF1urn4" crossorigin="anonymous"></script>
{css()}
</head>
<body>
<header>
  <div class="header-left">
    <a href="../index.html" class="back-link">&larr; Comp Set Overview</a>
    <h1>{e(prop_name)}</h1>
    <div class="meta">
      <span>{e(prop.get("address", ""))}</span>
      <span class="sep">/</span>
      <span>{e(prop.get("management_company", ""))}</span>
      <span class="sep">/</span>
      <span>Snap #{snap['id']} — {fetched}</span>
    </div>
  </div>
</header>

<div class="tabs" role="tablist" aria-label="Property sections">
  <button class="tab active" role="tab" aria-selected="true" aria-controls="tab-availability" id="btn-availability" data-tab="availability" tabindex="0">Availability</button>
  <button class="tab" role="tab" aria-selected="false" aria-controls="tab-dfees" id="btn-dfees" data-tab="dfees" tabindex="-1">Fees</button>
</div>

<div id="tab-availability" class="tab-panel active" role="tabpanel" aria-labelledby="btn-availability">
<div class="grid">
  <div class="card stat-card" style="grid-column:span 2"><div class="label">Leased</div><div class="stat">{leased_pct}%</div></div>
  <div class="card stat-card" style="grid-column:span 2"><div class="label">Exposure</div><div class="stat">{exposure}%</div></div>
  <div class="card stat-card" style="grid-column:span 2"><div class="label">Units Avail</div><div class="stat">{avail}</div></div>
  <div class="card stat-card" style="grid-column:span 2"><div class="label">Vacant</div><div class="stat">{vacant_count}</div></div>
  <div class="card stat-card" style="grid-column:span 2"><div class="label">Avg Rent</div><div class="stat">${avg_rent:,.0f}</div></div>
  <div class="card stat-card" style="grid-column:span 2"><div class="label">Avg Rent PSF</div><div class="stat">${avg_psf:.2f}</div></div>

  <div class="card span-4">
    <h2>Unit Mix</h2>
    <div class="chart-wrap"><canvas id="mixChart" aria-label="Doughnut chart showing unit mix by bedroom type"></canvas></div>
  </div>
  <div class="card span-8">
    <h2>Availability Over Time</h2>
    <div class="chart-wrap"><canvas id="totalChart" aria-label="Line chart showing available units over time"></canvas></div>
  </div>

  <div class="card span-12">
    <h2>Avg Rent by Type</h2>
    <div class="chart-wrap"><canvas id="rentChart" aria-label="Line chart showing average rent by bedroom type over time"></canvas></div>
  </div>

  <div class="card span-7">
    <h2>Current Units ({len(units)})</h2>
    <div class="scroll">
      <table class="data-table">
        <thead><tr><th>Type</th><th>Tier</th><th>Unit</th><th class="num">SqFt</th><th class="num">Rent</th><th>Avail</th><th>Concession</th></tr></thead>
        <tbody>{unit_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="card span-5">
    <h2>Recent Changes</h2>
    <div class="scroll">
      <table class="data-table">
        <thead><tr><th>When</th><th>Event</th><th>Unit</th><th>Detail</th></tr></thead>
        <tbody>{changes_html}</tbody>
      </table>
    </div>
  </div>
</div>
</div>

<div id="tab-dfees" class="tab-panel" role="tabpanel" aria-labelledby="btn-dfees" aria-hidden="true">
<div class="grid">{fees_html}</div>
</div>

<script>
/* Tab switching (WAI-ARIA tabs pattern) */
(function() {{
  var tabs = Array.from(document.querySelectorAll('[role="tab"]'));
  function activate(tab) {{
    tabs.forEach(function(t) {{
      t.classList.remove('active');
      t.setAttribute('aria-selected', 'false');
      t.setAttribute('tabindex', '-1');
    }});
    document.querySelectorAll('[role="tabpanel"]').forEach(function(p) {{ p.classList.remove('active'); p.setAttribute('aria-hidden', 'true'); }});
    tab.classList.add('active');
    tab.setAttribute('aria-selected', 'true');
    tab.setAttribute('tabindex', '0');
    tab.focus();
    tab.scrollIntoView({{inline:'center',block:'nearest',behavior:'smooth'}});
    var panel = document.getElementById('tab-' + tab.dataset.tab);
    panel.classList.add('active');
    panel.removeAttribute('aria-hidden');
  }}
  tabs.forEach(function(btn) {{ btn.addEventListener('click', function() {{ activate(btn); }}); }});
  tabs.forEach(function(btn) {{
    btn.addEventListener('keydown', function(e) {{
      var idx = tabs.indexOf(btn);
      if (e.key === 'ArrowRight') {{ activate(tabs[(idx + 1) % tabs.length]); e.preventDefault(); }}
      else if (e.key === 'ArrowLeft') {{ activate(tabs[(idx - 1 + tabs.length) % tabs.length]); e.preventDefault(); }}
      else if (e.key === 'Home') {{ activate(tabs[0]); e.preventDefault(); }}
      else if (e.key === 'End') {{ activate(tabs[tabs.length - 1]); e.preventDefault(); }}
    }});
  }});
}})();

/* Read theme colors from CSS custom properties */
var _cs = getComputedStyle(document.documentElement);
var _c = function(v) {{ return _cs.getPropertyValue(v).trim(); }};
var C_MUTED = _c('--muted'), C_LINE = _c('--line');
var C_LINE_ALPHA = 'rgba(48,54,61,0.6)';
var C_BED = ['{BED_COLORS[0]}','{BED_COLORS[1]}','{BED_COLORS[2]}','{BED_COLORS[3]}'];

Chart.defaults.color = C_MUTED;
Chart.defaults.borderColor = C_LINE;
Chart.defaults.font.family = "ui-monospace,SFMono-Regular,'Cascadia Mono',Menlo,monospace";
Chart.defaults.font.size = 11;

const counts = {json_safe({bed_label(b): n for b, n in sorted(counts_by_bed.items())})};
new Chart(document.getElementById('mixChart'), {{
  type: 'doughnut',
  data: {{ labels: Object.keys(counts), datasets: [{{ data: Object.values(counts), backgroundColor: C_BED, borderWidth: 0 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, cutout: '58%', plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 12, font: {{ size: 11 }}, color: C_MUTED }} }} }} }}
}});

const timeline = {timeline_json};
new Chart(document.getElementById('totalChart'), {{
  type: 'line',
  data: {{ labels: timeline.map(p => p.t.slice(0,10)), datasets: [{{ label: 'Available units', data: timeline.map(p => p.count), borderColor: C_BED[0], backgroundColor: 'rgba(88,166,255,0.08)', tension: 0.25, fill: true, borderWidth: 1.5, pointRadius: 3, pointHoverRadius: 6, pointHitRadius: 20 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ intersect: false, mode: 'index' }}, scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, maxTicksLimit: 15, font: {{ size: 10 }} }} }}, y: {{ beginAtZero: true, ticks: {{ font: {{ size: 10 }}, precision: 0 }}, grid: {{ color: C_LINE_ALPHA }} }} }}, plugins: {{ legend: {{ display: false }} }} }}
}});

const rentSeries = {rent_series_json};
new Chart(document.getElementById('rentChart'), {{
  type: 'line',
  data: {{ labels: rentSeries.map(p => p.t.slice(0,10)), datasets: [
    {{ label: 'Studio', data: rentSeries.map(p => p.studio), borderColor: C_BED[0], tension: 0.25, borderWidth: 2, pointRadius: 3, pointHoverRadius: 6, pointHitRadius: 20 }},
    {{ label: '1 BR', data: rentSeries.map(p => p.one_br), borderColor: C_BED[1], tension: 0.25, borderWidth: 2, pointRadius: 3, pointHoverRadius: 6, pointHitRadius: 20 }},
    {{ label: '2 BR', data: rentSeries.map(p => p.two_br), borderColor: C_BED[2], tension: 0.25, borderWidth: 2, pointRadius: 3, pointHoverRadius: 6, pointHitRadius: 20 }},
    {{ label: '3 BR', data: rentSeries.map(p => p.three_br), borderColor: C_BED[3], tension: 0.25, borderWidth: 2, pointRadius: 3, pointHoverRadius: 6, pointHitRadius: 20 }},
  ] }},
  options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ intersect: false, mode: 'index' }}, scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, maxTicksLimit: 15, font: {{ size: 10 }} }} }}, y: {{ ticks: {{ callback: v => '$' + Number(v).toLocaleString(), font: {{ size: 10 }} }}, grid: {{ color: C_LINE_ALPHA }} }} }}, plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 14, usePointStyle: true, pointStyleWidth: 8, font: {{ size: 11 }}, color: C_MUTED }} }} }} }}
}});
</script>
</body>
</html>"""


def _detail_empty_html(prop: dict) -> str:
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><title>{e(prop['name'])} — No Data</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
{css()}
</head><body>
<header><div class="header-left">
  <a href="../" class="back-link">&larr; Comp Set Overview</a>
  <h1>{e(prop['name'])}</h1>
  <div class="meta"><span>{e(prop.get('address',''))}</span></div>
</div></header>
<div class="grid"><div class="card span-12">
  <p class="muted">No snapshots yet for this property. Data will appear after the next daily run.</p>
</div></div>
</body></html>"""


# ===========================================================================
# FEES SECTION (for detail pages)
# ===========================================================================

def _render_fees_section(fees: dict | None) -> str:
    if fees is None:
        return ('<div class="card span-12">'
                '<p class="muted">No fee schedule configured for this property.</p>'
                '</div>')

    sections = []
    if fees.get("application"):
        rows = "".join(
            f"<tr><td>{e(item['item'])}</td><td class='num'>{e(item['cost'])}</td>"
            f"<td class='note'>{e(item.get('note', ''))}</td></tr>"
            for item in fees["application"]
        )
        sections.append(
            '<div class="card span-6"><h2>Application &amp; Admin</h2>'
            '<div class="scroll"><table class="data-table">'
            '<thead><tr><th>Fee</th><th class="num">Amount</th><th>Note</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></div>'
        )

    if fees.get("parking"):
        rows = "".join(
            f"<tr><td>{e(item['type'])}</td><td class='num'>{e(item['cost'])}</td></tr>"
            for item in fees["parking"]
        )
        sections.append(
            '<div class="card span-6"><h2>Parking</h2>'
            '<div class="scroll"><table class="data-table">'
            '<thead><tr><th>Type</th><th class="num">Monthly</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></div>'
        )

    if fees.get("bundled"):
        rows = "".join(
            f"<tr><td>{e(item['type'])}</td><td class='num'>{e(item['cost'])}</td></tr>"
            for item in fees["bundled"]
        )
        note = ""
        if fees.get("bundled_note"):
            note = f'<div class="small">{e(fees["bundled_note"])}</div>'
        sections.append(
            f'<div class="card span-6"><h2>Bundled Services</h2>{note}'
            '<div class="scroll"><table class="data-table">'
            '<thead><tr><th>Unit Type</th><th class="num">Monthly</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></div>'
        )

    if fees.get("pets"):
        rows = "".join(
            f"<tr><td>{e(item['item'])}</td><td class='num'>{e(item['cost'])}</td></tr>"
            for item in fees["pets"]
        )
        note = ""
        if fees.get("pet_policy"):
            note = f'<div class="small">{e(fees["pet_policy"])}</div>'
        sections.append(
            f'<div class="card span-6"><h2>Pets</h2>'
            '<div class="scroll"><table class="data-table">'
            '<thead><tr><th>Fee</th><th class="num">Amount</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>{note}</div>'
        )

    return "\n".join(sections)


# ===========================================================================
# CHANGE ROW (shared)
# ===========================================================================

def _render_change_row(c: dict) -> str:
    when = fmt_dt(c["snapshot_fetched_at"])
    et = c["event_type"]
    unit = e(c["unit_code"])
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
        sign = "+" if delta >= 0 else "\u2212"
        detail = f"${ov:,.0f} \u2192 ${nv:,.0f} ({sign}${abs(delta):,.0f})"
        badge = "<span class='badge badge-change'>rent</span>"
    elif et == "date_changed":
        ov = json.loads(c["old_value"]) if c["old_value"] else ""
        nv = json.loads(c["new_value"]) if c["new_value"] else ""
        detail = f"{(ov or '')[:10]} \u2192 {(nv or '')[:10]}"
        badge = "<span class='badge badge-change'>date</span>"
    else:
        detail = ""
        badge = f"<span class='badge'>{e(et)}</span>"
    return f"<tr><td>{when}</td><td>{badge}</td><td class='mono'>{unit}</td><td>{e(detail)}</td></tr>"
