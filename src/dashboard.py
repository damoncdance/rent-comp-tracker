"""Render the static HTML dashboard — HelloData-style comp set view.

Generates:
  dashboard/index.html         — comp set overview (all properties)
  dashboard/{slug}/index.html  — per-property detail pages

Single-file outputs with embedded JSON data and Chart.js from CDN.
No build step, no server.
"""
from __future__ import annotations

import html as html_mod
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.config import DASHBOARD_DIR, get_active_properties
from src.fees import FEES
from src.ner import calculate_ner
from src.storage import (
    db, comp_grid_data, rents_by_unit_type,
    exposure_history, rent_history_by_property,
    latest_snapshot_id, snapshot_summary_history, recent_changes,
)


# ---------------------------------------------------------------------------
# Color palette (matches existing dark theme)
# ---------------------------------------------------------------------------

_COLORS = [
    '#58a6ff', '#3fb950', '#d29922', '#f85149',
    '#bc8cff', '#f78166', '#7ee787', '#79c0ff',
    '#ffa657', '#ff7b72', '#d2a8ff', '#a5d6ff',
]
_BED_COLORS = {0: '#58a6ff', 1: '#3fb950', 2: '#d29922', 3: '#f85149'}
_BED_LABELS = {0: 'Studio', 1: '1 BR', 2: '2 BR', 3: '3 BR'}


def render() -> str:
    """Build all dashboard HTML files. Returns path to index.html."""
    # Overview page
    overview_path = _render_overview()

    # Per-property detail pages
    properties = get_active_properties()
    for prop in properties:
        _render_property_detail(prop)

    return str(overview_path)


# ===========================================================================
# OVERVIEW PAGE (HelloData Rent Comps Overview — pages 2-6, 16-20)
# ===========================================================================

def _render_overview() -> Path:
    grid = comp_grid_data()
    rents = rents_by_unit_type()
    exposure = exposure_history()
    rent_hist = rent_history_by_property()

    now = datetime.now(timezone.utc)
    generated = now.strftime("%b %d, %Y %H:%M UTC")

    # Subject property
    subject = next((p for p in grid if p.get("is_subject")), None)
    subject_name = subject["name"] if subject else "Comp Set"

    # Build the HTML sections
    overview_table = _build_overview_table(grid)
    bed_type_tables = _build_bed_type_tables(grid)
    rent_comps_cards = _build_rent_comps_cards(grid)
    unit_type_metrics = _build_unit_type_metrics(grid)
    rents_table = _build_rents_by_unit_type_table(rents)
    rankings_json = _build_rankings_data(grid)
    exposure_json = _build_exposure_chart_data(exposure)
    rent_trend_json = _build_rent_trend_chart_data(rent_hist)
    concessions_table = _build_concessions_table(grid)
    fees_table = _build_fees_comparison_table(grid)

    # Property nav links for sidebar
    nav_links = "".join(
        f'<a href="{_e(p["slug"])}/" class="nav-link{" subject" if p.get("is_subject") else ""}">'
        f'{_e(p["name"])}</a>'
        for p in grid
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_e(subject_name)} — Rent Comp Report</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
{_css()}
</head>
<body>
<header>
  <div class="header-left">
    <h1>Rent Comp Report</h1>
    <div class="meta">
      <span class="subject-badge">{_e(subject_name)}</span>
      <span class="sep">/</span>
      <span>{len(grid)} properties</span>
      <span class="sep">/</span>
      <span>{generated}</span>
    </div>
  </div>
</header>

<div class="tabs">
  <button class="tab active" data-tab="overview">Overview</button>
  <button class="tab" data-tab="bytypes">By Unit Type</button>
  <button class="tab" data-tab="comps">Rent Comps</button>
  <button class="tab" data-tab="rankings">Rankings</button>
  <button class="tab" data-tab="trends">Trends</button>
  <button class="tab" data-tab="concessions">Concessions</button>
  <button class="tab" data-tab="fees">Fees</button>
</div>

<!-- TAB: Overview -->
<div id="tab-overview" class="tab-panel active">
<div class="grid">
  <div class="card span-12">
    <h2>Rent Comps Overview</h2>
    <p class="subtitle">See key comp data in one place.</p>
    <div class="scroll scroll-wide">
      {overview_table}
    </div>
  </div>
</div>
{bed_type_tables}
</div>

<!-- TAB: By Unit Type -->
<div id="tab-bytypes" class="tab-panel">
<div class="grid">
  {unit_type_metrics}
  <div class="card span-12">
    <h2>Rents by Unit Type</h2>
    <p class="subtitle">Track rent and availability trends by unit type.</p>
    <div class="scroll scroll-wide">
      {rents_table}
    </div>
  </div>
</div>
</div>

<!-- TAB: Rent Comps -->
<div id="tab-comps" class="tab-panel">
<div class="grid">
  <div class="card span-12">
    <h2>Rent Comps</h2>
    <p class="subtitle">Benchmark your property against comps.</p>
  </div>
  {rent_comps_cards}
</div>
</div>

<!-- TAB: Rankings -->
<div id="tab-rankings" class="tab-panel">
<div class="grid">
  <div class="card span-12">
    <h2>Property Rankings</h2>
    <p class="subtitle">Compare asking rents by bedroom count across your market.</p>
  </div>
  <div class="card span-6"><h3>Studio</h3><div class="chart-wrap chart-tall"><canvas id="rankStudio"></canvas></div></div>
  <div class="card span-6"><h3>1 BR</h3><div class="chart-wrap chart-tall"><canvas id="rank1BR"></canvas></div></div>
  <div class="card span-6"><h3>2 BR</h3><div class="chart-wrap chart-tall"><canvas id="rank2BR"></canvas></div></div>
  <div class="card span-6"><h3>3 BR</h3><div class="chart-wrap chart-tall"><canvas id="rank3BR"></canvas></div></div>
</div>
</div>

