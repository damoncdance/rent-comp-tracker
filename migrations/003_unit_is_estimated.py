"""Migration 003: Flag estimated (interpolated) per-unit rents.

Adds `is_estimated` to the units table. SecureCafe only exposes tier-level
low/high prices, so its per-unit rents are interpolated rather than observed;
this flag lets the pricing engine trust them less and lets the UI label them.

Backfills history: marks existing units belonging to SecureCafe properties as
estimated so prior snapshots are consistent with new ones.

Idempotent — safe to run multiple times.

Usage:
    python -m migrations.003_unit_is_estimated
"""
from __future__ import annotations

import sqlite3

from src.config import DB_PATH


def migrate():
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(units)").fetchall()]

        if "is_estimated" not in cols:
            conn.execute(
                "ALTER TABLE units ADD COLUMN is_estimated INTEGER NOT NULL DEFAULT 0"
            )
            print("  Added is_estimated column to units")

        # Backfill: SecureCafe per-unit rents have always been interpolated.
        cur = conn.execute(
            """UPDATE units SET is_estimated = 1
               WHERE is_estimated = 0
                 AND snapshot_id IN (
                     SELECT s.id FROM snapshots s
                     JOIN properties p ON p.id = s.property_id
                     WHERE p.platform = 'securecafe'
                 )"""
        )
        print(f"  Backfilled {cur.rowcount} SecureCafe unit rows as estimated")

        conn.commit()
        print("Migration 003 complete.")

        estimated = conn.execute(
            "SELECT COUNT(*) FROM units WHERE is_estimated = 1"
        ).fetchone()[0]
        print(f"  {estimated} unit rows flagged estimated")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
