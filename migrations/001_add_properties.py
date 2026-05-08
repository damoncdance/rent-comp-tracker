"""Migration 001: Add properties table and property_id to snapshots.

Idempotent — safe to run multiple times. Checks for existence before altering.

Usage:
    python -m migrations.001_add_properties
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.config import DB_PATH


# All 12 properties from the HelloData comp report (May 2026).
# Aberdeen Crossing (1100 W Grand Ave) is already tracked; it gets id=1.
PROPERTIES = [
    # (slug, name, address, url, platform, unit_count_total, is_subject)
    ("aberdeen-crossing", "1100 W Grand Ave", "1100 West Grand Avenue, Chicago, IL 60642",
     "https://www.aberdeencrossingapts.com/floorplans", "rentcafe", 99, 0),
    ("inspire-west-town", "Inspire West Town", "670 North May Street, Chicago, IL 60642",
     "https://www.iwtchicago.com/floorplans", "rentcafe", 113, 1),
    ("nevele22", "Nevele22", "1122 West Chicago Avenue, Chicago, IL 60642",
     "https://lipeproperty.appfolio.com/listings", "appfolio", 97, 0),
    ("seven-10-west", "Seven 10 West", "710 West Grand Avenue, Chicago, IL 60654",
     "https://seven10west.urbanapt.com/api/listings", "nestio", 105, 0),
    ("westerly", "Westerly", "740 North Aberdeen Street, Chicago, IL 60642",
     "https://sightmap.com/app/api/v1/8ywkdk14plx/sightmaps/76952", "sightmap", 188, 0),
    ("hugo-river-north", "Hugo River North", "751 North Hudson Avenue, Chicago, IL 60654",
     "https://sightmap.com/app/api/v1/yzvgo8o7wln/sightmaps/39454", "sightmap", 227, 0),
    ("812-west-adams", "812 West Adams", "812 West Adams Street, Chicago, IL 60607",
     "https://812adams.net/wp-json/wc/store/v1/products?per_page=100", "woocommerce", 80, 0),
    ("the-jax", "The Jax", "1220 West Jackson Boulevard, Chicago, IL 60607",
     "https://cagan.securecafe.com/onlineleasing/1220-w-jackson-blvd/floorplans", "securecafe", 172, 0),
    ("the-ardus", "The Ardus", "676 North LaSalle Drive, Chicago, IL 60654",
     "https://sightmap.com/app/api/v1/05evez1mvqo/sightmaps/18809", "sightmap", 149, 0),
    ("evo-union-park", "Evo Union Park Apartments", "1454 West Randolph Street, Chicago, IL 60607",
     "https://sightmap.com/app/api/v1/4yjp2m79vxl/sightmaps/14346", "sightmap", 242, 0),
    ("arthurs-of-old-town", "Arthurs of Old Town", "300 West Division Street, Chicago, IL 60610",
     "https://divisionllc.appfolio.com/listings", "appfolio", 89, 0),
    ("the-van-buren", "The Van Buren", "808 West Van Buren Street, Chicago, IL 60607",
     "https://www.thevanburen.com/floorplans.aspx", "securecafe", 148, 0),
]


def migrate():
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF;")  # off during migration

    try:
        # Step 1: Create properties table if it doesn't exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS properties (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                slug            TEXT    NOT NULL UNIQUE,
                name            TEXT    NOT NULL,
                address         TEXT,
                url             TEXT    NOT NULL,
                platform        TEXT    NOT NULL DEFAULT 'rentcafe',
                unit_count_total INTEGER,
                is_subject      INTEGER NOT NULL DEFAULT 0,
                active          INTEGER NOT NULL DEFAULT 1,
                added_at        TEXT    NOT NULL
            )
        """)

        # Step 2: Insert properties (skip if already present)
        for slug, name, address, url, platform, units, is_subject in PROPERTIES:
            conn.execute("""
                INSERT OR IGNORE INTO properties
                    (slug, name, address, url, platform, unit_count_total, is_subject, active, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (slug, name, address, url, platform, units, is_subject,
                  1 if platform in ("rentcafe", "sightmap", "appfolio", "nestio", "securecafe", "woocommerce") else 0,
                  now))

        # Step 3: Add property_id column to snapshots if missing
        cols = [row[1] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()]
        if "property_id" not in cols:
            conn.execute("ALTER TABLE snapshots ADD COLUMN property_id INTEGER REFERENCES properties(id)")

            # Backfill: all existing snapshots belong to Aberdeen Crossing (id=1)
            aberdeen = conn.execute(
                "SELECT id FROM properties WHERE slug = 'aberdeen-crossing'"
            ).fetchone()
            if aberdeen:
                conn.execute("UPDATE snapshots SET property_id = ?", (aberdeen[0],))
                print(f"  Backfilled {conn.execute('SELECT changes()').fetchone()[0]} "
                      f"snapshots with property_id={aberdeen[0]}")

        conn.commit()
        print("Migration 001 complete.")

        # Summary
        count = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM properties WHERE active = 1").fetchone()[0]
        print(f"  {count} properties registered, {active} active")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
