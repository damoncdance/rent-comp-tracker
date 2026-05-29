"""Migration runner.

Applies pending migrations in numeric order and records each in a
`schema_migrations` ledger so it's only ever applied once.

Discovery: any file in this directory named `NNN_<description>.py` (e.g.
`001_add_properties.py`) that exposes a module-level `migrate()` callable is
treated as a migration. The version key is the filename stem.

All existing migrations are idempotent, so running this against a database
that predates the ledger is safe: prior migrations re-run as no-ops and are
then recorded.

Usage:
    python -m migrations.runner
    python -m migrations.runner --quiet
"""
from __future__ import annotations

import argparse
import importlib
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import DB_PATH

MIGRATIONS_DIR = Path(__file__).resolve().parent
_MIGRATION_RE = re.compile(r"^\d{3}_.+\.py$")


def discover_migrations() -> list[str]:
    """Return migration version keys (filename stems) in ascending order."""
    versions = [
        p.stem
        for p in MIGRATIONS_DIR.glob("*.py")
        if _MIGRATION_RE.match(p.name)
    ]
    return sorted(versions)


def _ensure_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version    TEXT PRIMARY KEY,
               applied_at TEXT NOT NULL
           )"""
    )
    conn.commit()


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def run(verbose: bool = True) -> list[str]:
    """Apply all pending migrations. Returns the list of versions applied now."""
    def log(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    conn = sqlite3.connect(DB_PATH)
    newly_applied: list[str] = []
    try:
        _ensure_ledger(conn)
        done = _applied_versions(conn)

        for version in discover_migrations():
            if version in done:
                log(f"  skip {version} (already applied)")
                continue

            log(f"  applying {version} ...")
            module = importlib.import_module(f"migrations.{version}")
            if not hasattr(module, "migrate"):
                raise RuntimeError(
                    f"migration {version} has no migrate() callable"
                )
            # Each migration manages its own connection/transaction and
            # raises on failure, which aborts the run before we record it.
            module.migrate()

            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            newly_applied.append(version)
            log(f"  recorded {version}")

        if newly_applied:
            log(f"Applied {len(newly_applied)} migration(s): {', '.join(newly_applied)}")
        else:
            log("No pending migrations.")
        return newly_applied
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply pending database migrations.")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Suppress per-migration logging.")
    args = parser.parse_args(argv)
    run(verbose=not args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
