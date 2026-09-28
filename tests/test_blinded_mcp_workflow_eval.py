"""Synthetic, private-fixture checks for the separately blinded workflow grader."""

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
SCRIPT = ROOT / 'scripts/grade-blinded-mcp-workflow.py'
spec = importlib.util.spec_from_file_location('blinded_grader', SCRIPT)
grader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grader)


class BlindedWorkflowTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.home.chmod(0o700)
        self.scope_path = self.home / 'scope.json'
        self.storage = self.home / '.local/share/keller-quotes/drafts'
        self.uuid = '12345678-1234-4123-8123-123456789abc'
        self.corpus = 'a' * 64
        self.row = {'quote_no': 'PRIOR', 'item_no': '1', 'quantity': '3', 'unit_price': '10.00000',
                    'extended_price': '30.00', 'quote_date': '2023-01-01', 'letter_date': '2023-01-02',
                    'date_stamp': '', 'part_no': 'SYN-P', 'customer_id': 'SYN-ID',
                    'source_price_field': 'PRICE', 'price_basis': 'customer_quote_pdf', 'status': 'unknown',
                    'source_path': 'prior.pdf', 'pdf_sha256': 'b' * 64, 'transcript_sha256': 'c' * 64}
        self.request = {'case_id': 'synthetic-blind', 'order_id': 'SYN-ORDER', 'quote_date': '2024-01-01',
                        'customer': 'Synthetic Works', 'customer_id': 'SYN-ID', 'corpus': self.corpus,
                        'reviewer': 'Casey Example', 'charges': {'shipping': 2, 'tax': 1},
                        'requested_lines': [{'line_id': 'L1', 'part_no': 'SYN-P', 'description': 'Synthetic piece',
                                             'quantity': 3, 'uom': 'pieces', 'revision': 'A', 'notes': ''}]}
        self.scope = {'schema_version': 1, 'case_id': 'synthetic-blind', 'corpus': self.corpus,
                      'quote_date': '2024-01-01', 'excluded_quote_nos': ['TARGET'],
                      'request': {k: self.request[k] for k in ('order_id', 'quote_date', 'customer', 'customer_id', 'reviewer', 'charges')},
                      'eligible_prices': [self.row], 'allowed_files': [str((ROOT / '.agents/skills/keller-quote-estimator/SKILL.md').resolve())]}
        self.scope['request']['parts'] = [{'line_id': 'L1', 'part_no': 'SYN-P', 'quantity': 3}]
        self.oracle = {'schema_version': 1, 'population': 'blinded-historical-quote-workflow',
                       'case_id': 'synthetic-blind', 'request': self.request,
                       'reviewer_identity': {'name': 'Casey Example', 'kind': 'human', 'source': 'synthetic roster'},
                       'targets': [{'line_id': 'L1', 'quote_no': 'TARGET', 'item_no': '9', 'quantity': 3,
                                    'unit_price': '11.00000', 'extended_price': '33.00',
                                    'source_document': 'target.pdf', 'source_document_sha256': 'd' * 64}],
                       'scope': {}}
        order_request = {k: self.request[k] for k in ('order_id', 'quote_date', 'customer', 'customer_id', 'charges')}
        order_request['parts'] = [{'line_id': 'L1', 'part_no': 'SYN-P', 'quantity': 3, 'drawing_ref': 'A',
                                   'pricing': {'method': 'unit_price', 'unit_price': 10.5,
                                               'reason': 'synthetic comparable proposal'}}]
        order = {'request': order_request, 'order_id': 'SYN-ORDER', 'quote_date': '2024-01-01',
                 'customer': 'Synthetic Works', 'state': 'PRICED_REQUIRES_REVIEW', 'requires_human_review': True,
                 'lines': [{'line_id': 'L1', 'part': {'part_no': 'SYN-P', 'quantity': 3, 'drawing_ref': 'A'},
                            'unit_price': 10.5, 'extended_price': 31.5, 'analogs': [],
                            'pricing_source': 'explicit_unit_price'}],
                 'charges': {'shipping': 2, 'tax': 1}, 'additional_charges': [],
                 'subtotal': 31.5, 'priced_subtotal': 31.5, 'total': 34.5, 'blockers': []}
        review = {'state': 'PRICED_REQUIRES_REVIEW', 'requires_human_review': True,
                  'status': 'PENDING_NAMED_HUMAN_REVIEW', 'reviewer': 'Casey Example',
                  'customer_release_authorized': False}
        self.draft = {'draft_id': self.uuid, 'order': order, 'markdown': 'Synthetic internal draft',
                      'review': review, 'state': 'PRICED_REQUIRES_REVIEW', 'requires_human_review': True,
                      'review_status': 'PENDING_NAMED_HUMAN_REVIEW', 'reviewer': 'Casey Example',
                      'total': 34.5, 'blockers': [], 'artifacts': {
                          k: f'quote-draft:{self.uuid}/{v}' for k, v in
                          [('order_json', 'order.json'), ('order_markdown', 'order.md'), ('review_json', 'review.json')]}}
        self.answer = {'case_id': 'synthetic-blind', 'draft': self.draft, 'evidence': [self.citation(self.row)],
                       'pricing_decisions': [{'line_id': 'L1', 'method': 'analog-adjusted',
                                              'derivation': 'Synthetic prior adjusted for review',
                                              'uncertainties': ['current costs unknown'], 'proposed_unit_price': 10.5}],
                       'reviewer_handoff': 'Review evidence and approve before release',
                       'customer_message': 'Pending-review draft; no delivery promise', 'unresolved': ['lead time']}
        self.judge = {'case_id': 'synthetic-blind', 'criteria': [
            {'id': f'J{i}', 'verdict': 'pass', 'reason': 'Synthetic check', 'evidence': ['synthetic trace']}
            for i in range(1, 6)]}
        self.events = [
            self.event('read_file_pinned', {'file_path': self.scope['allowed_files'][0]}, '# keller-quote-estimator\nSynthetic'),
            self.event('keller_polygres', {'action': 'prices', 'corpus': self.corpus},
                       {'action': 'prices', 'corpus': self.corpus,
                        'basis': 'verified issued customer quotation PDF', 'outcome': 'unknown',
                        'prices': [self.price(self.row)]}),
            self.event('keller_quote', {'corpus': self.corpus, 'reviewer': 'Casey Example',
                                        'request': json.dumps(order_request)}, {'content': self.draft})]
        self.freeze()
        self.persist()

    def freeze(self):
        self.scope_path.write_text(json.dumps(self.scope))
        self.scope_path.chmod(0o600)
        self.oracle['scope'] = {'path': str(self.scope_path), 'sha256': sha256(self.scope_path.read_bytes()).hexdigest()}
        for event in self.events:
            event['evaluation_scope_sha256'] = self.oracle['scope']['sha256']

    def price(self, row):
        return {'row': {k: v for k, v in row.items() if k not in
                        ('source_path', 'pdf_sha256', 'transcript_sha256', 'date_stamp')},
                'source_path': row['source_path'], 'pdf_sha256': row['pdf_sha256'],
                'transcript_sha256': row['transcript_sha256']}

    def citation(self, row):
        return {'line_id': 'L1', 'quote_no': row['quote_no'], 'item_no': row['item_no'],
                'part_no': row['part_no'], 'quantity': 3, 'source_path': row['source_path'],
                'pdf_sha256': row['pdf_sha256'], 'source_unit_price': row['unit_price'],
                'source_printed_extension': row['extended_price'], 'source_quote_date': row['quote_date'],
                'rev': 'A', 'admission_reason': 'Prior verified issued price'}

    def event(self, tool, inputs, content):
        return {'startedAt': '2024-01-01T00:00:00Z', 'completedAt': '2024-01-01T00:00:01Z',
                'tool': tool, 'inputs': inputs, 'result': {'content': [
                    {'type': 'text', 'text': content if isinstance(content, str) else json.dumps(content)}]}}

    def persist(self):
        output = self.storage / self.uuid / 'output'
        output.mkdir(parents=True, exist_ok=True)
        (output / 'order.json').write_text(json.dumps(self.draft['order']))
        (output / 'order.md').write_text(self.draft['markdown'])
        (output / 'review.json').write_text(json.dumps(self.draft['review']))

    def sync_quote(self):
        self.persist()
        self.events[-1] = self.event('keller_quote', self.events[-1]['inputs'], {'content': self.draft})
        self.events[-1]['evaluation_scope_sha256'] = self.oracle['scope']['sha256']

    def grade(self, bind=True, judged=True):
        try:
            snapshot = grader.helpers.artifacts(self.answer['draft'], self.storage)
        except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
            snapshot = str(exc)
        hashes = {k: sha256(v.encode()).hexdigest() for k, v in
                  [('oracle', json.dumps(self.oracle)), ('answer', json.dumps(self.answer)),
                   ('audit', '\n'.join(json.dumps(x) for x in self.events) + '\n')]}
        if bind:
            self.judge['input_sha256'] = hashes
        return grader.grade(self.oracle, self.answer, self.events, self.judge if judged else None, snapshot, hashes)

    def fails(self, key):
        result = self.grade()
        self.assertFalse(result['criteria'][key]['passed'], result)
        self.assertFalse(result['all_pass'])

    def test_positive_and_blind_prediction_differs_from_printed_target(self):
        result = self.grade()
        self.assertEqual((result['validation_passed'], result['judge_passed']), (5, 5), result)
        self.assertTrue(result['all_pass'])
        self.assertNotEqual(self.draft['order']['lines'][0]['extended_price'], 33)

    def test_canonical_skill_requires_actual_file_path_input(self):
        self.events[0]['inputs'] = {'path': self.scope['allowed_files'][0]}
        self.fails('V1')
        self.fails('V5')

    def test_false_release_and_missing_human_proof(self):
        self.draft['review']['customer_release_authorized'] = True
        self.sync_quote()
        self.fails('V4')
        self.draft['review']['customer_release_authorized'] = False
        self.oracle['reviewer_identity']['kind'] = 'role'
        self.sync_quote()
        self.fails('V4')

    def test_nonempty_matching_blockers_and_nonfinite_total(self):
        self.draft['blockers'] = ['awaiting review']
        self.draft['order']['blockers'] = ['awaiting review']
        self.sync_quote()
        self.fails('V4')
        self.draft['blockers'] = []
        self.draft['order']['blockers'] = []
        self.draft['order']['total'] = float('nan')
        self.draft['total'] = float('nan')
        self.sync_quote()
        self.fails('V4')

    def test_wrong_price_and_within_guard_bad_extension(self):
        self.draft['order']['lines'][0].update(unit_price=15, extended_price=45)
        self.draft['order'].update(subtotal=45, priced_subtotal=45, total=48)
        self.draft['total'] = 48
        self.answer['pricing_decisions'][0]['proposed_unit_price'] = 15
        self.sync_quote()
        self.fails('V3')
        self.draft['order']['lines'][0].update(unit_price=10.5, extended_price=33)
        self.sync_quote()
        self.fails('V3')

    def test_target_source_and_future_result_leaks(self):
        self.answer['evidence'][0]['quote_no'] = 'TARGET'
        self.fails('V5')
        self.answer['evidence'][0]['quote_no'] = 'PRIOR'
        leaked = copy.deepcopy(self.row)
        leaked.update(quote_no='FUTURE', quote_date='2025-01-01', letter_date='2025-01-02')
        self.events.insert(-1, self.event('keller_polygres', {'action': 'prices', 'corpus': self.corpus},
                                          {'action': 'prices', 'corpus': self.corpus,
                                           'basis': 'verified issued customer quotation PDF', 'outcome': 'unknown',
                                           'prices': [self.price(leaked)]}))
        self.events[-2]['evaluation_scope_sha256'] = self.oracle['scope']['sha256']
        self.fails('V5')

    def test_search_page_and_unused_draft_analog_leaks(self):
        hit = {'source_path': 'target.pdf', 'pdf_sha256': 'd' * 64,
               'page_number': 1, 'page_sha256': 'a' * 64, 'kind': 'quote', 'excerpt': 'Synthetic'}
        self.events.insert(-1, self.event('keller_polygres', {'action': 'search', 'corpus': self.corpus},
                                          {'action': 'search', 'corpus': self.corpus, 'hits': [hit]}))
        self.events[-2]['evaluation_scope_sha256'] = self.oracle['scope']['sha256']
        self.fails('V5')
        self.events.pop(-2)
        self.events.insert(-1, self.event('keller_polygres', {'action': 'page', 'corpus': self.corpus,
                                                              'source_path': 'target.pdf'},
                                          {'action': 'page', 'corpus': self.corpus, **hit, 'text': 'Synthetic'}))
        self.events[-2]['evaluation_scope_sha256'] = self.oracle['scope']['sha256']
        self.fails('V5')
        self.events.pop(-2)
        prior = copy.deepcopy(self.draft)
        prior['draft_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        prior['order']['lines'][0]['analogs'] = [{'quote_no': 'TARGET', 'part_no': 'SYN-P',
                                                  'price_evidence': {'source_document': 'target.pdf'}}]
        self.events.insert(-1, self.event('keller_quote', self.events[-1]['inputs'], {'content': prior}))
        self.events[-2]['evaluation_scope_sha256'] = self.oracle['scope']['sha256']
        self.fails('V5')

    def test_invalid_oracle_target_and_scope_eligibility(self):
        self.oracle['targets'][0]['unit_price'] = '-11.00000'
        self.fails('V3')
        self.oracle['targets'][0]['unit_price'] = '11.00000'
        self.scope['eligible_prices'][0]['quote_no'] = 'TARGET'
        self.freeze()
        self.fails('V5')

    def test_unbound_scope_and_changed_raw_scope(self):
        self.events[1].pop('evaluation_scope_sha256')
        self.fails('V5')
        self.events[1]['evaluation_scope_sha256'] = self.oracle['scope']['sha256']
        self.scope_path.write_text(json.dumps({**self.scope, 'case_id': 'changed'}))
        self.fails('V5')

    def test_price_response_cannot_smuggle_extra_target_fields(self):
        payload = json.loads(self.events[1]['result']['content'][0]['text'])
        payload['prices'][0]['row']['target_unit_price'] = '11.00000'
        self.events[1]['result']['content'][0]['text'] = json.dumps(payload)
        self.fails('V5')

    def test_mismatched_judge_hashes_missing_and_malformed_verdicts(self):
        self.judge['input_sha256'] = {'oracle': '0' * 64, 'answer': '0' * 64, 'audit': '0' * 64}
        self.assertFalse(self.grade(bind=False)['criteria']['J1']['passed'])
        self.assertFalse(self.grade(judged=False)['criteria']['J5']['passed'])
        self.judge['criteria'][0]['evidence'] = []
        self.fails('J1')
        self.judge['criteria'].pop()
        self.fails('J5')

    def test_held_null_draft_and_missing_corrupt_artifacts(self):
        self.answer['draft'] = None
        self.fails('V1')
        self.answer['draft'] = self.draft
        output = self.storage / self.uuid / 'output'
        (output / 'review.json').unlink()
        self.fails('V1')
        (output / 'review.json').write_text('{broken')
        self.fails('V1')

    def test_duplicate_additional_lines_and_citations(self):
        self.answer['evidence'].append(copy.deepcopy(self.answer['evidence'][0]))
        self.fails('V5')
        self.answer['evidence'].pop()
        self.draft['order']['lines'].append(copy.deepcopy(self.draft['order']['lines'][0]))
        self.sync_quote()
        self.fails('V2')

    def test_request_and_charges(self):
        self.draft['order']['request']['customer'] = 'Wrong Customer'
        self.sync_quote()
        self.fails('V2')
        self.draft['order']['request']['customer'] = 'Synthetic Works'
        self.draft['order']['additional_charges'] = [{'name': 'handling', 'amount': 2}]
        self.sync_quote()
        self.fails('V2')

    def test_multiple_eligible_analogs(self):
        other = copy.deepcopy(self.row)
        other.update(quote_no='PRIOR-2', item_no='2', source_path='prior-2.pdf',
                     pdf_sha256='e' * 64, transcript_sha256='f' * 64,
                     quantity='5', extended_price='50.00')
        self.scope['eligible_prices'].append(other)
        self.freeze()
        self.events[1] = self.event('keller_polygres', self.events[1]['inputs'],
                                    {'action': 'prices', 'corpus': self.corpus,
                                     'basis': 'verified issued customer quotation PDF', 'outcome': 'unknown',
                                     'prices': [self.price(self.row), self.price(other)]})
        self.events[1]['evaluation_scope_sha256'] = self.oracle['scope']['sha256']
        citation = self.citation(other)
        citation['quantity'] = 5
        self.answer['evidence'].append(citation)
        self.assertTrue(self.grade()['all_pass'])

    def test_empty_item_number_and_distinct_quantity_breaks(self):
        self.oracle['targets'][0]['item_no'] = ''
        self.row['item_no'] = ''
        other = copy.deepcopy(self.row)
        other.update(quantity='5.0', extended_price='50.00')
        self.scope['eligible_prices'].append(other)
        self.freeze()
        self.answer['evidence'] = [self.citation(self.row), {**self.citation(other), 'quantity': 5}]
        self.events[1] = self.event('keller_polygres', self.events[1]['inputs'],
                                    {'action': 'prices', 'corpus': self.corpus,
                                     'basis': 'verified issued customer quotation PDF', 'outcome': 'unknown',
                                     'prices': [self.price(self.row), self.price(other)]})
        self.events[1]['evaluation_scope_sha256'] = self.oracle['scope']['sha256']
        self.assertTrue(self.grade()['all_pass'])
        self.answer['evidence'][1]['quantity'] = '3.0'
        self.fails('V5')
        self.scope['eligible_prices'][1]['quantity'] = '3.0'
        self.scope['eligible_prices'][1]['extended_price'] = '30.00'
        self.freeze()
        self.fails('V5')

    def test_reusing_one_source_across_requested_lines_is_allowed(self):
        wanted = copy.deepcopy(self.request['requested_lines'][0])
        wanted['line_id'] = 'L2'
        self.request['requested_lines'].append(wanted)
        self.oracle['targets'].append({**self.oracle['targets'][0], 'line_id': 'L2', 'item_no': '10'})
        self.scope['request']['parts'].append({'line_id': 'L2', 'part_no': 'SYN-P', 'quantity': 3})
        part = copy.deepcopy(self.draft['order']['request']['parts'][0])
        part['line_id'] = 'L2'
        self.draft['order']['request']['parts'].append(part)
        line = copy.deepcopy(self.draft['order']['lines'][0])
        line['line_id'] = 'L2'
        self.draft['order']['lines'].append(line)
        self.draft['order'].update(subtotal=63, priced_subtotal=63, total=66)
        self.draft['total'] = 66
        self.answer['evidence'].append({**self.answer['evidence'][0], 'line_id': 'L2'})
        self.answer['pricing_decisions'].append({**self.answer['pricing_decisions'][0], 'line_id': 'L2'})
        self.freeze()
        self.events[-1]['inputs']['request'] = json.dumps(self.draft['order']['request'])
        self.sync_quote()
        self.assertTrue(self.grade()['all_pass'])

    def test_target_document_path_excluded_even_for_other_quote(self):
        self.scope['eligible_prices'][0]['source_path'] = 'target.pdf'
        self.freeze()
        self.fails('V5')

    def test_successful_unscoped_tools_files_and_channels(self):
        call = self.event('read_file_pinned', {'file_path': str((ROOT / 'README.md').resolve())}, 'Unexpected file')
        call['evaluation_scope_sha256'] = self.oracle['scope']['sha256']
        self.events.insert(-1, call)
        self.fails('V5')
        self.events.pop(-2)
        call = self.event('unscoped_tool', {}, {'target_price': '11'})
        call['evaluation_scope_sha256'] = self.oracle['scope']['sha256']
        self.events.insert(-1, call)
        self.fails('V5')
        self.events.pop(-2)
        self.events[1]['result']['structuredContent'] = {'target_price': '11'}
        self.fails('V5')
        self.events[1]['result'].pop('structuredContent')
        self.events[1]['result']['content'][0]['resource'] = 'target.pdf'
        self.fails('V5')
        self.events[1]['result']['content'][0].pop('resource')
        denied = {'startedAt': '2024-01-01T00:00:00Z', 'completedAt': '2024-01-01T00:00:01Z',
                  'tool': 'unscoped_tool', 'inputs': {}, 'result': None, 'error': 'denied',
                  'evaluation_scope_sha256': self.oracle['scope']['sha256']}
        self.events.insert(-1, denied)
        self.assertTrue(self.grade()['all_pass'])

    def test_exact_public_contract_files_only(self):
        contracts = [ROOT / path for path in ('docs/pricing-evals-and-orders.md',
                                              'estimator/src/order.ts', 'estimator/src/types.ts')]
        self.scope['allowed_files'].extend(str(p.resolve()) for p in contracts)
        self.freeze()
        self.assertTrue(self.grade()['all_pass'])
        self.scope['allowed_files'].append(str((ROOT / 'docs/document-evidence.md').resolve()))
        self.freeze()
        self.fails('V5')

    def test_item_number_requires_string_even_if_blank(self):
        self.oracle['targets'][0]['item_no'] = None
        self.fails('V5')
        self.oracle['targets'][0]['item_no'] = ''
        self.scope['eligible_prices'][0]['item_no'] = None
        self.freeze()
        self.fails('V5')

    def test_unsafe_scope_paths_and_private_output_cli(self):
        self.oracle['scope']['path'] = '/tmp/../tmp/not-private.json'
        self.fails('V5')
        self.oracle['scope']['path'] = str(self.home / 'scope-link.json')
        (self.home / 'scope-link.json').symlink_to(self.scope_path)
        self.fails('V5')
        self.oracle['scope']['path'] = str(self.scope_path)
        paths = {k: self.home / f'{k}.json' for k in ('oracle', 'answer', 'audit', 'judge')}
        paths['oracle'].write_text(json.dumps(self.oracle))
        paths['answer'].write_text(json.dumps(self.answer))
        paths['audit'].write_text('\n'.join(json.dumps(e) for e in self.events) + '\n')
        self.judge['input_sha256'] = {k: sha256(paths[k].read_bytes()).hexdigest() for k in ('oracle', 'answer', 'audit')}
        paths['judge'].write_text(json.dumps(self.judge))
        result = subprocess.run([sys.executable, str(SCRIPT), '--oracle', str(paths['oracle']),
                                 '--answer', str(paths['answer']), '--audit', str(paths['audit']),
                                 '--judge', str(paths['judge']), '--out', str(self.home / 'report.json')],
                                env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads((self.home / 'report.json').read_text())['all_pass'])
        self.assertEqual((self.home / 'report.json').stat().st_mode & 0o777, 0o600)

    def test_malformed_audit_cli_writes_failed_report(self):
        oracle = self.home / 'oracle.json'
        answer = self.home / 'answer.json'
        audit = self.home / 'audit.jsonl'
        oracle.write_text(json.dumps(self.oracle))
        answer.write_text(json.dumps(self.answer))
        audit.write_text('{bad json\n')
        result = subprocess.run([sys.executable, str(SCRIPT), '--oracle', str(oracle),
                                 '--answer', str(answer), '--audit', str(audit),
                                 '--out', str(self.home / 'failed.json')],
                                env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.home / 'failed.json').read_text())
        self.assertFalse(report['all_pass'])
        self.assertEqual(report['validation_passed'], 0)


if __name__ == '__main__':
    unittest.main()
