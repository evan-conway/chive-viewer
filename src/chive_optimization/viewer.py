"""Serve a read-only CHIVE data viewer on loopback."""

import argparse
import difflib
import errno
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

from diff_match_patch import diff_match_patch
from markdown_it import MarkdownIt

from .data import data_directory

STATIC = Path(__file__).with_name("static")


def message_text(messages):
    return "\n\n".join(f"[{m.get('role', 'unknown').upper()}]\n{m.get('content', '')}" for m in messages)


def semantic_word_diff(before, after):
    """Use diff-match-patch's documented word mode and semantic cleanup.

    https://github.com/google/diff-match-patch/wiki/Line-or-Word-Diffs
    Token encoding only sets granularity; the library computes and cleans the diff.
    """
    vocabulary = [""]
    word_ids = {}

    def encode(text):
        encoded = []
        for word in re.findall(r"\s+|\S+", text):
            if word not in word_ids:
                word_ids[word] = len(vocabulary)
                vocabulary.append(word)
            encoded.append(chr(word_ids[word]))
        return "".join(encoded)

    differ = diff_match_patch()
    changes = differ.diff_main(encode(before), encode(after), checklines=False)
    differ.diff_charsToLines(changes, vocabulary)
    differ.diff_cleanupSemantic(changes)
    return changes


def prompt_diff(before, after):
    """Respect message boundaries; use diff-match-patch semantic cleanup for text."""
    # Ignore spacing for turn alignment; preserve every byte in the output.
    before_tokens = [re.findall(r"\w+|[^\w\s]", m.get("content", "")) for m in before]
    after_tokens = [re.findall(r"\w+|[^\w\s]", m.get("content", "")) for m in after]
    n, m = len(before), len(after)
    scores = [[0.0] * (m + 1) for _ in range(n + 1)]
    actions = {}
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            candidates = [(scores[i + 1][j], "removed"), (scores[i][j + 1], "added")]
            if before[i].get("role") == after[j].get("role"):
                similarity = difflib.SequenceMatcher(
                    None, before_tokens[i], after_tokens[j], autojunk=False
                ).ratio()
                # Unrelated turns are clearer as whole removals/additions.
                if similarity >= 0.4:
                    candidates.insert(0, (similarity + scores[i + 1][j + 1], "paired"))
            scores[i][j], actions[i, j] = max(candidates, key=lambda c: c[0])

    def turn_text(messages, index):
        suffix = "\n\n" if index < len(messages) - 1 else ""
        return message_text([messages[index]]) + suffix

    operation_types = {diff_match_patch.DIFF_EQUAL: "same", diff_match_patch.DIFF_DELETE: "removed", diff_match_patch.DIFF_INSERT: "added"}
    parts = []
    i = j = 0
    while i < n or j < m:
        action = "added" if i == n else "removed" if j == m else actions[i, j]
        if action == "removed":
            parts.append({"type": "removed", "text": turn_text(before, i)})
            i += 1
        elif action == "added":
            parts.append({"type": "added", "text": turn_text(after, j)})
            j += 1
        else:
            changes = semantic_word_diff(turn_text(before, i), turn_text(after, j))
            parts.extend({"type": operation_types[operation], "text": text}
                         for operation, text in changes)
            i += 1
            j += 1
    return parts


def enrich(item):
    # HTML input is disabled; markdown-it also rejects unsafe link protocols.
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    for condition in [item["baseline"], *item["experiments"]]:
        for response in condition["responses"]:
            response["html"] = md.render(response["text"])
    for experiment in item["experiments"]:
        experiment["diff"] = prompt_diff(item["baseline"]["messages"], experiment["messages"])
    item["explanation_html"] = md.render(item["explanation"])
    return item


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, directory, **kwargs):
        self.directory = directory
        super().__init__(*args, **kwargs)

    def send(self, value, status=200, mime="application/json; charset=utf-8"):
        body = value if isinstance(value, bytes) else json.dumps(value, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'none'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path in {"/", "/app.js", "/style.css"}:
            path = STATIC / ("index.html" if url.path == "/" else url.path[1:])
            return self.send(path.read_bytes(), mime=(mimetypes.guess_type(path.name)[0] or "text/plain") + "; charset=utf-8")
        if not url.path.startswith("/api/"):
            return self.send({"error": "Not found"}, 404)
        db_path = self.directory / "viewer.sqlite3"
        if not db_path.exists():
            if url.path == "/api/datasets":
                return self.send([])
            return self.send({"error": "No data imported yet. See the README for the download command."}, 404)
        db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
        try:
            if url.path == "/api/datasets":
                return self.send([json.loads(row[0]) for row in db.execute("SELECT metadata FROM datasets ORDER BY id")])
            dataset = query.get("dataset", [""])[0]
            if url.path == "/api/investigations":
                return self.send([json.loads(row[0]) for row in db.execute("SELECT summary FROM investigations WHERE dataset=? ORDER BY id", (dataset,))])
            if url.path == "/api/investigation":
                prompt_id = query.get("id", [""])[0]
                row = db.execute("SELECT data FROM investigations WHERE dataset=? AND id=?", (dataset, prompt_id)).fetchone()
                if row:
                    return self.send(enrich(json.loads(row[0])))
                return self.send({"error": "Investigation not found"}, 404)
            return self.send({"error": "Not found"}, 404)
        except (sqlite3.Error, ValueError, KeyError) as error:
            self.log_error("%s", error)
            return self.send({"error": "Could not read this dataset. Check the server log."}, 500)
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", help="Cache directory; defaults to DATA_ROOT/chive-viewer if set, otherwise ./data")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    directory = data_directory(args.data_dir)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=directory))
    except OSError as error:
        if error.errno == errno.EADDRINUSE or getattr(error, "winerror", None) == 10048:
            parser.exit(1, f"Port {args.port} is already in use. An existing viewer may still be running; open http://127.0.0.1:{args.port} or choose another --port.\n")
        raise
    print(f"CHIVE viewer: http://127.0.0.1:{server.server_port}\nData directory: {directory}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
