"""Offline API/static-asset checks, also run against the installed wheel in CI."""
from functools import partial
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from chive_optimization.data import connect, normalize, summarize
from chive_optimization.viewer import Handler


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.directory = Path(self.folder.name)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=self.directory))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.folder.cleanup()

    def get(self, path):
        with urlopen(self.base + path, timeout=10) as response:
            return response.read(), response.headers

    def test_static_assets_and_empty_dataset(self):
        for path, mime, text in [('/', 'text/html', 'CHIVE'), ('/app.js?v=test', 'javascript', 'loadInvestigation'), ('/style.css?v=test', 'text/css', '.original-toolbar')]:
            body, headers = self.get(path)
            self.assertIn(mime, headers['Content-Type'])
            self.assertIn(text, body.decode())
            self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        body, _ = self.get('/api/datasets')
        self.assertEqual(json.loads(body), [])
        with self.assertRaises(HTTPError) as error:
            self.get('/AGENTS.md')
        self.assertEqual(error.exception.code, 404)

    def test_imported_fixture_can_be_read(self):
        raw = {'prompt_id': 'example', 'question': 'Why?', 'messages': [{'role': 'user', 'content': 'Hello'}], 'completions': ['**Hello** <script>bad()</script>'], 'baseline_grader_verdicts': [True], 'baseline_grader_yes': 1, 'experiment_log': []}
        item = normalize(raw, [], {})
        db = connect(self.directory)
        try:
            with db:
                db.execute('INSERT INTO datasets VALUES (?, ?)', ('test', json.dumps({'id': 'test', 'label': 'Test'})))
                db.execute('INSERT INTO investigations VALUES (?, ?, ?, ?)', ('test', 'example', json.dumps(summarize(item)), json.dumps(item)))
        finally:
            db.close()
        body, _ = self.get('/api/investigations?dataset=test')
        self.assertEqual(json.loads(body)[0]['id'], 'example')
        body, _ = self.get('/api/investigation?dataset=test&id=example')
        html = json.loads(body)['baseline']['responses'][0]['html']
        self.assertIn('<strong>Hello</strong>', html)
        self.assertNotIn('<script>', html)

    def test_port_conflict_explains_how_to_recover(self):
        env = {**os.environ, 'DATA_ROOT': ''}
        result = subprocess.run([sys.executable, '-m', 'chive_optimization.viewer', '--port', str(self.server.server_port), '--data-dir', str(self.directory)], capture_output=True, text=True, timeout=10, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already in use', result.stderr)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
