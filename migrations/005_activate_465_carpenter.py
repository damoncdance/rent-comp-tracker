"""Migration 005: Activate 465 Carpenter with its Cross Street source.

465 Carpenter's units ARE listed online — the marketing site embeds the
Cross Street leasing front-end (yourcrossstreet.com/leasing/il/465-carpenter/),
which is RentCafe/SecureCafe-backed and server-renders per-unit availability.
A dedicated `crossstreet` parser reads it, so we point the property at that URL,
switch its platform, and activate it so the daily run scrapes it.

Idempotent — safe to run multiple times.

Usage:
    python -m migrations.005_activate_465_carpenter
"""
from __future__ import annotations

import sqlite3

from src.config import DB_PATH

URL = "https://yourcrossstreet.com/leasing/il/465-carpenter/"


def migrate():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """UPDATE properties
                  SET url = ?, platform = 'crossstreet', active = 1
                WHERE slug = '465-carpenter'""",
            (URL,),
        )
        conn.commit()

        row = conn.execute(
            "SELECT id, slug, platform, active, url FROM properties WHERE slug = '465-carpenter'"
        ).fetchone()
        if row:
            print(f"  465 Carpenter (id={row[0]}): platform={row[2]}, "
                  f"active={row[3]}, url={row[4]}")
        else:
            print("  WARNING: 465-carpenter not found — run migration 004 first.")
        print("Migration 005 complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