<!-- TAB: Trends -->
<div id="tab-trends" class="tab-panel">
<div class="grid">
  <div class="card span-12">
    <h2>Historical Rent Trends</h2>
    <p class="subtitle">Average rent over time across your comp set.</p>
    <div class="chart-wrap chart-wide"><canvas id="rentTrendChart"></canvas></div>
  </div>
  <div class="card span-12">
    <h2>Historical Exposure</h2>
    <p class="subtitle">Track the percentage of units listed for rent over time.</p>
    <div class="chart-wrap chart-wide"><canvas id="exposureChart"></canvas></div>
  </div>
</div>
</div>

<!-- TAB: Concessions -->
<div id="tab-concessions" class="tab-panel">
<div class="grid">
  <div class="card span-12">
    <h2>Concessions</h2>
    <p class="subtitle">See how your concessions stack up against the competition.</p>
    <div class="scroll scroll-wide">
      {concessions_table}
    </div>
  </div>
</div>
</div>

<!-- TAB: Fees -->
<div id="tab-fees" class="tab-panel">
<div class="grid">
  <div class="card span-12">
    <h2>Fees</h2>
    <p class="subtitle">Compare your property's fees to market averages.</p>
    <div class="scroll scroll-wide">
      {fees_table}
    </div>
  </div>
</div>
</div>

<!-- Property Navigation -->
<nav class="prop-nav">
  <h3>Properties</h3>
  {nav_links}
</nav>

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

/* Rankings charts */
const rankings = {rankings_json};
function makeRankChart(canvasId, data) {{
  if (!data || data.labels.length === 0) return;
  new Chart(document.getElementById(canvasId), {{
    type: 'bar',
    data: {{
      labels: data.labels,
      datasets: [{{
        data: data.values,
        backgroundColor: data.colors,
        borderWidth: 0,
        borderRadius: 3,
        barThickness: 18,
      }}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            label: function(ctx) {{ return '$' + ctx.raw.toLocaleString(); }}
          }}
        }}
      }},
      scales: {{
        x: {{
          ticks: {{ callback: v => '$' + Number(v).toLocaleString(), font: {{ size: 10 }} }},
          grid: {{ color: 'rgba(48,54,61,0.6)' }}
        }},
        y: {{
          ticks: {{ font: {{ size: 11 }} }},
          grid: {{ display: false }}
        }}
      }}
    }}
  }});
}}
makeRankChart('rankStudio', rankings.studio);
makeRankChart('rank1BR', rankings.one_br);
makeRankChart('rank2BR', rankings.two_br);
makeRankChart('rank3BR', rankings.three_br);

/* Rent trend chart */
const rentTrend = {rent_trend_json};
if (rentTrend.datasets.length > 0) {{
  new Chart(document.getElementById('rentTrendChart'), {{
    type: 'line',
    data: {{ labels: rentTrend.labels, datasets: rentTrend.datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ intersect: false, mode: 'index' }},
      scales: {{
        x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, font: {{ size: 10 }} }} }},
        y: {{
          ticks: {{ callback: v => '$' + Number(v).toLocaleString(), font: {{ size: 10 }} }},
          grid: {{ color: 'rgba(48,54,61,0.6)' }}
        }}
      }},
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 14, usePointStyle: true, font: {{ size: 10 }}, color: '#8a8f98' }} }}
      }}
    }}
  }});
}}

/* Exposure chart */
const exposure = {exposure_json};
if (exposure.datasets.length > 0) {{
  new Chart(document.getElementById('exposureChart'), {{
    type: 'line',
    data: {{ labels: exposure.labels, datasets: exposure.datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ intersect: false, mode: 'index' }},
      scales: {{
        x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, font: {{ size: 10 }} }} }},
        y: {{
          ticks: {{ callback: v => v + '%', font: {{ size: 10 }} }},
          grid: {{ color: 'rgba(48,54,61,0.6)' }},
          beginAtZero: true
        }}
      }},
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 14, usePointStyle: true, font: {{ size: 10 }}, color: '#8a8f98' }} }}
      }}
    }}
  }});
}}
</script>
</body>
</html>"""

    out = DASHBOARD_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


# ===========================================================================
# OVERVIEW TABLE (HelloData p2 style)
# ===========================================================================

def _build_overview_table(grid: list[dict]) -> str:
    """Build the side-by-side comp overview table."""
    # Header row with property names
    headers = '<th class="row-label"></th>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        headers += f'<th{cls}>{_e(p["name"])}</th>'

    # Data rows
    rows = []

    # Management Company
    r = '<td class="row-label">Management Company</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        r += f'<td{cls}>{_e(p.get("management_company", ""))}</td>'
    rows.append(r)

    # Year Built
    r = '<td class="row-label">Year Built</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        yb = p.get("year_built") or ""
        r += f'<td{cls}>{yb}</td>'
    rows.append(r)

    # Stories
    r = '<td class="row-label">Stories</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        st = p.get("stories") or ""
        r += f'<td{cls}>{st}</td>'
    rows.append(r)

    # Total Units
    r = '<td class="row-label"># Units</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        r += f'<td{cls}>{p.get("unit_count_total", "")}</td>'
    rows.append(r)

    # Exposure %
    r = '<td class="row-label">Exposure</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        total = p.get("unit_count_total") or 0
        avail = p.get("unit_count") or 0
        if total and avail is not None:
            exp = round(avail / total * 100, 1)
            r += f'<td{cls}>{exp}%</td>'
        else:
            r += f'<td{cls}>—</td>'
    rows.append(r)

    # Available Units
    r = '<td class="row-label">Available Units</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        uc = p.get("unit_count")
        r += f'<td{cls}>{uc if uc is not None else "—"}</td>'
    rows.append(r)

    # Avg Rent
    r = '<td class="row-label">Rent</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        avg = p.get("avg_rent")
        if avg:
            r += f'<td{cls}>${avg:,.0f}</td>'
        else:
            r += f'<td{cls}>—</td>'
    rows.append(r)

    # Avg SqFt
    r = '<td class="row-label">Avg SqFt</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        sqft = p.get("avg_sqft")
        if sqft:
            r += f'<td{cls}>{sqft:,.0f} ft²</td>'
        else:
            r += f'<td{cls}>—</td>'
    rows.append(r)

    # Rent/ft²
    r = '<td class="row-label">Rent/ft²</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        avg = p.get("avg_rent")
        sqft = p.get("avg_sqft")
        if avg and sqft:
            r += f'<td{cls}>${avg/sqft:.2f}</td>'
        else:
            r += f'<td{cls}>—</td>'
    rows.append(r)

    # Concessions
    r = '<td class="row-label">Concessions</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        conc = p.get("concessions", [])
        if conc:
            text = conc[0][:80] + ("..." if len(conc[0]) > 80 else "")
            r += f'<td{cls} class="concession-cell">{_e(text)}</td>'
        else:
            r += f'<td{cls}>—</td>'
    rows.append(r)

    rows_html = "".join(f"<tr>{r}</tr>" for r in rows)

    return f"""<table class="comp-table">
