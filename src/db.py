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
    ingested_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screening_results (
    paper_id      TEXT PRIMARY KEY REFERENCES papers(id),
    relevant      INTEGER,
    confidence    REAL,
    reason        TEXT,
    themes        TEXT,
    model         TEXT,
    raw_response  TEXT,
    error         TEXT,
    screened_at   TEXT NOT NULL
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
