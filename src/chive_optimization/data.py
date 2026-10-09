"""Small, disk-backed index of the published CHIVE investigations."""

import json
import os
import sqlite3
from pathlib import Path

REPOSITORY = "adamkarvonen/chive-data"
DATASETS = {
    "qwen3_8b_wildchat_eval": "Qwen3-8B · WildChat",
    "gemma3_27b_it_wildchat_eval": "Gemma 3 27B · WildChat",
    "qwen3_8b_petri_eval": "Qwen3-8B · Petri",
    "qwen3p5_397b_wildchat_eval": "Qwen3.5-397B · WildChat",
    "qwen3p5_397b_petri_eval": "Qwen3.5-397B · Petri",
    "qwen3_8b_wildchat_thinking_eval": "Qwen3-8B · WildChat · thinking",
    "qwen3p5_397b_wildchat_thinking_eval": "Qwen3.5-397B · WildChat · thinking",
    "llama3_1_8b_wildchat_eval": "Llama 3.1 8B · WildChat",
    "qwen3_32b_wildchat_eval": "Qwen3-32B · WildChat · investigations only",
}

# This released run has transcripts but no claim bank or concreteness labels.
INVESTIGATION_ONLY_DATASETS = {"qwen3_32b_wildchat_eval"}


def data_directory(value=None):
    if value:
        return Path(value).expanduser().resolve()
    root = os.environ.get("DATA_ROOT")
    return Path(root).expanduser().resolve() / "chive-viewer" if root else Path.cwd() / "data"


def connect(directory):
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "viewer.sqlite3")
    db.row_factory = sqlite3.Row
    # Imports remain atomic without blocking the viewer's read connections.
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS investigations (
            dataset TEXT NOT NULL, id TEXT NOT NULL, summary TEXT NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY (dataset, id)
        );
    """)
    return db


def measurement(completions, verdicts, yes, n=None):
    """Keep missing labels unknown; never infer a no from an absent verdict."""
    n = len(completions) if n is None else n
    verdicts = verdicts or []
    labels = [v if isinstance(v, bool) else None for v in verdicts]
    warnings = []
    if yes is None and len(labels) == n and all(v is not None for v in labels):
        yes = sum(labels)
    if not isinstance(n, int) or n <= 0:
        n = 0
    if not isinstance(yes, int) or isinstance(yes, bool) or not 0 <= yes <= n:
        yes = None
    if len(completions) != n:
        warnings.append(f"Only {len(completions)} of {n} sampled responses are present.")
    if len(labels) != len(completions) or any(v is None for v in labels):
        warnings.append("Some individual grader labels are unavailable.")
    if len(labels) == n and all(v is not None for v in labels) and yes is not None and sum(labels) != yes:
        warnings.append("Stored grader count disagrees with the individual labels.")
    return {
        "yes": yes, "n": n, "rate": yes / n if yes is not None and n else None,
        "warnings": warnings,
        "responses": [{"index": i, "text": text, "verdict": labels[i] if i < len(labels) else None}
                      for i, text in enumerate(completions)],
    }


def normalize(raw, claims, meta):
    findings = raw.get("structured_findings") or {}
    summaries = {str(s["experiment_number"]): s for s in findings.get("experiment_summaries", [])}
    baseline = measurement(raw.get("completions", []), raw.get("baseline_grader_verdicts"), raw.get("baseline_grader_yes"))
    baseline["messages"] = raw.get("messages") or [{"role": "user", "content": raw.get("user_message", "")}]
    experiments = []
    for entry in raw.get("experiment_log", []):
        num = entry["exp_num"]
        summary = summaries.get(str(num), {})
        experiment = measurement(entry.get("completions", []), entry.get("grader_verdicts"), entry.get("grader_yes"), entry.get("n"))
        experiment.update({
            "number": num, "summary": summary.get("summary", "No experiment summary provided."),
            "is_key": summary.get("is_key", False),
            "messages": entry.get("messages") or [{"role": "user", "content": entry.get("prompt", "")}],
            "claims": [c for c in claims if num in c.get("experiment_numbers", [])],
            "delta": (experiment["rate"] - baseline["rate"]) * 100
                     if experiment["rate"] is not None and baseline["rate"] is not None else None,
        })
        experiments.append(experiment)
    result = {
        "id": raw["prompt_id"], "question": raw.get("question", raw["prompt_id"]),
        "behavior": raw.get("behavior_summary", ""), "classifier": raw.get("classifier_question", ""),
        "baseline": baseline, "experiments": experiments,
        "explanation": findings.get("structured_answer") or raw.get("investigation_report", ""),
        "commentary": findings.get("commentary", ""),
        "categories": meta.get("categories", []), "concreteness": meta.get("mechanism_concreteness"),
        "verification": max((c.get("verification_score", 0) for c in claims), default=None),
        "claim_count": len(claims),
    }
    return result


def summarize(item):
    return {
        **{k: item[k] for k in ("id", "question", "behavior", "categories", "concreteness", "verification", "claim_count")},
        "experiment_count": len(item["experiments"]),
        "max_effect": max((abs(e["delta"]) for e in item["experiments"] if e["delta"] is not None), default=None),
        "baseline_rate": item["baseline"]["rate"],
    }