<thead><tr>{headers}</tr></thead>
<tbody>{rows_html}</tbody>
</table>"""


# ===========================================================================
# PER-BED-TYPE TABLES (HelloData p3-6)
# ===========================================================================

def _build_bed_type_tables(grid: list[dict]) -> str:
    """Build per-bed-type breakdown tables (Studio, 1BR, 2BR, 3BR)."""
    sections = []
    for beds in [0, 1, 2, 3]:
        label = _BED_LABELS.get(beds, f"{beds} BR")
        color = _BED_COLORS.get(beds, '#58a6ff')

        headers = f'<th class="row-label" style="border-left:3px solid {color}">{label}</th>'
        for p in grid:
            cls = ' class="subject-col"' if p.get("is_subject") else ''
            headers += f'<th{cls}>{_e(p["name"])}</th>'

        row_defs = [
            ("Available Units", lambda p, b=beds: _bed_stat(p, b, "cnt")),
            ("Rent", lambda p, b=beds: _bed_stat_money(p, b, "avg_rent")),
            ("Average SqFt", lambda p, b=beds: _bed_stat_num(p, b, "avg_sqft")),
            ("Rent/ft²", lambda p, b=beds: _bed_stat_psf(p, b)),
        ]

        rows_html = ""
        for label_text, fn in row_defs:
            r = f'<td class="row-label">{label_text}</td>'
            for p in grid:
                cls = ' class="subject-col"' if p.get("is_subject") else ''
                r += f'<td{cls}>{fn(p)}</td>'
            rows_html += f"<tr>{r}</tr>"

        sections.append(f"""
<div class="grid" style="margin-top:0">
  <div class="card span-12">
    <div class="scroll scroll-wide">
      <table class="comp-table">
      <thead><tr>{headers}</tr></thead>
      <tbody>{rows_html}</tbody>
      </table>
    </div>
  </div>
