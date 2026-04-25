-- Schema v1: sessions, descriptors, transfers, endpoints, analyses.
-- Applied unconditionally via CREATE IF NOT EXISTS; future migrations will
-- gate on the schema_version row.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,       -- ISO-8601 UTC
    ended_at    TEXT,
    speed       TEXT,                -- 'ls' | 'fs' | 'hs' | 'unknown'
    status      TEXT NOT NULL,       -- 'live' | 'closed' | 'error'
    notes       TEXT,
    source_pcap TEXT                 -- path to raw pcap on disk (NULL for live-only)
);

-- USB descriptors observed during the session. kind is a free-text tag:
-- 'device', 'configuration', 'interface', 'endpoint', 'hid', 'class:uvc',
-- 'class:msc', etc. `index` is 0 for singletons, >0 for numbered descriptors
-- (interfaces by bInterfaceNumber, endpoints by bEndpointAddress, etc.).
CREATE TABLE IF NOT EXISTS descriptors (
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL,
    idx         INTEGER NOT NULL DEFAULT 0,
    raw_bytes   BLOB    NOT NULL,
    parsed_json TEXT,                -- tshark/our parse of raw_bytes, nullable
    PRIMARY KEY (session_id, kind, idx)
);

-- One row per logical transfer, NOT per link-layer packet.
-- type: 'control' | 'bulk' | 'interrupt' | 'isoch'
-- direction: 'in' | 'out' | 'setup' (setup is the initial SETUP token of
-- a control transfer; reply direction is captured on the trailing row).
-- setup_bytes: 8-byte SETUP packet for control transfers, NULL otherwise.
-- data_bytes: payload (may be 0 length; NULL if transfer was NAK'd before data).
-- status: 'ack' | 'nak' | 'stall' | 'nyet' | 'error' | 'timeout'
CREATE TABLE IF NOT EXISTS transfers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    ts_ns       INTEGER NOT NULL,    -- nanoseconds since epoch
    ep_addr     INTEGER NOT NULL,    -- bEndpointAddress (high bit = direction)
    device_addr INTEGER NOT NULL,    -- bDeviceAddress on the bus at this ts
    direction   TEXT    NOT NULL,
    type        TEXT    NOT NULL,
    setup_bytes BLOB,
    data_bytes  BLOB,
    length      INTEGER NOT NULL,    -- len(data_bytes) + (8 if setup else 0)
    status      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transfers_session_ts
    ON transfers (session_id, ts_ns);
CREATE INDEX IF NOT EXISTS idx_transfers_endpoint
    ON transfers (session_id, device_addr, ep_addr);

-- Derived endpoint summary. Fully rebuildable from transfers; cached here
-- so reports/analysis can read it without scanning the transfer log.
CREATE TABLE IF NOT EXISTS endpoints (
    session_id              INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    device_addr             INTEGER NOT NULL,
    ep_addr                 INTEGER NOT NULL,
    type                    TEXT,   -- inferred from traffic if descriptor not seen
    mps                     INTEGER, -- max packet size observed
    observed_summary_json   TEXT NOT NULL,  -- {"in":N,"out":N,"naks":N,...}
    PRIMARY KEY (session_id, device_addr, ep_addr)
);

-- One row per /analyze invocation. Not used in Phase 3; defined here so
-- later migrations don't have to CREATE.
CREATE TABLE IF NOT EXISTS analyses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    model               TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    tool_call_log_json  TEXT NOT NULL DEFAULT '[]',
    report_md           TEXT,
    status              TEXT NOT NULL  -- 'running' | 'done' | 'error'
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
