# literature-reviewer

This repository shall help you automate and speed up the process of conducting a literature review.

## Abstract/keyword screening with a local LLM

Screens papers from a Scopus CSV export against your inclusion/exclusion
criteria using a local Ollama model. Results are stored in SQLite so you can
resume, re-screen, and export at any time.

### Setup

Requires [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com)
running locally.

```sh
uv sync
ollama pull qwen2.5:14b   # or any other model you have pulled
ollama serve              # if not already running
```

Edit [criteria.yaml](criteria.yaml) with your review's topic and
inclusion/exclusion criteria.

### Usage

```sh
# 1. Load a Scopus CSV export into data/review.db
uv run python src/cli.py ingest "data/your_scopus_export.csv"

# 2. Screen papers not yet screened (safe to interrupt/resume)
uv run python src/cli.py screen --model qwen2.5:14b

# 3. Check progress
uv run python src/cli.py status

# 4. Export title/abstract/decision/reason/themes to CSV for manual review
uv run python src/cli.py export --out data/results.csv
```

Useful flags:

- `screen --limit N` — screen only the next N unscreened papers (good for a
  quick test before committing to a full run)
- `screen --rescreen` — re-screen every paper, e.g. after editing
  `criteria.yaml`
- `screen --model <name>` / `--base-url <url>` — use a different model or a
  non-default Ollama host
- `export --relevant-only` — export only papers the model marked relevant

Papers that fail to screen (e.g. Ollama unreachable, malformed model output)
are recorded with an error and automatically retried on the next `screen`
run.
