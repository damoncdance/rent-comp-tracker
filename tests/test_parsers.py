"""Tests for platform-specific parsers.

Each test loads a minimal fixture and verifies parse_all returns the expected
normalized (units, floorplans) structure.
"""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# RentCafe
# ---------------------------------------------------------------------------

class TestRentCafe:
    @pytest.fixture()
    def html(self):
        return (FIXTURES / "rentcafe_minimal.html").read_text()

    def test_parse_all_returns_units_and_floorplans(self, html):
        from src.parsers.rentcafe import parse_all
        units, floorplans = parse_all(html)
        assert len(units) == 2
        assert len(floorplans) == 2

    def test_unit_fields(self, html):
        from src.parsers.rentcafe import parse_all
        units, _ = parse_all(html)
        u = units[0]
        assert u["UnitCode"] == "101"
        assert u["Beds"] == 0
        assert u["MinRent"] == 1500.0
        assert u["SqFt"] == 450

    def test_concession_text_populated(self, html):
        from src.parsers.rentcafe import parse_all
        units, _ = parse_all(html)
        # Unit without Specials gets empty string
        assert units[0]["ConcessionText"] == ""
        # Unit with Specials gets it copied
        assert units[1]["ConcessionText"] == "1 month free!"

    def test_floorplan_fields(self, html):
        from src.parsers.rentcafe import parse_all
        _, floorplans = parse_all(html)
        fp = floorplans[1]
        assert fp["Id"] == 20
        assert fp["Beds"] == 1
        assert fp["MinRent"] == 2000.0
        assert fp["MaxRent"] == 2200.0

    def test_parse_error_on_missing_data(self):
        from src.parsers.rentcafe import parse_all, ParseError
        with pytest.raises(ParseError):
            parse_all("<html><body>No data here</body></html>")


# ---------------------------------------------------------------------------
# SightMap
# ---------------------------------------------------------------------------

class TestSightMap:
    @pytest.fixture()
    def json_text(self):
        return (FIXTURES / "sightmap_minimal.json").read_text()

    def test_parse_all_returns_units_and_floorplans(self, json_text):
        from src.parsers.sightmap import parse_all
        units, floorplans = parse_all(json_text)
        assert len(units) == 2
        assert len(floorplans) == 2

    def test_unit_fields(self, json_text):
        from src.parsers.sightmap import parse_all
        units, _ = parse_all(json_text)
        u = units[0]
        assert u["UnitCode"] == "301"
        assert u["FloorplanName"] == "Studio"
        assert u["Beds"] == 0
        assert u["MinRent"] == 1800.0
        assert u["SqFt"] == 550

    def test_concession_text(self, json_text):
        from src.parsers.sightmap import parse_all
        units, _ = parse_all(json_text)
        assert units[0]["ConcessionText"] == ""
        assert "$500 off" in units[1]["ConcessionText"]

    def test_floorplan_aggregation(self, json_text):
        from src.parsers.sightmap import parse_all
        _, floorplans = parse_all(json_text)
        # Each unit is on a different floorplan, so 1 unit each
        for fp in floorplans:
            assert fp["AvailableCount"] == 1
        studio = next(fp for fp in floorplans if fp["Beds"] == 0)
        assert studio["MinRent"] == 1800.0

    def test_parse_error_on_invalid_json(self):
        from src.parsers.sightmap import parse_all, ParseError
        with pytest.raises(ParseError):
            parse_all("not json at all")

    def test_units_without_price_skipped(self):
        import json
        from src.parsers.sightmap import parse_all
        data = {
            "data": {
                "units": [{"id": 1, "unit_number": "X", "floor_plan_id": 1}],
                "floor_plans": [{"id": 1, "name": "A", "bedroom_count": 0, "bathroom_count": 1}],
            }
        }
        units, _ = parse_all(json.dumps(data))
        assert len(units) == 0


# ---------------------------------------------------------------------------
# RentCafe Optimized
# ---------------------------------------------------------------------------

