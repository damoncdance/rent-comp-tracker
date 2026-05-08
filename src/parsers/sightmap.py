"""Parser for properties using the SightMap/Engrain API.

SightMap is used by many Yardi SecureCafe properties. Instead of scraping
HTML, we call the SightMap API directly which returns clean JSON.

The property URL in the DB should be the SightMap API endpoint, e.g.:
    https://sightmap.com/app/api/v1/{key}/sightmaps/{id}

The scraper fetches this URL and returns JSON text. This parser normalizes
the response into our standard (units, floorplans) format.
"""
from __future__ import annotations

import json
from collections import defaultdict


class ParseError(Exception):
    """Raised when SightMap JSON can't be parsed."""


def parse_all(response_text: str) -> tuple[list[dict], list[dict]]:
    """Parse SightMap API JSON. Returns (units, floorplans) in normalized format."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON from SightMap API: {e}")

    # Navigate to the data payload
    if "data" in data:
        data = data["data"]

    raw_units = data.get("units")
    raw_fps = data.get("floor_plans")

    if raw_units is None:
        raise ParseError("No 'units' array in SightMap response")
    if raw_fps is None:
        raise ParseError("No 'floor_plans' array in SightMap response")

    # Build floor plan lookup
    fp_lookup: dict[str, dict] = {}
    for fp in raw_fps:
        fp_lookup[str(fp["id"])] = fp

    # Normalize units
    units = []
    for u in raw_units:
        fp_id = str(u.get("floor_plan_id", ""))
        fp = fp_lookup.get(fp_id, {})

        unit_number = u.get("unit_number") or u.get("label") or ""
        price = u.get("price")
        if price is None:
            continue  # skip units without pricing

        units.append({
            "UnitCode": unit_number,
            "FloorplanId": int(fp_id) if fp_id.isdigit() else 0,
            "FloorplanName": fp.get("name", ""),
            "Beds": fp.get("bedroom_count", 0),
            "Baths": fp.get("bathroom_count", 1.0),
            "SqFt": u.get("area") or 0,
            "MinRent": float(price),
            "MaxRent": float(price),
            "AvailableDate": u.get("available_on") or "",
        })

    # Synthesize floorplan-level aggregates from units
    by_fp: dict[int, list[dict]] = defaultdict(list)
    for u in units:
        by_fp[u["FloorplanId"]].append(u)

    floorplans = []
    for fp_id_int, fp_units in sorted(by_fp.items()):
        fp = fp_lookup.get(str(fp_id_int), {})
        rents = [u["MinRent"] for u in fp_units]
        sqfts = [u["SqFt"] for u in fp_units if u["SqFt"]]
        dates = [u["AvailableDate"] for u in fp_units if u["AvailableDate"]]

        floorplans.append({
            "Id": fp_id_int,
            "Beds": fp.get("bedroom_count", 0),
            "Baths": fp.get("bathroom_count", 1.0),
            "MinSqFt": min(sqfts) if sqfts else 0,
            "MaxSqFt": max(sqfts) if sqfts else 0,
            "MinRent": min(rents) if rents else 0,
            "MaxRent": max(rents) if rents else 0,
            "AvailableCount": len(fp_units),
            "AvailableDate": min(dates) if dates else "",
        })

    return units, floorplans
