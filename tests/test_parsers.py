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
