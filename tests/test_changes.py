"""Tests for snapshot diffing — in particular the available-now date noise."""
from __future__ import annotations

import pytest

from src import changes
from src.changes import _both_available_now, diff_snapshots


class TestBothAvailableNow:
    @pytest.mark.parametrize("old,old_day,new,new_day,expected", [
        # Rolling "today" date on an available-now unit: noise.
        ("2026-11-01", "2026-11-01", "2026-11-02", "2026-11-02", True),
        # Past date replaced by today's date: still available now.
        ("2026-10-15", "2026-11-01", "2026-11-02", "2026-11-02", True),
        # Future move-in date pushed out: a real change.
        ("2026-12-01", "2026-11-01", "2026-12-15", "2026-11-02", False),
        # Available-now unit gets a future date (e.g. went on hold): real.
        ("2026-11-01", "2026-11-01", "2026-12-01", "2026-11-02", False),
        # Future date pulled in to now: real.
        ("2026-12-01", "2026-11-01", "2026-11-02", "2026-11-02", False),
        # Missing data: never suppress.
        (None, "2026-11-01", "2026-11-02", "2026-11-02", False),
        ("2026-11-01", None, "2026-11-02", "2026-11-02", False),
        # Datetime-shaped values compare on the date portion.
        ("2026-11-01T00:00:00", "2026-11-01", "2026-11-02T00:00:00", "2026-11-02", True),
    ])
    def test_cases(self, old, old_day, new, new_day, expected):
        assert _both_available_now(old, old_day, new, new_day) is expected


def _unit(code, rent, date):
    return {"unit_code": code, "floorplan_name": "A1", "beds": 1, "sqft": 700,
            "min_rent": rent, "available_date": date}


def test_diff_suppresses_rolling_dates_but_keeps_real_changes(monkeypatch):
    snaps = {
        1: {"A": _unit("A", 2000, "2026-11-01"),   # available now
            "B": _unit("B", 2100, "2026-12-01"),   # future
            "C": _unit("C", 2200, "2026-11-01")},  # will be removed
        2: {"A": _unit("A", 2000, "2026-11-02"),   # rolled date only -> no event
            "B": _unit("B", 2150, "2026-12-15"),   # rent + date change
            "D": _unit("D", 2300, "2026-11-02")},  # added
    }
    days = {1: "2026-11-01", 2: "2026-11-02"}
    monkeypatch.setattr(changes, "units_for_snapshot", lambda sid: snaps[sid])
    monkeypatch.setattr(changes, "_snapshot_day", lambda sid: days[sid])

    events = {(ev["event_type"], ev["unit_code"]) for ev in diff_snapshots(1, 2)}
    assert events == {
        ("rent_changed", "B"),
        ("date_changed", "B"),
        ("unit_added", "D"),
        ("unit_removed", "C"),
    }


def test_first_run_has_no_events():
    assert diff_snapshots(None, 1) == []
