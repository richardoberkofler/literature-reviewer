"""SQLite schema and connection helper for the literature review pipeline."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id               TEXT PRIMARY KEY,
    title            TEXT,
    year             INTEGER,
    source_title     TEXT,
    authors          TEXT,
    doi              TEXT,
    document_type    TEXT,
    cited_by         INTEGER,
    abstract         TEXT,
    author_keywords  TEXT,
    index_keywords   TEXT,
    source           TEXT,
    source_file      TEXT,
    ingested_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screening_results (
    paper_id      TEXT NOT NULL REFERENCES papers(id),
    criteria_file TEXT NOT NULL,
    relevant      INTEGER,
    confidence    REAL,
    reason        TEXT,
    themes        TEXT,
    peer_reviewed INTEGER,
    language      TEXT,
    study_type    TEXT,
    model         TEXT,
    raw_response  TEXT,
    error         TEXT,
    screened_at   TEXT NOT NULL,
    PRIMARY KEY (paper_id, criteria_file)
);
"""

# Columns added after the initial release; migrated in for existing databases
# that predate them (CREATE TABLE IF NOT EXISTS doesn't alter existing tables).
_MIGRATIONS = [
    ("screening_results", "peer_reviewed", "INTEGER"),
    ("screening_results", "language", "TEXT"),
    ("screening_results", "study_type", "TEXT"),
    ("papers", "source", "TEXT"),
    ("papers", "source_file", "TEXT"),
]


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, column, col_type in _MIGRATIONS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    return conn
