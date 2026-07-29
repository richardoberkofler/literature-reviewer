"""SQLite schema and connection helper for the literature review pipeline."""

import re
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

-- A "work" is a unique/canonical paper. Multiple rows in `papers` (e.g. the
-- same paper exported by both Scopus and Web of Science, or re-exported
-- under a different id) can point at the same work via `paper_works`.
CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY AUTOINCREMENT
);

CREATE TABLE IF NOT EXISTS paper_works (
    paper_id TEXT PRIMARY KEY REFERENCES papers(id),
    work_id  INTEGER NOT NULL REFERENCES works(id)
);

CREATE TABLE IF NOT EXISTS screening_results (
    work_id       INTEGER NOT NULL REFERENCES works(id),
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
    PRIMARY KEY (work_id, criteria_file)
);

-- One representative `papers` row per work: prefers the row with the
-- longest abstract (most complete record), falling back to the lowest id
-- for a stable tie-break. Screening and export operate on this view so
-- duplicates are only ever processed/reported once.
CREATE VIEW IF NOT EXISTS unique_papers AS
SELECT pw.work_id AS work_id, p.*
FROM paper_works pw
JOIN papers p ON p.id = pw.paper_id
WHERE p.id = (
    SELECT p2.id
    FROM paper_works pw2
    JOIN papers p2 ON p2.id = pw2.paper_id
    WHERE pw2.work_id = pw.work_id
    ORDER BY (p2.abstract IS NULL OR p2.abstract = ''), length(p2.abstract) DESC, p2.id
    LIMIT 1
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


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def normalize_title(title: str | None) -> str | None:
    if not title:
        return None
    title = title.strip().lower()
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    return title or None


def normalize_authors(authors: str | None) -> str | None:
    if not authors:
        return None
    authors = authors.strip().lower()
    authors = re.sub(r"[^a-z0-9]+", " ", authors).strip()
    return authors or None


def title_authors_key(title: str | None, authors: str | None) -> str | None:
    """Fallback dedup key for papers without a DOI.

    Requires both title AND authors to match: proceedings front-matter
    entries (prefaces, volume covers) often share an identical generic
    title with no DOI and no authors, and title-only matching would
    wrongly collapse those distinct entries into one work.
    """
    nt = normalize_title(title)
    na = normalize_authors(authors)
    if nt and na:
        return f"{nt}::{na}"
    return None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _backfill_paper_works(conn: sqlite3.Connection) -> None:
    """Link any `papers` rows that predate the `works`/`paper_works` tables.

    Dedupes on normalized DOI first, falling back to normalized (title, authors).
    """
    linked = {row[0] for row in conn.execute("SELECT paper_id FROM paper_works")}
    rows = conn.execute(
        "SELECT id, doi, title, authors FROM papers ORDER BY ingested_at, id"
    ).fetchall()

    doi_to_work: dict[str, int] = {}
    key_to_work: dict[str, int] = {}

    # Build lookup maps from already-linked papers first.
    for doi, title, authors, work_id in conn.execute(
        """
        SELECT p.doi, p.title, p.authors, pw.work_id FROM papers p
        JOIN paper_works pw ON pw.paper_id = p.id
        """
    ):
        nd = normalize_doi(doi)
        key = title_authors_key(title, authors)
        if nd and nd not in doi_to_work:
            doi_to_work[nd] = work_id
        if key and key not in key_to_work:
            key_to_work[key] = work_id

    for paper_id, doi, title, authors in rows:
        if paper_id in linked:
            continue
        nd = normalize_doi(doi)
        key = title_authors_key(title, authors)
        work_id = None
        if nd and nd in doi_to_work:
            work_id = doi_to_work[nd]
        elif key and key in key_to_work:
            work_id = key_to_work[key]

        if work_id is None:
            cur = conn.execute("INSERT INTO works DEFAULT VALUES")
            work_id = cur.lastrowid

        conn.execute(
            "INSERT INTO paper_works (paper_id, work_id) VALUES (?, ?)",
            (paper_id, work_id),
        )
        if nd:
            doi_to_work.setdefault(nd, work_id)
        if key:
            key_to_work.setdefault(key, work_id)


def _migrate_screening_results_to_work_id(conn: sqlite3.Connection) -> None:
    """Rebuild `screening_results` around work_id if it still uses paper_id.

    Existing per-paper rows are collapsed one-per-(work_id, criteria_file),
    preferring successful (non-error) results and the most recent screening.
    """
    if "paper_id" not in _table_columns(conn, "screening_results"):
        return

    conn.execute(
        """
        CREATE TABLE screening_results_new (
            work_id       INTEGER NOT NULL REFERENCES works(id),
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
            PRIMARY KEY (work_id, criteria_file)
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO screening_results_new
        SELECT pw.work_id, s.criteria_file, s.relevant, s.confidence, s.reason, s.themes,
               s.peer_reviewed, s.language, s.study_type, s.model, s.raw_response,
               s.error, s.screened_at
        FROM screening_results s
        JOIN paper_works pw ON pw.paper_id = s.paper_id
        ORDER BY (s.error IS NOT NULL), s.screened_at DESC
        """
    )
    conn.execute("DROP TABLE screening_results")
    conn.execute("ALTER TABLE screening_results_new RENAME TO screening_results")


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, column, col_type in _MIGRATIONS:
        existing = _table_columns(conn, table)
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    _backfill_paper_works(conn)
    _migrate_screening_results_to_work_id(conn)
    conn.commit()
    return conn
