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

    def test_units_are_not_estimated(self, json_text):
        # SightMap returns real per-unit prices — these are observed, not
        # interpolated, so they must not be flagged estimated.
        from src.parsers.sightmap import parse_all
        units, _ = parse_all(json_text)
        assert all(not u.get("IsEstimated") for u in units)

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

    # --- floorplan_cards path (current main-page layout) -------------------

    def _cards_payload(self):
        import json
        # Mirrors the real iwtchicago.com card data captured live.
        return json.dumps({
            "floorplan_cards": [
                {"fpId": "5936306", "name": "x02 1 Bed - 1 Bath", "sqft": "527",
                 "availCount": "2", "minRent": "2490", "maxRent": "2695",
                 "availDate": "6/29/2026"},
                {"fpId": "5936308", "name": "x07 Studio - 1 Bath", "sqft": "419",
                 "availCount": "1", "minRent": "2175", "maxRent": "2175",
                 "availDate": "7/8/2026"},
                # "Contact Us" / unpriced floorplan — must be dropped
                {"fpId": "5936999", "name": "z99 3 Bed - 2 Bath", "sqft": "1200",
                 "availCount": "", "minRent": "0", "maxRent": "0", "availDate": ""},
            ],
            "ga4_floorplans": [],
        })

    def test_cards_produce_estimated_tier_units(self):
        import json as _json
        from src.parsers.rentcafe_optimized import parse_all
        units, floorplans = parse_all(self._cards_payload())
        assert len(units) == 2          # $0 floorplan dropped
        assert len(floorplans) == 2
        u = next(u for u in units if u["FloorplanName"].startswith("x02"))
        assert u["UnitCode"] == "FP-5936306"   # stable id-based code
        assert u["Beds"] == 1 and u["Baths"] == 1
        assert u["SqFt"] == 527
        assert u["MinRent"] == 2490 and u["MaxRent"] == 2695
        assert u["AvailableDate"] == "6/29/2026"
        assert u["IsEstimated"] is True

    def test_cards_studio_beds_and_avail_count(self):
        from src.parsers.rentcafe_optimized import parse_all
        _, floorplans = parse_all(self._cards_payload())
        studio = next(f for f in floorplans if f["MinRent"] == 2175)
        assert studio["Beds"] == 0              # "Studio" → 0 beds
        assert studio["AvailableCount"] == 1
        x02 = next(f for f in floorplans if f["MinRent"] == 2490)
        assert x02["AvailableCount"] == 2       # real count preserved

    def test_cards_unit_codes_stable_across_runs(self):
        from src.parsers.rentcafe_optimized import parse_all
        u1, _ = parse_all(self._cards_payload())
        u2, _ = parse_all(self._cards_payload())
        assert {u["UnitCode"] for u in u1} == {u["UnitCode"] for u in u2}

    def test_real_units_preferred_over_cards(self):
        # Real per-apartment rows (detail pages) win over tier cards; cards are
        # only a fallback when no real units resolved.
        import json as _json
        from src.parsers.rentcafe_optimized import parse_all
        data = _json.dumps({
            "units": [
                {"fpName": "x02 1 Bed - 1 Bath", "beds": "1", "sqft": "527",
                 "minRent": "2720.00", "maxRent": "2720.00", "unitNumber": "702",
                 "moveInDate": "6/29/2026"},
            ],
            "floorplan_cards": [
                {"fpId": "5936306", "name": "x02 1 Bed - 1 Bath", "sqft": "527",
                 "availCount": "2", "minRent": "2490", "maxRent": "2695",
                 "availDate": "6/29/2026"},
            ],
        })
        units, _ = parse_all(data)
        assert [u["UnitCode"] for u in units] == ["702"]   # real apartment number
        assert not units[0].get("IsEstimated")             # observed, not estimated

    def test_cards_used_when_no_real_units(self):
        import json as _json
        from src.parsers.rentcafe_optimized import parse_all
        data = _json.dumps({
            "units": [],
            "floorplan_cards": [
                {"fpId": "1", "name": "a02 1 Bed - 1 Bath", "sqft": "500",
                 "availCount": "1", "minRent": "2000", "maxRent": "2000",
                 "availDate": ""},
            ],
        })
        units, _ = parse_all(data)
        assert [u["UnitCode"] for u in units] == ["FP-1"]
        assert units[0]["IsEstimated"] is True


# ---------------------------------------------------------------------------
# SecureCafe
# ---------------------------------------------------------------------------

