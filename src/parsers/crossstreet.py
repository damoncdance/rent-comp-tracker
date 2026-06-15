"""Parser for Cross Street (yourcrossstreet.com) leasing pages.

Cross Street is a property-marketing front-end backed by RentCafe/SecureCafe
(apply links point at <prop>.securecafe.com). Unlike the RentCafe sites, the
floorplan and per-unit availability is **server-rendered** into the HTML, so a
plain requests.get() is enough — no Playwright/Cloudflare needed.

Layout:
- Bed-type sections, each headed by `fp-content-title` → e.g.
  "Studio (16 Available Units)", "1 Bed (...)", "2 Beds (...)".
- Within a section, one `fp-content-item` per floorplan, whose bar carries the
  plan name (e.g. "Plan 04"), a "N Bath" label, and a sqft range.
- Within a floorplan, one `fp-content-multi-units-item` per available unit:
    <div class="unit-item-aptname">204</div>        ← real apartment number
    <div class="unit-item-aptrent">$2,406</div>
    <div class="unit-item-aptsize">593 Sq. Ft.</div>
    <div class="unit-item-aptavailable">Available Jul 10</div>

Returns the standard normalized (units, floorplans) tuple.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from hashlib import md5


class ParseError(Exception):
    """Raised when we can't parse the expected data."""


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_SECTION_RE = re.compile(
    r'fp-content-title[^>]*>\s*(?:<[^>]+>\s*)*([^<(]+?)\s*\(\s*\d+\s*Available\s+Units?\s*\)',
    re.IGNORECASE,
)
_ITEM_RE = re.compile(
    r'fp-content-item fp-auto-expand.*?(?=fp-content-item fp-auto-expand|$)',
    re.DOTALL,
)
# Floorplans with several available units render one row each:
_UNIT_RE = re.compile(
    r'unit-item-aptname"\s*>\s*([^<]+?)\s*</div>\s*'
    r'<div class="unit-item-aptrent"\s*>\s*\$?([\d,]+)[^<]*</div>\s*'
    r'<div class="unit-item-aptsize"\s*>\s*([\d,]+)\s*Sq[^<]*</div>\s*'
    r'<div class="unit-item-aptavailable"\s*>\s*([^<]*)</div>',
    re.IGNORECASE,
)
# Floorplans with a single available unit use a different class set:
_SINGLE_UNIT_RE = re.compile(
    r'fp-content-single-unit-name"[^>]*>\s*([^<]+?)\s*</div>\s*'
    r'<div class="fp-content-single-unit-rent"[^>]*>\s*\$?([\d,]+)[^<]*</div>\s*'
    r'<div class="fp-content-single-unit-size"[^>]*>\s*([\d,]+)\s*Sq[^<]*</div>\s*'
    r'<div class="fp-content-single-unit-available"[^>]*>\s*([^<]*)</div>',
    re.IGNORECASE,
)
_NAME_RE = re.compile(
    r'fp-content-item-bar-left"\s*>\s*<div[^>]*>\s*([^<]+?)\s*</div>',
    re.IGNORECASE,
)
_BATH_RE = re.compile(r'(\d+)\s*Bath', re.IGNORECASE)


def _beds_from_title(title: str) -> int:
    """'Studio' -> 0, '1 Bed' -> 1, '2 Beds' -> 2."""
    t = title.lower()
    if "studio" in t:
        return 0
    m = re.search(r'(\d+)\s*bed', t)
    return int(m.group(1)) if m else 0


def _parse_available(raw: str, today: date | None = None) -> str:
    """'Available Jul 10' -> 'YYYY-MM-DD'. 'Available Now'/'' -> '' (ready now).

    Months with no year are assumed to be the next occurrence (this year, or
    next year if the day has already passed).
    """
    today = today or date.today()
    raw = raw.strip()
    if not raw or "now" in raw.lower():
        return ""
    m = re.search(r'([A-Za-z]{3,})\.?\s+(\d{1,2})(?:,\s*(\d{4}))?', raw)
    if not m:
        return ""
    month = _MONTHS.get(m.group(1)[:3].lower())
    if not month:
        return ""
    day = int(m.group(2))
    year = int(m.group(3)) if m.group(3) else today.year
    try:
        cand = date(year, month, day)
    except ValueError:
        return ""
    if not m.group(3) and cand < today:
        cand = date(year + 1, month, day)
    return cand.isoformat()


def parse_all(html: str) -> tuple[list[dict], list[dict]]:
    """Parse Cross Street HTML into normalized (units, floorplans)."""
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)

    headers = list(_SECTION_RE.finditer(html))
    if not headers:
        raise ParseError(
            "No 'N Available Units' floorplan sections found — "
            "Cross Street layout may have changed."
        )

    units: list[dict] = []
    seen_units: set[tuple[str, int]] = set()

    for i, hdr in enumerate(headers):
        beds = _beds_from_title(hdr.group(1))
        start = hdr.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(html)
        section = html[start:end]

        for item in _ITEM_RE.findall(section):
            # Floorplan name = the bar-left's first inner div (e.g. "Plan 04").
            name_m = _NAME_RE.search(item)
            fp_name = (name_m.group(1).strip() if name_m else "").strip() or "Floorplan"

            bath_m = _BATH_RE.search(item)
            baths = int(bath_m.group(1)) if bath_m else 1

            fp_id = int(md5(fp_name.encode()).hexdigest()[:8], 16)

            # Multi-unit rows, plus single-unit floorplans (different markup).
            rows = _UNIT_RE.findall(item) + _SINGLE_UNIT_RE.findall(item)
            for unit_num, rent_s, sqft_s, avail_s in rows:
                unit_num = unit_num.strip()
                rent = int(rent_s.replace(",", ""))
                if rent == 0:
                    continue
                key = (unit_num, fp_id)
                if key in seen_units:
                    continue
                seen_units.add(key)

                units.append({
                    "UnitCode": unit_num,
                    "FloorplanId": fp_id,
                    "FloorplanName": fp_name,
                    "Beds": beds,
                    "Baths": baths,
                    "SqFt": int(sqft_s.replace(",", "")),
                    "MinRent": rent,
                    "MaxRent": rent,
                    "AvailableDate": _parse_available(avail_s),
                    "ConcessionText": "",
                })

    if not units:
        raise ParseError(
            "Found floorplan sections but no available units — "
            "Cross Street layout may have changed."
        )

    # Roll units up into per-floorplan tiers.
    groups: dict[int, list[dict]] = defaultdict(list)
    for u in units:
        groups[u["FloorplanId"]].append(u)

    floorplans = []
    for fp_id, fp_units in groups.items():
        first = fp_units[0]
        dates = [u["AvailableDate"] for u in fp_units if u["AvailableDate"]]
        floorplans.append({
            "Id": fp_id,
            "Beds": first["Beds"],
            "Baths": first["Baths"],
            "MinSqFt": min(u["SqFt"] for u in fp_units),
            "MaxSqFt": max(u["SqFt"] for u in fp_units),
            "MinRent": min(u["MinRent"] for u in fp_units),
            "MaxRent": max(u["MaxRent"] for u in fp_units),
            "AvailableCount": len(fp_units),
            "AvailableDate": min(dates) if dates else "",
        })

    return units, floorplans
