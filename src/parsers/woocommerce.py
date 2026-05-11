"""Parser for properties using WooCommerce as a listing platform.

812 West Adams uses a WordPress site with WooCommerce products to list
available units. The public WC Store API at:
    /wp-json/wc/store/v1/products?per_page=100
returns JSON with all unit data spread across three fields:
    - slug:              unit number (e.g. "unit-513")
    - short_description: bed/bath + sqft (e.g. "2 BED / 2 BATH SF: 1,077")
    - price_html:        move-in date + rent (e.g. "06/01 move-in — starting at $4,495")

The property URL in the DB should be the WC Store API endpoint directly.
"""
from __future__ import annotations

import json
from datetime import date
import re
from collections import defaultdict
from html import unescape

# Strip HTML tags for clean text extraction
_TAG_RE = re.compile(r"<[^>]+>")


class ParseError(Exception):
    """Raised when WooCommerce product data can't be parsed."""


def parse_all(response_text: str) -> tuple[list[dict], list[dict]]:
    """Parse WooCommerce Store API JSON. Returns (units, floorplans)."""
    try:
        products = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON from WC Store API: {e}")

    if not isinstance(products, list):
        raise ParseError("Expected JSON array from WC Store API")

    if not products:
        raise ParseError("No products returned from WC Store API")

    units = []
    fp_counter = 0
    fp_map: dict[str, int] = {}  # "beds-baths" -> floorplan id

    for item in products:
        slug = item.get("slug", "")
        short_desc = unescape(item.get("short_description", ""))
        price_html = unescape(item.get("price_html", ""))
        description = _TAG_RE.sub("", unescape(item.get("description", ""))).strip()

        # Extract unit number from slug: "unit-513" -> "513", "unit204" -> "204"
        unit_match = re.search(r"unit[- ]?(\w+)", slug, re.IGNORECASE)
        unit_code = unit_match.group(1) if unit_match else slug

        # Parse bed/bath from short_description
        # Patterns: "2 BED / 2 BATH", "CONVERTIBLE / 1 BATH", "1 BED / 1 BATH"
        beds, baths = 0, 1
        bb_match = re.search(
            r"(\d+|CONVERTIBLE|STUDIO)\s*(?:BED)?\s*/\s*(\d+)\s*BATH",
            short_desc, re.IGNORECASE,
        )
        if bb_match:
            b = bb_match.group(1).upper()
            beds = 0 if b in ("CONVERTIBLE", "STUDIO") else int(b)
            baths = int(bb_match.group(2))

        # Parse sqft from short_description: "SF: 1,077"
        sqft = 0.0
        sf_match = re.search(r"SF:\s*([\d,]+)", short_desc)
        if sf_match:
            sqft = float(sf_match.group(1).replace(",", ""))

        # Parse rent from price_html: "starting at $2,595" or "$4,495"
        rent = 0.0
        rent_match = re.search(r"\$([\d,]+)", price_html)
        if rent_match:
            rent = float(rent_match.group(1).replace(",", ""))

        # Parse move-in date from price_html: "06/01 move-in" or "Available Now"
        avail_date = ""
        date_match = re.search(r"(\d{1,2}/\d{1,2})\s*(?:move|Move)", price_html)
        if date_match:
            parts = date_match.group(1).split("/")
            if len(parts) == 2:
                month, day = int(parts[0]), int(parts[1])
                year = date.today().year
                # If the date is in the past, assume next year
                if date(year, month, day) < date.today():
                    year += 1
                avail_date = f"{year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
        elif re.search(r"available\s*now", price_html, re.IGNORECASE):
            avail_date = "now"

        if rent == 0:
            continue  # skip units with no pricing

        # Assign floorplan by bed/bath combo
        fp_key = f"{beds}-{baths}"
        if fp_key not in fp_map:
            fp_counter += 1
            fp_map[fp_key] = fp_counter

        units.append({
            "UnitCode": unit_code,
            "FloorplanId": fp_map[fp_key],
            "FloorplanName": f"{beds}BR/{baths}BA" if beds > 0 else f"Conv/{baths}BA",
            "Beds": beds,
            "Baths": float(baths),
            "SqFt": sqft,
            "MinRent": rent,
            "MaxRent": rent,
            "AvailableDate": avail_date,
            "ConcessionText": description if description else "",
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
