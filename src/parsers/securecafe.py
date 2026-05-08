"""Parser for properties using SecureCafe (Yardi) with Cloudflare protection.

SecureCafe is a Yardi product similar to RentCafe. The floorplans page embeds
a `var pageData = {...}` JavaScript object containing floorplan tiers with
unit lists, rents, sqft, and availability dates.

Unlike RentCafe (which inlines `ysi.unitsList` as valid JSON), SecureCafe's
`pageData` is a JS object literal (unquoted keys, trailing commas, etc.) so
we extract it via Playwright's `page.evaluate()` instead of regex + json.loads.

Because these sites sit behind Cloudflare bot protection, we must use a real
browser (Playwright) to solve the JS challenge before accessing the page.
"""
from __future__ import annotations

import json


class ParseError(Exception):
    """Raised when SecureCafe page data can't be parsed."""


def parse_all(page_data_json: str) -> tuple[list[dict], list[dict]]:
    """Parse SecureCafe pageData JSON. Returns (units, floorplans) in normalized format.

    Expects a JSON string of the pageData object (extracted via Playwright
    page.evaluate('JSON.stringify(pageData)') in the fetch step).
    """
    try:
        data = json.loads(page_data_json)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid pageData JSON: {e}")

    fp_list = data.get("floorplans")
    if fp_list is None:
        raise ParseError("No 'floorplans' key in pageData")

    if not fp_list:
        raise ParseError("Empty floorplans array in pageData")

    units = []
    floorplans = []

    for fp in fp_list:
        fp_id = fp.get("id", 0)
        fp_name = fp.get("name", "")
        beds = int(fp.get("beds", 0))
        baths = float(fp.get("baths", 1.0))
        sqft = fp.get("sqft", "0")
        sqft_val = float(str(sqft).replace(",", "")) if sqft else 0
        low_price = float(fp.get("lowPrice", 0))
        high_price = float(fp.get("highPrice", 0))
        avail_count = int(fp.get("availableCount", 0))
        avail_date = fp.get("availableDate", "")
        unit_list = fp.get("unitList", [])

        # Build normalized floorplan record
        floorplans.append({
            "Id": fp_id,
            "Beds": beds,
            "Baths": baths,
            "MinSqFt": sqft_val,
            "MaxSqFt": sqft_val,
            "MinRent": low_price,
            "MaxRent": high_price,
            "AvailableCount": avail_count,
            "AvailableDate": _normalize_date(avail_date),
        })

        # Build individual unit records from unitList
        if unit_list and avail_count > 0:
            # SecureCafe provides unit numbers but not per-unit rents.
            # Distribute the price range evenly if multiple units exist.
            for i, unit_code in enumerate(unit_list):
                if avail_count > 1 and low_price != high_price:
                    # Interpolate rent across units
                    frac = i / (len(unit_list) - 1) if len(unit_list) > 1 else 0
                    rent = low_price + frac * (high_price - low_price)
                else:
                    rent = low_price

                units.append({
                    "UnitCode": str(unit_code),
                    "FloorplanId": fp_id,
                    "FloorplanName": fp_name,
                    "Beds": beds,
                    "Baths": baths,
                    "SqFt": sqft_val,
                    "MinRent": round(rent, 2),
                    "MaxRent": round(rent, 2),
                    "AvailableDate": _normalize_date(avail_date),
                })

    return units, floorplans


def _normalize_date(date_str: str) -> str:
    """Convert SecureCafe date format (M/D/YYYY) to ISO (YYYY-MM-DD)."""
    if not date_str:
        return ""
    parts = date_str.split("/")
    if len(parts) == 3:
        month, day, year = parts
        # Handle 2-digit year
        if len(year) == 2:
            year = f"20{year}"
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return date_str
