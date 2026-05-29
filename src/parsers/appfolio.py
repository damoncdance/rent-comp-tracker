"""Parser for AppFolio listing pages.

AppFolio embeds a JavaScript variable `googleMap` with a `markers` array
containing structured listing data. Available dates are in the HTML cards.

The HTML cards show: address (with unit#), rent, bed/bath, available date.
The markers JSON has: address, rent_range, unit_specs (beds, baths, sqft).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict


class ParseError(Exception):
    """Raised when AppFolio data can't be parsed."""


# Regex to extract the markers array from the googleMap constructor
_MARKERS_RE = re.compile(
    r"new\s+GoogleMap\(\{[^}]*markers\s*:\s*(\[.*?\])\s*[,}]",
    re.DOTALL,
)

# Regex to find available dates in the HTML near detail URLs
_AVAIL_RE = re.compile(
    r'href="(/listings/detail/[^"]+)".*?'
    r'Available\s+([\w/]+)',
    re.DOTALL,
)


def parse_all(html: str) -> tuple[list[dict], list[dict]]:
    """Parse AppFolio listing page. Returns (units, floorplans).

    Distinguishes two very different states that look similar:
      - markers construct absent  → structural change → ParseError
      - markers present but empty  → no current availability (e.g. fully
        leased) → a valid, meaningful zero-unit snapshot, not a failure
    """
    markers = _extract_markers(html)
    if markers is None:
        raise ParseError("No googleMap markers construct found in AppFolio page. "
                         "Site structure may have changed — see scraper-recovery skill.")
    if not markers:
        # Empty markers array = building has no current availability.
        # Record it as a successful zero-unit snapshot so 100%-leased comps
        # show up as real data instead of phantom fetch failures.
        return [], []

    # Build available date lookup by detail URL
    avail_dates = {}
    for m in _AVAIL_RE.finditer(html):
        url, date_str = m.group(1), m.group(2)
        avail_dates[url] = _normalize_date(date_str)

    units = []
    fp_counter = 0
    fp_map: dict[str, int] = {}  # bed_bath key -> floorplan id

    for marker in markers:
        address = marker.get("address", "")
        unit_code = _extract_unit_code(address)
        rent = _parse_rent(marker.get("rent_range", ""))
        beds, baths, sqft = _parse_unit_specs(marker.get("unit_specs", ""))
        detail_url = marker.get("detail_page_url", "")
        avail_date = avail_dates.get(detail_url, "")

        if rent is None:
            continue

        # Assign a floorplan ID based on bed/bath combo
        fp_key = f"{beds}_{baths}"
        if fp_key not in fp_map:
            fp_counter += 1
            fp_map[fp_key] = fp_counter

        bed_label = "Studio" if beds == 0 else f"{beds} Bedroom"

        units.append({
            "UnitCode": unit_code,
            "FloorplanId": fp_map[fp_key],
            "FloorplanName": bed_label,
            "Beds": beds,
            "Baths": baths,
            "SqFt": sqft,
            "MinRent": rent,
            "MaxRent": rent,
            "AvailableDate": avail_date,
            "ConcessionText": "",
        })

    # Synthesize floorplan aggregates
    by_fp: dict[int, list[dict]] = defaultdict(list)
    for u in units:
        by_fp[u["FloorplanId"]].append(u)

    floorplans = []
    for fp_id, fp_units in sorted(by_fp.items()):
        rents = [u["MinRent"] for u in fp_units]
        sqfts = [u["SqFt"] for u in fp_units if u["SqFt"]]
        dates = [u["AvailableDate"] for u in fp_units if u["AvailableDate"]]
        floorplans.append({
            "Id": fp_id,
            "Beds": fp_units[0]["Beds"],
            "Baths": fp_units[0]["Baths"],
            "MinSqFt": min(sqfts) if sqfts else 0,
            "MaxSqFt": max(sqfts) if sqfts else 0,
            "MinRent": min(rents),
            "MaxRent": max(rents),
            "AvailableCount": len(fp_units),
            "AvailableDate": min(dates) if dates else "",
        })

    return units, floorplans


def _extract_markers(html: str) -> list[dict] | None:
    """Extract the markers JSON array from the googleMap constructor.

    Returns the (possibly empty) list of markers, or None if the markers
    construct can't be located/decoded at all — i.e. the page structure
    changed. An empty list is a valid 'no availability' state and the caller
    must distinguish it from None.
    """
    m = _MARKERS_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _extract_unit_code(address: str) -> str:
    """Extract unit number from AppFolio address strings.

    Patterns seen:
      '1122 W. Chicago Avenue. 405, Chicago, IL 60642'
      '1122 W. Chicago Avenue, 515, Chicago, IL 60642'
    The unit number is the segment between the street and the city.
    """
    # Split on comma and look for a short numeric-ish segment
    parts = [p.strip() for p in address.split(",")]
    for part in parts[1:]:  # skip the street address
        # Unit numbers are short (1-5 chars) and usually numeric
        cleaned = part.rstrip(".")
        if cleaned and len(cleaned) <= 6 and any(c.isdigit() for c in cleaned):
            return cleaned
    # Also check after period: "Avenue. 405"
    m = re.search(r'\.\s*(\d+)\s*,', address)
    if m:
        return m.group(1)
    # Fallback
    return parts[0].strip()[-10:]


def _parse_rent(rent_str: str) -> float | None:
    """Parse '$1,950' or '$1,950 - $2,100' into a float."""
    m = re.search(r'\$[\d,]+', rent_str)
    if not m:
        return None
    return float(m.group(0).replace("$", "").replace(",", ""))


def _parse_unit_specs(specs: str) -> tuple[int, float, float]:
    """Parse 'Studio, 1 ba, 451 Sq. Ft.' into (beds, baths, sqft)."""
    beds = 0
    baths = 1.0
    sqft = 0.0

    if "studio" in specs.lower():
        beds = 0
    else:
        m = re.search(r'(\d+)\s*(?:bd|bed)', specs, re.IGNORECASE)
        if m:
            beds = int(m.group(1))

    m = re.search(r'([\d.]+)\s*ba', specs, re.IGNORECASE)
    if m:
        baths = float(m.group(1))

    m = re.search(r'([\d,]+)\s*(?:sq|sf)', specs, re.IGNORECASE)
    if m:
        sqft = float(m.group(1).replace(",", ""))

    return beds, baths, sqft


def _normalize_date(date_str: str) -> str:
    """Convert 'NOW' or '8/21/26' to ISO date string."""
    if not date_str or date_str.upper() == "NOW":
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # M/D/YY format
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', date_str)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        return f"{year:04d}-{month:02d}-{day:02d}"

    return date_str
