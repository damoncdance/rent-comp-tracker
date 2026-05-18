from __future__ import annotations
import re
from collections import defaultdict
from datetime import datetime, timezone

from src.dashboard._constants import BED_COLORS, BED_LABELS
from src.dashboard._helpers import e, is_vacant
from src.fees import FEES


# ===========================================================================
# OVERVIEW TABLE (HelloData p2 style)
# ===========================================================================

def build_overview_table(grid: list[dict], dom_data: dict | None = None,
                         velocity_data: dict | None = None) -> str:
    """Build the side-by-side comp overview table."""
    # Header row with property names
    headers = '<th class="row-label"></th>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        headers += f'<th{cls}>{e(p["name"])}</th>'

    # Data rows
    rows = []

    # Management Company
    r = '<td class="row-label">Management Company</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        r += f'<td{cls}>{e(p.get("management_company", ""))}</td>'
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

    # Leased %
    r = '<td class="row-label">Leased</td>'
    today = datetime.now(timezone.utc).date()
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        total = p.get("unit_count_total") or 0
        avail_dates = p.get("avail_dates", [])
        if total and avail_dates is not None:
            vacant = sum(1 for d in avail_dates if is_vacant(d, today))
            leased = round((total - vacant) / total * 100, 1)
            r += f'<td{cls}>{leased}%</td>'
        else:
            r += f'<td{cls}>—</td>'
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

    # Days on Market
    r = '<td class="row-label">Avg Days on Mkt</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        dom = (dom_data or {}).get(p.get("id"), {})
        avg = dom.get("avg_dom")
        r += f'<td{cls}>{avg:.0f}d</td>' if avg is not None else f'<td{cls}>—</td>'
    rows.append(r)

    # Leasing Velocity (7-day)
    r = '<td class="row-label">Leased (7d)</td>'
    for p in grid:
        cls = ' class="subject-col"' if p.get("is_subject") else ''
        vel = (velocity_data or {}).get(p.get("id"), {})
        leased = vel.get("units_leased", 0)
        absorb = vel.get("absorption_pct", 0)
        if leased:
            r += f'<td{cls}>{leased} ({absorb}%)</td>'
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
            r += f'<td{cls} class="concession-cell">{e(text)}</td>'
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

def build_bed_type_tables(grid: list[dict]) -> str:
    """Build per-bed-type breakdown tables (Studio, 1BR, 2BR, 3BR)."""
    sections = []
    for beds in [0, 1, 2, 3]:
        label = BED_LABELS.get(beds, f"{beds} BR")
        color = BED_COLORS.get(beds, '#58a6ff')

        headers = f'<th class="row-label" style="border-left:3px solid {color}">{label}</th>'
        for p in grid:
            cls = ' class="subject-col"' if p.get("is_subject") else ''
            headers += f'<th{cls}>{e(p["name"])}</th>'

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
# RENTS BY UNIT TYPE TABLE (HelloData p19)
# ===========================================================================

