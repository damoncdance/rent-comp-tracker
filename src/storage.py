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
                  concession_text, is_estimated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(snapshot_id, u["UnitCode"], u["FloorplanId"], u["FloorplanName"],
              u["Beds"], u["Baths"], u["SqFt"], u["MinRent"], u["MaxRent"],
              u["AvailableDate"], u.get("ConcessionText"),
              1 if u.get("IsEstimated") else 0) for u in units],
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

                # Availability dates for leased % calculation
                avail_dates = conn.execute(
                    "SELECT available_date FROM units WHERE snapshot_id = ?",
                    (snap_id,),
                ).fetchall()
                row["avail_dates"] = [r["available_date"] for r in avail_dates]
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
                    "id": p["id"], "name": p["name"], "slug": p["slug"],
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
                "id": p["id"], "name": p["name"], "slug": p["slug"],
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


def days_on_market() -> dict[int, dict]:
    """Compute average Days on Market for each active property.

    For each currently-available unit, find the earliest snapshot where it
    appeared.  DOM = days between that first-seen date and today.

    Returns {property_id: {"avg_dom": float, "median_dom": float,
                           "by_bed": {beds: avg_dom}}}.
    """
    from statistics import median

    with db() as conn:
        # For each active property, get the latest snapshot's units
        props = conn.execute(
            """SELECT p.id, MAX(s.id) AS snap_id
               FROM properties p
               JOIN snapshots s ON s.property_id = p.id
               WHERE p.active = 1 AND s.fetch_status = 'success'
               GROUP BY p.id"""
        ).fetchall()

        today = datetime.now(timezone.utc).date()
        result: dict[int, dict] = {}

        for p in props:
            pid, snap_id = p["id"], p["snap_id"]
            # Current available units
            current_units = conn.execute(
                "SELECT unit_code, beds FROM units WHERE snapshot_id = ?",
                (snap_id,),
            ).fetchall()

            if not current_units:
                result[pid] = {"avg_dom": None, "median_dom": None, "by_bed": {}}
                continue

            unit_codes = [u["unit_code"] for u in current_units]
            beds_map = {u["unit_code"]: u["beds"] for u in current_units}

            # Find earliest appearance of each unit_code in this property's snapshots
            placeholders = ",".join("?" * len(unit_codes))
            first_seen_rows = conn.execute(
                f"""SELECT u.unit_code, MIN(s.fetched_at) AS first_seen
                    FROM units u
                    JOIN snapshots s ON s.id = u.snapshot_id
                    WHERE s.property_id = ? AND s.fetch_status = 'success'
                      AND u.unit_code IN ({placeholders})
                    GROUP BY u.unit_code""",
                (pid, *unit_codes),
            ).fetchall()

            doms: list[int] = []
            doms_by_bed: dict[int, list[int]] = defaultdict(list)
            for row in first_seen_rows:
                first = datetime.fromisoformat(row["first_seen"]).date()
                dom = (today - first).days
                doms.append(dom)
                beds = beds_map.get(row["unit_code"], 0)
                doms_by_bed[beds].append(dom)

            by_bed = {}
            for beds, vals in sorted(doms_by_bed.items()):
                by_bed[beds] = round(sum(vals) / len(vals), 1)

            result[pid] = {
                "avg_dom": round(sum(doms) / len(doms), 1) if doms else None,
                "median_dom": round(median(doms), 1) if doms else None,
                "by_bed": by_bed,
            }
        return result


def leasing_velocity(days: int = 7) -> dict[int, dict]:
    """Compute leasing velocity over a rolling window for each active property.

    Counts unit_removed events (assumed leased) in the last N days.
    Also computes weekly absorption rate = units_leased / available_at_start.

    Returns {property_id: {"units_leased": int, "absorption_pct": float,
                           "by_bed": {beds: units_leased}}}.
    """
    cutoff = datetime.now(timezone.utc).date().isoformat()  # YYYY-MM-DD

    with db() as conn:
        props = conn.execute(
            "SELECT id, unit_count_total FROM properties WHERE active = 1"
        ).fetchall()

        result: dict[int, dict] = {}
        for p in props:
            pid = p["id"]
            total = p["unit_count_total"] or 0

            # Count unit_removed events in the window
            removed = conn.execute(
                """SELECT ce.unit_code, ce.old_value, ce.detected_at
                   FROM change_events ce
                   JOIN snapshots s ON s.id = ce.snapshot_id
                   WHERE s.property_id = ?
                     AND ce.event_type = 'unit_removed'
                     AND DATE(ce.detected_at) >= DATE(?, '-' || ? || ' days')
                   ORDER BY ce.detected_at DESC""",
                (pid, cutoff, days),
            ).fetchall()

            units_leased = len(removed)

            # Parse bed counts from old_value (unit data before removal)
            by_bed: dict[int, int] = defaultdict(int)
            for r in removed:
                try:
                    val = json.loads(r["old_value"]) if r["old_value"] else {}
                    beds = val.get("beds", 0)
                except (json.JSONDecodeError, TypeError):
                    beds = 0
                by_bed[beds] += 1

            # Absorption = units leased / total units
            absorption = round(units_leased / total * 100, 1) if total else 0.0

            result[pid] = {
                "units_leased": units_leased,
                "absorption_pct": absorption,
                "by_bed": dict(sorted(by_bed.items())),
            }
        return result


def leasing_velocity_history(limit: int = 90) -> list[dict]:
    """Per-property daily leasing events over time for trend charts.

    Returns [{fetched_at, slug, name, units_leased, units_added}, ...].
    Each row represents one day's change events for one property.
    """
    with db() as conn:
        rows = conn.execute(
            """SELECT DATE(s.fetched_at) AS day, p.slug, p.name,
                      SUM(CASE WHEN ce.event_type = 'unit_removed' THEN 1 ELSE 0 END) AS units_leased,
                      SUM(CASE WHEN ce.event_type = 'unit_added' THEN 1 ELSE 0 END) AS units_added
               FROM change_events ce
               JOIN snapshots s ON s.id = ce.snapshot_id
               JOIN properties p ON p.id = s.property_id
               WHERE p.active = 1
               GROUP BY day, p.id
               ORDER BY day DESC
               LIMIT ?""",
            (limit * 14,),
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
