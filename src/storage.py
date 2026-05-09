"""SQLite read/write helpers. All snapshot data flows through here."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from src.config import DB_PATH


@contextmanager
def db():
    """Connection context manager. Always use this — never open conns ad-hoc."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def write_snapshot_failure(
    property_id: int,
    reason: str,
    http_status: int | None = None,
) -> int:
    """Record a fetch attempt that didn't produce parsable data. Returns snapshot id."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO snapshots
                 (property_id, fetched_at, fetch_status, http_status, unit_count, floorplan_count)
               VALUES (?, ?, ?, ?, NULL, NULL)""",
            (property_id, now, f"failed:{reason}", http_status),
        )
        return cur.lastrowid


def write_snapshot_success(
    property_id: int,
    units: list[dict],
    floorplans: list[dict],
    http_status: int = 200,
    raw_html_path: Path | None = None,
) -> int:
    """Persist a successful fetch. Returns the new snapshot_id."""
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO snapshots
                 (property_id, fetched_at, fetch_status, http_status, unit_count,
                  floorplan_count, raw_html_path)
               VALUES (?, ?, 'success', ?, ?, ?, ?)""",
            (property_id, now, http_status, len(units), len(floorplans),
             str(raw_html_path) if raw_html_path else None),
        )
        snapshot_id = cur.lastrowid

        conn.executemany(
            """INSERT INTO units
                 (snapshot_id, unit_code, floorplan_id, floorplan_name,
                  beds, baths, sqft, min_rent, max_rent, available_date,
                  concession_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(snapshot_id, u["UnitCode"], u["FloorplanId"], u["FloorplanName"],
              u["Beds"], u["Baths"], u["SqFt"], u["MinRent"], u["MaxRent"],
              u["AvailableDate"], u.get("ConcessionText")) for u in units],
        )

        # Roll units up to per-floorplan counts so we have tier-level history
        # even if the floorplansList structure changes upstream.
        by_fp: dict[int, list[dict]] = defaultdict(list)
        for u in units:
            by_fp[u["FloorplanId"]].append(u)

        fp_rows = []
        for fp in floorplans:
            fp_units = by_fp.get(fp["Id"], [])
            earliest = min((u["AvailableDate"] for u in fp_units),
                           default=fp.get("AvailableDate"))
            fp_rows.append((
                snapshot_id, fp["Id"],
                fp_units[0]["FloorplanName"] if fp_units else None,
                fp["Beds"], fp["Baths"], fp["MinSqFt"], fp["MaxSqFt"],
                fp["MinRent"], fp["MaxRent"], fp["AvailableCount"], earliest,
            ))
        conn.executemany(
            """INSERT INTO floorplans
                 (snapshot_id, floorplan_id, name, beds, baths,
                  min_sqft, max_sqft, min_rent, max_rent,
                  available_count, available_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            fp_rows,
        )

        return snapshot_id


def write_change_events(snapshot_id: int, events: list[dict]) -> None:
    """Persist diff events. Each event: {event_type, unit_code, old_value, new_value}."""
    if not events:
        return
    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.executemany(
            """INSERT INTO change_events
                 (snapshot_id, event_type, unit_code, old_value, new_value, detected_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [(snapshot_id, e["event_type"], e["unit_code"],
              json.dumps(e.get("old_value")) if e.get("old_value") is not None else None,
              json.dumps(e.get("new_value")) if e.get("new_value") is not None else None,
              now) for e in events],
        )


def latest_snapshot_id(property_id: int | None = None) -> int | None:
    """Return the most recent successful snapshot id, or None.

    If property_id is given, scoped to that property. Otherwise global.
    """
    with db() as conn:
        if property_id is not None:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE fetch_status = 'success' "
                "AND property_id = ? ORDER BY id DESC LIMIT 1",
                (property_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM snapshots WHERE fetch_status = 'success' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return row["id"] if row else None


def previous_snapshot_id(before_id: int, property_id: int | None = None) -> int | None:
    """Most recent successful snapshot strictly before `before_id`.

    If property_id is given, scoped to that property.
    """
    with db() as conn:
        if property_id is not None:
            row = conn.execute(
                "SELECT id FROM snapshots "
                "WHERE fetch_status = 'success' AND id < ? AND property_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (before_id, property_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM snapshots "
                "WHERE fetch_status = 'success' AND id < ? "
                "ORDER BY id DESC LIMIT 1",
                (before_id,),
            ).fetchone()
        return row["id"] if row else None


def units_for_snapshot(snapshot_id: int) -> dict[str, dict]:
    """Return {unit_code: row_dict} for a snapshot."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM units WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchall()
        return {r["unit_code"]: dict(r) for r in rows}


def snapshot_summary_history(limit: int = 90, property_id: int | None = None) -> list[dict]:
    """Per-snapshot rollups for charts: total units + avg rent by bed type."""
    with db() as conn:
        if property_id is not None:
            rows = conn.execute(
                """
                SELECT s.id, s.fetched_at, s.unit_count,
                       u.beds, COUNT(*) AS n, AVG(u.min_rent) AS avg_rent
                  FROM snapshots s
                  JOIN units u ON u.snapshot_id = s.id
                 WHERE s.fetch_status = 'success' AND s.property_id = ?
                 GROUP BY s.id, u.beds
                 ORDER BY s.id DESC
                 LIMIT ?
                """,
                (property_id, limit * 4),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT s.id, s.fetched_at, s.unit_count,
                       u.beds, COUNT(*) AS n, AVG(u.min_rent) AS avg_rent
                  FROM snapshots s
                  JOIN units u ON u.snapshot_id = s.id
                 WHERE s.fetch_status = 'success'
                 GROUP BY s.id, u.beds
                 ORDER BY s.id DESC
                 LIMIT ?
                """,
                (limit * 4,),
            ).fetchall()
        return [dict(r) for r in rows]


def recent_changes(limit: int = 50, property_id: int | None = None) -> list[dict]:
    """Most recent change events with snapshot timestamps."""
    with db() as conn:
        if property_id is not None:
            rows = conn.execute(
                """
                SELECT ce.*, s.fetched_at AS snapshot_fetched_at
                  FROM change_events ce
                  JOIN snapshots s ON s.id = ce.snapshot_id
                 WHERE s.property_id = ?
                 ORDER BY ce.id DESC
                 LIMIT ?
                """,
                (property_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT ce.*, s.fetched_at AS snapshot_fetched_at
                  FROM change_events ce
                  JOIN snapshots s ON s.id = ce.snapshot_id
                 ORDER BY ce.id DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
