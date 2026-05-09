"""Migration 002: Add static property details and concession tracking.

Adds year_built, stories, management_company to properties table.
Adds concession_text to units table for NER calculation.

Idempotent — safe to run multiple times.

Usage:
    python -m migrations.002_property_details_and_concessions
"""
from __future__ import annotations

import sqlite3

from src.config import DB_PATH


# Static property data from HelloData Comp Report #53 (May 2026)
PROPERTY_DETAILS = {
    # slug: (year_built, stories, management_company)
    "inspire-west-town":   (2023, 8, "Cagan"),
    "nevele22":            (2023, 7, "Nevele22"),
    "seven-10-west":       (2018, 8, "Luxury Living Chicago Realty"),
    "westerly":            (2020, 12, "Bozzuto"),
    "hugo-river-north":    (2023, 9, "Lg Development Group"),
    "812-west-adams":      (2024, 7, "Continuum Real Estate Brokers, Inc."),
    "the-jax":             (2020, 10, "Cagan"),
    "the-ardus":           (2018, 7, "Flats"),
    "evo-union-park":      (2021, 11, "Marquette Management"),
    "arthurs-of-old-town": (2021, 7, "Turbotenant"),
    "the-van-buren":       (2018, 12, "Greystar"),
    "aberdeen-crossing":   (2026, 7, "Cagan"),
}


def migrate():
    conn = sqlite3.connect(DB_PATH)

    try:
        # Step 1: Add static columns to properties if missing
        cols = [row[1] for row in conn.execute("PRAGMA table_info(properties)").fetchall()]

        if "year_built" not in cols:
            conn.execute("ALTER TABLE properties ADD COLUMN year_built INTEGER")
            print("  Added year_built column")

        if "stories" not in cols:
            conn.execute("ALTER TABLE properties ADD COLUMN stories INTEGER")
            print("  Added stories column")

        if "management_company" not in cols:
            conn.execute("ALTER TABLE properties ADD COLUMN management_company TEXT")
            print("  Added management_company column")

        # Step 2: Populate static data
        for slug, (year_built, stories, mgmt) in PROPERTY_DETAILS.items():
            conn.execute(
                """UPDATE properties
                   SET year_built = ?, stories = ?, management_company = ?
                   WHERE slug = ? AND (year_built IS NULL OR stories IS NULL OR management_company IS NULL)""",
                (year_built, stories, mgmt, slug),
            )
        updated = conn.execute("SELECT changes()").fetchone()[0]
        print(f"  Populated static data for {updated} properties")

        # Step 3: Add concession_text column to units if missing
        unit_cols = [row[1] for row in conn.execute("PRAGMA table_info(units)").fetchall()]

        if "concession_text" not in unit_cols:
            conn.execute("ALTER TABLE units ADD COLUMN concession_text TEXT")
            print("  Added concession_text column to units")

        conn.commit()
        print("Migration 002 complete.")

        # Summary
        rows = conn.execute(
            "SELECT slug, year_built, stories, management_company FROM properties ORDER BY name"
        ).fetchall()
        for slug, yb, st, mc in rows:
            print(f"  {slug}: {yb}, {st} stories, {mc}")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
