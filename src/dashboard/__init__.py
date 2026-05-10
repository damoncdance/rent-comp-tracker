"""Render the static HTML dashboard — HelloData-style comp set view.

Generates:
  dashboard/index.html         — comp set overview (all properties)
  dashboard/{slug}/index.html  — per-property detail pages

Single-file outputs with embedded JSON data and Chart.js from CDN.
No build step, no server.

Modules:
  _constants  — color palette, bed labels
  _helpers    — HTML escaping, date formatting, slug validation, JSON serialization
  _css        — shared stylesheet
  _detail     — per-property detail page rendering
  _tables     — overview/comp/fee/concession table builders
  _charts     — Chart.js data builders (rankings, trends, exposure)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path

from src.config import DASHBOARD_DIR, get_active_properties
from src.pricing import generate_recommendations, signal_label, signal_color
from src.storage import comp_grid_data, rents_by_unit_type, exposure_history, rent_history_by_property

from src.dashboard._constants import BED_COLORS as _BED_COLORS, BED_LABELS as _BED_LABELS
from src.dashboard._helpers import e as _e, json_safe as _json_safe, fmt_dt as _fmt_dt, safe_slug as _safe_slug, is_vacant as _is_vacant
from src.dashboard._css import css as _css
from src.dashboard._detail import render_property_detail as _render_property_detail
from src.dashboard._tables import (
    build_overview_table as _build_overview_table,
    build_bed_type_tables as _build_bed_type_tables,
    build_rents_by_unit_type_table as _build_rents_by_unit_type_table,
    build_concessions_table as _build_concessions_table,
    build_fees_comparison_table as _build_fees_comparison_table,
)
from src.dashboard._charts import (
    build_rankings_data as _build_rankings_data,
    build_rent_trend_chart_data as _build_rent_trend_chart_data,
    build_exposure_chart_data as _build_exposure_chart_data,
)


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
    # Count unique trend dates for sparse-data note
    _trend_dates = set(r["fetched_at"][:10] for r in rent_hist) if rent_hist else set()
    _sparse_note = (f'<p class="sparse-note">{len(_trend_dates)} of 7 days collected</p>'
                    if len(_trend_dates) < 7 else '')
    concessions_table = _build_concessions_table(grid)
    fees_table = _build_fees_comparison_table(grid)
    pricing_html = _build_pricing_tab()

    # Property nav links for sidebar
    nav_links = "".join(
        f'<a href="{_e(_safe_slug(p["slug"]))}/index.html" class="nav-link{" subject" if p.get("is_subject") else ""}" role="menuitem">'
        f'{_e(p["name"])}</a>'
        for p in grid
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_e(subject_name)} — Rent Comp Report</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js" integrity="sha384-9nhczxUqK87bcKHh20fSQcTGD4qq5GhayNYSYWqwBkINBhOfQLg/P5HG5lF1urn4" crossorigin="anonymous"></script>
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
  <nav class="prop-nav" id="propNav">
    <button class="prop-nav-toggle" aria-haspopup="true" aria-expanded="false" aria-controls="propNavMenu"
      onclick="var n=document.getElementById('propNav'),open=n.classList.toggle('open');this.setAttribute('aria-expanded',String(open))">
      Properties &#9660;
    </button>
    <div class="prop-nav-menu" id="propNavMenu" role="menu">
      {nav_links}
    </div>
  </nav>
</header>

<div class="tabs" role="tablist" aria-label="Dashboard sections">
  <button class="tab active" role="tab" aria-selected="true" aria-controls="tab-overview" id="btn-overview" data-tab="overview" tabindex="0">Overview</button>
  <button class="tab" role="tab" aria-selected="false" aria-controls="tab-bytypes" id="btn-bytypes" data-tab="bytypes" tabindex="-1">By Unit Type</button>
  <button class="tab" role="tab" aria-selected="false" aria-controls="tab-comps" id="btn-comps" data-tab="comps" tabindex="-1">Rent Comps</button>
  <button class="tab" role="tab" aria-selected="false" aria-controls="tab-rankings" id="btn-rankings" data-tab="rankings" tabindex="-1">Rankings</button>
  <button class="tab" role="tab" aria-selected="false" aria-controls="tab-trends" id="btn-trends" data-tab="trends" tabindex="-1">Trends</button>
  <button class="tab" role="tab" aria-selected="false" aria-controls="tab-concessions" id="btn-concessions" data-tab="concessions" tabindex="-1">Concessions</button>
  <button class="tab" role="tab" aria-selected="false" aria-controls="tab-fees" id="btn-fees" data-tab="fees" tabindex="-1">Fees</button>
  <button class="tab" role="tab" aria-selected="false" aria-controls="tab-pricing" id="btn-pricing" data-tab="pricing" tabindex="-1">Pricing</button>
</div>

<!-- TAB: Overview -->
<div id="tab-overview" class="tab-panel active" role="tabpanel" aria-labelledby="btn-overview">
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
<div id="tab-bytypes" class="tab-panel" role="tabpanel" aria-labelledby="btn-bytypes" aria-hidden="true">
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
<div id="tab-comps" class="tab-panel" role="tabpanel" aria-labelledby="btn-comps" aria-hidden="true">
<div class="grid">
  <div class="card span-12">
    <h2>Rent Comps</h2>
    <p class="subtitle">Benchmark your property against comps.</p>
  </div>
  {rent_comps_cards}
</div>
</div>

<!-- TAB: Rankings -->
<div id="tab-rankings" class="tab-panel" role="tabpanel" aria-labelledby="btn-rankings" aria-hidden="true">
<div class="grid">
  <div class="card span-12">
    <h2>Property Rankings</h2>
    <p class="subtitle">Compare asking rents by bedroom count across your market.</p>
  </div>
  <div class="card span-6"><h3>Studio</h3><div class="chart-wrap chart-tall"><canvas id="rankStudio" aria-label="Bar chart ranking properties by studio rent"></canvas></div></div>
  <div class="card span-6"><h3>1 BR</h3><div class="chart-wrap chart-tall"><canvas id="rank1BR" aria-label="Bar chart ranking properties by 1-bedroom rent"></canvas></div></div>
  <div class="card span-6"><h3>2 BR</h3><div class="chart-wrap chart-tall"><canvas id="rank2BR" aria-label="Bar chart ranking properties by 2-bedroom rent"></canvas></div></div>
  <div class="card span-6"><h3>3 BR</h3><div class="chart-wrap chart-tall"><canvas id="rank3BR" aria-label="Bar chart ranking properties by 3-bedroom rent"></canvas></div></div>
</div>
</div>

<!-- TAB: Trends -->
<div id="tab-trends" class="tab-panel" role="tabpanel" aria-labelledby="btn-trends" aria-hidden="true">
{_sparse_note}
<div class="grid">
  <div class="card span-12">
    <h2>Historical Rent Trends</h2>
    <p class="subtitle">Average rent over time across your comp set.</p>
    <div class="chart-wrap chart-wide"><canvas id="rentTrendChart" aria-label="Line chart showing average rent trends over time across all properties"></canvas></div>
  </div>
  <div class="card span-12">
    <h2>Historical Exposure</h2>
    <p class="subtitle">Track the percentage of units listed for rent over time.</p>
    <div class="chart-wrap chart-wide"><canvas id="exposureChart" aria-label="Line chart showing exposure percentage over time across all properties"></canvas></div>
  </div>
</div>
</div>

<!-- TAB: Concessions -->
<div id="tab-concessions" class="tab-panel" role="tabpanel" aria-labelledby="btn-concessions" aria-hidden="true">
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
<div id="tab-fees" class="tab-panel" role="tabpanel" aria-labelledby="btn-fees" aria-hidden="true">
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

<!-- TAB: Pricing -->
<div id="tab-pricing" class="tab-panel" role="tabpanel" aria-labelledby="btn-pricing" aria-hidden="true">
{pricing_html}
</div>

<script>
/* Close property dropdown on outside click or Escape */
document.addEventListener('click', function(e) {{
  var nav = document.getElementById('propNav');
  if (nav && !nav.contains(e.target)) {{
    nav.classList.remove('open');
    nav.querySelector('.prop-nav-toggle').setAttribute('aria-expanded', 'false');
  }}
}});
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') {{
    var nav = document.getElementById('propNav');
    if (nav && nav.classList.contains('open')) {{
      nav.classList.remove('open');
      var btn = nav.querySelector('.prop-nav-toggle');
      btn.setAttribute('aria-expanded', 'false');
      btn.focus();
    }}
  }}
}});

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
    var panel = document.getElementById('tab-' + tab.dataset.tab);
    panel.classList.add('active');
    panel.removeAttribute('aria-hidden');
  }}
  tabs.forEach(function(btn) {{ btn.addEventListener('click', function() {{ activate(btn); }}); }});
  /* Keyboard: Left/Right arrows, Home/End */
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
var C_MUTED = _c('--muted'), C_LINE = _c('--line'), C_GREEN = _c('--green'),
    C_RED = _c('--red'), C_YELLOW = _c('--yellow'), C_ACCENT = _c('--accent');
var C_LINE_ALPHA = 'rgba(48,54,61,0.6)';

Chart.defaults.color = C_MUTED;
Chart.defaults.borderColor = C_LINE;
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
          grid: {{ color: C_LINE_ALPHA }}
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
          grid: {{ color: C_LINE_ALPHA }}
        }}
      }},
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ boxWidth: 6, padding: 10, usePointStyle: true, pointStyleWidth: 6, font: {{ size: 10 }}, color: C_MUTED }} }}
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
          grid: {{ color: C_LINE_ALPHA }},
          beginAtZero: true,
          max: 100
        }}
      }},
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ boxWidth: 6, padding: 10, usePointStyle: true, pointStyleWidth: 6, font: {{ size: 10 }}, color: C_MUTED }} }}
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
# RENT COMPS CARDS (HelloData p16-17)
# ===========================================================================

def _build_rent_comps_cards(grid: list[dict]) -> str:
    """Build per-property detail cards like HelloData p16-17."""
    cards = []
    today = datetime.now(timezone.utc).date()
    current_year = today.year
    for i, p in enumerate(grid):
        is_subj = p.get("is_subject")
        badge = '<span class="badge badge-subject">Subject</span>' if is_subj else f'<span class="comp-num">{i}</span>'
        # Flag lease-up properties (built within last 12 months)
        yb = p.get("year_built")
        is_leaseup = yb is not None and isinstance(yb, (int, float)) and (current_year - int(yb)) <= 1
        total = p.get("unit_count_total") or 0
        avail = p.get("unit_count") or 0
        exposure = round(avail / total * 100, 1) if total else 0

        # Leased % uses 7-day vacancy threshold (consistent with overview tab)
        avail_dates = p.get("avail_dates", [])
        if total and avail_dates:
            vacant = sum(1 for d in avail_dates if _is_vacant(d, today))
            leased = round((total - vacant) / total * 100, 1)
        elif total:
            leased = round((1 - avail / total) * 100, 1)
        else:
            leased = 0

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
        <div class="comp-name">{_e(p["name"])}{'<span class="badge-leaseup">Lease-Up</span>' if is_leaseup else ''}</div>
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
# PRICING RECOMMENDATIONS TAB
# ===========================================================================

def _build_pricing_tab() -> str:
    """Build the Pricing tab content with recommendations for the subject property."""
    report = generate_recommendations()
    if report is None:
        return ('<div class="grid"><div class="card span-12">'
                '<p class="muted">No pricing data available. Need subject + comp snapshots.</p>'
                '</div></div>')

    s = report.summary

    # Signal badge helper
    def _signal_badge(sig: str) -> str:
        color = signal_color(sig)
        label = signal_label(sig)
        return (f'<span style="color:{color};font-weight:600;'
                f'font-size:11px;">{_e(label)}</span>')

    # Revenue impact color
    impact = s["monthly_revenue_impact"]
    impact_color = "var(--green)" if impact >= 0 else "var(--red)"
    impact_sign = "+" if impact >= 0 else ""

    # Summary cards
    cards_html = f"""
