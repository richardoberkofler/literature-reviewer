"""Load a Scopus CSV export into the papers table."""

import csv
import sys
from datetime import datetime, timezone

import db

csv.field_size_limit(sys.maxsize)  # Scopus 'References' cells can be huge


def _int_or_none(value: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def ingest_csv(csv_path: str, db_path: str) -> tuple[int, int]:
    """Insert/replace papers from a Scopus CSV export. Returns (inserted, skipped)."""
    conn = db.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()

    inserted = 0
    skipped = 0
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            paper_id = (row.get("EID") or row.get("DOI") or row.get("Title") or "").strip()
            if not paper_id:
                skipped += 1
                continue

            conn.execute(
                """
                INSERT INTO papers (
                    id, title, year, source_title, authors, doi,
                    document_type, cited_by, abstract,
                    author_keywords, index_keywords, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    year=excluded.year,
                    source_title=excluded.source_title,
                    authors=excluded.authors,
                    doi=excluded.doi,
                    document_type=excluded.document_type,
                    cited_by=excluded.cited_by,
                    abstract=excluded.abstract,
                    author_keywords=excluded.author_keywords,
                    index_keywords=excluded.index_keywords
                """,
                (
                    paper_id,
                    row.get("Title"),
                    _int_or_none(row.get("Year")),
                    row.get("Source title"),
                    row.get("Authors"),
                    row.get("DOI"),
                    row.get("Document Type"),
                    _int_or_none(row.get("Cited by")),
                    row.get("Abstract"),
                    row.get("Author Keywords"),
                    row.get("Index Keywords"),
                    now,
                ),
            )
            inserted += 1

    conn.commit()
    conn.close()
    return inserted, skipped