</div>""")

    return "\n".join(sections)


def _bed_stat(p: dict, beds: int, key: str) -> str:
    bd = p.get("by_bed", {}).get(beds)
    if not bd:
        return "—"
    val = bd.get(key)
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:,.0f}"
    return str(val)


def _bed_stat_money(p: dict, beds: int, key: str) -> str:
    bd = p.get("by_bed", {}).get(beds)
    if not bd:
        return "—"
    val = bd.get(key)
    return f"${val:,.0f}" if val else "—"


def _bed_stat_num(p: dict, beds: int, key: str) -> str:
    bd = p.get("by_bed", {}).get(beds)
    if not bd:
        return "—"
    val = bd.get(key)
    return f"{val:,.0f} ft²" if val else "—"


def _bed_stat_psf(p: dict, beds: int) -> str:
    bd = p.get("by_bed", {}).get(beds)
    if not bd:
        return "—"
    rent = bd.get("avg_rent")
    sqft = bd.get("avg_sqft")
    if rent and sqft:
        return f"${rent/sqft:.2f}/ft²"
    return "—"


# ===========================================================================
# RENT COMPS CARDS (HelloData p16-17)
# ===========================================================================

def _build_rent_comps_cards(grid: list[dict]) -> str:
    """Build per-property detail cards like HelloData p16-17."""
    cards = []
    for i, p in enumerate(grid):
        is_subj = p.get("is_subject")
        badge = '<span class="badge badge-subject">Subject</span>' if is_subj else f'<span class="comp-num">{i}</span>'
        total = p.get("unit_count_total") or 0
        avail = p.get("unit_count") or 0
        exposure = round(avail / total * 100, 1) if total else 0
        leased = round((1 - avail / total) * 100, 1) if total else 0

        # Per-bed rent table
        bed_rows = ""
        for beds in [0, 1, 2, 3]:
            bd = p.get("by_bed", {}).get(beds)
            if not bd:
                continue
            label = _BED_LABELS.get(beds, f"{beds}BR")
            rent = bd.get("avg_rent", 0)
            sqft = bd.get("avg_sqft", 0)
            psf = f"${rent/sqft:.2f}" if rent and sqft else "—"
            bed_rows += (
                f'<tr><td class="bed-label">{label}</td>'
                f'<td class="num">${rent:,.0f}</td>'
                f'<td class="num">{sqft:,.0f}</td>'
                f'<td class="num">{psf}</td></tr>'
            )

        if not bed_rows:
            bed_rows = '<tr><td colspan="4" class="muted">No data</td></tr>'

        cards.append(f"""
  <div class="card span-6 comp-card{' subject-card' if is_subj else ''}">
    <div class="comp-header">
      {badge}
      <div>
        <div class="comp-name">{_e(p["name"])}</div>
        <div class="comp-addr">{_e(p.get("address", ""))}</div>
        <div class="comp-mgmt">{_e(p.get("management_company", ""))}</div>
      </div>
    </div>
    <div class="comp-stats">
      <div class="comp-stat"><span class="label">Built</span><span>{p.get("year_built", "—")}</span></div>
      <div class="comp-stat"><span class="label">Units</span><span>{total}</span></div>
      <div class="comp-stat"><span class="label">Stories</span><span>{p.get("stories", "—")}</span></div>
      <div class="comp-stat"><span class="label">Leased</span><span>{leased}%</span></div>
      <div class="comp-stat"><span class="label">Exposure</span><span>{exposure}%</span></div>
      <div class="comp-stat"><span class="label">Available</span><span>{avail}</span></div>
    </div>
    <table class="comp-bed-table">
      <thead><tr><th>Type</th><th class="num">Rent</th><th class="num">SqFt</th><th class="num">PSF</th></tr></thead>
      <tbody>{bed_rows}</tbody>
    </table>
  </div>""")

    return "\n".join(cards)


# ===========================================================================
# UNIT TYPE METRICS (HelloData p18)
# ===========================================================================

def _build_unit_type_metrics(grid: list[dict]) -> str:
    """Build unit type metric summary cards."""
    # Aggregate across all properties
    bed_agg: dict[int, dict] = defaultdict(lambda: {"rents": [], "sqfts": [], "count": 0})
    for p in grid:
        for beds, bd in p.get("by_bed", {}).items():
            bed_agg[beds]["rents"].append(bd.get("avg_rent", 0))
            bed_agg[beds]["sqfts"].append(bd.get("avg_sqft", 0))
            bed_agg[beds]["count"] += bd.get("cnt", 0)

    cards = []
    for beds in [0, 1, 2, 3]:
        label = _BED_LABELS.get(beds, f"{beds} BR")
        color = _BED_COLORS.get(beds, '#58a6ff')
        agg = bed_agg.get(beds)
        if not agg or not agg["rents"]:
            continue

        rents = [r for r in agg["rents"] if r]
        sqfts = [s for s in agg["sqfts"] if s]
        avg_rent = sum(rents) / len(rents) if rents else 0
        avg_sqft = sum(sqfts) / len(sqfts) if sqfts else 0
        avg_psf = avg_rent / avg_sqft if avg_sqft else 0

        cards.append(f"""
  <div class="card span-3 metric-card">
    <div class="metric-header" style="border-top:3px solid {color}">
      <h3>{label}</h3>
    </div>
    <div class="metric-body">
      <div class="metric-row"><span># Listings</span><span>{agg['count']}</span></div>
      <div class="metric-row"><span>Avg SqFt</span><span>{avg_sqft:,.0f} ft²</span></div>
      <div class="metric-row"><span>Asking Rent / PSF</span><span>${avg_rent:,.0f} / ${avg_psf:.2f}</span></div>
    </div>
  </div>""")

    return "\n".join(cards)


# ===========================================================================
# RENTS BY UNIT TYPE TABLE (HelloData p19)
# ===========================================================================

def _build_rents_by_unit_type_table(rents: list[dict]) -> str:
    """Build the cross-property rent comparison table."""
    rows = ""
    for r in rents:
        is_subj = r.get("is_subject")
        cls = ' class="subject-row"' if is_subj else ''
        name = _e(r["name"])
        active = r.get("active_units", 0)

        if active == 0:
            rows += f'<tr{cls}><td>{name}</td><td class="num">0</td>' + '<td class="num">—</td>' * 5 + '</tr>'
            continue

        min_r = r.get("min_rent", 0) or 0
        avg_r = r.get("avg_rent", 0) or 0
        max_r = r.get("max_rent", 0) or 0
        avg_sf = r.get("avg_sqft", 0) or 0
        avg_psf = r.get("avg_psf", 0) or 0

        rows += (
            f'<tr{cls}>'
            f'<td>{name}</td>'
            f'<td class="num">{active}</td>'
            f'<td class="num">${min_r:,.0f}</td>'
            f'<td class="num">${avg_r:,.0f}</td>'
            f'<td class="num">${max_r:,.0f}</td>'
            f'<td class="num">{avg_sf:,.0f} ft²</td>'
            f'<td class="num">${avg_psf:.2f}/ft²</td>'
            f'</tr>'
        )

    # Comp average row
    comp_rents = [r for r in rents if not r.get("is_subject") and r.get("active_units", 0) > 0]
    if comp_rents:
        avg_active = sum(r["active_units"] for r in comp_rents) / len(comp_rents)
        avg_rent = sum(r.get("avg_rent", 0) or 0 for r in comp_rents) / len(comp_rents)
        avg_min = sum(r.get("min_rent", 0) or 0 for r in comp_rents) / len(comp_rents)
        avg_max = sum(r.get("max_rent", 0) or 0 for r in comp_rents) / len(comp_rents)
        avg_sqft = sum(r.get("avg_sqft", 0) or 0 for r in comp_rents) / len(comp_rents)
        avg_psf = avg_rent / avg_sqft if avg_sqft else 0
        rows += (
            f'<tr class="comp-avg-row">'
            f'<td><strong>Comp Average</strong></td>'
            f'<td class="num">{avg_active:.0f}</td>'
            f'<td class="num">${avg_min:,.0f}</td>'
            f'<td class="num">${avg_rent:,.0f}</td>'
            f'<td class="num">${avg_max:,.0f}</td>'
            f'<td class="num">{avg_sqft:,.0f} ft²</td>'
            f'<td class="num">${avg_psf:.2f}/ft²</td>'
            f'</tr>'
        )

    return f"""<table class="data-table">
