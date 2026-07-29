"""Command-line entry point for the literature review pipeline.

Usage:
    python src/cli.py ingest <path> [--db data/review.db]
                              (accepts a Scopus .csv or Web of Science .xls/.xlsx export)
    python src/cli.py screen [--db data/review.db] [--criteria criteria.yaml]
                              [--model qwen2.5:14b] [--base-url http://localhost:11434]
                              [--limit N] [--rescreen]
    python src/cli.py status [--db data/review.db] [--criteria criteria.yaml]
    python src/cli.py export [--db data/review.db] [--out data/results.csv]
                              [--criteria criteria.yaml] [--relevant-only]
"""

import argparse
import sys

import db
import export as export_mod
import ingest as ingest_mod
import screen as screen_mod

DEFAULT_DB = "data/review.db"


def cmd_ingest(args):
    inserted, skipped = ingest_mod.ingest(args.file_path, args.db)
    print(f"Ingested {inserted} papers into {args.db} ({skipped} rows skipped: no id).")


def cmd_screen(args):
    def on_progress(i, total, paper, failed):
        print(f"[{i}/{total}] {paper['title'][:80]!r}", file=sys.stderr)

    try:
        done, failed = screen_mod.screen_all(
            db_path=args.db,
            criteria_path=args.criteria,
            model=args.model,
            base_url=args.base_url,
            limit=args.limit,
            rescreen=args.rescreen,
            on_progress=on_progress,
        )
    except KeyboardInterrupt:
        print("\nScreening cancelled.", file=sys.stderr)
        sys.exit(130)

    print(f"Screened {done} papers ({failed} failed) using model '{args.model}'.")
    if failed:
        print("Re-run `screen` (without --rescreen) later to retry failed papers.")


def cmd_status(args):
    conn = db.connect(args.db)
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    screened = conn.execute(
        "SELECT COUNT(*) FROM screening_results WHERE criteria_file = ? AND error IS NULL",
        (args.criteria,),
    ).fetchone()[0]
    relevant = conn.execute(
        "SELECT COUNT(*) FROM screening_results WHERE criteria_file = ? AND relevant = 1",
        (args.criteria,),
    ).fetchone()[0]
    failed = conn.execute(
        "SELECT COUNT(*) FROM screening_results WHERE criteria_file = ? AND error IS NOT NULL",
        (args.criteria,),
    ).fetchone()[0]
    conn.close()
    print(f"Criteria file:    {args.criteria}")
    print(f"Papers ingested:  {total}")
    print(f"Screened (ok):    {screened}")
    print(f"  -> relevant:    {relevant}")
    print(f"  -> excluded:    {screened - relevant}")
    print(f"Failed/errored:   {failed}")
    print(f"Not yet screened: {total - screened - failed}")


def cmd_export(args):
    n = export_mod.export_csv(args.db, args.out, args.criteria, relevant_only=args.relevant_only)
    print(f"Wrote {n} rows to {args.out}")


def main():
    parser = argparse.ArgumentParser(description="Local-LLM assisted literature review screening")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Load a Scopus CSV or Web of Science Excel export into the database")
    p_ingest.add_argument("file_path")
    p_ingest.add_argument("--db", default=DEFAULT_DB)
    p_ingest.set_defaults(func=cmd_ingest)

    p_screen = sub.add_parser("screen", help="Screen papers with a local Ollama model")
    p_screen.add_argument("--db", default=DEFAULT_DB)
    p_screen.add_argument("--criteria", default="criteria.yaml")
    p_screen.add_argument("--model", default="qwen2.5:14b")
    p_screen.add_argument("--base-url", default="http://localhost:11434")
    p_screen.add_argument("--limit", type=int, default=None, help="Only screen the next N papers")
    p_screen.add_argument("--rescreen", action="store_true", help="Re-screen all papers, not just new/failed ones")
    p_screen.set_defaults(func=cmd_screen)

    p_status = sub.add_parser("status", help="Show ingest/screening progress")
    p_status.add_argument("--db", default=DEFAULT_DB)
    p_status.add_argument("--criteria", default="criteria.yaml")
    p_status.set_defaults(func=cmd_status)

    p_export = sub.add_parser("export", help="Export results to CSV")
    p_export.add_argument("--db", default=DEFAULT_DB)
    p_export.add_argument("--out", default="data/results.csv")
    p_export.add_argument("--criteria", default="criteria.yaml")
    p_export.add_argument("--relevant-only", action="store_true")
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
