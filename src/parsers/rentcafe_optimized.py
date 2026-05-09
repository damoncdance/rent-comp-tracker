"""Parser for newer RentCafe "optimized floorplans" pages.

Some RentCafe sites (like Inspire West Town) use a newer layout that does NOT
embed `ysi.unitsList` or `ysi.floorplansList` in the HTML. Instead, floorplan
data is embedded in Google Analytics tracking calls:

    setGA4Cookie('GT', 'floorplanName', 'beds', 'minSqft', 'maxSqft', 'minRent', 'maxRent')

These calls are in the static HTML and can be extracted with a regex. This
parser produces synthetic unit/floorplan dicts from those calls so the rest
of the pipeline works unchanged.

Limitation: this format gives us one "unit" per floorplan tier (not per
physical unit), so unit_count reflects distinct floorplan tiers, not individual
apartments. Available-unit granularity requires the standard RentCafe format.
"""
from __future__ import annotations

import re
from hashlib import md5


class ParseError(Exception):
    """Raised when the expected GA4 cookie calls aren't found."""


# setGA4Cookie('GT', 'fpName', 'beds', 'minSqft', 'maxSqft', 'minRent', 'maxRent')
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

# Also try to find available counts from the page (e.g. "3 Available")
_AVAIL_COUNT_RE = re.compile(r"(\d+)\s*(?:Available|Avail)", re.IGNORECASE)


def parse_all(html: str) -> tuple[list[dict], list[dict]]:
    """Parse setGA4Cookie calls into (units, floorplans).

    Returns normalized dicts matching the standard RentCafe field names.
    """
    matches = _GA4_RE.findall(html)
    if not matches:
        raise ParseError(
            "No setGA4Cookie('GT', ...) calls found in HTML. "
            "Site may have changed format — check manually."
        )

    # Deduplicate by (name, beds) since the same floorplan can appear multiple times
    seen = set()
    units = []
    floorplans = []

    for fp_name, beds_s, min_sqft_s, max_sqft_s, min_rent_s, max_rent_s in matches:
        beds = int(beds_s)
        key = (fp_name, beds)
        if key in seen:
            continue
        seen.add(key)

        min_sqft = int(min_sqft_s)
        max_sqft = int(max_sqft_s)
        min_rent = int(min_rent_s)
        max_rent = int(max_rent_s)

        # Generate a stable floorplan ID from the name
        fp_id = int(md5(fp_name.encode()).hexdigest()[:8], 16)

        # Synthetic unit code: FP-name-beds (one per tier)
        unit_code = f"FP-{fp_name.replace(' ', '-')}"

        units.append({
            "UnitCode": unit_code,
            "FloorplanId": fp_id,
            "FloorplanName": fp_name,
            "Beds": beds,
            "Baths": 1,  # not available in GA4 data
            "SqFt": min_sqft,
            "MinRent": min_rent,
            "MaxRent": max_rent,
            "AvailableDate": "",
            "ConcessionText": "",
        })

        floorplans.append({
            "Id": fp_id,
            "Beds": beds,
            "Baths": 1,
            "MinSqFt": min_sqft,
            "MaxSqFt": max_sqft,
            "MinRent": min_rent,
            "MaxRent": max_rent,
            "AvailableCount": 1,
            "AvailableDate": "",
        })

    return units, floorplans