class TestRentCafeOptimized:
    def test_parse_json_with_real_units(self):
        import json
        from src.parsers.rentcafe_optimized import parse_all
        data = json.dumps({
            "units": [
                {"fpName": "x02 1 Bed - 1 Bath", "beds": "1 Bed(s)", "sqft": "527",
                 "minRent": "2720.00", "maxRent": "2720.00", "unitNumber": "702",
                 "moveInDate": "6/29/2026"},
                {"fpName": "x05 2 Bed - 2 Bath", "beds": "2 Bed(s)", "sqft": "788",
                 "minRent": "3550.00", "maxRent": "3550.00", "unitNumber": "605",
                 "moveInDate": "7/8/2026"},
            ],
            "ga4_floorplans": [],
        })
        units, floorplans = parse_all(data)
        assert len(units) == 2
        assert units[0]["UnitCode"] == "702"
        assert units[0]["Beds"] == 1
        assert units[0]["Baths"] == 1
        assert units[0]["MinRent"] == 2720
        assert units[0]["AvailableDate"] == "6/29/2026"
        assert units[1]["UnitCode"] == "605"
        assert len(floorplans) == 2

    def test_zero_rent_units_filtered(self):
        import json
        from src.parsers.rentcafe_optimized import parse_all
        data = json.dumps({
            "units": [
                {"fpName": "x01 1 Bed - 1 Bath", "beds": "1", "sqft": "647",
                 "minRent": "0.00", "maxRent": "0.00", "unitNumber": "401",
                 "moveInDate": ""},
                {"fpName": "x02 1 Bed - 1 Bath", "beds": "1", "sqft": "527",
                 "minRent": "2720.00", "maxRent": "2720.00", "unitNumber": "702",
                 "moveInDate": "6/29/2026"},
            ],
            "ga4_floorplans": [],
        })
        units, floorplans = parse_all(data)
        assert len(units) == 1
        assert units[0]["UnitCode"] == "702"

    def test_ga4_fallback_filters_zero_rent(self):
        import json
        from src.parsers.rentcafe_optimized import parse_all
        data = json.dumps({
            "units": [],
            "ga4_floorplans": [
                {"name": "x01 1 Bed - 1 Bath", "beds": "1", "minSqft": "647",
                 "maxSqft": "647", "minRent": "0", "maxRent": "0"},
                {"name": "x02 1 Bed - 1 Bath", "beds": "1", "minSqft": "527",
                 "maxSqft": "527", "minRent": "2720", "maxRent": "2720"},
            ],
        })
        units, floorplans = parse_all(data)
        assert len(units) == 1
        assert units[0]["FloorplanName"] == "x02 1 Bed - 1 Bath"
        # GA4 fallback uses synthetic FP- prefix
        assert units[0]["UnitCode"].startswith("FP-")

    def test_legacy_html_fallback(self):
        from src.parsers.rentcafe_optimized import parse_all
        html = """<script>setGA4Cookie('GT', 'Studio A', '0', '400', '400', '1800', '1800')</script>"""
        units, floorplans = parse_all(html)
        assert len(units) == 1
        assert units[0]["MinRent"] == 1800

    def test_bath_extraction_from_name(self):
        import json
        from src.parsers.rentcafe_optimized import parse_all
        data = json.dumps({
            "units": [
                {"fpName": "x05 2 Bed - 2 Bath", "beds": "2", "sqft": "788",
                 "minRent": "3550.00", "maxRent": "3550.00", "unitNumber": "605",
                 "moveInDate": ""},
            ],
            "ga4_floorplans": [],
        })
        units, _ = parse_all(data)
        assert units[0]["Baths"] == 2

    def test_duplicate_units_deduplicated(self):
        import json
        from src.parsers.rentcafe_optimized import parse_all
        data = json.dumps({
            "units": [
                {"fpName": "x02 1 Bed - 1 Bath", "beds": "1", "sqft": "527",
                 "minRent": "2720.00", "maxRent": "2720.00", "unitNumber": "702",
                 "moveInDate": "6/29/2026"},
                {"fpName": "x02 1 Bed - 1 Bath", "beds": "1", "sqft": "527",
                 "minRent": "2720.00", "maxRent": "2720.00", "unitNumber": "702",
                 "moveInDate": "6/29/2026"},
            ],
            "ga4_floorplans": [],
        })
        units, _ = parse_all(data)
        assert len(units) == 1
