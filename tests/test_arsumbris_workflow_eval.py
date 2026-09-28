"""Synthetic workflow grader tests; fixtures contain no customer data."""

import copy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/grade-mcp-workflow.py'
spec = importlib.util.spec_from_file_location('workflow_grader', SCRIPT)
grader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grader)


class WorkflowGraderTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.storage = self.home / '.local/share/keller-quotes/drafts'
        self.identifier = '12345678-1234-4123-8123-123456789abc'
        self.corpus = 'a' * 64
        self.sha = 'b' * 64
        self.row = {'quote_no': 'SYN-Q', 'item_no': '1', 'part_no': 'SYN-P', 'quantity': '3',
                    'unit_price': '1.23456', 'source_price_field': 'unit_price',
                    'price_basis': 'customer_quote_pdf', 'status': 'unknown',
                    'extended_price': '3.70', 'quote_date': '2024-01-01', 'letter_date': '2024-01-02',
                    'customer_id': 'SYN-ID', 'customer': 'Synthetic Works', 'rev': 'A',
                    'source_document': 'synthetic/source.pdf', 'source_document_sha256': self.sha}
        self.request = {'case_id': 'synthetic-case', 'order_id': 'SYN-ORDER', 'quote_date': '2025-01-01',
                        'customer': 'Synthetic Works', 'customer_id': 'SYN-ID', 'corpus': self.corpus,
                        'reviewer': 'Casey Example', 'requested_lines': [
                            {'line_id': 'L1', 'quote_no': 'SYN-Q', 'part_no': 'SYN-P', 'quantity': 3, 'uom': 'piece'}],
                        'charges': {'shipping': 1.25, 'tax': 0}}
        self.oracle = {'case_id': 'synthetic-case', 'request': self.request, 'lines': [self.row],
                       'reviewer_identity': {'name': 'Casey Example', 'kind': 'human',
                                             'source': 'synthetic fixture identity'},
                       'expected_total_exact_source': '4.95'}
        order_request = {'order_id': 'SYN-ORDER', 'quote_date': '2025-01-01', 'customer': 'Synthetic Works',
                         'customer_id': 'SYN-ID', 'parts': [
                             {'line_id': 'L1', 'part_no': 'SYN-P', 'quantity': 3, 'drawing_ref': 'A',
                              'pricing': {'method': 'unit_price', 'unit_price': 1.2333, 'reason': 'synthetic proposal'}}],
                         'charges': {'shipping': 1.25, 'tax': 0}}
        order = {'request': order_request, 'order_id': 'SYN-ORDER', 'quote_date': '2025-01-01',
                 'customer': 'Synthetic Works', 'state': 'PRICED_REQUIRES_REVIEW', 'requires_human_review': True,
                 'lines': [{'line_id': 'L1', 'part': {'part_no': 'SYN-P', 'quantity': 3, 'drawing_ref': 'A'},
                            'unit_price': 1.2333, 'extended_price': 3.70, 'pricing_source': 'explicit_unit_price'}],
                 'charges': {'shipping': 1.25, 'tax': 0}, 'additional_charges': [],
                 'subtotal': 3.70, 'priced_subtotal': 3.70, 'total': 4.95, 'blockers': []}
        review = {'state': 'PRICED_REQUIRES_REVIEW', 'requires_human_review': True,
                  'status': 'PENDING_NAMED_HUMAN_REVIEW', 'reviewer': 'Casey Example',
                  'customer_release_authorized': False}
        self.draft = {'draft_id': self.identifier, 'order': order, 'markdown': 'Synthetic internal draft',
                      'review': review, 'state': 'PRICED_REQUIRES_REVIEW', 'requires_human_review': True,
                      'review_status': 'PENDING_NAMED_HUMAN_REVIEW', 'reviewer': 'Casey Example',
                      'total': 4.95, 'blockers': [], 'artifacts': {
                          key: f'quote-draft:{self.identifier}/{file}' for key, file in (
                              ('order_json', 'order.json'), ('order_markdown', 'order.md'),
                              ('review_json', 'review.json'))}}
        self.answer = {'case_id': 'synthetic-case', 'draft': self.draft, 'evidence': [{
            'line_id': 'L1', 'quote_no': 'SYN-Q', 'part_no': 'SYN-P', 'quantity': 3,
            'source_path': 'synthetic/source.pdf', 'pdf_sha256': self.sha, 'source_unit_price': '1.23456',
            'source_printed_extension': '3.70', 'source_quote_date': '2024-01-01', 'rev': 'A',
            'admission_reason': 'Synthetic verified issued price'}],
            'reviewer_handoff': 'Synthetic review pending', 'customer_message': 'Draft pending review',
            'unresolved': ['lead time']}
        self.judge = {'case_id': 'synthetic-case', 'criteria': [
            {'id': f'J{i}', 'verdict': 'pass', 'reason': 'Synthetic check', 'evidence': ['artifact: synthetic']}
            for i in range(1, 6)]}
        self.events = [
            self.event('read_file_pinned', {'path': '.agents/skills/keller-quote-estimator/SKILL.md'},
                       '# keller-quote-estimator\nSynthetic procedure'),
            self.event('keller_polygres', {'action': 'prices', 'corpus': self.corpus, 'quote_no': 'SYN-Q'},
                       {'action': 'prices', 'corpus': self.corpus, 'basis': 'verified issued customer quotation PDF',
                        'prices': [{'row': self.row, 'source_path': self.row['source_document'],
                                    'pdf_sha256': self.sha}]}),
            self.event('keller_quote', {'corpus': self.corpus, 'request': json.dumps(order_request),
                                        'reviewer': 'Casey Example'}, {'content': self.draft})]
        self.persist()

    def event(self, tool, inputs, content):
        return {'startedAt': '2025-01-01T00:00:00Z', 'completedAt': '2025-01-01T00:00:01Z',
                'tool': tool, 'inputs': inputs, 'result': {'content': [
                    {'type': 'text', 'text': content if isinstance(content, str) else json.dumps(content)}]}}

    def persist(self):
        output = self.storage / self.identifier / 'output'
        output.mkdir(parents=True, exist_ok=True)
        (output / 'order.json').write_text(json.dumps(self.draft['order']))
        (output / 'order.md').write_text(self.draft['markdown'])
        (output / 'review.json').write_text(json.dumps(self.draft['review']))

    def hashes(self):
        return {key: sha256(data.encode()).hexdigest() for key, data in (
            ('oracle', json.dumps(self.oracle)), ('answer', json.dumps(self.answer)),
            ('audit', '\n'.join(json.dumps(event) for event in self.events) + '\n'))}

    def grade(self, judge=True, bind=True):
        try:
            snapshot = grader.artifacts(self.draft, self.storage)
        except (ValueError, OSError) as exc:
            snapshot = str(exc)
        expected = self.hashes()
        if judge and bind:
            self.judge['input_sha256'] = expected
        return grader.grade(self.oracle, self.answer, self.events, self.judge if judge else None, snapshot, expected)

    def failure(self, key):
        result = self.grade()
        self.assertFalse(result['criteria'][key]['passed'], result)
        self.assertTrue(result['criteria'][key]['reasons'])
        self.assertFalse(result['all_pass'])
        return result

    def test_complete_synthetic_trace_artifacts_and_judge(self):
        result = self.grade()
        self.assertEqual((result['validation_passed'], result['judge_passed']), (5, 5), result)
        self.assertEqual((result['validation_score'], result['judge_score'], result['combined_score']), (1, 1, 1))
        self.assertTrue(result['all_pass'])
        self.request['requested_lines'][0]['uom'] = 'pieces'
        self.assertTrue(self.grade()['all_pass'])

    def test_wrong_price_and_source(self):
        self.draft['order']['lines'][0]['unit_price'] = 2.00
        self.draft['order']['lines'][0]['extended_price'] = 6.00
        self.persist()
        self.events[-1] = self.event('keller_quote', self.events[-1]['inputs'], {'content': self.draft})
        self.failure('V3')
        self.draft['order']['lines'][0]['unit_price'] = 1.2333
        self.draft['order']['lines'][0]['extended_price'] = 3.70
        self.answer['evidence'][0]['pdf_sha256'] = 'c' * 64
        self.persist()
        self.events[-1] = self.event('keller_quote', self.events[-1]['inputs'], {'content': self.draft})
        self.failure('V5')

    def test_advertised_price_fields_and_equivalent_numeric_formats(self):
        self.answer['evidence'][0]['source_unit_price'] = '1.234560'
        self.answer['evidence'][0]['source_printed_extension'] = '3.700'
        observed = copy.deepcopy(self.row)
        observed['unit_price'] = '1.234560'
        observed['extended_price'] = '3.700'
        observed['quantity'] = '3.0'
        observed.pop('rev')
        self.events[1] = self.event('keller_polygres', self.events[1]['inputs'],
            {'action': 'prices', 'corpus': self.corpus, 'basis': 'verified issued customer quotation PDF',
             'prices': [{'row': observed, 'source_path': self.row['source_document'], 'pdf_sha256': self.sha}]})
        self.assertTrue(self.grade()['all_pass'])
        observed['unit_price'] = '1.23457'
        self.events[1] = self.event('keller_polygres', self.events[1]['inputs'],
            {'action': 'prices', 'corpus': self.corpus, 'basis': 'verified issued customer quotation PDF',
             'prices': [{'row': observed, 'source_path': self.row['source_document'], 'pdf_sha256': self.sha}]})
        self.failure('V5')

    def test_prior_draft_allowed_but_latest_must_match(self):
        previous = copy.deepcopy(self.draft)
        previous['draft_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        self.events.insert(2, self.event('keller_quote', self.events[-1]['inputs'], {'content': previous}))
        self.assertTrue(self.grade()['all_pass'])
        self.events.append(self.events.pop(2))
        self.failure('V1')

    def test_missing_and_mismatched_persisted_artifact(self):
        output = self.storage / self.identifier / 'output'
        (output / 'order.md').unlink()
        self.failure('V1')
        self.persist()
        (output / 'review.json').write_text('{}')
        self.failure('V1')

    def test_false_release(self):
        self.draft['review']['customer_release_authorized'] = True
        self.persist()
        self.events[-1] = self.event('keller_quote', self.events[-1]['inputs'], {'content': self.draft})
        self.failure('V4')

    def test_reviewer_requires_explicit_human_oracle_proof(self):
        self.assertTrue(self.grade()['all_pass'])
        identity = self.oracle.pop('reviewer_identity')
        self.failure('V4')
        self.oracle['reviewer_identity'] = {'name': 'Casey Example', 'kind': 'role',
                                            'source': 'synthetic fixture role'}
        self.failure('V4')
        self.oracle['reviewer_identity'] = {'name': 'Casey Example', 'kind': 'human', 'source': ' '}
        self.failure('V4')
        self.oracle['reviewer_identity'] = identity
        self.assertTrue(self.grade()['all_pass'])
        self.oracle['reviewer_identity']['name'] = 'Other Example'
        self.failure('V4')
        self.oracle['reviewer_identity']['name'] = 'Casey Example'
        self.request['reviewer'] = 'Estimator role'
        self.failure('V4')
        self.request['reviewer'] = 'Casey Example'
        self.draft['reviewer'] = 'Estimator role'
        self.failure('V4')
        self.draft['reviewer'] = 'Casey Example'
        self.draft['review']['reviewer'] = 'Estimator role'
        self.failure('V4')

    def test_missing_tool_and_future_evidence_fail(self):
        self.events = self.events[1:]
        self.failure('V1')
        self.events.insert(0, self.event('read_file_pinned',
                                         {'path': '.agents/skills/keller-quote-estimator/SKILL.md'},
                                         '# keller-quote-estimator\nSynthetic procedure'))
        self.events = [event for event in self.events if event['tool'] != 'keller_quote']
        self.failure('V1')
        self.events.append(self.event('keller_quote', {'corpus': self.corpus,
            'request': json.dumps(self.draft['order']['request']), 'reviewer': 'Casey Example'},
            {'content': self.draft}))
        self.row['quote_date'] = '2026-01-01'
        self.answer['evidence'][0]['source_quote_date'] = '2026-01-01'
        self.events[1] = self.event('keller_polygres', self.events[1]['inputs'],
            {'action': 'prices', 'corpus': self.corpus, 'basis': 'verified issued customer quotation PDF',
             'prices': [{'row': self.row, 'source_path': self.row['source_document'], 'pdf_sha256': self.sha}]})
        self.failure('V5')

    def test_missing_duplicate_and_malformed_judge(self):
        result = self.grade(judge=False)
        self.assertEqual(result['judge_passed'], 0)
        self.assertEqual(result['combined_score'], .5)
        self.assertFalse(result['all_pass'])
        self.judge['criteria'][1]['id'] = 'J1'
        self.assertEqual(self.grade()['judge_passed'], 0)
        self.judge['criteria'][1]['id'] = 'J2'
        self.judge['criteria'][0]['evidence'] = []
        self.assertEqual(self.grade()['judge_passed'], 0)
        self.judge['criteria'][0]['evidence'] = ['artifact: synthetic']
        self.judge['case_id'] = 'unknown'
        self.assertEqual(self.grade()['judge_passed'], 0)

    def test_same_case_cross_attempt_judgments_fail_closed(self):
        self.assertTrue(self.grade()['all_pass'])
        self.assertEqual(grader.grade(self.oracle, self.answer, self.events, self.judge,
                                      grader.artifacts(self.draft, self.storage))['judge_passed'], 0)
        prior_hashes = self.judge['input_sha256'].copy()
        self.answer['reviewer_handoff'] += ' another attempt'
        self.assertEqual(self.grade(bind=False)['judge_passed'], 0)
        self.assertEqual(self.grade(bind=False)['validation_passed'], 5)
        self.answer['reviewer_handoff'] = 'Synthetic review pending'
        self.events.insert(0, {'startedAt': '2025-01-01T00:00:00Z', 'completedAt': '2025-01-01T00:00:01Z',
                               'tool': 'tools/list', 'inputs': {}, 'result': {'tools': [{'name': 'keller_quote'}]}})
        self.assertEqual(self.judge['input_sha256'], prior_hashes)
        self.assertEqual(self.grade(bind=False)['judge_passed'], 0)
        self.judge.pop('input_sha256')
        self.assertEqual(self.grade(bind=False)['judge_passed'], 0)
        self.judge['input_sha256'] = {'oracle': 'not-a-hash', 'answer': prior_hashes['answer'],
                                      'audit': prior_hashes['audit']}
        self.assertEqual(self.grade(bind=False)['judge_passed'], 0)

    def test_missing_lines_and_charges(self):
        self.draft['order']['lines'] = []
        self.persist()
        self.events[-1] = self.event('keller_quote', self.events[-1]['inputs'], {'content': self.draft})
        self.failure('V2')
        self.draft['order']['lines'] = [{'line_id': 'L1', 'part': {'part_no': 'SYN-P', 'quantity': 3},
                                         'unit_price': 1.2333, 'extended_price': 3.70}]
        self.draft['order']['charges']['shipping'] = 0
        self.persist()
        self.events[-1] = self.event('keller_quote', self.events[-1]['inputs'], {'content': self.draft})
        self.failure('V2')
        self.answer['evidence'] = []
        self.failure('V5')

    def test_audit_parsing_file_text_and_malformed_result(self):
        audit = self.home / 'audit.jsonl'
        audit.write_text('\n'.join(json.dumps(event) for event in self.events) + '\n')
        self.assertEqual(len(grader.trace(audit)), 3)
        tools = {'startedAt': '2025-01-01T00:00:00Z', 'completedAt': '2025-01-01T00:00:01Z',
                 'tool': 'tools/list', 'inputs': {}, 'result': {'tools': [{'name': 'keller_quote'}]}}
        audit.write_text(json.dumps(tools) + '\n' + audit.read_text())
        self.assertEqual(len(grader.trace(audit)), 4)
        graph = [self.event('au_type', {'name': 'OrderRequest'}, None),
                 self.event('au_instances_of', {'type': 'synthetic'}, [])]
        audit.write_text(''.join(json.dumps(event) + '\n' for event in graph) + audit.read_text())
        self.assertEqual(len(grader.trace(audit)), 6)
        self.events[:0] = graph
        self.assertTrue(self.grade()['all_pass'])
        for bad in ('not json', json.dumps({'tool': 'keller_quote'}),
                    json.dumps(self.event('keller_quote', {}, 'not json')),
                    json.dumps(self.event('au_type', {}, 'not json')),
                    json.dumps(self.event('keller_quote', {}, None)),
                    json.dumps(self.event('keller_polygres', {}, [])),
                    json.dumps(self.event('keller_sources', {}, 0))):
            audit.write_text(bad + '\n')
            with self.assertRaises(ValueError):
                grader.trace(audit)

    def test_cli_fails_closed_on_bad_answer_and_trace(self):
        paths = {name: self.home / f'{name}.json' for name in ('oracle', 'answer', 'judge')}
        for name, data in (('oracle', self.oracle), ('answer', self.answer)):
            paths[name].write_text(json.dumps(data))
        audit = self.home / 'audit.jsonl'
        audit.write_text('\n'.join(json.dumps(e) for e in self.events) + '\n')
        self.judge['input_sha256'] = {name: sha256(path.read_bytes()).hexdigest() for name, path in
                                      (('oracle', paths['oracle']), ('answer', paths['answer']), ('audit', audit))}
        paths['judge'].write_text(json.dumps(self.judge))
        out = self.home / 'report.json'
        command = [sys.executable, str(SCRIPT), '--oracle', str(paths['oracle']), '--answer', str(paths['answer']),
                   '--audit', str(audit), '--judge', str(paths['judge']), '--out', str(out)]
        env = {**os.environ, 'HOME': str(self.home)}
        subprocess.run(command, check=True, env=env)
        self.assertTrue(json.loads(out.read_text())['all_pass'])
        paths['answer'].write_text('{')
        subprocess.run(command, check=True, env=env)
        result = json.loads(out.read_text())
        self.assertEqual(result['validation_passed'], 0)
        self.assertFalse(result['all_pass'])
        paths['answer'].write_text(json.dumps(self.answer))
        audit.write_text('{')
        subprocess.run(command, check=True, env=env)
        self.assertEqual(json.loads(out.read_text())['validation_passed'], 0)

    def test_cli_hashes_raw_bytes_even_when_case_and_json_are_unchanged(self):
        oracle, answer, audit, judge, out = (self.home / name for name in
                                              ('oracle.json', 'answer.json', 'audit.jsonl', 'judge.json', 'out.json'))
        oracle.write_text(json.dumps(self.oracle))
        answer.write_text(json.dumps(self.answer))
        audit.write_text('\n'.join(json.dumps(e) for e in self.events) + '\n')
        self.judge['input_sha256'] = {key: sha256(path.read_bytes()).hexdigest() for key, path in
                                      (('oracle', oracle), ('answer', answer), ('audit', audit))}
        judge.write_text(json.dumps(self.judge))
        command = [sys.executable, str(SCRIPT), '--oracle', str(oracle), '--answer', str(answer),
                   '--audit', str(audit), '--judge', str(judge), '--out', str(out)]
        env = {**os.environ, 'HOME': str(self.home)}
        def invoke():
            subprocess.run(command, check=True, env=env)
            return json.loads(out.read_text())
        self.assertTrue(invoke()['all_pass'])
        answer.write_text(answer.read_text() + ' ')
        result = invoke()
        self.assertEqual(result['case_id'], self.oracle['case_id'])
        self.assertEqual((result['validation_passed'], result['judge_passed']), (5, 0))
        answer.write_text(answer.read_text().rstrip())
        audit.write_text(audit.read_text().replace('\n', ' \n', 1))
        result = invoke()
        self.assertEqual((result['validation_passed'], result['judge_passed']), (5, 0))
        audit.write_text(audit.read_text().replace(' \n', '\n', 1))
        self.assertTrue(invoke()['all_pass'])
        self.judge.pop('input_sha256')
        judge.write_text(json.dumps(self.judge))
        self.assertEqual(invoke()['judge_passed'], 0)


if __name__ == '__main__':
    unittest.main()
