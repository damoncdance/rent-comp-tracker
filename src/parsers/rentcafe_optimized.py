"""Parser for newer RentCafe "optimized floorplans" pages.

Some RentCafe sites (like Inspire West Town) use a newer layout that does NOT
embed `ysi.unitsList` or `ysi.floorplansList` in the HTML. Instead, unit data
is found by:

1. Visiting the main /floorplans page to find "Availability" links
2. Visiting each floorplan detail page to extract real unit data from
   `applyGAClick()` calls (which include apartment number, rent, sqft,
   and move-in date)

Floorplans that show "Contact Us" instead of "Availability" have no available
units and are excluded from the results — $0 rent in the GA4 data means
the unit is not available.

The scraper (`fetch_rentcafe_optimized`) handles the multi-page navigation
and returns a JSON string of extracted data. This parser normalizes that
into the standard (units, floorplans) format.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from hashlib import md5


class ParseError(Exception):
    """Raised when we can't parse the expected data."""


# Fallback: extract floorplan-tier data from GA4 cookies on main page
_GA4_RE = re.compile(
    r"setGA4Cookie\(\s*'GT'\s*,"
    r"\s*'([^']+)'\s*,"   # floorplan name
    r"\s*'(\d+)'\s*,"     # beds
    r"\s*'(\d+)'\s*,"     # min sqft
    r"\s*'(\d+)'\s*,"     # max sqft
    r"\s*'(\d+)'\s*,"     # min rent
    r"\s*'(\d+)'\s*"      # max rent
    r"\)",
)

# Extract bath count from floorplan name like "x02 1 Bed - 1 Bath"
_BATHS_RE = re.compile(r"(\d+)\s*Bath", re.IGNORECASE)


def _parse_baths(fp_name: str) -> int:
    """Extract bath count from floorplan name. Defaults to 1."""
    m = _BATHS_RE.search(fp_name)
    return int(m.group(1)) if m else 1


def parse_all(data: str) -> tuple[list[dict], list[dict]]:
    """Parse unit-level data from the scraper's JSON output.

    The scraper returns JSON with:
    - "units": list of unit dicts from detail pages (real apartment numbers)
    - "ga4_floorplans": list of GA4 floorplan-tier data from main page

    If the data is plain HTML (legacy/fallback), extract GA4 cookie data.
    Returns normalized (units, floorplans) dicts.
    """
    # Try JSON format first (new scraper output)
    try:
        parsed = json.loads(data)
        if isinstance(parsed, dict) and "units" in parsed:
            return _parse_json_data(parsed)
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: treat as HTML and extract GA4 cookies (legacy behavior)
    return _parse_ga4_html(data)


