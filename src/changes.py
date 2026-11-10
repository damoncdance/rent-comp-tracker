"""Compute diff events between two snapshots.

Event types produced:
  - unit_added:    a unit_code present in the new snapshot but not the old
  - unit_removed:  a unit_code present in the old snapshot but not the new
  - rent_changed:  same unit_code, different min_rent
  - date_changed:  same unit_code, different available_date (ignored when
                   the unit was available-now in both snapshots)
"""
from __future__ import annotations

from src.storage import db, units_for_snapshot


def diff_snapshots(old_id: int | None, new_id: int) -> list[dict]:
    """Return a list of change-event dicts. Empty if old_id is None (first run)."""
    if old_id is None:
        return []

    old = units_for_snapshot(old_id)
    new = units_for_snapshot(new_id)
    old_day, new_day = _snapshot_day(old_id), _snapshot_day(new_id)

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
        if (old_row["available_date"] != new_row["available_date"]
                and not _both_available_now(old_row["available_date"], old_day,
                                            new_row["available_date"], new_day)):
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


def _snapshot_day(snapshot_id: int) -> str | None:
    """YYYY-MM-DD (UTC) the snapshot was fetched, or None if unknown."""
    with db() as conn:
        row = conn.execute(
            "SELECT fetched_at FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
    return row["fetched_at"][:10] if row and row["fetched_at"] else None


def _both_available_now(old_date, old_day, new_date, new_day) -> bool:
    """True when the unit was move-in-ready in both snapshots.

    Many sites list available-now units with *today's* date, so the date
    rolls forward every day (11-01 -> 11-02 -> ...). That is not a real
    change and previously produced ~60 noise events per daily digest.
    """
    if not (old_date and new_date and old_day and new_day):
        return False
    return str(old_date)[:10] <= old_day and str(new_date)[:10] <= new_day


def _summary(row: dict) -> dict:
    """Compact representation we'll JSON-store as old_value / new_value."""
    return {
        "floorplan_name": row["floorplan_name"],
        "beds": row["beds"],
        "sqft": row["sqft"],
        "min_rent": row["min_rent"],
        "available_date": row["available_date"],
    }
