import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('keller_evidence_fixtures', REPO / 'scripts/test/test_keller_ground_truth.py')
FIXTURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURES)
GROUND = FIXTURES.GROUND
SPEC = importlib.util.spec_from_file_location('keller_decision_eval', REPO / 'evals/decision-eval.py')
DECISION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DECISION)


class DecisionFixture(FIXTURES.Fixture):
    def write(self, name, value):
        if not isinstance(value, bytes):
            value = (json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str) + '\n').encode()
        return super().write(name, value)

    def __init__(self, owner, cohort='eligible_quote', population='synthetic'):
        super().__init__(owner)
        self.current, self.current_ref = self.current_quote()
        self.assess()
        assessment_path = Path(self.config['out']) / 'assessment.private.json'
        self.assessment = {'path': str(assessment_path), 'sha256': GROUND.digest(assessment_path.read_bytes())}
        self.request = {'order_id': 'SYNTHETIC-ORDER', 'quote_date': '2026-10-01', 'customer': 'SYNTHETIC CUSTOMER', 'customer_id': '000001',
                        'parts': [{'line_id': 'line-1', 'part_no': 'P-1', 'quantity': 10, 'drawing_ref': 'D-1'}],
                        'charges': {'shipping': '0.00', 'tax': '0.00'}}
        manufacturing = self.current['manufacturing']
        specification = {'kind': 'manufacturing_specification', 'identity': self.identity, 'manufacturing': manufacturing,
                         'recorded_at': '2026-10-01T08:00:00Z'}
        self.spec_ref = {'source': self.write('specification.json', specification), 'pointer': ''}
        self.terms = {'payment_terms': 'Net 30', 'valid_until': '2026-10-31', 'lead_time_days': 10,
                      'shipping': '0.00', 'tax': '0.00', 'additional_charges': []}
        self.requirements = {'schema_version': 1, 'kind': 'full_rfq_requirements', 'case_id': self.case_id,
            'quote_date': self.request['quote_date'], 'currency': 'USD', 'customer_id': '000001', 'terms': self.terms,
            'lines': [{'line_id': 'line-1', 'identity': self.identity, 'manufacturing': manufacturing, 'manufacturing_evidence': self.spec_ref}]}
        self.draft = {'schema_version': 1, 'request': copy.deepcopy(self.request), 'order_id': 'SYNTHETIC-ORDER',
            'quote_date': self.request['quote_date'], 'customer': self.request['customer'], 'currency': 'USD',
            'state': 'PRICED_REQUIRES_REVIEW', 'requires_human_review': True, 'blockers': [],
            'lines': [{'line_id': 'line-1', 'part': {k: v for k, v in self.request['parts'][0].items() if k != 'line_id'},
                       'unit_price': '2.00000', 'extended_price': '20.00'}],
            'charges': self.request['charges'], 'additional_charges': [], 'priced_subtotal': '20.00', 'subtotal': '20.00', 'total': '20.00'}
        self.decisions = {'case_id': self.case_id, 'pricing_decisions': [{'line_id': 'line-1', 'proposed_unit_price': '2.00000',
            'proposal_status': 'NUMERIC_PROVISIONAL', 'supported_quote': self.current_ref, 'manufacturing_assumptions': manufacturing}],
            'terms': self.terms, 'uncertainties': ['Synthetic material assumption must be reviewed']}
        self.producer, self.reviewer = 'synthetic-worker', 'synthetic-independent-reviewer'
        self.assignment = {'kind': 'independent_review_assignment', 'case_id': self.case_id,
            'assigned_at': '2026-10-01T08:45:00Z', 'reviewer_id': self.reviewer, 'executor_id': self.reviewer, 'method': 'human_source_review'}
        self.case_cohort, self.population = cohort, population
        self.trace_override, self.review_override, self.status = None, None, 'COMPLETED'
        self.attempt_id = 'attempt-1'
        self.sequence = 0
        self.seal()

    def seal(self, request_provenance=None):
        self.sequence += 1
        request_ref = self.write('request.json', self.request)
        requirements_ref = self.write('requirements.json', self.requirements)
        self.draft['provenance'] = request_provenance if request_provenance is not None else {
            'request_sha256': GROUND.semantic_request_sha256(Path(request_ref['path']).read_bytes())}
        draft_ref = self.write('draft.json', self.draft)
        self.decisions.update(request_sha256=request_ref['sha256'], draft_sha256=draft_ref['sha256'])
        decisions_ref = self.write('decisions.json', self.decisions)
        assignment_ref = {'source': self.write('assignment.json', self.assignment), 'pointer': ''}
        allowed = [self.spec_ref['source']] + [c['evidence']['source'] for c in self.current['costs']]
        allowed += [line['drawing_asset']['source'] for line in self.requirements['lines'] if 'drawing_asset' in line]
        frozen_case = {'id': self.case_id, 'cohort': self.case_cohort, 'request': request_ref, 'requirements': requirements_ref,
            'assessment_case_id': self.case_id, 'review_assignment': assignment_ref, 'allowed_sources': allowed}
        findings = [self.current_ref, self.spec_ref]
        if self.case_cohort == 'predeclared_blocked':
            blocker = {'kind': 'predeclared_quote_blocker', 'case_id': self.case_id, 'identity': self.identity,
                       'adjudicated_at': '2026-10-01T08:00:00Z', 'missing_fact': 'No valid independent vendor quote'}
            frozen_case['blocked_evidence'] = {'source': self.write('blocker.json', blocker), 'pointer': ''}
            findings = [frozen_case['blocked_evidence']]
        self.challenge = {'schema_version': 1, 'kind': 'frozen_full_rfq_challenge', 'frozen_at': '2026-10-01T09:00:00Z',
                          'cohort': self.population, 'cases': [frozen_case]}
        challenge_ref = self.write('challenge.json', self.challenge)
        self.trace = {'schema_version': 1, 'kind': 'quote_workflow_trace', 'case_id': self.case_id, 'attempt_id': self.attempt_id,
            'producer_id': self.producer, 'request_sha256': request_ref['sha256'], 'events': [
                {'ordinal': 1, 'at': '2026-10-01T12:01:00Z', 'kind': 'source_read', 'status': 'OK', 'access': 'read_only', 'sources': allowed},
                {'ordinal': 2, 'at': '2026-10-01T12:02:00Z', 'kind': 'draft_persisted', 'status': 'OK', 'artifact': draft_ref},
                {'ordinal': 3, 'at': '2026-10-01T12:03:00Z', 'kind': 'price_decision_persisted', 'status': 'OK', 'artifact': decisions_ref}]}
        if self.trace_override:
            self.trace_override(self.trace)
        trace_ref = self.write('trace.json', self.trace)
        self.receipt = {'kind': 'workflow_execution_receipt', 'case_id': self.case_id, 'attempt_id': self.attempt_id,
            'producer_id': self.producer, 'status': self.status, 'started_at': '2026-10-01T12:00:00Z', 'finished_at': '2026-10-01T12:10:00Z',
            'request_sha256': request_ref['sha256'], 'trace_sha256': trace_ref['sha256'], 'draft_sha256': draft_ref['sha256'],
            'price_decisions_sha256': decisions_ref['sha256']}
        self.review = {'kind': 'independent_quote_review', 'case_id': self.case_id, 'attempt_id': self.attempt_id,
            'assignment_sha256': assignment_ref['source']['sha256'], 'reviewer_id': self.reviewer,
            'request_sha256': request_ref['sha256'], 'assessment_sha256': self.assessment['sha256'], 'draft_sha256': draft_ref['sha256'],
            'price_decisions_sha256': decisions_ref['sha256'], 'trace_sha256': trace_ref['sha256'],
            'disposition': 'APPROVED_FOR_HUMAN_HANDOFF' if self.case_cohort == 'eligible_quote' else 'HELD',
            'criteria': [{'id': key, 'verdict': 'PASS', 'reason': 'Synthetic source-supported check', 'source_findings': findings}
                         for key in DECISION.CRITERIA if self.case_cohort == 'eligible_quote']}
        if self.case_cohort == 'predeclared_blocked':
            self.review['criteria'] = [{'id': 'safe_hold', 'verdict': 'PASS', 'reason': 'Synthetic predeclared missing-cost hold', 'source_findings': findings}]
        if self.review_override:
            self.review_override(self.review)
        review_ref = self.write('review.json', self.review)
        self.review_receipt = {'kind': 'independent_review_execution', 'reviewer_id': self.reviewer, 'executor_id': self.reviewer,
            'job_id': 'synthetic-review-job-1', 'review_sha256': review_ref['sha256'], 'assignment_sha256': assignment_ref['source']['sha256'],
            'started_at': '2026-10-01T13:00:00Z', 'finished_at': '2026-10-01T13:10:00Z',
            **{k: self.review[k] for k in ('request_sha256', 'assessment_sha256', 'draft_sha256', 'price_decisions_sha256', 'trace_sha256')}}
        handoff = {'kind': 'human_handoff_receipt', 'reviewer_id': self.reviewer, 'case_id': self.case_id, 'channel': 'internal_private_review',
            'received_at': '2026-10-01T13:20:00Z', 'review_sha256': review_ref['sha256'], 'draft_sha256': draft_ref['sha256'], 'request_sha256': request_ref['sha256']}
        self.ledger = {'schema_version': 1, 'kind': 'sealed_execution_ledger', 'challenge_sha256': challenge_ref['sha256'],
            'sealed_at': '2026-10-01T12:20:00Z', 'attempts': [{'case_id': self.case_id, 'attempt_id': self.attempt_id, 'producer_id': self.producer,
                'status': self.status, 'started_at': self.receipt['started_at'], 'finished_at': self.receipt['finished_at'],
                'receipt': {'source': self.write('execution-receipt.json', self.receipt), 'pointer': ''}}]}
        ledger_ref = self.write('ledger.json', self.ledger)
        self.artifacts = {'schema_version': 1, 'kind': 'sealed_quote_artifacts', 'ledger_sha256': ledger_ref['sha256'], 'attempts': [
            {'case_id': self.case_id, 'attempt_id': self.attempt_id, 'trace': trace_ref, 'draft': draft_ref, 'price_decisions': decisions_ref,
             'review': review_ref, 'review_receipt': {'source': self.write('review-receipt.json', self.review_receipt), 'pointer': ''},
             'handoff': {'source': self.write('handoff.json', handoff), 'pointer': ''}}]}
        self.eval_config = {'schema_version': 1, 'challenge': challenge_ref, 'assessment': self.assessment, 'ledger': ledger_ref,
                            'artifacts': self.write('artifacts.json', self.artifacts), 'out': str(self.root / f'decisions-v{self.sequence}')}

    def evaluate(self):
        DECISION.evaluate(self.eval_config, GROUND)
        return GROUND.parse_json((Path(self.eval_config['out']) / 'decisions.private.json').read_bytes())


