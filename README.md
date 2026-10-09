# CHIVE investigation viewer

A local web app for reading [CHIVE](https://huggingface.co/datasets/adamkarvonen/chive-data) investigations: browse the original conversation, compare counterfactual prompt edits, and read individual model responses alongside measured behavior changes.

Built to help researchers inspect examples before writing idealized explanations or tool responses. The viewer makes **no model calls** and needs **no GPU, API keys, Node.js, or frontend build step**. It serves a local SQLite cache and a plain HTML/CSS/JavaScript interface.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git, then run:

```bash
git clone https://github.com/evan-conway/chive-viewer.git
cd chive-viewer
uv sync --locked
uv run --locked chive-download --data-dir ./data
uv run --locked chive-viewer --data-dir ./data
```

Open **http://127.0.0.1:8765**. Stop the server with Ctrl+C. `uv` installs the project's Python version and dependencies as needed; Python 3.12 or newer is supported.

The default download imports Qwen3-8B WildChat: 649 investigations, including all their saved responses and counterfactuals. It streams about 1.5 GB from Hugging Face and stores about 0.5 GB locally, so allow a few minutes and an internet connection. Dataset files are **not included in the Git repository**. Once imported, browsing works offline.

For a smaller first download, replace the download command with:

```bash
uv run --locked chive-download --data-dir ./data --limit 10
```

Run it again without `--limit` to replace the preview with the complete dataset. The viewer opens with an empty-state setup message if you start it before downloading data.

## Other models

List dataset IDs:

```bash
uv run --locked chive-download --list-datasets
```

Import a specific dataset, or all nine supported evaluation runs:

```bash
uv run --locked chive-download --data-dir ./data --dataset qwen3p5_397b_wildchat_thinking_eval
uv run --locked chive-download --data-dir ./data --all-datasets --skip-existing
```

Refresh the browser after an import to update the dataset selector. Importing all nine runs stores approximately **5.4 GB** and streams about **13 GB** of source investigations. `--skip-existing` keeps complete matching imports and retries incomplete/preview datasets; it does not check for newer upstream revisions. Omit it to refresh a dataset from the source.

| Dataset ID | Target and prompt source |
| --- | --- |
| `qwen3_8b_wildchat_eval` | Qwen3-8B · WildChat |
| `qwen3_8b_petri_eval` | Qwen3-8B · Petri |
| `qwen3_8b_wildchat_thinking_eval` | Qwen3-8B · WildChat · thinking |
| `qwen3p5_397b_wildchat_eval` | Qwen3.5-397B-A17B · WildChat |
| `qwen3p5_397b_petri_eval` | Qwen3.5-397B-A17B · Petri |
| `qwen3p5_397b_wildchat_thinking_eval` | Qwen3.5-397B-A17B · WildChat · thinking |
| `gemma3_27b_it_wildchat_eval` | Gemma 3 27B · WildChat |
| `llama3_1_8b_wildchat_eval` | Llama 3.1 8B · WildChat |
| `qwen3_32b_wildchat_eval` | Qwen3-32B · WildChat · investigations only |

For runs with canonical evaluation claims, the importer retains every investigation referenced by `eval_set_conc3_n2000.jsonl`, including its other experiments. `--all-investigations` also includes investigations outside that set. Qwen3-32B has no published claim bank or canonical eval set, so its import includes all 1,441 investigations and labels the dataset accordingly. Training runs are not imported.

In CHIVE, targets run without thinking unless the dataset is marked “thinking”; those runs use a 1,024-token thinking budget. WildChat evaluation runs share the same source prompt pool, but their retained investigations can differ. See the [upstream dataset card](https://huggingface.co/datasets/adamkarvonen/chive-data) for provenance and experiment settings.

## Reading workflow

- Select an investigation. **Original** opens by default; explicit links to counterfactuals preserve that selection.
- Select a counterfactual to compare its prompt and sampled responses with the original. Response samples across the columns are independent, **not paired**.
- Open **Show details** for the behavior grading question. **Statistics** shows original/edited rates and counts. “pp” means percentage points: 60% to 40% is a change of −20 pp.
- Read **Prompt & conversation** above the sampled response, or collapse it to focus on responses. Its collapsed state persists across edits within the investigation.
- **Reading options** provides verdict filtering, response-text search, font size, and raw text. **Prompt edit** provides a semantic word diff and full conversations. **Eval claims** shows benchmark statements and labels.
- Collapse the investigation explorer for more reading space. Investigations are paginated in groups of 10; the browser preloads the current page and nearby pages, including complete responses.
- **Shortlist** saves bookmarks in this browser's local storage. It is not a server-side annotation store. Copy the URL to reference a dataset/investigation/edit; another person can open its path and hash on their own running viewer after importing the same dataset.

Behavior rates come from recorded grader results. Missing labels and inconsistent counts are flagged; source denominators are preserved. The generated investigator explanation is collapsed below the edited response views.

This is an unblinded data exploration tool: outcomes and labels are visible. Predictor-agent integration, blinded evaluation, and a handwritten-summary editor are not implemented.

## Configuration and troubleshooting

Both commands accept `--data-dir` and `--help`. Cache directory precedence is:

1. Explicit `--data-dir`.
2. `$DATA_ROOT/chive-viewer`, if `DATA_ROOT` is set.
3. `./data` in the current working directory.

No `.env` or direnv setup is required. Use the same directory for downloading and serving. Keep this disposable cache on local disk for good SQLite performance.

- **Port already in use:** an earlier viewer may still be running. Open its URL, or use `uv run --locked chive-viewer --data-dir ./data --port 8766`.
- **No datasets shown:** check the printed data directory, run the downloader against that directory, then refresh.
- **Interrupted/failed import:** rerun the command. Each dataset import is atomic: the previous version survives failure, and other completed datasets are retained. `--all-datasets --skip-existing` resumes a multi-dataset import. A partly downloaded dataset restarts from the beginning.
- **New data not visible:** refresh the page to clear the in-memory response cache and reload dataset metadata.

### Running on a remote machine

Run the viewer on that machine, then forward its port from your laptop:

```bash
ssh -N -L 8765:127.0.0.1:8765 user@your-server
```

Open http://127.0.0.1:8765 locally. VSCode Remote SSH port forwarding also works. For a server that survives terminal disconnects, run the viewer in a tmux session you own.

The server intentionally binds only to loopback. It is a local research tool without authentication, not a public web hosting service. Sharing this repository lets collaborators run their own copy.

## Development and agent setup

Read [AGENTS.md](AGENTS.md) for a concise setup and maintenance guide.

```bash
uv sync --locked
uv run --locked -m unittest discover -s tests -v
uv build
```

If Node.js is available, also run `node --check src/chive_optimization/static/app.js`. Node is only used for this optional syntax check, not to run the app. An optional [GitHub Actions workflow](docs/github-actions-checks.yml) checks Python tests on Linux and Windows, JavaScript syntax, and the installed wheel including its static assets. To enable it, copy it to `.github/workflows/checks.yml` and push using credentials authorized to manage workflows.

- `src/chive_optimization/data.py`: normalization, dataset registry, SQLite storage.
- `src/chive_optimization/download.py`: streaming imports from a recorded Hugging Face revision; no model inference.
- `src/chive_optimization/viewer.py`: read-only HTTP API, safe Markdown rendering, conversation-aware diffs using diff-match-patch semantic word cleanup.
- `src/chive_optimization/static/`: buildless frontend. Static assets are included in the Python package.
- `tests/`: offline fixtures; tests do not download public datasets or require credentials.

Existing `uv run -m chive_optimization.download` and `uv run -m chive_optimization.viewer` commands also work. SQLite WAL mode allows browsing during imports. Dataset content is escaped, Markdown raw HTML is disabled, and the server uses a restrictive content security policy.

## License and attribution

Viewer code is licensed under [MIT](LICENSE). **That license does not apply to the datasets.** Data is downloaded separately from [adamkarvonen/chive-data](https://huggingface.co/datasets/adamkarvonen/chive-data), which documents its mixed upstream terms and provenance.

CHIVE investigation pipeline: [adamkarvonen/chive](https://github.com/adamkarvonen/chive). WildChat-derived material originates from [AI2/allenai WildChat](https://huggingface.co/datasets/allenai/WildChat-4.8M). Llama-derived data is Built with Llama; Gemma-derived data carries Google's Gemma terms. Refer to the upstream dataset card for the terms applying to each component.
