"""Tests for the pricing recommendation engine.

Two layers:
  1. Pure-helper tests with hand-derived expected values. These assert the
     *math* is correct independent of the tunable coefficients, so they stay
     meaningful even if the model is retuned (they target structure: bounds,
     monotonicity, and exact values on controlled inputs).
  2. A seeded end-to-end run against a temporary database that exercises
     generate_recommendations() and checks its invariants.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import pricing
from src.pricing import (
    _infer_floor,
    _size_adjustment,
    _quality_score,
    _unit_level_adjustment,
    _compute_market_psf,
)

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


# ---------------------------------------------------------------------------
# _infer_floor — fully deterministic
# ---------------------------------------------------------------------------

class TestInferFloor:
    @pytest.mark.parametrize("code,expected", [
        ("L8-101", 8),
        ("L10", 10),
        ("l3-204", 3),     # case-insensitive
        ("816", 8),        # 3-digit: first digit
        ("1204", 12),      # 4-digit: first two digits
        ("12", None),      # 2-digit numeric: not inferable
        ("PH-1", None),    # non-numeric, no L prefix
        ("", None),
        ("abc", None),
    ])
    def test_infer_floor(self, code, expected):
        assert _infer_floor(code) == expected


# ---------------------------------------------------------------------------
# _size_adjustment — discount for units smaller than comp average
# ---------------------------------------------------------------------------

class TestSizeAdjustment:
    def _comps(self, *sqfts, beds=1):
        return [{"beds": beds, "sqft": s} for s in sqfts]

    def test_at_comp_average_no_adjustment(self):
        assert _size_adjustment(1000, 1, self._comps(1000, 1000)) == 1.0

    def test_above_comp_average_no_adjustment(self):
        # Larger than average → no bonus (captured by PSF), still 1.0
        assert _size_adjustment(1200, 1, self._comps(1000, 1000)) == 1.0

    def test_ten_percent_below_is_two_percent_discount(self):
        # comp avg 1000, unit 900 → 10% below → -1% per 5% → -2% → 0.98
        assert _size_adjustment(900, 1, self._comps(1000, 1000)) == 0.98

    def test_discount_is_floored_at_ninety(self):
        # 50% below would be -10%; far-below stays clamped at 0.90
        assert _size_adjustment(400, 1, self._comps(1000, 1000)) == 0.90

    def test_no_comps_for_bed_type_returns_unity(self):
        assert _size_adjustment(800, 3, self._comps(1000, beds=1)) == 1.0


# ---------------------------------------------------------------------------
# _quality_score — bounded, monotonic in build year
# ---------------------------------------------------------------------------

class TestQualityScore:
    def test_empty_property_is_midpoint(self):
        assert _quality_score({}, None) == 5.0

    def test_always_within_bounds(self):
        # Stuff every positive lever to its max
        hot = {"year_built": 2025, "stories": 50, "management_company": "Greystar"}
        amen = {"building_amenities": list(range(20)), "pool": True,
                "doorman_concierge": True, "fitness": "Premium Peloton", "rooftop": True}
        score = _quality_score(hot, amen)
        assert 1.0 <= score <= 10.0

    def test_newer_building_scores_higher(self):
        new = _quality_score({"year_built": 2024}, None)
        old = _quality_score({"year_built": 2005}, None)
        assert new > old

    def test_management_tier_increases_score(self):
        premium = _quality_score({"management_company": "Greystar"}, None)
        unknown = _quality_score({"management_company": "Nobody Co"}, None)
        assert premium > unknown


# ---------------------------------------------------------------------------
# _unit_level_adjustment — floorplan/floor premiums and discounts
# ---------------------------------------------------------------------------

class TestUnitLevelAdjustment:
    def test_plain_unit_no_adjustment(self):
        assert _unit_level_adjustment({"floorplan_name": "", "unit_code": ""}) == 1.0

    def test_penthouse_premium(self):
        adj = _unit_level_adjustment({"floorplan_name": "Penthouse", "unit_code": ""})
        assert adj == 1.05

    def test_balcony_plus_high_floor(self):
        # balcony (+0.03) and floor 8 (+0.04) → 1.07
        adj = _unit_level_adjustment({"floorplan_name": "1BR Balcony", "unit_code": "816"})
        assert adj == pytest.approx(1.07)

    def test_low_floor_discount(self):
        adj = _unit_level_adjustment({"floorplan_name": "Studio", "unit_code": "L2-1"})
        assert adj == pytest.approx(0.98)


# ---------------------------------------------------------------------------
# _compute_market_psf — weighted PSF by bed type
# ---------------------------------------------------------------------------

class TestComputeMarketPsf:
    def test_small_sample_is_plain_mean(self):
        # <3 units for a bed type → plain mean, no weighting/outlier removal.
        comp_units = [
            {"beds": 1, "sqft": 1000, "min_rent": 2000, "_prop": {"id": 1, "unit_count_total": 100}},
            {"beds": 1, "sqft": 1000, "min_rent": 3000, "_prop": {"id": 2, "unit_count_total": 100}},
        ]
        snaps = {1: {"unit_count": 10}, 2: {"unit_count": 10}}
        result = _compute_market_psf(comp_units, [], snaps)
        # psfs are 2.0 and 3.0 → mean 2.5
        assert result[1] == pytest.approx(2.5)

    def test_uniform_psf_weighted_branch(self):
        # >=3 units all at psf 2.0 → weighted average is exactly 2.0
        comp_units = [
            {"beds": 2, "sqft": 1000, "min_rent": 2000, "_prop": {"id": i, "unit_count_total": 100}}
            for i in range(4)
        ]
        snaps = {i: {"unit_count": 5} for i in range(4)}
        result = _compute_market_psf(comp_units, [], snaps)
        assert result[2] == pytest.approx(2.0)

    def test_zero_sqft_units_ignored(self):
        comp_units = [
            {"beds": 1, "sqft": 0, "min_rent": 2000, "_prop": {"id": 1, "unit_count_total": 100}},
            {"beds": 1, "sqft": 1000, "min_rent": 2500, "_prop": {"id": 2, "unit_count_total": 100}},
        ]
        snaps = {1: {"unit_count": 10}, 2: {"unit_count": 10}}
        result = _compute_market_psf(comp_units, [], snaps)
        # Only the 1000sqft unit counts → psf 2.5
        assert result[1] == pytest.approx(2.5)

    def test_estimated_units_are_down_weighted(self):
        # Same set of PSFs and exposures in both runs; only the estimated flag
        # on the highest-PSF unit differs. Halving its weight must pull the
        # weighted market PSF down relative to treating it as observed.
        # (Comparison form so it's robust to the outlier-trim step, which is
        # identical across both runs since the PSF values are unchanged.)
        snaps = {i: {"unit_count": 10} for i in (1, 2, 3, 4)}

        def units(high_estimated):
            psfs = [(1, 2400), (2, 2500), (3, 2500), (4, 2600)]
            return [
                {"beds": 1, "sqft": 1000, "min_rent": rent,
                 "is_estimated": (pid == 4 and high_estimated),
                 "_prop": {"id": pid, "unit_count_total": 100}}
                for pid, rent in psfs
            ]

        observed_psf = _compute_market_psf(units(False), [], snaps)[1]
        estimated_psf = _compute_market_psf(units(True), [], snaps)[1]
        assert estimated_psf < observed_psf


# ---------------------------------------------------------------------------
# generate_recommendations — seeded end-to-end invariants
# ---------------------------------------------------------------------------

VALID_SIGNALS = {"underpriced", "market", "overpriced", "well_above"}


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text())
    now = datetime.now(timezone.utc).isoformat()

    def add_property(slug, name, is_subject, total):
        cur = conn.execute(
            "INSERT INTO properties (slug, name, url, platform, unit_count_total, "
            "is_subject, active, added_at) VALUES (?, ?, ?, 'rentcafe', ?, ?, 1, ?)",
            (slug, name, f"https://example.com/{slug}", total, is_subject, now),
        )
        return cur.lastrowid

    def add_snapshot(prop_id, units):
        cur = conn.execute(
            "INSERT INTO snapshots (property_id, fetched_at, fetch_status, http_status, "
            "unit_count, floorplan_count) VALUES (?, ?, 'success', 200, ?, 0)",
            (prop_id, now, len(units)),
        )
        sid = cur.lastrowid
        for code, beds, sqft, rent in units:
            conn.execute(
                "INSERT INTO units (snapshot_id, unit_code, floorplan_id, floorplan_name, "
                "beds, baths, sqft, min_rent, max_rent, available_date) "
                "VALUES (?, ?, 1, ?, ?, 1, ?, ?, ?, '2026-07-01')",
                (sid, code, f"{beds}BR", beds, sqft, rent, rent),
            )
        return sid

    subj = add_property("subject", "Subject Prop", 1, 100)
    add_snapshot(subj, [("S1", 1, 750, 2000), ("S2", 2, 1000, 2800)])

    c1 = add_property("comp-one", "Comp One", 0, 100)
    add_snapshot(c1, [("C1", 1, 800, 2200), ("C2", 2, 1050, 3000), ("C3", 1, 820, 2250)])

    c2 = add_property("comp-two", "Comp Two", 0, 120)
    add_snapshot(c2, [("D1", 1, 780, 2150), ("D2", 2, 1020, 2950), ("D3", 2, 1010, 2900)])

    conn.commit()
    conn.close()


@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
    db_path = tmp_path / "pricing_test.db"
    _seed_db(db_path)
    # storage.db() reads its module-level DB_PATH at connect time.
    monkeypatch.setattr("src.storage.DB_PATH", db_path)
    # Reset the in-process pricing cache so each test computes fresh.
    monkeypatch.setattr(pricing, "_cache_valid", False, raising=False)
    monkeypatch.setattr(pricing, "_cached_report", None, raising=False)
    return db_path


class TestGenerateRecommendations:
    def test_produces_report_for_each_subject_unit(self, seeded_db):
        report = pricing.generate_recommendations(force=True)
        assert report is not None
        assert report.subject_slug == "subject"
        # One recommendation per subject unit with positive rent
        assert len(report.units) == 2
        assert report.comp_count == 2

    def test_recommendation_invariants(self, seeded_db):
        report = pricing.generate_recommendations(force=True)
        for rec in report.units:
            assert rec.recommended_rent > 0
            assert rec.recommended_psf > 0
            assert rec.signal in VALID_SIGNALS
            # delta is exactly recommended minus listed
            assert rec.delta == rec.recommended_rent - rec.listed_rent
            # confidence band brackets the recommendation
            assert rec.conservative_rent <= rec.recommended_rent <= rec.aggressive_rent

    def test_market_psf_covers_present_bed_types(self, seeded_db):
        report = pricing.generate_recommendations(force=True)
        # Comps have 1BR and 2BR units
        assert set(report.market_psf_by_bed.keys()) == {1, 2}

    def test_summary_totals_consistent(self, seeded_db):
        report = pricing.generate_recommendations(force=True)
        s = report.summary
        assert s["total_units"] == len(report.units)
        assert s["overpriced_count"] + s["underpriced_count"] + s["market_count"] <= s["total_units"]

    def test_caching_returns_same_object(self, seeded_db):
        first = pricing.generate_recommendations(force=True)
        second = pricing.generate_recommendations()  # cached
        assert first is second

    def test_no_subject_returns_none(self, tmp_path, monkeypatch):
        db_path = tmp_path / "no_subject.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA.read_text())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO properties (slug, name, url, platform, unit_count_total, "
            "is_subject, active, added_at) VALUES "
            "('c', 'Comp', 'https://e.com', 'rentcafe', 100, 0, 1, ?)",
            (now,),
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr("src.storage.DB_PATH", db_path)
        monkeypatch.setattr(pricing, "_cache_valid", False, raising=False)
        assert pricing.generate_recommendations(force=True) is None
