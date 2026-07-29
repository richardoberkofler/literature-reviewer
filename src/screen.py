"""Screen ingested papers against criteria.yaml using a local Ollama model."""

import json
from datetime import datetime, timezone

import yaml

import db
from ollama_client import OllamaError, generate_json

PROMPT_TEMPLATE = """You are assisting with the screening step of a systematic literature review.

Research topic:
{topic}

Inclusion criteria:
{inclusion}

Exclusion criteria:
{exclusion}

Additional notes:
{notes}

Given the paper below, decide whether it should be INCLUDED in the review.

Title: {title}
Author Keywords: {author_keywords}
Index Keywords: {index_keywords}
Abstract: {abstract}

Respond with ONLY a JSON object of this exact shape, no other text:
{{
  "relevant": true or false,
  "confidence": a number between 0.0 and 1.0,
  "reason": "one or two sentence justification",
  "themes": ["short theme", "short theme"]
}}
"""


def load_criteria(criteria_path: str) -> dict:
    with open(criteria_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_prompt(paper: dict, criteria: dict) -> str:
    bullet = lambda items: "\n".join(f"- {item}" for item in items) or "(none specified)"
    return PROMPT_TEMPLATE.format(
        topic=(criteria.get("topic") or "").strip(),
        inclusion=bullet(criteria.get("inclusion_criteria") or []),
        exclusion=bullet(criteria.get("exclusion_criteria") or []),
        notes=(criteria.get("notes") or "(none)").strip(),
        title=paper["title"] or "",
        author_keywords=paper["author_keywords"] or "",
        index_keywords=paper["index_keywords"] or "",
        abstract=paper["abstract"] or "",
    )


def screen_all(
    db_path: str,
    criteria_path: str,
    model: str,
    base_url: str = "http://localhost:11434",
    limit: int | None = None,
    rescreen: bool = False,
    on_progress=None,
) -> tuple[int, int]:
    """Screen unscreened (or all, if rescreen=True) papers. Returns (done, failed)."""
    criteria = load_criteria(criteria_path)
    conn = db.connect(db_path)

    if rescreen:
        query = "SELECT * FROM papers"
    else:
        query = """
            SELECT p.* FROM papers p
            LEFT JOIN screening_results s ON s.paper_id = p.id
            WHERE s.paper_id IS NULL OR s.error IS NOT NULL
        """
    if limit:
        query += f" LIMIT {int(limit)}"

    rows = conn.execute(query).fetchall()
    done = 0
    failed = 0

    for i, row in enumerate(rows, start=1):
        paper = dict(row)
        prompt = build_prompt(paper, criteria)
        now = datetime.now(timezone.utc).isoformat()

        try:
            result = generate_json(prompt, model=model, base_url=base_url)
            conn.execute(
                """
                INSERT INTO screening_results
                    (paper_id, relevant, confidence, reason, themes, model, raw_response, error, screened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    relevant=excluded.relevant,
                    confidence=excluded.confidence,
                    reason=excluded.reason,
                    themes=excluded.themes,
                    model=excluded.model,
                    raw_response=excluded.raw_response,
                    error=NULL,
                    screened_at=excluded.screened_at
                """,
                (
                    paper["id"],
                    1 if result.get("relevant") else 0,
                    result.get("confidence"),
                    result.get("reason"),
                    json.dumps(result.get("themes") or []),
                    model,
                    json.dumps(result),
                    now,
                ),
            )
            done += 1
        except OllamaError as exc:
            conn.execute(
                """
                INSERT INTO screening_results
                    (paper_id, relevant, confidence, reason, themes, model, raw_response, error, screened_at)
                VALUES (?, NULL, NULL, NULL, NULL, ?, NULL, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    error=excluded.error,
                    model=excluded.model,
                    screened_at=excluded.screened_at
                """,
                (paper["id"], model, str(exc), now),
            )
            failed += 1

        conn.commit()
        if on_progress:
            on_progress(i, len(rows), paper, failed)

    conn.close()
    return done, failed
