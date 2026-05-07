-- Aberdeen Crossing Availability Tracker schema
-- Append-only design: every fetch writes a new snapshot row.
-- Never UPDATE existing rows; that would erase history.

CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at      TEXT    NOT NULL,           -- ISO 8601 UTC
    fetch_status    TEXT    NOT NULL,           -- 'success' or 'failed:<reason>'
    http_status     INTEGER,                    -- HTTP status code, NULL on network errors
    unit_count      INTEGER,                    -- how many units were parsed
    floorplan_count INTEGER,                    -- how many floorplan tiers were parsed
    raw_html_path   TEXT                        -- path to saved raw HTML, or NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_fetched_at ON snapshots(fetched_at);

CREATE TABLE IF NOT EXISTS units (
    snapshot_id     INTEGER NOT NULL,
    unit_code       TEXT    NOT NULL,           -- e.g. "1100-701"
    floorplan_id    INTEGER,
    floorplan_name  TEXT,                       -- e.g. "Tier 01 - Penthouse"
    beds            INTEGER,                    -- 0 = studio
    baths           REAL,
    sqft            REAL,
    min_rent        REAL,
    max_rent        REAL,
    available_date  TEXT,                       -- ISO 8601 date
    PRIMARY KEY (snapshot_id, unit_code),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_units_unit_code ON units(unit_code);
CREATE INDEX IF NOT EXISTS idx_units_floorplan_id ON units(floorplan_id);

CREATE TABLE IF NOT EXISTS floorplans (
    snapshot_id     INTEGER NOT NULL,
    floorplan_id    INTEGER NOT NULL,
    name            TEXT,
    beds            INTEGER,
    baths           REAL,
    min_sqft        REAL,
    max_sqft        REAL,
    min_rent        REAL,
    max_rent        REAL,
    available_count INTEGER,
    available_date  TEXT,                       -- earliest move-in across units in this tier
    PRIMARY KEY (snapshot_id, floorplan_id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_floorplans_id ON floorplans(floorplan_id);

-- Change events between consecutive snapshots.
-- Populated by src/changes.py after each fetch.
CREATE TABLE IF NOT EXISTS change_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL,           -- the NEW snapshot that introduced this change
    event_type      TEXT    NOT NULL,           -- 'unit_added', 'unit_removed', 'rent_changed', 'date_changed'
    unit_code       TEXT    NOT NULL,
    old_value       TEXT,                       -- prior value, JSON-encoded for flexibility
    new_value       TEXT,                       -- new value, JSON-encoded
    detected_at     TEXT    NOT NULL,           -- ISO 8601 UTC
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_change_events_snapshot ON change_events(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_change_events_type ON change_events(event_type);
CREATE INDEX IF NOT EXISTS idx_change_events_unit ON change_events(unit_code);