class DecisionTests(unittest.TestCase):
    def test_completed_synthetic_quote_has_all_required_artifacts_but_cannot_certify_live_goal(self):
        fixture = DecisionFixture(self)
        report = fixture.evaluate()
        case = report['attempts'][0]
        self.assertEqual(case['errors'], [])
        self.assertTrue(case['completed_quote_all_pass'])
        self.assertEqual(report['summary']['completed_quote_rate'], 1)
        self.assertEqual(report['summary']['live_90pct_goal'], 'NOT_ESTABLISHED_REQUIRES_EXTERNAL_CONFIRMATION')
        values = {p['basis']: p for p in case['numeric_proposals']}
        self.assertEqual(values['internal_calculation']['signed_unit_error'], '-0.50000')
        self.assertEqual(values['recorded_customer_quote']['signed_unit_error'], '0.00000')
        self.assertIsNone(report['summary']['numeric_diagnostics_by_basis']['internal_calculation']['sample_variance_signed_relative_error'])

    def test_provisional_finite_price_without_independent_cost_assessment_is_not_completion(self):
        fixture = DecisionFixture(self)
        fixture.decisions['pricing_decisions'][0].pop('supported_quote')
        fixture.seal()
        case = fixture.evaluate()['attempts'][0]
        self.assertFalse(case['completed_quote_all_pass'])
        self.assertFalse(case['criteria']['source_fitness']['pass'])
        self.assertFalse(case['criteria']['cost_arithmetic']['pass'])

    def test_mismatched_request_revision_quantity_currency_and_manufacturing_fail(self):
        for axis in ('quantity', 'part_no', 'currency', 'manufacturing'):
            with self.subTest(axis=axis):
                fixture = DecisionFixture(self)
                if axis in ('quantity', 'part_no'):
                    fixture.draft['lines'][0]['part'][axis] = 20 if axis == 'quantity' else 'P-2'
                elif axis == 'currency':
                    fixture.draft['currency'] = 'EUR'
                else:
                    fixture.decisions['pricing_decisions'][0]['manufacturing_assumptions'] = {'material': 'invented steel'}
                fixture.seal()
                self.assertFalse(fixture.evaluate()['attempts'][0]['completed_quote_all_pass'])

    def test_arithmetic_errors_and_missing_terms_cannot_be_cancelled_by_a_review(self):
        for axis in ('extension', 'total', 'terms', 'line'):
            with self.subTest(axis=axis):
                fixture = DecisionFixture(self)
                if axis == 'extension':
                    fixture.draft['lines'][0]['extended_price'] = '21.00'
                elif axis == 'total':
                    fixture.draft['total'] = '21.00'
                elif axis == 'terms':
                    fixture.decisions['terms'] = {'payment_terms': 'Net 30'}
                else:
                    fixture.decisions['pricing_decisions'] = []
                fixture.seal()
                case = fixture.evaluate()['attempts'][0]
                self.assertFalse(case['completed_quote_all_pass'])
                self.assertTrue(case['criteria']['independent_review']['pass'])

    def test_explicit_rfq_material_drawing_and_charges_cannot_be_ignored(self):
        for axis in ('material', 'drawing_ref', 'shipping'):
            with self.subTest(axis=axis):
                fixture = DecisionFixture(self)
                if axis == 'shipping':
                    fixture.request['charges']['shipping'] = '1.00'
                    fixture.draft['charges'] = {'shipping': '0.00', 'tax': '0.00'}
                else:
                    fixture.request['parts'][0][axis] = 'unsupported aluminum' if axis == 'material' else 'D-2'
                    fixture.draft['lines'][0]['part'][axis] = fixture.request['parts'][0][axis]
                fixture.draft['request'] = copy.deepcopy(fixture.request)
                fixture.seal()
                case = fixture.evaluate()['attempts'][0]
                self.assertEqual(case['criteria']['identity']['pass'], axis != 'drawing_ref')
                self.assertFalse(case['completed_quote_all_pass'])
                criterion = 'completeness_terms' if axis == 'shipping' else 'manufacturing'
                self.assertFalse(case['criteria'][criterion]['pass'])

    def test_actual_request_revision_and_plain_drawing_identity_bind_to_independent_requirements(self):
        for key, value in [('revision', 'B'), ('rev', 'B'), ('drawing_no', 'D-2'), ('drawing_ref', 'D-2')]:
            with self.subTest(key=key):
                fixture = DecisionFixture(self)
                fixture.request['parts'][0][key] = value
                fixture.draft['request'] = copy.deepcopy(fixture.request)
                fixture.draft['lines'][0]['part'][key] = value
                fixture.seal()
                case = fixture.evaluate()['attempts'][0]
                self.assertTrue(case['criteria']['source_fitness']['pass'])
                self.assertFalse(case['criteria']['identity']['pass'])
                self.assertFalse(case['completed_quote_all_pass'])

    def test_drawing_asset_path_needs_actual_bytes_and_independent_specification_binding(self):
        fixture = DecisionFixture(self)
        fixture.request['parts'][0]['drawing_ref'] = 'drawings/P-1.pdf'
        fixture.draft['request'] = copy.deepcopy(fixture.request)
        fixture.draft['lines'][0]['part']['drawing_ref'] = 'drawings/P-1.pdf'
        fixture.seal()
        self.assertFalse(fixture.evaluate()['attempts'][0]['completed_quote_all_pass'])
        asset_source = fixture.write('synthetic-drawing.pdf', FIXTURES.synthetic_pdf(['SYNTHETIC DRAWING D-1', 'REVISION A']))
        asset = {'request_ref': 'drawings/P-1.pdf', 'source': asset_source, 'drawing_no': 'D-1', 'revision': 'A'}
        fixture.requirements['lines'][0]['drawing_asset'] = asset
        specification = GROUND.bound_record(fixture.spec_ref, GROUND.EvidenceIO())
        specification['drawing_asset'] = asset
        fixture.spec_ref['source'] = fixture.write('asset-specification.json', specification)
        fixture.seal()
        self.assertTrue(fixture.evaluate()['attempts'][0]['completed_quote_all_pass'])
        specification['drawing_asset'] = {**asset, 'revision': 'B'}
        fixture.spec_ref['source'] = fixture.write('mismatched-asset-specification.json', specification)
        fixture.seal()
        self.assertFalse(fixture.evaluate()['attempts'][0]['criteria']['manufacturing']['pass'])

    def test_real_order_numeric_fractions_follow_json_stringify_provenance_not_python_strings(self):
        fixture = DecisionFixture(self)
        fixture.request['charges'] = {'shipping': 10.5, 'tax': 1.25}
        fixture.request['parts'][0]['pricing'] = {'method': 'unit_price', 'unit_price': 2.25, 'reason': 'Synthetic independently supported price'}
        fixture.terms.update(shipping=10.5, tax=1.25)
        cost = fixture.current['costs'][0]
        observation = GROUND.bound_record(cost['evidence'], GROUND.EvidenceIO())
        observation.update(amount='0.88750', extension='8.88')
        cost.update(amount='0.88750', evidence={'source': fixture.write('fractional-material-cost.json', observation), 'pointer': ''})
        fixture.current['amount'] = {'unit_price': '2.25000', 'extension': '22.50'}
        fixture.current_ref['source'] = fixture.write('fractional-current-quote.json', fixture.current)
        fixture.decisions['pricing_decisions'][0]['proposed_unit_price'] = '2.25000'
        fixture.config['out'] = str(fixture.root / 'fractional-assessment-v1')
        fixture.assess()
        assessment_path = Path(fixture.config['out']) / 'assessment.private.json'
        fixture.assessment = {'path': str(assessment_path), 'sha256': GROUND.digest(assessment_path.read_bytes())}
        program = ("import fs from 'node:fs';"
                   "import {buildPricedOrder} from './estimator/src/order.ts';"
                   "import {QuoteRegister} from './estimator/src/register.ts';"
                   "const request=JSON.parse(fs.readFileSync(0,'utf8'));"
                   "const draft=await buildPricedOrder(new QuoteRegister([]),request,{registerSha256:'a'.repeat(64)});"
                   "process.stdout.write(JSON.stringify(draft));")
        node = shutil.which('node')
        result = subprocess.run([node, '--import', str(REPO / 'estimator/node_modules/tsx/dist/loader.mjs'),
            '--input-type=module', '-e', program], cwd=REPO, input=json.dumps(fixture.request).encode(), capture_output=True,
            env={'PATH': os.defpath, 'LANG': 'C.UTF-8', 'TZ': 'UTC', 'OFFLINE': '1', 'KELLER_OFFLINE': '1'}, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        actual = json.loads(result.stdout)
        actual_sha = actual['provenance']['request_sha256']
        fixture.draft = actual
        fixture.seal(request_provenance=actual['provenance'])
        self.assertEqual(fixture.draft['provenance']['request_sha256'], actual_sha)
        case = fixture.evaluate()['attempts'][0]
        self.assertTrue(case['criteria']['identity']['pass'], case['errors'])
        self.assertTrue(case['completed_quote_all_pass'], case['errors'])
        fixture.receipt['request_sha256'] = actual_sha
        fixture.ledger['attempts'][0]['receipt']['source'] = fixture.write('semantic-instead-of-raw-receipt.json', fixture.receipt)
        fixture.eval_config['ledger'] = fixture.write('semantic-instead-of-raw-ledger.json', fixture.ledger)
        fixture.artifacts['ledger_sha256'] = fixture.eval_config['ledger']['sha256']
        fixture.eval_config['artifacts'] = fixture.write('semantic-instead-of-raw-artifacts.json', fixture.artifacts)
        fixture.eval_config['out'] = str(fixture.root / 'semantic-instead-of-raw-result')
        wrong_receipt = fixture.evaluate()['attempts'][0]
        self.assertIn('EXECUTION_RECEIPT_MISMATCH', wrong_receipt['errors'])
        self.assertFalse(wrong_receipt['completed_quote_all_pass'])
        fixture.draft['request']['parts'][0]['quantity'] = 11
        fixture.draft['lines'][0]['part']['quantity'] = 11
        fixture.seal(request_provenance=actual['provenance'])
        self.assertFalse(fixture.evaluate()['attempts'][0]['criteria']['identity']['pass'])

    def test_handoff_cannot_precede_completed_review(self):
        fixture = DecisionFixture(self)
        handoff = GROUND.bound_record(fixture.artifacts['attempts'][0]['handoff'], GROUND.EvidenceIO())
        handoff['received_at'] = '2026-10-01T13:05:00Z'
        fixture.artifacts['attempts'][0]['handoff']['source'] = fixture.write('premature-handoff.json', handoff)
        fixture.eval_config['artifacts'] = fixture.write('premature-artifacts.json', fixture.artifacts)
        case = fixture.evaluate()['attempts'][0]
        self.assertTrue(case['criteria']['independent_review']['pass'])
        self.assertFalse(case['criteria']['human_handoff']['pass'])
        self.assertFalse(case['completed_quote_all_pass'])

    def test_fabricated_self_or_unbound_review_cannot_pass(self):
        for axis in ('self', 'bool', 'findings', 'receipt'):
            with self.subTest(axis=axis):
                fixture = DecisionFixture(self)
                if axis == 'self':
                    fixture.assignment['reviewer_id'] = fixture.producer
                elif axis == 'bool':
                    fixture.review_override = lambda review: review.update(criteria=[{'id': k, 'pass': True} for k in DECISION.CRITERIA])
                elif axis == 'findings':
                    fixture.review_override = lambda review: [c.update(source_findings=[]) for c in review['criteria']]
                fixture.seal()
                if axis == 'receipt':
                    fixture.review_receipt['executor_id'] = fixture.producer
                    fixture.artifacts['attempts'][0]['review_receipt']['source'] = fixture.write('bad-review-receipt.json', fixture.review_receipt)
                    fixture.eval_config['artifacts'] = fixture.write('bad-artifacts.json', fixture.artifacts)
                self.assertFalse(fixture.evaluate()['attempts'][0]['completed_quote_all_pass'])

    def test_dropped_missing_timed_out_and_invalid_attempts_stay_in_denominator(self):
        fixture = DecisionFixture(self)
        fixture.artifacts['attempts'] = []
        fixture.eval_config['artifacts'] = fixture.write('dropped-artifacts.json', fixture.artifacts)
        summary = fixture.evaluate()['summary']
        self.assertEqual(summary['eligible_attempts'], 1)
        self.assertEqual(summary['completed_quote_all_pass'], 0)
        for status in ('TIMED_OUT', 'ERROR', 'INVALID'):
            fixture.status = status
            fixture.seal()
            summary = fixture.evaluate()['summary']
            self.assertEqual(summary['attempt_states'], {status: 1})
            self.assertEqual(summary['completed_quote_all_pass'], 0)
        fixture.ledger['attempts'] = []
        ledger = fixture.write('empty-ledger.json', fixture.ledger)
        fixture.artifacts.update(ledger_sha256=ledger['sha256'], attempts=[])
        fixture.eval_config.update(ledger=ledger, artifacts=fixture.write('empty-artifacts.json', fixture.artifacts), out=str(fixture.root / 'missing-v1'))
        report = fixture.evaluate()
        self.assertEqual(report['summary']['eligible_attempts'], 1)
        self.assertEqual(report['summary']['attempt_states'], {'MISSING_ATTEMPT': 1})

    def test_duplicate_or_orphan_attempts_are_retained_as_failures(self):
        fixture = DecisionFixture(self)
        fixture.ledger['attempts'].append(copy.deepcopy(fixture.ledger['attempts'][0]))
        ledger = fixture.write('duplicate-ledger.json', fixture.ledger)
        fixture.artifacts['ledger_sha256'] = ledger['sha256']
        fixture.eval_config.update(ledger=ledger, artifacts=fixture.write('duplicate-artifacts.json', fixture.artifacts))
        summary = fixture.evaluate()['summary']
        self.assertEqual(summary['eligible_attempts'], 2)
        self.assertEqual(summary['completed_quote_all_pass'], 0)
        fixture.seal()
        orphan = copy.deepcopy(fixture.artifacts['attempts'][0])
        orphan['attempt_id'] = 'orphan'
        fixture.artifacts['attempts'].append(orphan)
        fixture.eval_config['artifacts'] = fixture.write('orphan-artifacts.json', fixture.artifacts)
        summary = fixture.evaluate()['summary']
        self.assertEqual(summary['eligible_attempts'], 2)
        self.assertEqual(summary['completed_quote_all_pass'], 1)

    def test_invalid_output_bytes_are_still_verified_and_retained_without_price_zero(self):
        fixture = DecisionFixture(self)
        fixture.status = 'INVALID'
        fixture.seal()
        fixture.artifacts['attempts'][0]['draft'] = fixture.write('invalid-output.json', b'{not-json')
        fixture.eval_config['artifacts'] = fixture.write('invalid-artifacts.json', fixture.artifacts)
        report = fixture.evaluate()
        attempt = report['attempts'][0]
        self.assertEqual(attempt['attempt_status'], 'INVALID')
        self.assertEqual(attempt['artifact_integrity']['draft'], 'VERIFIED_REFERENCED_BYTES')
        self.assertEqual(attempt['numeric_proposals'], [])
        self.assertFalse(attempt['completed_quote_all_pass'])
        self.assertIn(fixture.artifacts['attempts'][0]['draft']['path'], report['inputs'])

    def test_safe_predeclared_hold_is_a_separate_result_and_never_quote_completion(self):
        fixture = DecisionFixture(self, cohort='predeclared_blocked')
        fixture.status = 'HELD'
        fixture.draft.update(state='BLOCKED', total=None, subtotal=None, blockers=['Missing independent vendor quote'])
        fixture.draft['lines'][0].update(unit_price=None, extended_price=None)
        fixture.seal()
        report = fixture.evaluate()
        self.assertTrue(report['attempts'][0]['safety_hold_all_pass'], report['attempts'][0]['errors'])
        self.assertFalse(report['attempts'][0]['completed_quote_all_pass'])
        self.assertEqual(report['summary']['eligible_attempts'], 0)
        self.assertIsNone(report['summary']['completed_quote_rate'])
        self.assertEqual(report['summary']['safe_hold_all_pass'], 1)
        self.assertEqual(report['attempts'][0]['numeric_proposals'][0]['numeric_state'], 'MISSING')

    def test_later_or_stale_cost_bytes_and_changed_assessment_sources_fail_closed(self):
        fixture = DecisionFixture(self)
        cost_path = Path(fixture.current['costs'][0]['evidence']['source']['path'])
        cost = GROUND.parse_json(cost_path.read_bytes())
        cost['valid_until'] = '2026-09-30'
        cost_path.write_bytes(GROUND.encode(cost))
        with self.assertRaisesRegex(ValueError, 'DIGEST_MISMATCH'):
            fixture.evaluate()
        fixture = DecisionFixture(self)
        current = copy.deepcopy(fixture.current)
        current['recorded_at'] = '2026-10-02T08:00:00Z'
        fixture.decisions['pricing_decisions'][0]['supported_quote'] = {'source': fixture.write('later-current.json', current), 'pointer': ''}
        fixture.seal()
        self.assertFalse(fixture.evaluate()['attempts'][0]['criteria']['source_fitness']['pass'])

    def test_unfrozen_sources_or_missing_trace_events_and_fake_live_claims_fail(self):
        for axis in ('hidden_source', 'event', 'live'):
            with self.subTest(axis=axis):
                fixture = DecisionFixture(self, population='independent_live' if axis == 'live' else 'exposed_diagnostic')
                if axis == 'hidden_source':
                    fixture.trace_override = lambda trace: trace['events'][0].update(sources=[fixture.assessment])
                elif axis == 'event':
                    fixture.trace_override = lambda trace: trace['events'].pop(1)
                fixture.seal()
                report = fixture.evaluate()
                self.assertFalse(report['attempts'][0]['criteria']['trace_integrity']['pass'])
                self.assertEqual(report['summary']['live_90pct_goal'], 'NOT_ESTABLISHED_REQUIRES_EXTERNAL_CONFIRMATION')

    def test_multiple_actual_proposals_retain_signed_magnitude_and_variance_by_basis(self):
        fixture = DecisionFixture(self)
        earlier = copy.deepcopy(fixture.draft)
        earlier['lines'][0]['unit_price'] = '3.00000'
        earlier['lines'][0]['extended_price'] = '30.00'
        earlier.update(priced_subtotal='30.00', subtotal='30.00', total='30.00')
        earlier_ref = fixture.write('earlier-draft.json', earlier)
        def proposals(trace):
            trace['events'].insert(1, {'ordinal': 2, 'at': '2026-10-01T12:01:30Z', 'kind': 'draft_persisted', 'status': 'OK', 'artifact': earlier_ref})
            for index, event in enumerate(trace['events'], 1):
                event['ordinal'] = index
        fixture.trace_override = proposals
        fixture.seal()
        report = fixture.evaluate()
        self.assertEqual(len(report['attempts'][0]['numeric_proposals']), 4)
        summary = report['summary']['numeric_diagnostics_by_basis']['internal_calculation']
        self.assertEqual(summary['comparable_proposals'], 2)
        self.assertEqual(summary['mean_signed_relative_error'], '0.0')
        self.assertEqual(summary['sample_variance_signed_relative_error'], '0.08')

    def test_decisions_cli_is_an_actual_consumer_and_outputs_no_client_targets(self):
        fixture = DecisionFixture(self)
        config = fixture.write('decision-config.json', fixture.eval_config)
        result = subprocess.run(['python', str(REPO / 'scripts/keller-ground-truth.py'), 'decisions', '--config', config['path']], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['completed_quote_all_pass'], 1)
        self.assertNotIn('P-1', result.stdout)
        self.assertNotIn('2.50000', result.stdout)
        self.assertNotIn(fixture.case_id, result.stdout)


if __name__ == '__main__':
    unittest.main()
