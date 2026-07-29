"""Screen ingested papers against criteria.yaml using a local Ollama model."""

import json
import threading
from datetime import datetime, timezone

import requests
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

Respond with ONLY a JSON object of this exact shape, no other text (themes can include up to 5 entries):
{{
  "relevant": true or false,
  "confidence": a number between 0.0 and 1.0,
  "reason": "one or two sentence justification for each inclusion/exclusion decision",
  "themes": ["short theme", "short theme", "etc."]
}}
"""


def load_criteria(criteria_path: str) -> dict:
    with open(criteria_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_prompt(paper: dict, criteria: dict) -> str:
    bullet = (
        lambda items: "\n".join(f"- {item}" for item in items) or "(none specified)"
    )
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
    """Screen unscreened (or all, if rescreen=True) papers against the given criteria file.

    Results are tracked per (paper, criteria_file), so screening with a different
    criteria file never overwrites or deletes results recorded under another one.
    Rescreening only updates rows already recorded under this criteria_file.
    """
    criteria = load_criteria(criteria_path)
    conn = db.connect(db_path)

    if rescreen:
        query = """
            SELECT p.* FROM papers p
            JOIN screening_results s ON s.paper_id = p.id AND s.criteria_file = ?
        """
        params: tuple = (criteria_path,)
    else:
        query = """
            SELECT p.* FROM papers p
            LEFT JOIN screening_results s ON s.paper_id = p.id AND s.criteria_file = ?
            WHERE s.paper_id IS NULL OR s.error IS NOT NULL
        """
        params = (criteria_path,)
    if limit:
        query += f" LIMIT {int(limit)}"

    rows = conn.execute(query, params).fetchall()
    done = 0
    failed = 0

    for i, row in enumerate(rows, start=1):
        paper = dict(row)
        prompt = build_prompt(paper, criteria)
        now = datetime.now(timezone.utc).isoformat()

        # Run the model call on a worker thread so a Ctrl+C in the main
        # thread can abort it immediately (by closing the session) instead
        # of waiting for the request to time out or return on its own.
        session = requests.Session()
        outcome: dict = {}

        def _call():
            try:
                outcome["result"] = generate_json(
                    prompt, model=model, base_url=base_url, session=session
                )
            except OllamaError as exc:
                outcome["error"] = exc
            except requests.exceptions.RequestException:
                pass  # session was closed to cancel the request; nothing to report

        worker = threading.Thread(target=_call, daemon=True)
        worker.start()
        try:
            while worker.is_alive():
                worker.join(timeout=0.2)
        except KeyboardInterrupt:
            session.close()
            worker.join(timeout=2)
            conn.commit()
            conn.close()
            raise
        finally:
            session.close()

        if "error" in outcome:
            exc = outcome["error"]
            conn.execute(
                """
                INSERT INTO screening_results
                    (paper_id, criteria_file, relevant, confidence, reason, themes, model, raw_response, error, screened_at)
                VALUES (?, ?, NULL, NULL, NULL, NULL, ?, NULL, ?, ?)
                ON CONFLICT(paper_id, criteria_file) DO UPDATE SET
                    error=excluded.error,
                    model=excluded.model,
                    screened_at=excluded.screened_at
                """,
                (paper["id"], criteria_path, model, str(exc), now),
            )
            failed += 1
        else:
            result = outcome["result"]
            conn.execute(
                """
                INSERT INTO screening_results
                    (paper_id, criteria_file, relevant, confidence, reason, themes, model, raw_response, error, screened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(paper_id, criteria_file) DO UPDATE SET
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
                    criteria_path,
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

        conn.commit()
        if on_progress:
            on_progress(i, len(rows), paper, failed)

    conn.close()
    return done, failed