def build_rents_by_unit_type_table(rents: list[dict],
                                   dom_data: dict | None = None,
                                   velocity_data: dict | None = None) -> str:
    """Build the cross-property rent comparison table."""
    rows = ""
    for r in rents:
        is_subj = r.get("is_subject")
        cls = ' class="subject-row"' if is_subj else ''
        name = e(r["name"])
        active = r.get("active_units", 0)
        pid = r.get("id")

        # DOM and velocity for this property
        dom = (dom_data or {}).get(pid, {})
        vel = (velocity_data or {}).get(pid, {})
        avg_dom = dom.get("avg_dom")
        leased_7d = vel.get("units_leased", 0)

        if active == 0:
            rows += f'<tr{cls}><td>{name}</td><td class="num">0</td>' + '<td class="num">—</td>' * 7 + '</tr>'
            continue

        min_r = r.get("min_rent", 0) or 0
        avg_r = r.get("avg_rent", 0) or 0
        max_r = r.get("max_rent", 0) or 0
        avg_sf = r.get("avg_sqft", 0) or 0
        avg_psf = r.get("avg_psf", 0) or 0
        dom_str = f'{avg_dom:.0f}d' if avg_dom is not None else '—'
        vel_str = str(leased_7d) if leased_7d else '—'

        rows += (
            f'<tr{cls}>'
            f'<td>{name}</td>'
            f'<td class="num">{active}</td>'
            f'<td class="num">${min_r:,.0f}</td>'
            f'<td class="num">${avg_r:,.0f}</td>'
            f'<td class="num">${max_r:,.0f}</td>'
            f'<td class="num">{avg_sf:,.0f} ft²</td>'
            f'<td class="num">${avg_psf:.2f}/ft²</td>'
            f'<td class="num">{dom_str}</td>'
            f'<td class="num">{vel_str}</td>'
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

        # Average DOM across comps
        comp_doms = [
            (dom_data or {}).get(r.get("id"), {}).get("avg_dom")
            for r in comp_rents
        ]
        comp_doms_valid = [d for d in comp_doms if d is not None]
        avg_dom_str = f'{sum(comp_doms_valid)/len(comp_doms_valid):.0f}d' if comp_doms_valid else '—'

        # Total leased across comps
        comp_leased = sum(
            (velocity_data or {}).get(r.get("id"), {}).get("units_leased", 0)
            for r in comp_rents
        )
        vel_avg_str = str(comp_leased) if comp_leased else '—'

        rows += (
            f'<tr class="comp-avg-row">'
            f'<td><strong>Comp Average</strong></td>'
            f'<td class="num">{avg_active:.0f}</td>'
            f'<td class="num">${avg_min:,.0f}</td>'
            f'<td class="num">${avg_rent:,.0f}</td>'
            f'<td class="num">${avg_max:,.0f}</td>'
            f'<td class="num">{avg_sqft:,.0f} ft²</td>'
            f'<td class="num">${avg_psf:.2f}/ft²</td>'
            f'<td class="num">{avg_dom_str}</td>'
            f'<td class="num">{vel_avg_str}</td>'
            f'</tr>'
        )

    return f"""<table class="data-table">
<thead><tr>
  <th>Property</th><th class="num"># Active</th>
  <th class="num">Min Rent</th><th class="num">Avg Rent</th><th class="num">Max Rent</th>
  <th class="num">Avg SqFt</th><th class="num">Avg PSF</th>
  <th class="num">Avg DOM</th><th class="num">Leased 7d</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>"""


# ===========================================================================
# CONCESSIONS TABLE (HelloData p31)
# ===========================================================================

def build_concessions_table(grid: list[dict]) -> str:
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
        rows += f'<tr{cls}><td>{e(p["name"])}</td><td class="concession-cell">{e(text)}</td></tr>'

    return f"""<table class="data-table">
<thead><tr><th>Property</th><th>Concession</th></tr></thead>
<tbody>{rows}</tbody>
</table>"""


# ===========================================================================
# FEES COMPARISON TABLE (HelloData p30)
# ===========================================================================

def build_fees_comparison_table(grid: list[dict]) -> str:
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
            f'<tr{cls}><td>{e(p["name"])}</td>'
            f'<td class="num">{e(app_fee)}</td>'
            f'<td class="num">{e(admin_fee)}</td>'
            f'<td class="num">{e(pet_rent)}</td>'
            f'<td class="num">{e(parking)}</td></tr>'
        )

    # Market average row — extract first dollar amount from each fee string
    def _parse_dollars(s: str) -> float | None:
        if not s or s == "—":
            return None
        m = re.search(r'\$([0-9,]+(?:\.\d+)?)', s)
        return float(m.group(1).replace(",", "")) if m else None

    # Collect parsed values per column
    all_fees: dict[str, list[float]] = {"app": [], "admin": [], "pet": [], "park": []}
    for p in grid:
        fees = FEES.get(p["name"], {})
        af = ad = pr = pk = "—"
        if fees.get("application"):
            for item in fees["application"]:
                if "application" in item["item"].lower():
                    af = item["cost"]
                elif "admin" in item["item"].lower():
                    ad = item["cost"]
        if fees.get("pets"):
            for item in fees["pets"]:
                if "monthly" in item["item"].lower() or "rent" in item["item"].lower():
                    pr = item["cost"]
        if fees.get("parking"):
            costs = [item["cost"] for item in fees["parking"]]
            pk = costs[0] if costs else "—"
        for key, val in [("app", af), ("admin", ad), ("pet", pr), ("park", pk)]:
            v = _parse_dollars(val)
            if v is not None:
                all_fees[key].append(v)

    def _avg_fmt(vals: list[float]) -> str:
        return f"${sum(vals)/len(vals):,.0f}" if vals else "—"

    avg_row = (
        f'<tr class="comp-avg-row"><td><strong>Market Average</strong></td>'
        f'<td class="num">{_avg_fmt(all_fees["app"])}</td>'
        f'<td class="num">{_avg_fmt(all_fees["admin"])}</td>'
        f'<td class="num">{_avg_fmt(all_fees["pet"])}</td>'
        f'<td class="num">{_avg_fmt(all_fees["park"])}</td></tr>'
    )

    return f"""<table class="data-table">
<thead><tr><th>Property</th><th class="num">Application Fee</th>
<th class="num">Admin Fee</th><th class="num">Pet Rent</th>
<th class="num">Parking</th></tr></thead>
<tbody>{rows}{avg_row}</tbody>
</table>"""