class TestSecureCafe:
    @pytest.fixture()
    def json_text(self):
        return (FIXTURES / "securecafe_minimal.json").read_text()

    def test_parse_all_returns_units_and_floorplans(self, json_text):
        from src.parsers.securecafe import parse_all
        units, floorplans = parse_all(json_text)
        assert len(units) == 3
        assert len(floorplans) == 2

    def test_unit_fields(self, json_text):
        from src.parsers.securecafe import parse_all
        units, _ = parse_all(json_text)
        u = units[0]
        assert u["UnitCode"] == "101"
        assert u["Beds"] == 0
        assert u["SqFt"] == 500
        assert u["MinRent"] == 1600.0

    def test_concession_text(self, json_text):
        from src.parsers.securecafe import parse_all
        units, _ = parse_all(json_text)
        assert units[0]["ConcessionText"] == ""
        assert units[2]["ConcessionText"] == "$500 off first month"

    def test_date_normalization(self, json_text):
        from src.parsers.securecafe import parse_all
        units, _ = parse_all(json_text)
        assert units[0]["AvailableDate"] == "2026-05-15"

    def test_parse_error_on_missing_floorplans(self):
        from src.parsers.securecafe import parse_all, ParseError
        with pytest.raises(ParseError):
            parse_all('{"other": []}')

    def test_price_interpolation_multiple_units(self, json_text):
        from src.parsers.securecafe import parse_all
        units, _ = parse_all(json_text)
        # Studio A has 2 units with price range 1600-1700
        assert units[0]["MinRent"] == 1600.0

    def test_units_are_flagged_estimated(self, json_text):
        # SecureCafe only exposes tier low/high prices, so every per-unit
        # rent is interpolated and must be marked estimated.
        from src.parsers.securecafe import parse_all
        units, _ = parse_all(json_text)
        assert units
        assert all(u.get("IsEstimated") is True for u in units)
        assert units[1]["MinRent"] == 1700.0


# ---------------------------------------------------------------------------
# AppFolio
# ---------------------------------------------------------------------------

class TestAppFolio:
    @pytest.fixture()
    def html(self):
        return (FIXTURES / "appfolio_minimal.html").read_text()

    def test_parse_all_returns_units_and_floorplans(self, html):
        from src.parsers.appfolio import parse_all
        units, floorplans = parse_all(html)
        assert len(units) == 2
        assert len(floorplans) == 2

    def test_unit_fields(self, html):
        from src.parsers.appfolio import parse_all
        units, _ = parse_all(html)
        u = units[0]
        assert u["UnitCode"] == "405"
        assert u["Beds"] == 0
        assert u["SqFt"] == 451.0
        assert u["MinRent"] == 1950.0

    def test_one_bedroom_parsed(self, html):
        from src.parsers.appfolio import parse_all
        units, _ = parse_all(html)
        u = units[1]
        assert u["Beds"] == 1
        assert u["MinRent"] == 2400.0

    def test_parse_error_on_no_markers(self):
        from src.parsers.appfolio import parse_all, ParseError
        with pytest.raises(ParseError):
            parse_all("<html><body>No markers</body></html>")

    def test_empty_markers_is_zero_availability_not_error(self):
        """An empty markers array means 'no current availability' (e.g. fully
        leased), which is a valid zero-unit snapshot — not a parse failure."""
        from src.parsers.appfolio import parse_all
        html = (
            "<script>var googleMap = new GoogleMap({\n"
            "  container: 'googlemap',\n"
            "  markers: [],\n"
            "  zoom: 14\n"
            "});</script>"
        )
        units, floorplans = parse_all(html)
        assert units == []
        assert floorplans == []


# ---------------------------------------------------------------------------
# Nestio
# ---------------------------------------------------------------------------

class TestNestio:
    @pytest.fixture()
    def json_text(self):
        return (FIXTURES / "nestio_minimal.json").read_text()

    def test_parse_all_returns_units_and_floorplans(self, json_text):
        from src.parsers.nestio import parse_all
        units, floorplans = parse_all(json_text)
        assert len(units) == 2
        assert len(floorplans) == 2

    def test_unit_fields(self, json_text):
        from src.parsers.nestio import parse_all
        units, _ = parse_all(json_text)
        u = units[0]
        assert u["UnitCode"] == "4A"
        assert u["Beds"] == 1
        assert u["SqFt"] == 650.0
        assert u["MinRent"] == 2100.0

    def test_concession_text(self, json_text):
        from src.parsers.nestio import parse_all
        units, _ = parse_all(json_text)
        assert units[0]["ConcessionText"] == ""
        assert "$1000" in units[1]["ConcessionText"]

    def test_parse_error_on_invalid_json(self):
        from src.parsers.nestio import parse_all, ParseError
        with pytest.raises(ParseError):
            parse_all("not json")


# ---------------------------------------------------------------------------
# WooCommerce
# ---------------------------------------------------------------------------