<thead><tr>
  <th>Property</th><th class="num"># Active</th>
  <th class="num">Min Rent</th><th class="num">Avg Rent</th><th class="num">Max Rent</th>
  <th class="num">Avg SqFt</th><th class="num">Avg PSF</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>"""


# ===========================================================================
# RANKINGS (HelloData p20)
# ===========================================================================

def _build_rankings_data(grid: list[dict]) -> str:
    """Build JSON data for the 4 ranking bar charts."""
    result = {}
    for beds, key in [(0, 'studio'), (1, 'one_br'), (2, 'two_br'), (3, 'three_br')]:
        items = []
        for p in grid:
            bd = p.get("by_bed", {}).get(beds)
            if bd and bd.get("avg_rent"):
                items.append({
                    "name": p["name"],
                    "rent": round(bd["avg_rent"]),
                    "is_subject": bool(p.get("is_subject")),
                })
        items.sort(key=lambda x: x["rent"], reverse=True)

        if items:
            subject_color = '#6e7681'
            bed_color = _BED_COLORS.get(beds, '#58a6ff')
            result[key] = {
                "labels": [i["name"][:20] for i in items],
                "values": [i["rent"] for i in items],
                "colors": [subject_color if i["is_subject"] else bed_color for i in items],
            }
        else:
            result[key] = {"labels": [], "values": [], "colors": []}

    return _json_safe(result)


# ===========================================================================
# TREND CHARTS DATA
# ===========================================================================

def _build_rent_trend_chart_data(rent_hist: list[dict]) -> str:
    """Build Chart.js data for rent trends."""
    by_prop: dict[str, list] = defaultdict(list)
    all_dates = set()
    for r in rent_hist:
        date = r["fetched_at"][:10]
        all_dates.add(date)
        by_prop[r["name"]].append({"date": date, "rent": r["avg_rent"]})

    labels = sorted(all_dates)
    datasets = []
    for i, (name, points) in enumerate(sorted(by_prop.items())):
        rent_by_date = {p["date"]: round(p["rent"]) for p in points}
        color = _COLORS[i % len(_COLORS)]
        datasets.append({
            "label": name,
            "data": [rent_by_date.get(d) for d in labels],
            "borderColor": color,
            "tension": 0.25,
            "borderWidth": 1.5,
            "pointRadius": 2,
            "fill": False,
            "spanGaps": True,
        })

    return _json_safe({"labels": labels, "datasets": datasets})


def _build_exposure_chart_data(exposure: list[dict]) -> str:
    """Build Chart.js data for exposure % over time."""
    by_prop: dict[str, list] = defaultdict(list)
    all_dates = set()
    for r in exposure:
        date = r["fetched_at"][:10]
        all_dates.add(date)
        by_prop[r["name"]].append({"date": date, "pct": r["exposure_pct"]})

    labels = sorted(all_dates)
    datasets = []
    for i, (name, points) in enumerate(sorted(by_prop.items())):
        pct_by_date = {p["date"]: p["pct"] for p in points}
        color = _COLORS[i % len(_COLORS)]
        datasets.append({
            "label": name,
            "data": [pct_by_date.get(d) for d in labels],
            "borderColor": color,
            "tension": 0.25,
            "borderWidth": 1.5,
            "pointRadius": 2,
            "fill": False,
            "spanGaps": True,
        })

    return _json_safe({"labels": labels, "datasets": datasets})


# ===========================================================================
# CONCESSIONS TABLE (HelloData p31)
# ===========================================================================

def _build_concessions_table(grid: list[dict]) -> str:
    """Build cross-property concessions table."""
    rows = ""
    for p in grid:
        is_subj = p.get("is_subject")
        cls = ' class="subject-row"' if is_subj else ''
        concs = p.get("concessions", [])
        if concs:
            text = "; ".join(c[:120] for c in concs)
        else:
            text = "—"
        rows += f'<tr{cls}><td>{_e(p["name"])}</td><td class="concession-cell">{_e(text)}</td></tr>'

    return f"""<table class="data-table">
<thead><tr><th>Property</th><th>Concession</th></tr></thead>
<tbody>{rows}</tbody>
</table>"""


# ===========================================================================
# FEES COMPARISON TABLE (HelloData p30)
# ===========================================================================

def _build_fees_comparison_table(grid: list[dict]) -> str:
    """Build cross-property fee comparison table."""
    rows = ""
    for p in grid:
        is_subj = p.get("is_subject")
        cls = ' class="subject-row"' if is_subj else ''
        fees = FEES.get(p["name"], {})

        app_fee = "—"
        admin_fee = "—"
        pet_rent = "—"
        parking = "—"

        if fees.get("application"):
            for item in fees["application"]:
                if "application" in item["item"].lower():
                    app_fee = item["cost"]
                elif "admin" in item["item"].lower():
                    admin_fee = item["cost"]

        if fees.get("pets"):
            for item in fees["pets"]:
                if "monthly" in item["item"].lower() or "rent" in item["item"].lower():
                    pet_rent = item["cost"]

        if fees.get("parking"):
            costs = [item["cost"] for item in fees["parking"]]
            parking = costs[0] if costs else "—"

        rows += (
            f'<tr{cls}><td>{_e(p["name"])}</td>'
            f'<td class="num">{_e(app_fee)}</td>'
            f'<td class="num">{_e(admin_fee)}</td>'
            f'<td class="num">{_e(pet_rent)}</td>'
            f'<td class="num">{_e(parking)}</td></tr>'
        )

    return f"""<table class="data-table">
