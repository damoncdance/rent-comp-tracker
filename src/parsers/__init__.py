"""Parser registry. Maps platform names to parser modules.

Each parser module must expose:
    parse_all(html: str) -> tuple[list[dict], list[dict]]
    ParseError (exception class)

The returned (units, floorplans) use the same normalized field names as
the RentCafe parser (the reference implementation):
    units:      UnitCode, FloorplanId, FloorplanName, Beds, Baths, SqFt,
                MinRent, MaxRent, AvailableDate
    floorplans: Id, Beds, Baths, MinSqFt, MaxSqFt, MinRent, MaxRent,
                AvailableCount, AvailableDate
"""
from __future__ import annotations

from types import ModuleType


class UnsupportedPlatformError(Exception):
    """Raised when no parser exists for a given platform."""


def get_parser(platform: str) -> ModuleType:
    """Return the parser module for the given platform string."""
    if platform == "rentcafe":
        from src.parsers import rentcafe
        return rentcafe
    if platform == "sightmap":
        from src.parsers import sightmap
        return sightmap
    if platform == "appfolio":
        from src.parsers import appfolio
        return appfolio
    if platform == "nestio":
        from src.parsers import nestio
        return nestio
    if platform == "securecafe":
        from src.parsers import securecafe
        return securecafe
    if platform == "woocommerce":
        from src.parsers import woocommerce
        return woocommerce
    raise UnsupportedPlatformError(
        f"No parser for platform '{platform}'. "
        f"Supported: rentcafe, sightmap, appfolio, nestio, securecafe, woocommerce"
    )
