"""Export papers + screening results to a CSV for manual review."""

import csv

import db

COLUMNS = [
    "id", "title", "year", "source_title", "authors", "doi",
    "relevant", "confidence", "reason", "themes",
    "peer_reviewed", "language", "study_type", "error",
    "abstract", "author_keywords", "index_keywords",
    "source", "source_file",
]


def export_csv(db_path: str, out_path: str, criteria_path: str, relevant_only: bool = False) -> int:
    conn = db.connect(db_path)
    query = """
        SELECT p.*, s.relevant, s.confidence, s.reason, s.themes,
               s.peer_reviewed, s.language, s.study_type, s.error
        FROM unique_papers p
        LEFT JOIN screening_results s ON s.work_id = p.work_id AND s.criteria_file = ?
    """
    params: list = [criteria_path]
    if relevant_only:
        query += " WHERE s.relevant = 1"
    query += " ORDER BY s.relevant DESC, s.confidence DESC"

    rows = conn.execute(query, params).fetchall()
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    conn.close()
    return len(rows)