<thead><tr><th>Property</th><th class="num">Application Fee</th>
<th class="num">Admin Fee</th><th class="num">Pet Rent</th>
<th class="num">Parking</th></tr></thead>
<tbody>{rows}</tbody>
</table>"""


# ===========================================================================
# PER-PROPERTY DETAIL PAGE
# ===========================================================================

def _render_property_detail(prop: dict) -> Path:
    """Generate dashboard/{slug}/index.html for a single property."""
    slug = prop["slug"]
    prop_id = prop["id"]
    prop_name = prop["name"]

    snap_id = latest_snapshot_id(property_id=prop_id)
    if snap_id is None:
        html = _detail_empty_html(prop)
    else:
        html = _detail_full_html(prop, snap_id)

    out_dir = DASHBOARD_DIR / slug
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

    fetched = _fmt_dt(snap["fetched_at"])
    total = prop.get("unit_count_total") or 0
    avail = snap.get("unit_count") or 0
    exposure = round(avail / total * 100, 1) if total else 0

    # Bed type breakdown
    by_bed: dict[int, list] = defaultdict(list)
    for u in units:
        by_bed[u["beds"]].append(u)

    rents = [u["min_rent"] for u in units]
    avg_rent = sum(rents) / len(rents) if rents else 0

    # Unit table
    bed_label = lambda b: "Studio" if b == 0 else f"{b} BR"
    unit_rows = "".join(
        f"<tr>"
        f"<td>{bed_label(u['beds'])}</td>"
        f"<td>{_e(u['floorplan_name'])}</td>"
        f"<td class='mono'>{_e(u['unit_code'])}</td>"
        f"<td class='num'>{int(u['sqft']):,}</td>"
        f"<td class='num'>${u['min_rent']:,.0f}</td>"
        f"<td>{_fmt_date(u['available_date'])}</td>"
        f"<td class='concession-cell'>{_e(u.get('concession_text') or '')}</td>"
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

    timeline_json = _json_safe([
        {"t": t["fetched_at"], "count": t["unit_count"]}
        for t in timeline
    ])
    rent_series_json = _json_safe([
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
<title>{_e(prop_name)} — Availability Detail</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
{_css()}
</head>
<body>
<header>
  <div class="header-left">
    <a href="../" class="back-link">&larr; Comp Set Overview</a>
    <h1>{_e(prop_name)}</h1>
    <div class="meta">
      <span>{_e(prop.get("address", ""))}</span>
      <span class="sep">/</span>
      <span>{_e(prop.get("management_company", ""))}</span>
      <span class="sep">/</span>
      <span>Snap #{snap['id']} — {fetched}</span>
    </div>
  </div>
</header>

<div class="tabs">
  <button class="tab active" data-tab="availability">Availability</button>
  <button class="tab" data-tab="dfees">Fees</button>
</div>

<div id="tab-availability" class="tab-panel active">
<div class="grid">
  <div class="card span-3 stat-card"><div class="label">Units Avail</div><div class="stat">{avail}</div></div>
  <div class="card span-3 stat-card"><div class="label">Avg Rent</div><div class="stat">${avg_rent:,.0f}</div></div>
  <div class="card span-3 stat-card"><div class="label">Exposure</div><div class="stat">{exposure}%</div></div>
  <div class="card span-3 stat-card"><div class="label">Total Units</div><div class="stat">{total}</div></div>

  <div class="card span-4">
    <h2>Unit Mix</h2>
    <div class="chart-wrap"><canvas id="mixChart"></canvas></div>
  </div>
  <div class="card span-8">
    <h2>Availability Over Time</h2>
    <div class="chart-wrap"><canvas id="totalChart"></canvas></div>
  </div>

  <div class="card span-12">
    <h2>Avg Rent by Type</h2>
    <div class="chart-wrap"><canvas id="rentChart"></canvas></div>
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

<div id="tab-dfees" class="tab-panel">
<div class="grid">{fees_html}</div>
</div>

<script>
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

const counts = {_json_safe({bed_label(b): n for b, n in sorted(counts_by_bed.items())})};
new Chart(document.getElementById('mixChart'), {{
  type: 'doughnut',
  data: {{ labels: Object.keys(counts), datasets: [{{ data: Object.values(counts), backgroundColor: ['#58a6ff','#3fb950','#d29922','#f85149'], borderWidth: 0 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, cutout: '58%', plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 12, font: {{ size: 11 }}, color: '#8a8f98' }} }} }} }}
}});

const timeline = {timeline_json};
new Chart(document.getElementById('totalChart'), {{
  type: 'line',
  data: {{ labels: timeline.map(p => p.t.slice(0,10)), datasets: [{{ label: 'Available units', data: timeline.map(p => p.count), borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.08)', tension: 0.25, fill: true, borderWidth: 1.5, pointRadius: 2 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ intersect: false, mode: 'index' }}, scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, font: {{ size: 10 }} }} }}, y: {{ beginAtZero: true, ticks: {{ font: {{ size: 10 }}, precision: 0 }}, grid: {{ color: 'rgba(48,54,61,0.6)' }} }} }}, plugins: {{ legend: {{ display: false }} }} }}
}});

const rentSeries = {rent_series_json};
new Chart(document.getElementById('rentChart'), {{
  type: 'line',
  data: {{ labels: rentSeries.map(p => p.t.slice(0,10)), datasets: [
    {{ label: 'Studio', data: rentSeries.map(p => p.studio), borderColor: '#58a6ff', tension: 0.25, borderWidth: 1.5, pointRadius: 2 }},
    {{ label: '1 BR', data: rentSeries.map(p => p.one_br), borderColor: '#3fb950', tension: 0.25, borderWidth: 1.5, pointRadius: 2 }},
    {{ label: '2 BR', data: rentSeries.map(p => p.two_br), borderColor: '#d29922', tension: 0.25, borderWidth: 1.5, pointRadius: 2 }},
    {{ label: '3 BR', data: rentSeries.map(p => p.three_br), borderColor: '#f85149', tension: 0.25, borderWidth: 1.5, pointRadius: 2 }},
  ] }},
  options: {{ responsive: true, maintainAspectRatio: false, interaction: {{ intersect: false, mode: 'index' }}, scales: {{ x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0, font: {{ size: 10 }} }} }}, y: {{ ticks: {{ callback: v => '$' + Number(v).toLocaleString(), font: {{ size: 10 }} }}, grid: {{ color: 'rgba(48,54,61,0.6)' }} }} }}, plugins: {{ legend: {{ position: 'bottom', labels: {{ boxWidth: 10, padding: 14, usePointStyle: true, font: {{ size: 11 }}, color: '#8a8f98' }} }} }} }}
}});
</script>
</body>
</html>"""


