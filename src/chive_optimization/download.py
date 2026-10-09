"""Stream public source records directly into a local SQLite cache; no model calls."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import sqlite3
import urllib.error
import urllib.request

from .data import DATASETS, INVESTIGATION_ONLY_DATASETS, REPOSITORY, connect, data_directory, normalize, summarize


def open_url(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "chive-local-viewer/0.1"}), timeout=120)


def rows(url):
    with open_url(url) as response:
        for line in response:
            if line.strip():
                yield json.loads(line)


def download(directory, dataset, limit=0, all_investigations=False):
    with open_url(f"https://huggingface.co/api/datasets/{REPOSITORY}") as response:
        revision = json.load(response)["sha"]
    base = f"https://huggingface.co/datasets/{REPOSITORY}/resolve/{revision}/datasets/{dataset}"
    claims = defaultdict(list)
    has_eval = dataset not in INVESTIGATION_ONLY_DATASETS
    if has_eval:
        print(f"Reading canonical evaluation claims for {DATASETS[dataset]}…", flush=True)
        for claim in rows(f"{base}/eval_set_conc3_n2000.jsonl"):
            # Preserve the claim and its provenance, without duplicating full transcripts.
            claims[claim["prompt_id"]].append({k: v for k, v in claim.items() if k not in {"messages", "transcript", "chosen_completion"}})
        metadata = {row["prompt_id"]: row for row in rows(f"{base}/mechanism_concreteness.jsonl")}
    else:
        print(f"Importing {DATASETS[dataset]} (no published evaluation claims)…", flush=True)
        metadata = {}
        all_investigations = True
    count = 0
    ids = set()
    db = connect(directory)
    try:
        with db:
            db.execute("DELETE FROM investigations WHERE dataset = ?", (dataset,))
            print("Streaming investigations (keeping every response and counterfactual for each included investigation)…", flush=True)
            for raw in rows(f"{base}/investigations.jsonl"):
                prompt_id = raw["prompt_id"]
                if not all_investigations and prompt_id not in claims:
                    continue
                item = normalize(raw, claims.get(prompt_id, []), metadata.get(prompt_id, {}))
                db.execute("INSERT INTO investigations VALUES (?, ?, ?, ?)",
                           (dataset, prompt_id, json.dumps(summarize(item)), json.dumps(item)))
                ids.add(prompt_id)
                count += 1
                if count % 25 == 0:
                    print(f"  {count} investigations indexed", flush=True)
                if limit and count >= limit:
                    break
            missing = set(claims) - ids
            if not limit and missing:
                raise ValueError(f"Missing {len(missing)} canonical evaluation investigations; import rolled back.")
            info = {
                "id": dataset, "label": DATASETS[dataset], "count": count,
                "scope": "Investigations only; no published evaluation claims" if not has_eval else "All investigations" if all_investigations else "Canonical evaluation investigations",
                "limited": bool(limit and (missing or all_investigations)), "canonical_total": len(claims) if has_eval else None,
                "has_eval_claims": has_eval,
                "revision": revision, "repository": REPOSITORY,
                "source_url": f"https://huggingface.co/datasets/{REPOSITORY}/tree/{revision}/datasets/{dataset}",
                "imported_at": datetime.now(timezone.utc).isoformat(),
            }
            db.execute("INSERT OR REPLACE INTO datasets VALUES (?, ?)", (dataset, json.dumps(info)))
    finally:
        db.close()
    print(f"Ready: {count} investigations in {directory / 'viewer.sqlite3'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--dataset", choices=DATASETS, help="Dataset to import; defaults to qwen3_8b_wildchat_eval")
    selection.add_argument("--all-datasets", action="store_true", help="Import all supported evaluation datasets sequentially")
    parser.add_argument("--list-datasets", action="store_true", help="List supported dataset IDs and exit")
    parser.add_argument("--skip-existing", action="store_true", help="Skip complete imports already present (useful when resuming --all-datasets)")
    parser.add_argument("--data-dir", help="Cache directory; defaults to DATA_ROOT/chive-viewer if set, otherwise ./data")
    parser.add_argument("--limit", type=int, default=0, help="Optional investigation limit; 0 imports the complete selected set")
    parser.add_argument("--all-investigations", action="store_true", help="Also include investigations outside the canonical eval set")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.list_datasets:
        for dataset, label in DATASETS.items():
            print(f"{dataset}\t{label}")
        return
    directory = data_directory(args.data_dir)
    datasets = list(DATASETS) if args.all_datasets else [args.dataset or "qwen3_8b_wildchat_eval"]
    existing = {}
    if args.skip_existing and (directory / "viewer.sqlite3").exists():
        with sqlite3.connect((directory / "viewer.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
            existing = {row[0]: json.loads(row[1]) for row in db.execute("SELECT id, metadata FROM datasets")}
    try:
        for dataset in datasets:
            previous = existing.get(dataset, {})
            scope_matches = not args.all_investigations or previous.get("scope") == "All investigations" or dataset in INVESTIGATION_ONLY_DATASETS
            if previous and not previous.get("limited", True) and scope_matches:
                print(f"Already imported: {DATASETS[dataset]}", flush=True)
                continue
            download(directory, dataset, args.limit, args.all_investigations)
    except (urllib.error.URLError, TimeoutError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Import failed: {error}\nCompleted datasets are preserved. Retry the command; use --skip-existing to resume a multi-dataset import.\n")


if __name__ == "__main__":
    main()
