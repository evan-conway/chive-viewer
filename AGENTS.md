# CHIVE viewer: coding-agent guide

This repository is a local, read-only viewer for published CHIVE data. It does not run models, evaluations, or training. No GPU or credentials are required.

## Fresh clone

1. Read README.md. Use `uv` for Python package management.
2. Run `uv sync --locked` (Python 3.12+; no Node build needed).
3. For a small real-data preview, run `uv run --locked chive-download --data-dir ./data --limit 10`. A fresh clone has no data. A full import replaces this preview when rerun without `--limit`.
4. Run `uv run --locked chive-viewer --data-dir ./data` and open http://127.0.0.1:8765.
5. Run `uv run --locked -m unittest discover -s tests -v`. Tests use local synthetic fixtures and need no downloaded data.

## Layout

- `src/chive_optimization/data.py`: dataset registry, normalization, cache paths.
- `src/chive_optimization/download.py`: source-revision-pinned streaming importer.
- `src/chive_optimization/viewer.py`: loopback HTTP server, Markdown, diffs.
- `src/chive_optimization/static/`: plain JavaScript/CSS/HTML, shipped in the wheel.
- `tests/`: offline unit and HTTP/CLI tests.
- `data/`: ignored SQLite cache. Never commit data, local results, or secrets.

## Preserve these semantics

- An investigation contains the original condition and counterfactual conditions. Samples across conditions are independent, not matched pairs.
- Grader counts/rates are the recorded measurements. Do not infer missing verdicts, change denominators to match missing transcripts, or use narrative summaries as measurements.
- Missing canonical claims are distinct from false claims. Qwen3-32B has investigations but no released eval claims.
- Import all saved responses and edits for each included investigation. Dataset replacement must remain atomic and browsing must remain available during imports.
- Treat all dataset text as untrusted. Escape HTML, keep Markdown HTML disabled, preserve the CSP, and do not expose arbitrary filesystem paths or bind publicly.
- Original is selected on investigation entry unless a URL specifies an edit. Preserve investigation caching/preloading, explicit deep links, and reading preferences.
- Keep UI changes focused. Make room for reading; keep secondary controls collapsed.

## Verification and local processes

- Run Python tests for data/backend changes; use `node --check src/chive_optimization/static/app.js` for JavaScript changes when Node is available.
- Run `uv build` for packaging changes; ensure HTML, CSS, and JavaScript are included in the wheel.
- Browser-check UI changes when browser tooling is available. Use a small fixture or existing data; do not require an all-dataset download for tests.
- Static changes need a browser refresh; Python server changes need a restart. Do not stop someone else's server. Start your own test server on another port (or `--port 0`) and stop only processes you created.
- Use `--data-dir` explicitly in scripts and tests. Otherwise paths resolve from `DATA_ROOT/chive-viewer`, then `./data`; no machine-specific paths or `.env` are required.
