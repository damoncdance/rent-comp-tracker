"""Extract unitsList and floorplansList from the raw HTML.

The site embeds two JSON arrays in <script> tags:
    ysi.unitsList = [ {...}, {...}, ... ];
    ysi.floorplansList = [ {...}, {...}, ... ];

We pull them out with a regex and json.loads. The HTML is dynamic but the
variable names and structure are stable across the RentCafe platform.
"""
from __future__ import annotations

import json
import re


class ParseError(Exception):
    """Raised when the expected JS variables aren't found in the HTML."""


_UNITS_RE      = re.compile(r"ysi\.unitsList\s*=\s*(\[.*?\]);", re.DOTALL)
_FLOORPLANS_RE = re.compile(r"ysi\.floorplansList\s*=\s*(\[.*?\]);", re.DOTALL)


def parse_units(html: str) -> list[dict]:
    """Return the list of available unit dicts.

    Each dict has keys: Id, UnitCode, Beds, Baths, SqFt, MinRent, MaxRent,
    AvailableDate, FloorplanName, FloorplanId, isCommercial, PropertyId.
    """
    m = _UNITS_RE.search(html)
    if not m:
        raise ParseError(
            "ysi.unitsList not found in HTML. "
            "Site may have changed platform — see scraper-recovery skill."
        )
    return json.loads(m.group(1))


def parse_floorplans(html: str) -> list[dict]:
    """Return the list of floorplan tier dicts.

    Each dict has keys: Id, Beds, Baths, MinSqFt, MaxSqFt, MinRent, MaxRent,
    Units (always null in static HTML — actual units live in unitsList),
    AvailableDate, AvailableCount.
    """
    m = _FLOORPLANS_RE.search(html)
    if not m:
        raise ParseError("ysi.floorplansList not found in HTML.")
    return json.loads(m.group(1))


def parse_all(html: str) -> tuple[list[dict], list[dict]]:
    """Convenience: return (units, floorplans) in one call."""
    units = parse_units(html)
    # Ensure every unit dict has ConcessionText
    for u in units:
        if "ConcessionText" not in u:
            u["ConcessionText"] = u.get("Specials", "") or ""
    return units, parse_floorplans(html)