def _detail_empty_html(prop: dict) -> str:
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><title>{_e(prop['name'])} — No Data</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
{_css()}
</head><body>
<header><div class="header-left">
  <a href="../" class="back-link">&larr; Comp Set Overview</a>
  <h1>{_e(prop['name'])}</h1>
  <div class="meta"><span>{_e(prop.get('address',''))}</span></div>
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
            f"<tr><td>{_e(item['item'])}</td><td class='num'>{_e(item['cost'])}</td>"
            f"<td class='note'>{_e(item.get('note', ''))}</td></tr>"
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
            f"<tr><td>{_e(item['type'])}</td><td class='num'>{_e(item['cost'])}</td></tr>"
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
            f"<tr><td>{_e(item['type'])}</td><td class='num'>{_e(item['cost'])}</td></tr>"
            for item in fees["bundled"]
        )
        note = ""
        if fees.get("bundled_note"):
            note = f'<div class="small">{_e(fees["bundled_note"])}</div>'
        sections.append(
            f'<div class="card span-6"><h2>Bundled Services</h2>{note}'
            '<div class="scroll"><table class="data-table">'
            '<thead><tr><th>Unit Type</th><th class="num">Monthly</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></div>'
        )

    if fees.get("pets"):
        rows = "".join(
            f"<tr><td>{_e(item['item'])}</td><td class='num'>{_e(item['cost'])}</td></tr>"
            for item in fees["pets"]
        )
        note = ""
        if fees.get("pet_policy"):
            note = f'<div class="small">{_e(fees["pet_policy"])}</div>'
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
        badge = f"<span class='badge'>{_e(et)}</span>"
    return f"<tr><td>{when}</td><td>{badge}</td><td class='mono'>{unit}</td><td>{_e(detail)}</td></tr>"


# ===========================================================================
# CSS (shared between overview + detail pages)
# ===========================================================================