def _parse_json_data(data: dict) -> tuple[list[dict], list[dict]]:
    """Parse the structured JSON from the multi-page scraper."""
    raw_units = data.get("units", [])
    ga4_fps = data.get("ga4_floorplans", [])

    if not raw_units and not ga4_fps:
        raise ParseError(
            "No unit or floorplan data found. "
            "Site may have changed format — check manually."
        )

    units = []
    seen_units = set()

    for u in raw_units:
        unit_num = u.get("unitNumber", "")
        fp_name = u.get("fpName", "")
        key = (unit_num, fp_name)
        if key in seen_units:
            continue
        seen_units.add(key)

        # Parse rent values (come as "2720.00" strings)
        min_rent = int(float(u.get("minRent", 0)))
        max_rent = int(float(u.get("maxRent", 0)))

        # Skip $0 units — "Contact Us" means not available
        if min_rent == 0 and max_rent == 0:
            continue

        beds_str = u.get("beds", "0")
        # beds comes as "1 Bed(s)" or just "1"
        beds_match = re.match(r"(\d+)", beds_str)
        beds = int(beds_match.group(1)) if beds_match else 0

        baths = _parse_baths(fp_name)
        sqft = int(u.get("sqft", 0))
        avail_date = u.get("moveInDate", "")

        # Generate a stable floorplan ID from the name
        fp_id = int(md5(fp_name.encode()).hexdigest()[:8], 16)

        units.append({
            "UnitCode": str(unit_num),
            "FloorplanId": fp_id,
            "FloorplanName": fp_name,
            "Beds": beds,
            "Baths": baths,
            "SqFt": sqft,
            "MinRent": min_rent,
            "MaxRent": max_rent,
            "AvailableDate": avail_date,
            "ConcessionText": "",
        })

    # Build floorplan summary from units
    fp_groups: dict[int, list[dict]] = defaultdict(list)
    for u in units:
        fp_groups[u["FloorplanId"]].append(u)

    floorplans = []
    for fp_id, fp_units in fp_groups.items():
        first = fp_units[0]
        floorplans.append({
            "Id": fp_id,
            "Beds": first["Beds"],
            "Baths": first["Baths"],
            "MinSqFt": min(u["SqFt"] for u in fp_units),
            "MaxSqFt": max(u["SqFt"] for u in fp_units),
            "MinRent": min(u["MinRent"] for u in fp_units),
            "MaxRent": max(u["MaxRent"] for u in fp_units),
            "AvailableCount": len(fp_units),
            "AvailableDate": first["AvailableDate"],
        })

    # If no units from detail pages, fall back to GA4 data (excluding $0)
    if not units and ga4_fps:
        return _parse_ga4_list(ga4_fps)

    return units, floorplans


def _parse_ga4_list(ga4_fps: list[dict]) -> tuple[list[dict], list[dict]]:
    """Fallback: build units/floorplans from GA4 floorplan-tier data."""
    units = []
    floorplans = []
    seen = set()

    for fp in ga4_fps:
        fp_name = fp["name"]
        if fp_name in seen:
            continue
        seen.add(fp_name)

        min_rent = int(fp.get("minRent", 0))
        max_rent = int(fp.get("maxRent", 0))

        # Skip $0 (Contact Us / unavailable)
        if min_rent == 0 and max_rent == 0:
            continue

        beds = int(fp.get("beds", 0))
        baths = _parse_baths(fp_name)
        min_sqft = int(fp.get("minSqft", 0))
        max_sqft = int(fp.get("maxSqft", 0))
        fp_id = int(md5(fp_name.encode()).hexdigest()[:8], 16)

        # Synthetic unit code since we don't have real apartment numbers
        unit_code = f"FP-{fp_name.replace(' ', '-')}"

        units.append({
            "UnitCode": unit_code,
            "FloorplanId": fp_id,
            "FloorplanName": fp_name,
            "Beds": beds,
            "Baths": baths,
            "SqFt": min_sqft,
            "MinRent": min_rent,
            "MaxRent": max_rent,
            "AvailableDate": "",
            "ConcessionText": "",
        })

        floorplans.append({
            "Id": fp_id,
            "Beds": beds,
            "Baths": baths,
            "MinSqFt": min_sqft,
            "MaxSqFt": max_sqft,
            "MinRent": min_rent,
            "MaxRent": max_rent,
            "AvailableCount": 1,
            "AvailableDate": "",
        })

    if not units:
        raise ParseError("All floorplans show $0 / Contact Us — no available units.")

    return units, floorplans


def _parse_ga4_html(html: str) -> tuple[list[dict], list[dict]]:
    """Legacy fallback: extract GA4 cookie data from raw HTML."""
    matches = _GA4_RE.findall(html)
    if not matches:
        raise ParseError(
            "No setGA4Cookie('GT', ...) calls found in HTML. "
            "Site may have changed format — check manually."
        )

    ga4_fps = []
    for fp_name, beds_s, min_sqft_s, max_sqft_s, min_rent_s, max_rent_s in matches:
        ga4_fps.append({
            "name": fp_name,
            "beds": beds_s,
            "minSqft": min_sqft_s,
            "maxSqft": max_sqft_s,
            "minRent": min_rent_s,
            "maxRent": max_rent_s,
        })

    return _parse_ga4_list(ga4_fps)
