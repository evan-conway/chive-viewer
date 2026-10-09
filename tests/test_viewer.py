import io
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chive_optimization.data import connect, measurement, normalize
from chive_optimization.download import download
from chive_optimization.viewer import enrich, message_text, prompt_diff, semantic_word_diff


def fixture():
    return {
        'prompt_id': 'prompt_test', 'question': 'Why does it refuse?',
        'messages': [{'role': 'user', 'content': 'Original request'}],
        'completions': ['No', 'No', 'Yes'],
        'baseline_grader_verdicts': [True, True, False], 'baseline_grader_yes': 2,
        'classifier_question': 'Does the response refuse?',
        'structured_findings': {'experiment_summaries': [
            {'experiment_number': 9, 'summary': 'Changed the framing', 'is_key': True},
            {'experiment_number': 2, 'summary': 'Added context'},
        ]},
        'experiment_log': [{'exp_num': 2, 'n': 4, 'grader_yes': 1,
                            'grader_verdicts': [False, True, False], 'completions': ['Yes', 'No', 'Yes'],
                            'messages': [{'role': 'user', 'content': 'Edited request'}]}],
    }


class MeasurementTests(unittest.TestCase):
    def test_missing_labels_stay_unknown(self):
        value = measurement(['a', 'b'], [True], None)
        self.assertIsNone(value['rate'])
        self.assertIsNone(value['responses'][1]['verdict'])

    def test_complete_labels_can_supply_missing_count(self):
        self.assertEqual(measurement(['a', 'b'], [True, False], None)['rate'], .5)

    def test_missing_responses_do_not_change_recorded_denominator(self):
        value = measurement(['a', 'b'], [True, False], 1, 3)
        self.assertEqual(value['rate'], 1 / 3)
        self.assertEqual(len(value['responses']), 2)
        self.assertTrue(value['warnings'])

    def test_conflicting_counts_are_flagged(self):
        value = measurement(['a', 'b'], [True, True], 1)
        self.assertEqual(value['rate'], .5)
        self.assertIn('disagrees', value['warnings'][0])

    def test_normalization_joins_by_experiment_number_and_uses_measured_rates(self):
        item = normalize(fixture(), [{'experiment_numbers': [2], 'verification_score': 9}], {})
        exp = item['experiments'][0]
        self.assertEqual(exp['summary'], 'Added context')
        self.assertAlmostEqual(exp['delta'], (1/4 - 2/3)*100)
        self.assertEqual(len(exp['claims']), 1)


