"""Load bibliographic exports (Scopus CSV, Web of Science Excel) into the papers table."""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import xlrd

import db

csv.field_size_limit(sys.maxsize)  # Scopus 'References' cells can be huge


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _upsert_paper(conn, row: dict, source: str, source_file: str, now: str) -> bool:
    paper_id = str(row.get("id") or "").strip()
    if not paper_id:
        return False
    conn.execute(
        """
        INSERT INTO papers (
            id, title, year, source_title, authors, doi,
            document_type, cited_by, abstract,
            author_keywords, index_keywords, source, source_file, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            index_keywords=excluded.index_keywords,
            source=excluded.source,
            source_file=excluded.source_file
        """,
        (
            paper_id,
            row.get("title"),
            row.get("year"),
            row.get("source_title"),
            row.get("authors"),
            row.get("doi"),
            row.get("document_type"),
            row.get("cited_by"),
            row.get("abstract"),
            row.get("author_keywords"),
            row.get("index_keywords"),
            source,
            source_file,
            now,
        ),
    )
    return True


def _rows_from_scopus_csv(path: str):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            yield {
                "id": raw.get("EID") or raw.get("DOI") or raw.get("Title"),
                "title": raw.get("Title"),
                "year": _int_or_none(raw.get("Year")),
                "source_title": raw.get("Source title"),
                "authors": raw.get("Authors"),
                "doi": raw.get("DOI"),
                "document_type": raw.get("Document Type"),
                "cited_by": _int_or_none(raw.get("Cited by")),
                "abstract": raw.get("Abstract"),
                "author_keywords": raw.get("Author Keywords"),
                "index_keywords": raw.get("Index Keywords"),
            }


def _rows_from_wos_dicts(dict_rows):
    for raw in dict_rows:
        yield {
            "id": raw.get("UT (Unique WOS ID)") or raw.get("DOI") or raw.get("Article Title"),
            "title": raw.get("Article Title"),
            "year": _int_or_none(raw.get("Publication Year")),
            "source_title": raw.get("Source Title"),
            "authors": raw.get("Authors"),
            "doi": raw.get("DOI"),
            "document_type": raw.get("Document Type"),
            "cited_by": _int_or_none(raw.get("Times Cited, WoS Core")),
            "abstract": raw.get("Abstract"),
            "author_keywords": raw.get("Author Keywords"),
            "index_keywords": raw.get("Keywords Plus"),
        }


def _read_xls(path: str):
    """Read rows from a legacy binary .xls file (the format WoS actually exports)."""
    wb = xlrd.open_workbook(path)
    sheet = wb.sheet_by_index(0)
    headers = [str(v) for v in sheet.row_values(0)]
    for r in range(1, sheet.nrows):
        yield dict(zip(headers, sheet.row_values(r)))


def _read_xlsx(path: str):
    """Read rows from a modern zip-based .xlsx file."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = wb.active
    rows = sheet.iter_rows(values_only=True)
    headers = [str(v) if v is not None else "" for v in next(rows)]
    for values in rows:
        yield dict(zip(headers, values))


def ingest(file_path: str, db_path: str) -> tuple[int, int]:
    """Insert/replace papers from a Scopus CSV or Web of Science Excel export.

    The source database and file format are both detected from the file
    extension. Returns (inserted, skipped).
    """
    suffix = Path(file_path).suffix.lower()
    if suffix == ".csv":
        source = "scopus"
        rows = _rows_from_scopus_csv(file_path)
    elif suffix == ".xls":
        source = "webofscience"
        rows = _rows_from_wos_dicts(_read_xls(file_path))
    elif suffix == ".xlsx":
        source = "webofscience"
        rows = _rows_from_wos_dicts(_read_xlsx(file_path))
    else:
        raise ValueError(f"Unsupported file type: {file_path!r} (expected .csv, .xls, or .xlsx)")

    conn = db.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    source_file = Path(file_path).name

    inserted = 0
    skipped = 0
    for row in rows:
        if _upsert_paper(conn, row, source, source_file, now):
            inserted += 1
        else:
            skipped += 1

    conn.commit()
    conn.close()
    return inserted, skipped