def _css() -> str:
    return """<style>
  :root {
    --fg:#e8e8e8; --fg-strong:#fff; --muted:#8a8f98; --bg:#0e1117; --card:#161b22;
    --line:#30363d; --accent:#7c6bf1; --accent-soft:rgba(124,107,241,0.08);
    --green:#3fb950; --red:#f85149; --yellow:#d29922;
    --mono:ui-monospace,SFMono-Regular,"Cascadia Mono",Menlo,monospace;
  }
  * { box-sizing:border-box; margin:0; }
  body {
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--fg); margin:0;
    padding:0 clamp(12px,3vw,24px) 48px;
    font-size:13px; line-height:1.45; -webkit-font-smoothing:antialiased;
  }
  header {
    max-width:1400px; margin:0 auto;
    padding:16px 0 0; display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
  }
  .header-left { flex:1; }
  h1 {
    font-size:18px; font-weight:700; color:var(--fg-strong);
    letter-spacing:-0.01em;
  }
  .meta {
    color:var(--muted); font-size:12px; font-family:var(--mono);
    display:flex; gap:6px; flex-wrap:wrap; align-items:baseline; margin-top:4px;
  }
  .meta a { color:var(--accent); text-decoration:none; }
  .meta .sep { opacity:0.35; }
  .back-link {
    color:var(--accent); text-decoration:none; font-size:12px;
    font-family:var(--mono); display:inline-block; margin-bottom:4px;
  }
  .back-link:hover { text-decoration:underline; }
  .subject-badge {
    background:var(--accent); color:#fff; padding:2px 8px; border-radius:3px;
    font-size:11px; font-weight:700; letter-spacing:0.03em;
  }

  /* Tab bar */
  .tabs {
    max-width:1400px; margin:0 auto;
    display:flex; gap:0; border-bottom:1px solid var(--line);
    padding-top:10px; overflow-x:auto;
  }
  .tab {
    padding:8px 16px; font-size:11px; font-weight:600; color:var(--muted);
    text-transform:uppercase; letter-spacing:.05em; cursor:pointer;
    border:1px solid transparent; border-bottom:none; border-radius:4px 4px 0 0;
    background:none; font-family:inherit; position:relative; bottom:-1px;
    white-space:nowrap;
  }
  .tab:hover { color:var(--fg); }
  .tab.active {
    color:var(--fg-strong); background:var(--bg);
    border-color:var(--line); border-bottom:1px solid var(--bg);
  }
  .tab-panel { display:none; }
  .tab-panel.active { display:block; }

  .grid {
    max-width:1400px; margin:12px auto 0; display:grid;
    grid-template-columns:repeat(12,minmax(0,1fr)); gap:10px;
  }
  .card {
    background:var(--card); border:1px solid var(--line); border-radius:6px;
    padding:14px 16px;
  }
  .span-3 { grid-column:span 3; } .span-4 { grid-column:span 4; }
  .span-5 { grid-column:span 5; } .span-6 { grid-column:span 6; }
  .span-7 { grid-column:span 7; } .span-8 { grid-column:span 8; }
  .span-12 { grid-column:span 12; }
  @media (max-width:960px) {
    .span-3 { grid-column:span 6; }
    .span-4,.span-5,.span-6,.span-7,.span-8 { grid-column:span 12; }
  }
  @media (max-width:520px) { .span-3 { grid-column:span 12; } }

  /* KPI stat cards */
  .stat-card { display:flex; flex-direction:column; gap:2px; min-height:68px; justify-content:center; }
  .label {
    font-size:10px; color:var(--muted); text-transform:uppercase;
    letter-spacing:.08em; font-weight:600;
  }
  .stat {
    font-size:22px; font-weight:700; color:var(--fg-strong);
    font-family:var(--mono); line-height:1.15; font-variant-numeric:tabular-nums;
  }

  /* Section headings */
  h2 {
    font-size:13px; font-weight:600; color:var(--accent);
    text-transform:uppercase; letter-spacing:.04em;
    margin:0 0 6px;
  }
  h3 { font-size:13px; font-weight:600; color:var(--fg-strong); margin:0 0 8px; }
  .subtitle { color:var(--muted); font-size:11px; margin-bottom:10px; }
  .small {
    font-size:11px; color:var(--muted); margin-top:10px;
    font-family:var(--mono); line-height:1.4;
  }

  /* Charts */
  .chart-wrap { position:relative; height:220px; width:100%; }
  .chart-tall { height:300px; }
  .chart-wide { height:280px; }

  /* Tables */
  table { width:100%; border-collapse:collapse; font-size:12px; font-family:var(--mono); }
  th,td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
  tbody tr:hover td { background:var(--accent-soft); }
  th {
    background:var(--card); font-weight:600; font-size:10px;
    text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
    position:sticky; top:0; z-index:1;
  }
  th.num { text-align:right; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  td.mono { font-size:12px; }
  td.note { color:var(--muted); font-size:11px; }
  .muted { color:var(--muted); text-align:center; padding:24px !important; font-size:12px; }
  .scroll {
    max-height:min(540px,58vh); overflow:auto;
    border-radius:4px; border:1px solid var(--line); background:var(--card);
  }
  .scroll-wide { max-height:none; overflow-x:auto; }
  .scroll table { margin:0; }

  /* Comp table (overview) */
  .comp-table { min-width:800px; }
  .comp-table th { white-space:nowrap; font-size:11px; text-transform:none; letter-spacing:0; font-weight:700; min-width:100px; }
  .comp-table td { white-space:nowrap; font-size:12px; min-width:100px; }
  .comp-table .row-label {
    font-weight:600; color:var(--muted); font-size:11px; text-transform:uppercase;
    letter-spacing:.04em; position:sticky; left:0; background:var(--card); z-index:2;
    min-width:140px;
  }
  .comp-table thead th:first-child { position:sticky; left:0; background:var(--card); z-index:3; }
  .subject-col { background:rgba(124,107,241,0.06) !important; }
  .subject-row td { background:rgba(124,107,241,0.06) !important; }
  .subject-row td:first-child { color:var(--accent); font-weight:700; }

  /* Data table */
  .data-table { min-width:600px; }

  /* Comp average row */
  .comp-avg-row td { border-top:2px solid var(--line); font-weight:600; }

  /* Concession cell */
  .concession-cell { max-width:250px; white-space:normal !important; font-size:11px; color:var(--muted); }

  /* Badges */
  .badge {
    display:inline-block; padding:2px 7px; border-radius:3px;
    font-size:10px; font-weight:700; letter-spacing:.03em;
    text-transform:uppercase; white-space:nowrap; font-family:var(--mono);
  }
  .badge-add { background:rgba(63,185,80,0.15); color:var(--green); }
  .badge-remove { background:rgba(248,81,73,0.15); color:var(--red); }
  .badge-change { background:rgba(210,153,34,0.15); color:var(--yellow); }
  .badge-subject { background:var(--accent); color:#fff; }

  /* Comp cards (rent comps tab) */
  .comp-card { }
  .subject-card { border-color:var(--accent); border-width:2px; }
  .comp-header { display:flex; gap:12px; align-items:flex-start; margin-bottom:10px; }
  .comp-num {
    background:var(--accent); color:#fff; width:24px; height:24px;
    border-radius:50%; display:flex; align-items:center; justify-content:center;
    font-size:11px; font-weight:700; flex-shrink:0;
  }
  .comp-name { font-weight:700; color:var(--fg-strong); font-size:14px; }
  .comp-addr { font-size:11px; color:var(--muted); }
  .comp-mgmt { font-size:11px; color:var(--muted); font-style:italic; }
  .comp-stats {
    display:grid; grid-template-columns:repeat(3,1fr); gap:6px;
    margin-bottom:10px; padding:8px; background:rgba(255,255,255,0.03); border-radius:4px;
  }
  .comp-stat { text-align:center; }
  .comp-stat .label { display:block; font-size:9px; margin-bottom:2px; }
  .comp-stat span:last-child { font-weight:700; font-size:13px; color:var(--fg-strong); font-family:var(--mono); }
  .comp-bed-table { font-size:12px; }
  .comp-bed-table th { font-size:10px; }
  .bed-label { font-weight:600; }

  /* Metric cards */
  .metric-card { padding:0; overflow:hidden; }
  .metric-header { padding:12px 16px 8px; }
  .metric-header h3 { margin:0; }
  .metric-body { padding:0 16px 12px; }
  .metric-row {
    display:flex; justify-content:space-between; padding:5px 0;
    font-size:12px; border-bottom:1px solid var(--line);
    font-family:var(--mono);
  }
  .metric-row span:last-child { font-weight:600; color:var(--fg-strong); }

  /* Property nav */
  .prop-nav {
    position:fixed; top:80px; right:clamp(8px,2vw,20px);
    background:var(--card); border:1px solid var(--line); border-radius:6px;
    padding:12px; width:180px; max-height:calc(100vh - 120px); overflow-y:auto;
    z-index:10;
  }
  .prop-nav h3 {
    font-size:10px; color:var(--muted); text-transform:uppercase;
    letter-spacing:.06em; margin-bottom:8px;
  }
  .nav-link {
    display:block; padding:4px 8px; font-size:11px; color:var(--fg);
    text-decoration:none; border-radius:3px; margin-bottom:2px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }
  .nav-link:hover { background:var(--accent-soft); color:var(--fg-strong); }
  .nav-link.subject { color:var(--accent); font-weight:600; }

  @media (max-width:1200px) { .prop-nav { display:none; } }

  /* Disclaimer */
  .disclaimer {
    color:var(--muted); font-size:11px; font-style:italic;
    line-height:1.5; font-family:var(--mono);
  }
</style>"""


# ===========================================================================
# HELPERS
# ===========================================================================

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
    if s is None:
        return ""
    return html_mod.escape(str(s), quote=True)


def _json_safe(data) -> str:
    """Serialize data to JSON safe for embedding inside <script> tags.

    Escapes sequences that could break out of a script context:
      </   → <\\/   (prevents </script> injection)
      <!--  → <\\!-- (prevents HTML comment injection)
    Using ensure_ascii=True so all non-ASCII chars are \\uXXXX-escaped.
    """
    raw = json.dumps(data, ensure_ascii=True)
    raw = raw.replace("</", r"<\/")
    raw = raw.replace("<!--", r"<\!--")
    return raw
