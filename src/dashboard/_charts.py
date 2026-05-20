from __future__ import annotations
from collections import defaultdict
from src.dashboard._constants import COLORS, BED_COLORS
from src.dashboard._helpers import json_safe

# Subject line gets heavier stroke + larger points; comps are thinner + muted.
_SUBJECT_STYLE = {"borderWidth": 2.5, "pointRadius": 4, "pointHoverRadius": 7, "pointHitRadius": 20}
_COMP_STYLE = {"borderWidth": 1.5, "pointRadius": 2, "pointHoverRadius": 5, "pointHitRadius": 20}


# ===========================================================================
# RANKINGS (HelloData p20)
# ===========================================================================

def build_rankings_data(grid: list[dict]) -> str:
    """Build JSON data for the 4 ranking bar charts."""
    result = {}
    for beds, key in [(0, 'studio'), (1, 'one_br'), (2, 'two_br'), (3, 'three_br')]:
        items = []
        for p in grid:
            bd = p.get("by_bed", {}).get(beds)
            if bd and bd.get("avg_rent"):
                items.append({
                    "name": p["name"],
                    "short": p["name"][:18] + "\u2026" if len(p["name"]) > 18 else p["name"],
                    "rent": round(bd["avg_rent"]),
                    "is_subject": bool(p.get("is_subject")),
                })
        items.sort(key=lambda x: x["rent"], reverse=True)

        if items:
            subject_color = '#6e7681'
            bed_color = BED_COLORS.get(beds, '#58a6ff')
            result[key] = {
                "labels": [i["short"] for i in items],
                "fullNames": [i["name"] for i in items],
                "values": [i["rent"] for i in items],
                "colors": [subject_color if i["is_subject"] else bed_color for i in items],
            }
        else:
            result[key] = {"labels": [], "fullNames": [], "values": [], "colors": []}

    return json_safe(result)


# ===========================================================================
# TREND CHARTS DATA
# ===========================================================================

def build_rent_trend_chart_data(rent_hist: list[dict], subject_name: str = "") -> str:
    """Build Chart.js data for rent trends with subject emphasis."""
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
        color = COLORS[i % len(COLORS)]
        is_subj = (name == subject_name)
        style = _SUBJECT_STYLE if is_subj else _COMP_STYLE
        ds = {
            "label": name,
            "data": [rent_by_date.get(d) for d in labels],
            "borderColor": color,
            "tension": 0.25,
            "fill": False,
            "spanGaps": True,
            **style,
        }
        if is_subj:
            ds["order"] = 0  # draw subject on top
        datasets.append(ds)

    # Move subject dataset to front so it renders on top
    datasets.sort(key=lambda d: 0 if d.get("order") == 0 else 1)

    return json_safe({"labels": labels, "datasets": datasets})


def build_leasing_activity_chart_data(activity: list[dict]) -> str:
    """Build Chart.js data for daily leasing activity (stacked bar).

    Only includes properties that had at least one leasing event to reduce
    legend noise.
    """
    by_prop: dict[str, list] = defaultdict(list)
    all_dates = set()
    for r in activity:
        day = r["day"]
        all_dates.add(day)
        by_prop[r["name"]].append({"day": day, "leased": r["units_leased"]})

    labels = sorted(all_dates)
    datasets = []
    for i, (name, points) in enumerate(sorted(by_prop.items())):
        leased_by_date = {p["day"]: p["leased"] for p in points}
        total_leased = sum(leased_by_date.values())
        if total_leased == 0:
            continue  # skip properties with no activity
        color = COLORS[i % len(COLORS)]
        datasets.append({
            "label": name,
            "data": [leased_by_date.get(d, 0) for d in labels],
            "backgroundColor": color,
            "borderWidth": 0,
            "borderRadius": 2,
        })

    return json_safe({"labels": labels, "datasets": datasets})


def build_exposure_chart_data(exposure: list[dict], subject_name: str = "") -> str:
    """Build Chart.js data for exposure % over time with subject emphasis."""
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
        color = COLORS[i % len(COLORS)]
        is_subj = (name == subject_name)
        style = _SUBJECT_STYLE if is_subj else _COMP_STYLE
        ds = {
            "label": name,
            "data": [pct_by_date.get(d) for d in labels],
            "borderColor": color,
            "tension": 0.25,
            "fill": False,
            "spanGaps": True,
            **style,
        }
        if is_subj:
            ds["order"] = 0
        datasets.append(ds)

    datasets.sort(key=lambda d: 0 if d.get("order") == 0 else 1)

    return json_safe({"labels": labels, "datasets": datasets})