class TestWooCommerce:
    @pytest.fixture()
    def json_text(self):
        return (FIXTURES / "woocommerce_minimal.json").read_text()

    def test_parse_all_returns_units_and_floorplans(self, json_text):
        from src.parsers.woocommerce import parse_all
        units, floorplans = parse_all(json_text)
        assert len(units) == 2
        assert len(floorplans) == 2

    def test_unit_fields(self, json_text):
        from src.parsers.woocommerce import parse_all
        units, _ = parse_all(json_text)
        u = units[0]
        assert u["UnitCode"] == "513"
        assert u["Beds"] == 2
        assert u["SqFt"] == 1077.0
        assert u["MinRent"] == 4495.0

    def test_convertible_as_studio(self, json_text):
        from src.parsers.woocommerce import parse_all
        units, _ = parse_all(json_text)
        u = units[1]
        assert u["Beds"] == 0
        assert u["MinRent"] == 2595.0

    def test_parse_error_on_empty(self):
        from src.parsers.woocommerce import parse_all, ParseError
        with pytest.raises(ParseError):
            parse_all("[]")


# ---------------------------------------------------------------------------
# Cross Street (yourcrossstreet.com) — server-rendered, real unit numbers
# ---------------------------------------------------------------------------

class TestCrossStreet:
    # Mirrors the live 465 Carpenter markup: bed-type sections, a multi-unit
    # floorplan, and a single-unit floorplan (different class set).
    HTML = """
    <div class="fp-content-wrapper" id="fp_content_0">
      <div class="fp-content-title"><h3>Studio (3 Available Units)</h3></div>
      <div class="fp-content-item fp-auto-expand">
        <div class="fp-content-item-bar"><div class="fp-content-item-bar-left">
          <div>Plan 04</div><div class="desktop-rent">$2,406-2,429</div></div>
          <div class="fp-content-item-bar-right">1 Bath</div></div>
        <div class="fp-content-item-content"><div class="fp-units-available">
          <div class="fp-content-multi-units-item"><div class="unit-item-aptname">204</div><div class="unit-item-aptrent">$2,406</div><div class="unit-item-aptsize">593 Sq. Ft.</div><div class="unit-item-aptavailable">Available Jul 10</div></div>
          <div class="fp-content-multi-units-item"><div class="unit-item-aptname">304</div><div class="unit-item-aptrent">$2,429</div><div class="unit-item-aptsize">579 Sq. Ft.</div><div class="unit-item-aptavailable">Available Now</div></div>
        </div></div>
      </div>
    </div>
    <div class="fp-content-wrapper" id="fp_content_2">
      <div class="fp-content-title"><h3>2 Beds (1 Available Units)</h3></div>
      <div class="fp-content-item fp-auto-expand">
        <div class="fp-content-item-bar"><div class="fp-content-item-bar-left">
          <div>Plan 05.1</div><div class="desktop-rent">$5,390</div></div>
          <div class="fp-content-item-bar-right">2 Beds 2 Baths</div></div>
        <div class="fp-content-item-content"><div class="fp-content-single-unit">
          <div class="fp-content-single-unit-name">405</div>
          <div class="fp-content-single-unit-rent">$5,390</div>
          <div class="fp-content-single-unit-size">1,278 Sq. Ft.</div>
          <div class="fp-content-single-unit-available" style="margin-bottom:20px;">Jul 10</div>
        </div></div>
      </div>
    </div>
    """

    def test_real_unit_numbers_and_counts(self):
        from src.parsers.crossstreet import parse_all
        units, floorplans = parse_all(self.HTML)
        assert len(units) == 3                       # 2 multi + 1 single
        codes = {u["UnitCode"] for u in units}
        assert codes == {"204", "304", "405"}        # real apartment numbers
        assert all(not u.get("IsEstimated") for u in units)  # observed, not estimated

    def test_beds_from_section_baths_from_bar(self):
        from src.parsers.crossstreet import parse_all
        units, _ = parse_all(self.HTML)
        u204 = next(u for u in units if u["UnitCode"] == "204")
        assert u204["Beds"] == 0 and u204["Baths"] == 1 and u204["SqFt"] == 593
        u405 = next(u for u in units if u["UnitCode"] == "405")
        assert u405["Beds"] == 2 and u405["Baths"] == 2 and u405["MinRent"] == 5390

    def test_available_date_parsing(self):
        from src.parsers.crossstreet import parse_all
        units, _ = parse_all(self.HTML)
        u204 = next(u for u in units if u["UnitCode"] == "204")
        assert u204["AvailableDate"].endswith("-07-10")   # 'Jul 10' -> ISO
        u304 = next(u for u in units if u["UnitCode"] == "304")
        assert u304["AvailableDate"] == ""                # 'Available Now' -> ready

    def test_floorplan_rollup(self):
        from src.parsers.crossstreet import parse_all
        _, floorplans = parse_all(self.HTML)
        studio = next(f for f in floorplans if f["Beds"] == 0)
        assert studio["AvailableCount"] == 2
        assert studio["MinRent"] == 2406 and studio["MaxRent"] == 2429

    def test_parse_error_on_empty(self):
        from src.parsers.crossstreet import parse_all, ParseError
        with pytest.raises(ParseError):
            parse_all("<html><body>no floorplans here</body></html>")