class PresentationTests(unittest.TestCase):
    def test_removed_history_does_not_match_words_inside_the_assistant_turn(self):
        fragment = 'The most overpowered, hyper powerful, supernatural Leo, Aries, Gemini in all realities.'
        before = [
            {'role': 'user', 'content': 'Do I need a comma in all realities?'},
            {'role': 'assistant', 'content': 'This list is grammatically correct. No comma is needed in all realities.'},
            {'role': 'user', 'content': 'and what about this ' + fragment},
        ]
        after = [{'role': 'user', 'content': 'Is this grammatically correct? ' + fragment}]
        diff = prompt_diff(before, after)
        self.assertEqual(diff[0], {'type': 'removed', 'text': message_text(before[:1]) + '\n\n'})
        self.assertEqual(diff[1], {'type': 'removed', 'text': message_text(before[1:2]) + '\n\n'})
        self.assertIn(fragment, ''.join(p['text'] for p in diff if p['type'] == 'same'))
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'added'), message_text(before))
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'removed'), message_text(after))

    def test_identical_text_with_a_different_role_is_a_whole_turn_change(self):
        before = [{'role': 'system', 'content': 'Follow these instructions.'}]
        after = [{'role': 'user', 'content': 'Follow these instructions.'}]
        self.assertFalse(any(p['type'] == 'same' for p in prompt_diff(before, after)))

    def test_small_edit_preserves_shared_prefix_and_suffix(self):
        prefix = 'red green blue ' * 80
        suffix = 'one two three ' * 80
        before = [{'role': 'user', 'content': prefix + 'cat ' + suffix}]
        after = [{'role': 'user', 'content': prefix + 'dog ' + suffix}]
        diff = prompt_diff(before, after)
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] == 'removed'), 'cat')
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] == 'added'), 'dog')

    def test_only_changed_lines_are_replaced(self):
        before = [{'role': 'user', 'content': 'Keep this introduction.\n\nThe powerful Leo, Aries, Gemini.\n\nKeep this ending.'}]
        after = [{'role': 'user', 'content': 'Keep this introduction.\n\nThe experienced engineers, developers, architects.\n\nKeep this ending.'}]
        diff = prompt_diff(before, after)
        # The library can preserve shared punctuation outside the changed block.
        self.assertEqual(len([p for p in diff if p['type'] == 'removed']), 1)
        self.assertEqual(len([p for p in diff if p['type'] == 'added']), 1)
        shared = ''.join(p['text'] for p in diff if p['type'] == 'same')
        self.assertIn('Keep this introduction.\n\nThe ', shared)
        self.assertIn('\n\nKeep this ending.', shared)
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'added'), message_text(before))
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'removed'), message_text(after))

    def test_shared_suffix_survives_trailing_newline_change(self):
        body = 'The most overpowered, hyper powerful, supernatural Leo in all realities.'
        before = [{'role': 'user', 'content': 'and what about this ' + body + '\n\n'}]
        after = [{'role': 'user', 'content': 'Can you check the grammar on this? ' + body}]
        diff = prompt_diff(before, after)
        self.assertIn(body, ''.join(p['text'] for p in diff if p['type'] == 'same'))
        self.assertEqual([p['text'] for p in diff if p['type'] == 'removed' and p['text'].strip()], ['and what about this'])
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'added'), message_text(before))
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'removed'), message_text(after))

    def test_many_substitutions_stay_in_one_readable_block(self):
        before = [{'role': 'user', 'content': 'Intro. The powerful Leo, and Aries, in all realities. End.'}]
        after = [{'role': 'user', 'content': 'Intro. The skilled engineers, and developers, in all departments. End.'}]
        diff = prompt_diff(before, after)
        self.assertEqual(len([p for p in diff if p['type'] == 'removed']), 1)
        self.assertEqual(len([p for p in diff if p['type'] == 'added']), 1)
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'added'), message_text(before))
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'removed'), message_text(after))

    def test_semantic_cleanup_removes_coincidental_matches(self):
        self.assertEqual(semantic_word_diff('mouse', 'sofas'), [(-1, 'mouse'), (1, 'sofas')])

    def test_word_encoding_preserves_unicode_and_whitespace(self):
        before = '雪\t猫\n\n🙂 café\u2028fin'
        after = '雪\t犬\n🙂 café\u2028fin!'
        changes = semantic_word_diff(before, after)
        self.assertEqual(''.join(text for op, text in changes if op != 1), before)
        self.assertEqual(''.join(text for op, text in changes if op != -1), after)

    def test_inserted_and_empty_conversations_preserve_text(self):
        turns = [{'role': 'user', 'content': 'Hello!'}, {'role': 'assistant', 'content': 'Hi.'}]
        for before, after in [(turns, []), ([], turns), ([], []), (turns[:1], turns)]:
            diff = prompt_diff(before, after)
            self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'added'), message_text(before))
            self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'removed'), message_text(after))

    def test_diff_preserves_full_multiturn_prompts(self):
        before = [{'role': 'system', 'content': 'Keep  spacing\nline'}, {'role': 'user', 'content': 'old text'}]
        after = [{'role': 'user', 'content': 'new text\n\n雪'}]
        diff = prompt_diff(before, after)
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'added'), message_text(before))
        self.assertEqual(''.join(p['text'] for p in diff if p['type'] != 'removed'), message_text(after))

    def test_dataset_html_cannot_execute(self):
        raw = fixture()
        raw['completions'][0] = '<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n**bold**'
        item = enrich(normalize(raw, [], {}))
        html = item['baseline']['responses'][0]['html']
        self.assertNotIn('<script>', html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn('<strong>bold</strong>', html)


class ImportTests(unittest.TestCase):
    def test_investigation_only_run_does_not_require_unreleased_claim_files(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch('chive_optimization.download.open_url', return_value=io.BytesIO(b'{"sha":"test"}')), patch('chive_optimization.download.rows', return_value=iter([fixture()])) as source:
                download(directory, 'qwen3_32b_wildchat_eval')
            self.assertEqual(source.call_count, 1)
            self.assertTrue(source.call_args.args[0].endswith('/investigations.jsonl'))
            with closing(connect(directory)) as db, db:
                info = json.loads(db.execute('SELECT metadata FROM datasets').fetchone()[0])
                item = json.loads(db.execute('SELECT data FROM investigations').fetchone()[0])
            self.assertFalse(info['has_eval_claims'])
            self.assertIsNone(info['canonical_total'])
            self.assertEqual(info['count'], 1)
            self.assertEqual(item['claim_count'], 0)
            self.assertEqual(len(item['baseline']['responses']), 3)
            self.assertEqual(len(item['experiments']), 1)

    def test_viewer_can_read_during_import(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            with connect(directory) as writer:
                writer.execute('INSERT INTO datasets VALUES (?, ?)', ('existing', '{}'))
            try:
                writer.execute('INSERT INTO datasets VALUES (?, ?)', ('new', '{}'))
                with closing(sqlite3.connect((directory / 'viewer.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=0)) as reader:
                    self.assertEqual(reader.execute('SELECT id FROM datasets').fetchall(), [('existing',)])
                writer.rollback()
            finally:
                writer.close()

    def test_failed_import_preserves_previous_dataset(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            with closing(connect(directory)) as db, db:
                db.execute('INSERT INTO datasets VALUES (?, ?)', ('qwen3_8b_wildchat_eval', '{"previous":true}'))
                db.execute('INSERT INTO investigations VALUES (?, ?, ?, ?)', ('qwen3_8b_wildchat_eval', 'old', '{}', '{}'))

            def source(url):
                if 'eval_set' in url:
                    yield {'prompt_id': 'prompt_test', 'experiment_numbers': [2]}
                    yield {'prompt_id': 'missing', 'experiment_numbers': [2]}
                elif 'mechanism' in url:
                    return
                else:
                    yield fixture()

            with patch('chive_optimization.download.open_url', return_value=io.BytesIO(b'{"sha":"test"}')), patch('chive_optimization.download.rows', side_effect=source):
                with self.assertRaisesRegex(ValueError, 'Missing 1'):
                    download(directory, 'qwen3_8b_wildchat_eval')
            with closing(connect(directory)) as db, db:
                self.assertEqual(db.execute('SELECT id FROM investigations').fetchone()[0], 'old')
                self.assertTrue(json.loads(db.execute('SELECT metadata FROM datasets').fetchone()[0])['previous'])


if __name__ == '__main__':
    unittest.main()
