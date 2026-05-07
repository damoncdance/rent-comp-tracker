"""Compute diff events between two snapshots.

Event types produced:
  - unit_added:    a unit_code present in the new snapshot but not the old
  - unit_removed:  a unit_code present in the old snapshot but not the new
  - rent_changed:  same unit_code, different min_rent
  - date_changed:  same unit_code, different available_date
"""
from __future__ import annotations

from src.storage import units_for_snapshot


def diff_snapshots(old_id: int | None, new_id: int) -> list[dict]:
    """Return a list of change-event dicts. Empty if old_id is None (first run)."""
    if old_id is None:
        return []

    old = units_for_snapshot(old_id)
    new = units_for_snapshot(new_id)

    events: list[dict] = []

    for unit_code, new_row in new.items():
        if unit_code not in old:
            events.append({
                "event_type": "unit_added",
                "unit_code": unit_code,
                "old_value": None,
                "new_value": _summary(new_row),
            })
            continue

        old_row = old[unit_code]
        if old_row["min_rent"] != new_row["min_rent"]:
            events.append({
                "event_type": "rent_changed",
                "unit_code": unit_code,
                "old_value": old_row["min_rent"],
                "new_value": new_row["min_rent"],
            })
        if old_row["available_date"] != new_row["available_date"]:
            events.append({
                "event_type": "date_changed",
                "unit_code": unit_code,
                "old_value": old_row["available_date"],
                "new_value": new_row["available_date"],
            })

    for unit_code, old_row in old.items():
        if unit_code not in new:
            events.append({
                "event_type": "unit_removed",
                "unit_code": unit_code,
                "old_value": _summary(old_row),
                "new_value": None,
            })

    return events


def _summary(row: dict) -> dict:
    """Compact representation we'll JSON-store as old_value / new_value."""
    return {
        "floorplan_name": row["floorplan_name"],
        "beds": row["beds"],
        "sqft": row["sqft"],
        "min_rent": row["min_rent"],
        "available_date": row["available_date"],
    }
