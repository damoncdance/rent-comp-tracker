"""Parser for properties using Nestio/UrbanApt JSON API.

Some properties embed a Nestio widget (now part of Funnel Leasing).
The widget loads data from a clean public JSON API at:
    https://{subdomain}.urbanapt.com/api/listings

The property URL in the DB should be this API endpoint directly.
"""
from __future__ import annotations

import json
from collections import defaultdict


class ParseError(Exception):
    """Raised when Nestio JSON can't be parsed."""


def parse_all(response_text: str) -> tuple[list[dict], list[dict]]:
    """Parse Nestio API JSON. Returns (units, floorplans) in normalized format."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON from Nestio API: {e}")

    items = data.get("items")
    if items is None:
        raise ParseError("No 'items' array in Nestio response")

    if not items:
        raise ParseError("No listings returned from Nestio API")

    # Normalize units
    units = []
    fp_counter = 0
    fp_map: dict[str, int] = {}  # layout name -> floorplan id

    for item in items:
        unit_number = item.get("unit_number") or ""
        price = item.get("price")
        if price is None:
            continue

        beds = item.get("bedrooms") or 0
        baths = item.get("bathrooms") or 1.0
        sqft = item.get("square_footage") or 0
        layout = item.get("layout") or f"{beds}BR"
        avail = item.get("date_available") or ""
        concession = (item.get("incentives_marketing_description")
                      or item.get("incentives") or "")

        # Assign floorplan ID by layout name
        if layout not in fp_map:
            fp_counter += 1
            fp_map[layout] = fp_counter

        units.append({
            "UnitCode": str(unit_number),
            "FloorplanId": fp_map[layout],
            "FloorplanName": layout,
            "Beds": int(beds),
            "Baths": float(baths),
            "SqFt": float(sqft),
            "MinRent": float(price),
            "MaxRent": float(price),
            "AvailableDate": avail[:10] if avail else "",
            "ConcessionText": concession,
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