<div class="grid">
  <div class="card span-3 stat-card">
    <div class="label">Quality Score</div>
    <div class="stat">{s['subject_quality_score']}<span style="font-size:13px;color:var(--muted);font-weight:400;"> / 10</span></div>
    <div style="font-size:11px;color:var(--muted);margin-top:2px;">Comp avg: {s['comp_avg_quality_score']}</div>
  </div>
  <div class="card span-3 stat-card">
    <div class="label">Exposure</div>
    <div class="stat">{s['subject_exposure']}%</div>
    <div style="font-size:11px;color:var(--muted);margin-top:2px;">Comp avg: {s['comp_avg_exposure']}%</div>
  </div>
  <div class="card span-3 stat-card">
    <div class="label">Revenue Impact</div>
    <div class="stat" style="color:{impact_color};">{impact_sign}${abs(impact):,}<span style="font-size:13px;font-weight:400;">/mo</span></div>
    <div style="font-size:11px;color:var(--muted);margin-top:2px;">If all units at recommended</div>
  </div>
  <div class="card span-3 stat-card">
    <div class="label">Pricing Signals</div>
    <div style="font-size:13px;margin-top:4px;font-family:var(--mono);">
      <span style="color:var(--red);">{s['overpriced_count']}</span> over
      <span style="margin:0 4px;opacity:0.3;">|</span>
      <span style="color:var(--muted);">{s['market_count']}</span> market
      <span style="margin:0 4px;opacity:0.3;">|</span>
      <span style="color:var(--green);">{s['underpriced_count']}</span> under
    </div>
    <div style="font-size:10px;color:var(--muted);margin-top:6px;">
      <span style="color:var(--red);">Red</span> = listed above recommended &middot;
      <span style="color:var(--green);">Green</span> = listed below recommended &middot;
      Gray = at market
    </div>
  </div>
