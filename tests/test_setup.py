"""Offline checks for fresh-clone defaults and import CLI behavior."""
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chive_optimization.data import DATASETS, connect, data_directory
from chive_optimization.download import main


class SetupTests(unittest.TestCase):
    def test_cache_directory_precedence(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict(os.environ, {}, clear=True), patch('pathlib.Path.cwd', return_value=root):
                self.assertEqual(data_directory(), root / 'data')
                with patch.dict(os.environ, {'DATA_ROOT': str(root / 'shared')}):
                    self.assertEqual(data_directory(), root / 'shared' / 'chive-viewer')
                    self.assertEqual(data_directory(str(root / 'explicit')), root / 'explicit')

    def test_list_datasets_is_offline(self):
        with patch('sys.argv', ['chive-download', '--list-datasets']), patch('sys.stdout', new_callable=io.StringIO) as output, patch('chive_optimization.download.open_url') as network:
            main()
        network.assert_not_called()
        self.assertEqual(len(output.getvalue().splitlines()), len(DATASETS))

    def test_resume_skips_complete_imports_but_replaces_previews(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            db = connect(directory)
            try:
                with db:
                    db.executemany('INSERT INTO datasets VALUES (?, ?)', [
                        ('qwen3_8b_wildchat_eval', json.dumps({'limited': False, 'scope': 'Canonical evaluation investigations'})),
                        ('gemma3_27b_it_wildchat_eval', json.dumps({'limited': True})),
                    ])
            finally:
                db.close()
            with patch('sys.argv', ['chive-download', '--data-dir', folder, '--all-datasets', '--skip-existing']), patch('chive_optimization.download.download') as importer:
                main()
            imported = {call.args[1] for call in importer.call_args_list}
            self.assertEqual(imported, set(DATASETS) - {'qwen3_8b_wildchat_eval'})
            with patch('sys.argv', ['chive-download', '--data-dir', folder, '--dataset', 'qwen3_8b_wildchat_eval', '--skip-existing', '--all-investigations']), patch('chive_optimization.download.download') as importer:
                main()
            importer.assert_called_once()


if __name__ == '__main__':
    unittest.main()
