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


def comp_grid_data() -> list[dict]:
    """Return per-property summary data for the comp grid overview.

    For each active property, returns its latest snapshot stats:
    property info, unit count, avg rent by bed type, exposure %, concessions.
    """
    with db() as conn:
        props = conn.execute(
            """SELECT p.*, s.id AS snap_id, s.fetched_at, s.unit_count
               FROM properties p
               LEFT JOIN snapshots s ON s.id = (
                   SELECT MAX(s2.id) FROM snapshots s2
                   WHERE s2.property_id = p.id AND s2.fetch_status = 'success'
               )
               WHERE p.active = 1
               ORDER BY p.is_subject DESC, p.name"""
        ).fetchall()

        results = []
        for p in props:
            row = dict(p)
            snap_id = row.get("snap_id")
            if snap_id:
                # Get per-bed-type breakdown
                bed_rows = conn.execute(
                    """SELECT beds, COUNT(*) AS cnt,
                              AVG(min_rent) AS avg_rent,
                              AVG(sqft) AS avg_sqft,
                              MIN(min_rent) AS min_rent,
                              MAX(min_rent) AS max_rent
                       FROM units WHERE snapshot_id = ?
                       GROUP BY beds ORDER BY beds""",
                    (snap_id,),
                ).fetchall()
                row["by_bed"] = {r["beds"]: dict(r) for r in bed_rows}

                # Get concession text samples
                concessions = conn.execute(
                    """SELECT DISTINCT concession_text FROM units
                       WHERE snapshot_id = ? AND concession_text IS NOT NULL
                             AND concession_text != ''
                       LIMIT 3""",
                    (snap_id,),
                ).fetchall()
                row["concessions"] = [r["concession_text"] for r in concessions]

                # Overall stats
                totals = conn.execute(
                    """SELECT AVG(min_rent) AS avg_rent, AVG(sqft) AS avg_sqft,
                              MIN(min_rent) AS min_rent, MAX(min_rent) AS max_rent
                       FROM units WHERE snapshot_id = ?""",
                    (snap_id,),
                ).fetchone()
                row["avg_rent"] = totals["avg_rent"]
                row["avg_sqft"] = totals["avg_sqft"]
                row["overall_min_rent"] = totals["min_rent"]
                row["overall_max_rent"] = totals["max_rent"]
            else:
                row["by_bed"] = {}
                row["concessions"] = []
                row["avg_rent"] = None
                row["avg_sqft"] = None

            results.append(row)
        return results


def rents_by_unit_type() -> list[dict]:
    """Cross-property rent comparison table (HelloData p19 style).

    Returns one row per property with overall stats: available units,
    min/avg/max rent, avg sqft, avg PSF, NER, concession %.
    """
    with db() as conn:
        props = conn.execute(
            "SELECT id, slug, name, is_subject, unit_count_total "
            "FROM properties WHERE active = 1 "
            "ORDER BY is_subject DESC, name"
        ).fetchall()

        results = []
        for p in props:
            snap = conn.execute(
                "SELECT MAX(id) AS sid FROM snapshots "
                "WHERE property_id = ? AND fetch_status = 'success'",
                (p["id"],),
            ).fetchone()
            sid = snap["sid"] if snap else None
            if not sid:
                results.append({
                    "name": p["name"], "slug": p["slug"],
                    "is_subject": p["is_subject"], "active_units": 0,
                })
                continue

            stats = conn.execute(
                """SELECT COUNT(*) AS cnt,
                          MIN(min_rent) AS min_rent,
                          AVG(min_rent) AS avg_rent,
                          MAX(min_rent) AS max_rent,
                          AVG(sqft) AS avg_sqft
                   FROM units WHERE snapshot_id = ?""",
                (sid,),
            ).fetchone()

            avg_psf = (stats["avg_rent"] / stats["avg_sqft"]
                       if stats["avg_sqft"] and stats["avg_rent"] else None)

            results.append({
                "name": p["name"], "slug": p["slug"],
                "is_subject": p["is_subject"],
                "total_units": p["unit_count_total"],
                "active_units": stats["cnt"],
                "min_rent": stats["min_rent"],
                "avg_rent": stats["avg_rent"],
                "max_rent": stats["max_rent"],
                "avg_sqft": stats["avg_sqft"],
                "avg_psf": avg_psf,
            })
        return results


def exposure_history(limit: int = 90) -> list[dict]:
    """Per-property exposure % over time for the historical exposure chart.

    Returns [{fetched_at, slug, name, exposure_pct}, ...].
    """
    with db() as conn:
        rows = conn.execute(
            """SELECT s.fetched_at, p.slug, p.name, p.unit_count_total,
                      s.unit_count
               FROM snapshots s
               JOIN properties p ON p.id = s.property_id
               WHERE s.fetch_status = 'success' AND p.active = 1
               ORDER BY s.fetched_at DESC
               LIMIT ?""",
            (limit * 12,),
        ).fetchall()
        results = []
        for r in rows:
            total = r["unit_count_total"] or 1
            results.append({
                "fetched_at": r["fetched_at"],
                "slug": r["slug"],
                "name": r["name"],
                "exposure_pct": round(r["unit_count"] / total * 100, 1)
                if r["unit_count"] is not None else None,
            })
        return results


def rent_history_by_property(limit: int = 90) -> list[dict]:
    """Per-property average rent over time for trend charts.

    Returns [{fetched_at, slug, name, avg_rent}, ...].
    """
    with db() as conn:
        rows = conn.execute(
            """SELECT s.fetched_at, p.slug, p.name,
                      AVG(u.min_rent) AS avg_rent
               FROM snapshots s
               JOIN properties p ON p.id = s.property_id
               JOIN units u ON u.snapshot_id = s.id
               WHERE s.fetch_status = 'success' AND p.active = 1
               GROUP BY s.id, p.id
               ORDER BY s.fetched_at DESC
               LIMIT ?""",
            (limit * 12,),
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