"""

    # Market PSF cards
    psf_cards = ""
    for beds in sorted(report.market_psf_by_bed.keys()):
        label = _BED_LABELS.get(beds, f"{beds} BR")
        color = _BED_COLORS.get(beds, '#58a6ff')
        psf = report.market_psf_by_bed[beds]
        psf_cards += (
            f'<div class="card span-3 metric-card">'
            f'<div class="metric-header" style="border-top:3px solid {color}"><h3>{label} Market PSF</h3></div>'
            f'<div class="metric-body">'
            f'<div class="metric-row"><span>Market PSF</span><span>${psf:.2f}/ft²</span></div>'
            f'</div></div>'
        )
    cards_html += psf_cards

    # Recommendation table — grouped by bed type with subtotals
    rows = ""
    # Sort units by beds then unit code
    sorted_units = sorted(report.units, key=lambda u: (u.beds, u.unit_code))
    # Group by bed type
    from itertools import groupby
    for beds, group in groupby(sorted_units, key=lambda u: u.beds):
        bed_units = list(group)
        beds_label = "Studio" if beds == 0 else f"{beds} BR"
        color = _BED_COLORS.get(beds, '#58a6ff')

        # Section header row
        rows += (
            f'<tr class="bed-group-header">'
            f'<td colspan="13" style="border-left:3px solid {color};font-weight:700;'
            f'font-size:11px;text-transform:uppercase;letter-spacing:.04em;'
            f'color:var(--fg-strong);padding:10px 10px 6px;">{beds_label} ({len(bed_units)} units)</td>'
            f'</tr>'
        )

        for u in bed_units:
            delta_color = "var(--green)" if u.delta > 0 else "var(--red)" if u.delta < 0 else "var(--muted)"
            delta_sign = "+" if u.delta >= 0 else ""

            rows += (
                f'<tr>'
                f'<td class="mono">{_e(u.unit_code)}</td>'
                f'<td>{_e(u.floorplan_name)}</td>'
                f'<td class="num">{beds_label[:1] if beds == 0 else str(beds) + "BR"}</td>'
                f'<td class="num">{int(u.sqft):,}</td>'
                f'<td class="num">${u.listed_rent:,.0f}</td>'
                f'<td class="num" style="font-weight:700;">${u.recommended_rent:,.0f}</td>'
                f'<td class="num">${u.aggressive_rent:,.0f}</td>'
                f'<td class="num">${u.conservative_rent:,.0f}</td>'
                f'<td class="num" style="color:{delta_color};">{delta_sign}${abs(u.delta):,.0f}</td>'
                f'<td class="num" style="color:{delta_color};">{u.delta_pct*100:+.1f}%</td>'
                f'<td>{_signal_badge(u.signal)}</td>'
                f'<td class="num">${u.unit_psf:.2f}</td>'
                f'<td class="num">${u.recommended_psf:.2f}</td>'
                f'</tr>'
            )

        # Subtotal row for this bed type
        avg_listed = sum(u.listed_rent for u in bed_units) / len(bed_units)
        avg_rec = sum(u.recommended_rent for u in bed_units) / len(bed_units)
        avg_delta = sum(u.delta for u in bed_units) / len(bed_units)
        total_impact = sum(u.delta for u in bed_units)
        sub_color = "var(--green)" if avg_delta > 0 else "var(--red)" if avg_delta < 0 else "var(--muted)"
        sub_sign = "+" if avg_delta >= 0 else ""
        rows += (
            f'<tr style="border-top:1px solid var(--line);font-weight:600;font-size:11px;">'
            f'<td colspan="4" style="text-align:right;color:var(--muted);">{beds_label} subtotal</td>'
            f'<td class="num">${avg_listed:,.0f}</td>'
            f'<td class="num">${avg_rec:,.0f}</td>'
            f'<td colspan="2"></td>'
            f'<td class="num" style="color:{sub_color};">{sub_sign}${abs(avg_delta):,.0f}</td>'
            f'<td colspan="2"></td>'
            f'<td colspan="2" class="num" style="color:{sub_color};">Impact: {sub_sign}${abs(total_impact):,.0f}/mo</td>'
            f'</tr>'
        )

    table_html = f"""
  <div class="card span-12">
    <h2 style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">Pricing — {_e(report.subject_name)}</h2>
    <p class="subtitle">{report.comp_count} comps analyzed &middot; Generated {_fmt_dt(report.generated_at)}</p>
    <div class="scroll scroll-wide">
      <table class="data-table" style="min-width:1100px;">
        <thead><tr>
          <th>Unit</th><th>Floorplan</th><th class="num">Type</th><th class="num">SqFt</th>
          <th class="num">Listed</th><th class="num">Recommended</th>
          <th class="num">Aggressive</th><th class="num">Conservative</th>
          <th class="num">Delta</th><th class="num">Delta %</th><th>Signal</th>
          <th class="num">Listed PSF</th><th class="num">Rec PSF</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
"""

    # Summary row
    summary_html = f"""
  <div class="card span-12">
    <h2>Summary</h2>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;font-family:var(--mono);font-size:12px;">
      <div><span style="color:var(--muted);">Avg Listed:</span> <strong>${s['avg_listed']:,}</strong></div>
      <div><span style="color:var(--muted);">Avg Recommended:</span> <strong>${s['avg_recommended']:,}</strong></div>
      <div><span style="color:var(--muted);">Avg Delta:</span> <strong style="color:{delta_color};">{impact_sign}${abs(s['avg_delta']):,}</strong></div>
      <div><span style="color:var(--muted);">Avg Delta %:</span> <strong style="color:{delta_color};">{s['avg_delta_pct']*100:+.1f}%</strong></div>
    </div>
  </div>
"""

    return cards_html + table_html + summary_html + "</div>"

