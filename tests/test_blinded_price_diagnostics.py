"""Synthetic per-turn price diagnostics; no commercial observations."""

import copy
from decimal import Decimal
from hashlib import sha256
import json
import os
import subprocess
import sys
import unittest

import test_blinded_mcp_workflow_eval as fixtures


class PriceDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.BlindedWorkflowTest('test_positive_and_blind_prediction_differs_from_printed_target')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def quote(self, draft, inputs=None):
        case = self.case
        event = case.event('keller_quote', inputs or case.events[-1]['inputs'], {'content': draft})
        event['evaluation_scope_sha256'] = case.oracle['scope']['sha256']
        return event

    def diagnostics(self):
        return self.case.grade()['price_diagnostics']

    def test_all_pass_grades_unchanged_and_final_linked_once(self):
        result = self.case.grade()
        diagnostic = result['price_diagnostics']
        self.assertEqual((result['validation_passed'], result['judge_passed'], result['combined_score'], result['all_pass']),
                         (5, 5, 1, True))
        self.assertTrue(diagnostic['non_acceptance_diagnostic'])
        self.assertEqual(diagnostic['finite_priced_line_count'], 1)
        self.assertEqual(len(diagnostic['turns']), 1)
        self.assertEqual(diagnostic['final']['linked_audit_ordinal'], 3)
        self.assertTrue(diagnostic['final']['pricing_decisions_match_draft'])
        line = diagnostic['turns'][0]['lines'][0]
        self.assertEqual(tuple(map(Decimal, (line['unit_delta_usd'], line['signed_percentage_error_pp'],
                          line['recorded_minus_target_extension_usd']))),
                         (Decimal('-0.5'), Decimal('-0.5') / 11 * 100, Decimal('-1.5')))

    def test_automatic_then_explicit_and_cost_input_provenance(self):
        case = self.case
        auto = copy.deepcopy(case.draft)
        auto['draft_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        auto['order']['lines'][0].update(unit_price=10, extended_price=30, pricing_source='historical_analog')
        automatic_request = copy.deepcopy(case.draft['order']['request'])
        automatic_request['parts'][0].pop('pricing')
        case.events.insert(-1, self.quote(auto, {**case.events[-1]['inputs'], 'request': json.dumps(automatic_request)}))
        diagnostic = self.diagnostics()
        self.assertEqual([turn['input_provenance'][0]['mode'] for turn in diagnostic['turns']],
                         ['automatic', 'explicit_unit_price'])
        self.assertEqual(diagnostic['turns'][1]['input_provenance'][0]['pricing_inputs']['unit_price'], 10.5)
        self.assertEqual([Decimal(turn['lines'][0]['unit_delta_usd']) for turn in diagnostic['turns']],
                         [Decimal('-1'), Decimal('-0.5')])
        self.assertEqual(diagnostic['final']['linked_audit_ordinal'], 4)
        cost = copy.deepcopy(automatic_request)
        cost['parts'][0]['pricing'] = {'method': 'cost_plus', 'material_per_unit': 4, 'labor_per_unit': 3,
                                       'outside_per_unit': 0, 'setup_total': 9, 'margin_pct': 10,
                                       'reason': 'Synthetic costs'}
        case.events.insert(-1, self.quote(auto, {**case.events[-1]['inputs'], 'request': json.dumps(cost)}))
        self.assertEqual(self.diagnostics()['turns'][-2]['input_provenance'][0]['mode'], 'cost_plus')

    def test_under_over_two_line_statistics_and_variance(self):
        case = self.case
        second = copy.deepcopy(case.request['requested_lines'][0])
        second['line_id'] = 'L2'
        case.request['requested_lines'].append(second)
        case.oracle['targets'].append({**case.oracle['targets'][0], 'line_id': 'L2'})
        case.scope['request']['parts'].append({'line_id': 'L2', 'part_no': 'SYN-P', 'quantity': 3})
        part = copy.deepcopy(case.draft['order']['request']['parts'][0])
        part['line_id'] = 'L2'
        case.draft['order']['request']['parts'].append(part)
        case.draft['order']['lines'][0].update(unit_price=10, extended_price=30)
        line = copy.deepcopy(case.draft['order']['lines'][0])
        line.update(line_id='L2', unit_price=12, extended_price=36)
        case.draft['order']['lines'].append(line)
        case.answer['pricing_decisions'].append({**case.answer['pricing_decisions'][0], 'line_id': 'L2',
                                                 'proposed_unit_price': 12})
        case.answer['pricing_decisions'][0]['proposed_unit_price'] = 10
        case.draft['order'].update(subtotal=66, priced_subtotal=66, total=69)
        case.draft['total'] = 69
        case.freeze()
        case.events[-1]['inputs']['request'] = json.dumps(case.draft['order']['request'])
        case.sync_quote()
        diagnostic = self.diagnostics()
        self.assertEqual(diagnostic['finite_priced_line_count'], 2)
        self.assertEqual([Decimal(x['unit_delta_usd']) for x in diagnostic['turns'][0]['lines']],
                         [Decimal('-1'), Decimal('1')])
        dollar = diagnostic['unit_error_usd']
        for field, value in [('mean_signed_error', 0), ('mean_absolute_error', 1),
                             ('mse', 1), ('rmse', 1), ('population_variance', 1), ('population_sd', 1)]:
            self.assertEqual(Decimal(dollar[field]), value)
        percent = diagnostic['percentage_error_pp']
        self.assertEqual(Decimal(percent['mean_signed_error']), 0)
        self.assertLess(abs(Decimal(percent['mape_pp']) - Decimal(100) / 11), Decimal('1e-24'))
        self.assertLess(abs(Decimal(percent['median_ape_pp']) - Decimal(100) / 11), Decimal('1e-24'))
        self.assertLess(abs(Decimal(percent['population_variance']) - (Decimal(100) / 11) ** 2), Decimal('1e-22'))
        self.assertIn('pp²', percent['unit'])
        self.assertIn('USD²', dollar['unit'])

    def test_null_denied_error_and_malformed_turns_retained(self):
        case = self.case
        denied = {'tool': 'keller_quote', 'inputs': case.events[-1]['inputs'], 'result': None,
                  'error': 'denied', 'evaluation_scope_sha256': case.oracle['scope']['sha256']}
        error = case.event('keller_quote', case.events[-1]['inputs'], 'not a price')
        error['result']['isError'] = True
        error['evaluation_scope_sha256'] = case.oracle['scope']['sha256']
        malformed = case.event('keller_quote', case.events[-1]['inputs'], 'not JSON')
        malformed['evaluation_scope_sha256'] = case.oracle['scope']['sha256']
        case.events[-1:-1] = [denied, error, malformed]
        diagnostic = self.diagnostics()
        self.assertEqual([turn['state'] for turn in diagnostic['turns']],
                         ['error', 'error', 'malformed', 'success'])
        self.assertEqual(diagnostic['finite_priced_line_count'], 1)
        self.assertIsNone(diagnostic['turns'][1]['draft_id'])

    def test_invalid_numbers_missing_duplicate_wrong_identity_and_unpriced(self):
        for invalid in (True, 'NaN', 0, -1, 'Infinity'):
            with self.subTest(invalid=invalid):
                case = self.case
                draft = copy.deepcopy(case.draft)
                draft['draft_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
                draft['order']['lines'][0]['unit_price'] = invalid
                case.events.insert(-1, self.quote(draft))
                turn = self.diagnostics()['turns'][0]
                self.assertEqual(turn['lines'][0]['state'], 'invalid')
                self.assertIsNone(turn['lines'][0]['unit_delta_usd'])
                case.events.pop(-2)
        draft = copy.deepcopy(self.case.draft)
        draft['order']['lines'][0].update(unit_price=None, extended_price=None)
        draft['state'] = 'BLOCKED'
        self.case.events.insert(-1, self.quote(draft))
        self.assertEqual((self.diagnostics()['turns'][0]['state'], self.diagnostics()['turns'][0]['lines'][0]['state']),
                         ('unpriced', 'unpriced'))
        self.case.events.pop(-2)
        for mutation in ('missing', 'duplicate', 'wrong_line', 'wrong_part', 'wrong_quantity'):
            with self.subTest(mutation=mutation):
                draft = copy.deepcopy(self.case.draft)
                lines = draft['order']['lines']
                if mutation == 'missing':
                    lines.clear()
                elif mutation == 'duplicate':
                    lines.append(copy.deepcopy(lines[0]))
                elif mutation == 'wrong_line':
                    lines[0]['line_id'] = 'OTHER'
                elif mutation == 'wrong_part':
                    lines[0]['part']['part_no'] = 'OTHER'
                else:
                    lines[0]['part']['quantity'] = True
                self.case.events.insert(-1, self.quote(draft))
                diagnostic = self.diagnostics()
                self.assertEqual(diagnostic['turns'][0]['lines'][0]['state'], 'invalid')
                self.assertEqual(diagnostic['finite_priced_line_count'], 1)
                self.case.events.pop(-2)
        draft = copy.deepcopy(self.case.draft)
        draft['order']['lines'][0]['extended_price'] = False
        self.case.events.insert(-1, self.quote(draft))
        self.assertEqual(self.diagnostics()['turns'][0]['lines'][0]['state'], 'invalid')
        self.case.events.pop(-2)
        request = copy.deepcopy(self.case.draft['order']['request'])
        request['parts'][0]['part_no'] = 'OTHER'
        self.case.events.insert(-1, self.quote(self.case.draft,
                                               {**self.case.events[-1]['inputs'], 'request': json.dumps(request)}))
        diagnostic = self.diagnostics()
        self.assertFalse(diagnostic['turns'][0]['input_provenance'][0]['input_identity_valid'])
        self.assertEqual(diagnostic['turns'][0]['lines'][0]['state'], 'invalid')
        self.assertEqual(diagnostic['finite_priced_line_count'], 1)

    def test_malformed_intermediate_method_and_line_id_do_not_abort_report(self):
        case = self.case
        for method in ([], {}, 4):
            with self.subTest(method=method):
                request = copy.deepcopy(case.draft['order']['request'])
                request['parts'][0]['pricing']['method'] = method
                prior = copy.deepcopy(case.draft)
                prior['draft_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
                case.events.insert(-1, self.quote(prior, {**case.events[-1]['inputs'],
                                                          'request': json.dumps(request)}))
                result = case.grade()
                self.assertTrue(result['all_pass'], result)
                self.assertEqual(result['price_diagnostics']['turns'][0]['input_provenance'][0]['mode'], 'unknown')
                case.events.pop(-2)
        for line_id in ([], {}, 3):
            with self.subTest(line_id=line_id):
                prior = copy.deepcopy(case.draft)
                prior['draft_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
                prior['order']['lines'].append({**prior['order']['lines'][0], 'line_id': line_id})
                case.events.insert(-1, self.quote(prior))
                result = case.grade()
                self.assertTrue(result['all_pass'], result)
                self.assertEqual(result['price_diagnostics']['turns'][0]['lines'][0]['state'], 'invalid')
                self.assertEqual(result['price_diagnostics']['finite_priced_line_count'], 1)
                case.events.pop(-2)

    def test_exact_boundary_and_half_up_cent_extension(self):
        case = self.case
        draft = copy.deepcopy(case.draft)
        draft['draft_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        draft['order']['lines'][0].update(unit_price='8.8', extended_price='26.40')
        case.events.insert(-1, self.quote(draft))
        diagnostic = self.diagnostics()
        self.assertEqual(diagnostic['turns'][0]['lines'][0]['signed_percentage_error_pp'], '-20.0')
        case.events.pop(-2)
        draft['order']['lines'][0].update(unit_price='13.2', extended_price='39.60')
        case.events.insert(-1, self.quote(draft))
        self.assertEqual(self.diagnostics()['turns'][0]['lines'][0]['signed_percentage_error_pp'], '20.0')
        case.events.pop(-2)
        draft['order']['lines'][0].update(unit_price='10.005', extended_price='30.02')
        case.events.insert(-1, self.quote(draft))
        line = self.diagnostics()['turns'][0]['lines'][0]
        self.assertEqual((line['expected_extension_usd'], line['expected_minus_recorded_extension_usd'],
                          line['recorded_minus_target_extension_usd']), ('30.02', '0.00', '-2.98'))

    def test_duplicate_draft_calls_and_final_hold_with_persisted_draft(self):
        case = self.case
        case.events.insert(-1, self.quote(case.draft))
        result = case.grade()
        self.assertFalse(result['all_pass'])
        self.assertIsNone(result['price_diagnostics']['final']['linked_audit_ordinal'])
        self.assertEqual(result['price_diagnostics']['finite_priced_line_count'], 2)
        case.events.pop(-2)
        case.answer['pricing_decisions'][0]['proposed_unit_price'] = None
        result = case.grade()
        self.assertFalse(result['all_pass'])
        self.assertFalse(result['criteria']['V5']['passed'])
        diagnostic = result['price_diagnostics']
        self.assertEqual(diagnostic['final']['state'], 'priced_draft')
        self.assertEqual(diagnostic['final']['pricing_decision_state'], 'held_or_null')
        self.assertFalse(diagnostic['final']['pricing_decisions_match_draft'])
        self.assertEqual(diagnostic['finite_priced_line_count'], 1)
        case.answer['draft'] = None
        diagnostic = self.diagnostics()
        self.assertEqual(diagnostic['final']['state'], 'held_or_null')
        self.assertIsNone(diagnostic['final']['linked_audit_ordinal'])
        self.assertEqual(diagnostic['finite_priced_line_count'], 1)
        case.events.pop()
        diagnostic = self.diagnostics()
        self.assertEqual(diagnostic['finite_priced_line_count'], 0)
        self.assertIsNone(diagnostic['unit_error_usd']['population_variance'])
        self.assertIsNone(diagnostic['percentage_error_pp']['mape_pp'])

    def test_blocked_and_malformed_final_drafts_are_not_priced_drafts(self):
        case = self.case
        blocked = copy.deepcopy(case.draft)
        blocked['state'] = blocked['order']['state'] = 'BLOCKED'
        blocked['order']['lines'][0].update(unit_price=None, extended_price=None)
        case.answer['draft'] = blocked
        result = case.grade()
        self.assertFalse(result['all_pass'])
        self.assertEqual(result['price_diagnostics']['final']['state'], 'unpriced_draft')
        self.assertEqual(result['price_diagnostics']['final']['pricing_decision_state'], 'held_or_null')
        self.assertIsNone(result['price_diagnostics']['final']['linked_audit_ordinal'])
        blocked['order']['lines'][0].update(unit_price=10.5, extended_price=31.5)
        self.assertEqual(case.grade()['price_diagnostics']['final']['state'], 'held_draft')
        case.answer['draft'] = {}
        result = case.grade()
        self.assertFalse(result['all_pass'])
        self.assertEqual(result['price_diagnostics']['final']['state'], 'malformed_draft')

    def test_invalid_scope_never_promotes_diagnostics_to_pass(self):
        self.case.events[-1].pop('evaluation_scope_sha256')
        result = self.case.grade()
        self.assertFalse(result['all_pass'])
        self.assertFalse(result['price_diagnostics']['grading_result']['v_context']['V5']['passed'])
        self.assertFalse(result['price_diagnostics']['grading_result']['all_pass'])
        self.assertEqual(result['price_diagnostics']['finite_priced_line_count'], 1)
        self.case.events[-1]['evaluation_scope_sha256'] = self.case.oracle['scope']['sha256']
        self.case.oracle['targets'][0]['unit_price'] = 'NaN'
        diagnostic = self.diagnostics()
        self.assertFalse(diagnostic['oracle_valid'])
        self.assertEqual(diagnostic['finite_priced_line_count'], 0)
        self.assertIsNone(diagnostic['percentage_error_pp']['mape_pp'])

    def test_normal_cli_report_contains_private_diagnostics(self):
        case = self.case
        paths = {key: case.home / f'{key}.json' for key in ('oracle', 'answer', 'audit', 'judge')}
        paths['oracle'].write_text(json.dumps(case.oracle))
        paths['answer'].write_text(json.dumps(case.answer))
        paths['audit'].write_text('\n'.join(json.dumps(event) for event in case.events) + '\n')
        case.judge['input_sha256'] = {key: sha256(paths[key].read_bytes()).hexdigest()
                                      for key in ('oracle', 'answer', 'audit')}
        paths['judge'].write_text(json.dumps(case.judge))
        report_path = case.home / 'report.json'
        run = subprocess.run([sys.executable, str(fixtures.SCRIPT), '--oracle', str(paths['oracle']),
                              '--answer', str(paths['answer']), '--audit', str(paths['audit']),
                              '--judge', str(paths['judge']), '--out', str(report_path)],
                             env={**os.environ, 'HOME': str(case.home)}, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(report_path.read_text())
        self.assertTrue(report['all_pass'])
        self.assertEqual(report['price_diagnostics']['final']['linked_audit_ordinal'], 3)
        self.assertEqual(report_path.stat().st_mode & 0o777, 0o600)
        paths['audit'].write_text('{bad json\n')
        run = subprocess.run([sys.executable, str(fixtures.SCRIPT), '--oracle', str(paths['oracle']),
                              '--answer', str(paths['answer']), '--audit', str(paths['audit']),
                              '--judge', str(paths['judge']), '--out', str(report_path)],
                             env={**os.environ, 'HOME': str(case.home)}, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(report_path.read_text())
        self.assertFalse(report['price_diagnostics']['grading_result']['all_pass'])
        self.assertEqual(report['price_diagnostics']['grading_result']['validation_passed'], 0)
        self.assertIsNone(report['price_diagnostics']['percentage_error_pp']['mape_pp'])


if __name__ == '__main__':
    unittest.main()
