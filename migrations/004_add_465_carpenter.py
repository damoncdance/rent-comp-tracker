"""Migration 004: Add 455 Carpenter (inactive) to the comp set.

455 N Carpenter St is a new 72-unit building by Range Group in West Town.
The website (465carpenter.com) runs on Wix with no scrapable listing platform,
so the property is added as inactive until a parseable source is available.

Idempotent — safe to run multiple times.

Usage:
    python -m migrations.004_add_455_carpenter
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.config import DB_PATH


def migrate():
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute(
            """INSERT OR IGNORE INTO properties
               (slug, name, address, url, platform, unit_count_total,
                is_subject, active, added_at,
                year_built, stories, management_company)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "455-carpenter",
                "455 Carpenter",
                "455 N Carpenter St, Chicago, IL 60642",
                "https://www.465carpenter.com/",   # Wix site — no scrapable endpoint yet
                "rentcafe",                        # placeholder until real platform identified
                72,
                0,      # is_subject
                0,      # active = 0 (inactive until scrapable source found)
                now,
                2026,   # year_built
                5,      # stories
                "Range Group",
            ),
        )

        conn.commit()

        row = conn.execute(
            "SELECT id, slug, name, active FROM properties WHERE slug = '455-carpenter'"
        ).fetchone()
        if row:
            print(f"  Added property id={row[0]}: {row[2]} (slug={row[1]}, active={row[3]})")
        else:
            print("  Property 455-carpenter already existed (no changes).")

        print("Migration 004 complete.")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
