"""Synthetic sealed attempts for operator-only MCP trajectory reconstruction."""

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/analyze-mcp-trajectory.py'
IDS = [f'{group}{i}' for group in ('V', 'J') for i in range(1, 6)]


class TrajectoryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.chmod(0o700)
        self.output = self.root / 'analysis.json'
        self.baseline = self.attempt('baseline')
        self.current = self.attempt('current')

    def write(self, path, content):
        path.write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode())
        path.chmod(0o600)
        return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}

    def attempt(self, name, flags=None, session=False):
        directory = self.root / name
        directory.mkdir(mode=0o700)
        draft = {'draft_id': 'draft-1', 'state': 'PRICED_REQUIRES_REVIEW',
                 'order': {'lines': [{'unit_price': '12.00'}]}}
        events = [{'startedAt': '2026-01-01T00:00:00Z', 'completedAt': '2026-01-01T00:00:01Z',
                   'tool': 'keller_quote', 'inputs': {'request': '{}'},
                   'result': {'content': [{'type': 'text', 'text': json.dumps(draft)}]}}]
        flags = flags or {key: True for key in IDS}
        grade = {'population': 'blinded-historical-quote-workflow', 'case_id': 'case-a',
                 'criteria': {key: {'passed': flags[key],
                  'reasons': [] if flags[key] else [f'{key} unsupported']} for key in IDS},
                 'validation_passed': sum(flags[key] for key in IDS[:5]),
                 'judge_passed': sum(flags[key] for key in IDS[5:]),
                 'all_pass': all(flags.values()), 'price_diagnostics': {'turns': []}}
        artifacts = {
            'request': self.write(directory / 'request.json', {'case_id': 'case-a', 'order': 'fixed'}),
            'criteria': self.write(directory / 'criteria.json', {'case_id': 'case-a', 'rubric': IDS}),
            'answer': self.write(directory / 'answer.json', {'case_id': 'case-a', 'draft': draft}),
            'audit': self.write(directory / 'audit.jsonl', ('\n'.join(json.dumps(e) for e in events) + '\n').encode()),
            'grade': self.write(directory / 'grade.json', grade),
        }
        if session:
            artifacts['session'] = self.write(directory / 'session.json', {'observations': []})
        manifest = {'schema_version': 1, 'run_id': name, 'case_id': 'case-a', 'artifacts': artifacts,
                    'execution': {'checkout': 'recorded-commit', 'model': 'recorded-model', 'skill': 'recorded-skill'},
                    'validity': {'status': 'valid', 'reason': 'sealed fixture'}}
        return self.write(directory / 'manifest.json', manifest)['path']

    def edit_manifest(self, filename, mutation):
        path = Path(filename)
        manifest = json.loads(path.read_text())
        mutation(manifest)
        self.write(path, manifest)

    def edit_artifact(self, manifest_path, key, mutation):
        manifest = json.loads(Path(manifest_path).read_text())
        ref = manifest['artifacts'][key]
        path = Path(ref['path'])
        value = json.loads(path.read_text()) if key != 'audit' else [json.loads(x) for x in path.read_text().splitlines()]
        mutation(value)
        ref['sha256'] = self.write(path, ('\n'.join(json.dumps(e) for e in value) + '\n').encode()
                                   if key == 'audit' else value)['sha256']
        self.write(Path(manifest_path), manifest)

    def run_cli(self, baseline=True, flag=True, out=None):
        args = [sys.executable, str(SCRIPT), '--manifest', self.current, '--out', str(out or self.output)]
        if baseline:
            args.extend(['--baseline', self.baseline])
        if flag:
            args.append('--fail-on-regression')
        return subprocess.run(args, text=True, capture_output=True)

    def report(self):
        return json.loads(self.output.read_text())

    def test_same_total_hidden_loss_and_gain(self):
        self.edit_artifact(self.baseline, 'grade', lambda g: g['criteria']['J1'].update(passed=False, reasons=['old']))
        self.edit_artifact(self.baseline, 'grade', lambda g: g.update(judge_passed=4, all_pass=False))
        self.edit_artifact(self.current, 'grade', lambda g: g['criteria']['J2'].update(passed=False, reasons=['new']))
        self.edit_artifact(self.current, 'grade', lambda g: g.update(judge_passed=4, all_pass=False))
        run = self.run_cli()
        self.assertEqual(run.returncode, 1, run.stderr)
        comparison = self.report()['comparison']
        self.assertEqual(comparison['status'], 'regression')
        self.assertEqual([x['criterion'] for x in comparison['losses']], ['J2'])
        self.assertEqual([x['criterion'] for x in comparison['gains']], ['J1'])
        self.assertEqual(comparison['losses'][0]['after_reasons'], ['new'])
        self.assertEqual(self.report()['attempt']['original_grade']['judge_passed'], 4)

    def test_ordinary_loss_gain_and_execution_difference(self):
        self.edit_artifact(self.baseline, 'grade', lambda g: g['criteria']['V1'].update(passed=False, reasons=['before']))
        self.edit_artifact(self.baseline, 'grade', lambda g: g.update(validation_passed=4, all_pass=False))
        self.edit_artifact(self.current, 'grade', lambda g: g['criteria']['J5'].update(passed=False, reasons=['after']))
        self.edit_artifact(self.current, 'grade', lambda g: g.update(judge_passed=4, all_pass=False))
        self.edit_manifest(self.current, lambda m: m['execution'].update(checkout='different'))
        self.assertEqual(self.run_cli().returncode, 1)
        report = self.report()['comparison']
        self.assertEqual((report['losses'][0]['criterion'], report['gains'][0]['criterion']), ('J5', 'V1'))
        self.assertEqual(report['execution_differences']['checkout'], {'baseline': 'recorded-commit', 'current': 'different'})

    def test_changed_case_request_and_rubric_each_prevent_comparison(self):
        for key in ('case', 'request', 'criteria'):
            with self.subTest(key=key):
                if key == 'case':
                    self.edit_manifest(self.current, lambda m: m.update(case_id='other'))
                else:
                    self.edit_artifact(self.current, key, lambda value: value.update(note=key))
                self.assertEqual(self.run_cli().returncode, 1)
                self.assertEqual(self.report()['comparison']['status'], 'not_comparable')
                self.output.unlink()
                self.current = self.attempt('reset-' + key)

    def test_invalid_unknown_and_bad_grade_cannot_pass(self):
        for status in ('invalid', 'unknown'):
            with self.subTest(status=status):
                self.edit_manifest(self.current, lambda m: m['validity'].update(status=status))
                self.assertEqual(self.run_cli().returncode, 1)
                self.assertEqual(self.report()['comparison']['status'], 'not_comparable')
                self.output.unlink()
        for mutation in (lambda g: g['criteria'].pop('J5'),
                         lambda g: g['criteria']['J5'].update(passed='true'),
                         lambda g: g['criteria'].update(J6={'passed': True, 'reasons': []}),
                         lambda g: g.update(all_pass=False),
                         lambda g: g.update(all_pass=False, validation_passed=4),
                         lambda g: g['criteria']['J1'].update(passed=False, reasons=['unsupported'])):
            with self.subTest(mutation=mutation):
                self.current = self.attempt('grade-' + str(len(list(self.root.iterdir()))))
                self.edit_artifact(self.current, 'grade', mutation)
                self.assertEqual(self.run_cli().returncode, 1)
                self.assertEqual(self.report()['attempt']['original_grade']['status'], 'malformed')
                self.assertEqual(self.report()['comparison']['status'], 'not_comparable')
                self.output.unlink()
        self.current = self.attempt('contradiction')
        self.edit_artifact(self.current, 'grade', lambda g: g.update(all_pass=True, judge_passed=4,
                          criteria={**g['criteria'], 'J1': {'passed': False, 'reasons': ['failed']}}))
        self.assertEqual(self.run_cli().returncode, 1)
        self.assertEqual(self.report()['attempt']['original_grade']['status'], 'malformed')
        self.output.unlink()
        self.current = self.attempt('unknown-execution')
        self.edit_manifest(self.current, lambda m: m['execution'].update(model='unknown'))
        self.assertEqual(self.run_cli().returncode, 1)
        self.assertEqual(self.report()['comparison']['status'], 'not_comparable')

    def test_duplicate_grade_json_key_retains_observations(self):
        manifest = json.loads(Path(self.current).read_text())
        grade = Path(manifest['artifacts']['grade']['path'])
        raw = grade.read_text().replace('"J5":', '"J5": {"passed": true, "reasons": []}, "J5":')
        manifest['artifacts']['grade']['sha256'] = self.write(grade, raw.encode())['sha256']
        self.write(Path(self.current), manifest)
        self.assertEqual(self.run_cli().returncode, 1)
        self.assertEqual(self.report()['attempt']['original_grade']['status'], 'malformed')
        self.assertEqual(self.report()['attempt']['trajectory'][0]['status'], 'success')

    def test_hash_mismatch_fails_without_output(self):
        manifest = json.loads(Path(self.current).read_text())
        manifest['artifacts']['audit']['sha256'] = '0' * 64
        self.write(Path(self.current), manifest)
        run = self.run_cli()
        self.assertEqual(run.returncode, 2)
        self.assertFalse(self.output.exists())
        self.assertNotIn('request', run.stderr)

    def test_null_error_unpriced_malformed_and_repeated_final(self):
        draft = json.loads(Path(json.loads(Path(self.current).read_text())['artifacts']['answer']['path']).read_text())['draft']
        def append(events):
            base = {k: events[0][k] for k in ('startedAt', 'completedAt', 'tool', 'inputs')}
            events[:0] = [{**base, 'result': None, 'error': 'denied', 'error_code': 'EVALUATION_SCOPE_DENIED'},
                         {**base, 'result': None},
                         {**base, 'result': {'content': [{'type': 'text', 'text': json.dumps({**draft, 'state': 'HELD', 'order': {'lines': [{'unit_price': None}]}})}]}},
                         {**base, 'result': {'content': [{'type': 'text', 'text': '{bad'}]}}]
            events.append(events[-1].copy())
        self.edit_artifact(self.current, 'audit', append)
        self.assertEqual(self.run_cli().returncode, 1)
        report = self.report()['attempt']
        self.assertEqual([e['status'] for e in report['trajectory']],
                         ['error', 'unknown', 'unpriced', 'malformed', 'success', 'success'])
        self.assertEqual(report['trajectory'][0]['error_code'], 'EVALUATION_SCOPE_DENIED')
        self.assertEqual(report['trajectory'][0]['started_at'], '2026-01-01T00:00:00Z')
        self.assertTrue(report['final_answer']['ambiguous'])
        self.assertIsNone(report['final_answer']['linked_audit_ordinal'])
        self.assertEqual(self.report()['comparison']['status'], 'not_comparable')

    def test_no_session_and_private_output_permissions(self):
        run = self.run_cli(baseline=False, flag=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.report()['attempt']['session'], {'status': 'unavailable'})
        self.assertEqual(self.report()['attempt']['price_diagnostics']['json_pointer'], '/price_diagnostics')
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.run_cli(baseline=False, flag=False).returncode, 2)
        self.output.unlink()
        alias = self.root / 'alias.json'
        alias.symlink_to(self.current)
        self.assertEqual(self.run_cli(baseline=False, flag=False, out=alias).returncode, 2)
        self.root.chmod(0o755)
        self.assertEqual(self.run_cli(baseline=False, flag=False).returncode, 2)

    def test_input_alias_session_and_cli_exit(self):
        self.edit_manifest(self.current, lambda m: m['artifacts'].update(session=m['artifacts']['answer']))
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertFalse(self.output.exists())
        self.current = self.attempt('with-session', session=True)
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.report()['attempt']['session']['status'], 'snapshot_recorded')
        self.assertEqual(self.report()['comparison']['status'], 'no_observed_criterion_loss')
        self.output.unlink()
        self.assertNotEqual(self.run_cli(baseline=False, flag=True).returncode, 0)
        self.assertFalse(self.output.exists())

    def test_symlink_artifact_rejected(self):
        manifest = json.loads(Path(self.current).read_text())
        alias = self.root / 'linked-audit.jsonl'
        alias.symlink_to(manifest['artifacts']['audit']['path'])
        manifest['artifacts']['audit']['path'] = str(alias)
        self.write(Path(self.current), manifest)
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertFalse(self.output.exists())

    def test_empty_and_only_unknown_audit_are_not_comparable(self):
        for lines in (b'', b'{"startedAt":"2026-01-01T00:00:00Z","tool":"keller_quote","inputs":{},"result":null}\n'):
            with self.subTest(lines=lines):
                manifest = json.loads(Path(self.current).read_text())
                ref = manifest['artifacts']['audit']
                ref['sha256'] = self.write(Path(ref['path']), lines)['sha256']
                self.write(Path(self.current), manifest)
                self.assertEqual(self.run_cli().returncode, 1)
                self.assertFalse(self.report()['attempt']['audit_readable'])
                self.assertEqual(self.report()['comparison']['status'], 'not_comparable')
                self.output.unlink()

    def test_nonquote_content_and_duplicate_event_payload_keys(self):
        for result in ({'content': []}, {'content': [{'type': 'text'}]},
                       {'content': [{'type': 'text', 'text': 42}]},
                       {'content': [{'type': 'text', 'text': '{"action":"prices","action":"search"}'}]}):
            with self.subTest(result=result):
                self.edit_artifact(self.current, 'audit', lambda events: events[0].update(tool='keller_polygres', result=result))
                self.assertEqual(self.run_cli().returncode, 1)
                self.assertEqual(self.report()['attempt']['trajectory'][0]['status'], 'malformed')
                self.output.unlink()
        for raw in (
            b'{"tool":"keller_quote","tool":"keller_quote","inputs":{},"result":null}\n',
            b'{"tool":"keller_quote","inputs":{},"result":{"content":[{"type":"text","text":"{\\"draft_id\\":\\"one\\",\\"draft_id\\":\\"two\\"}"}]}}\n',
        ):
            with self.subTest(raw=raw):
                manifest = json.loads(Path(self.current).read_text())
                ref = manifest['artifacts']['audit']
                ref['sha256'] = self.write(Path(ref['path']), raw)['sha256']
                self.write(Path(self.current), manifest)
                self.assertEqual(self.run_cli().returncode, 1)
                self.assertEqual(self.report()['attempt']['trajectory'][0]['status'], 'malformed')
                self.assertEqual(self.report()['comparison']['status'], 'not_comparable')
                self.output.unlink()

    def test_grade_population_missing_or_mixed(self):
        self.edit_artifact(self.current, 'grade', lambda g: g.pop('population'))
        self.assertEqual(self.run_cli().returncode, 1)
        self.assertEqual(self.report()['attempt']['original_grade']['status'], 'malformed')
        self.output.unlink()
        self.current = self.attempt('mixed-population')
        self.edit_artifact(self.current, 'grade', lambda g: g.update(population='exact-reissue'))
        self.assertEqual(self.run_cli().returncode, 1)
        self.assertEqual(self.report()['comparison']['status'], 'not_comparable')
        self.assertIn('grade populations differ', self.report()['comparison']['reasons'])

    def test_quote_state_classification_and_observed_action(self):
        cases = (
            ('UNRECOGNIZED', [{'unit_price': '12.00'}], 'malformed'),
            (None, [{'unit_price': '12.00'}], 'malformed'),
            ('BLOCKED', [{'unit_price': '12.00'}], 'held'),
            ('HELD', [{'unit_price': '12.00'}], 'held'),
            ('BLOCKED', [{'unit_price': None}], 'unpriced'),
            ('PRICED_REQUIRES_REVIEW', [], 'malformed'),
            ('PRICED_REQUIRES_REVIEW', None, 'malformed'),
        )
        for index, (state, lines, expected) in enumerate(cases):
            with self.subTest(state=state, lines=lines):
                self.current = self.attempt(f'state-{index}')
                def change(events):
                    events[0]['inputs']['action'] = 'prices'
                    draft = json.loads(events[0]['result']['content'][0]['text'])
                    if state is None:
                        draft.pop('state')
                    else:
                        draft['state'] = state
                    if lines is None:
                        draft['order'].pop('lines')
                    else:
                        draft['order']['lines'] = lines
                    events[0]['result']['content'][0]['text'] = json.dumps(draft)
                self.edit_artifact(self.current, 'audit', change)
                self.assertEqual(self.run_cli().returncode, int(expected == 'malformed'))
                observation = self.report()['attempt']['trajectory'][0]
                self.assertEqual(observation['status'], expected)
                self.assertEqual(observation['action'], 'prices')
                self.assertEqual(self.report()['comparison']['status'],
                                 'not_comparable' if expected == 'malformed' else 'no_observed_criterion_loss')
                self.output.unlink()


if __name__ == '__main__':
    unittest.main()
