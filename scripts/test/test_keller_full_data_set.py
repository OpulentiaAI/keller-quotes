import copy
import csv
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import unittest
from unittest import mock

from test_keller_ground_truth import Fixture, GROUND, REPO, synthetic_dbf


SPEC = importlib.util.spec_from_file_location('keller_full_data_set', REPO / 'scripts/keller-full-data-set.py')
FULL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FULL)


class FullFixture(Fixture):
    def __init__(self, owner, **kwargs):
        super().__init__(owner, **kwargs)
        self.version = 0
        self.preparer = 'synthetic-preparer'
        self.item = {'case_id': self.case_id}
        self.records = {}
        self.assessment = self.write('assessment-config.private.json', self.config)
        self.full_config = {'schema_version': 1, 'as_of': '2026-10-04', 'assessment_config': self.assessment,
                            'confirmations': {}, 'out': str(self.root / 'full-data-v1')}

    def bind(self, name, record):
        self.records[name] = record
        self.item[name] = {'source': self.write(name + '.json', record), 'pointer': ''}
        return self.item[name]

    def primary(self, kind, record_id, recorded_at, **values):
        return {'kind': kind, 'record_id': record_id, 'issuer': 'synthetic-independent-primary-source',
                'identity': copy.deepcopy(self.identity), 'recorded_at': recorded_at, **values}

    def candidates(self):
        data, physical = synthetic_dbf([('WO_NO', 'C', 12), ('COMP_ID', 'C', 6), ('PART_NO', 'C', 16),
                                       ('REV_NO', 'C', 8), ('QTY', 'N', 8)],
                                      {'WO_NO': 'SYNTHETIC-WO', 'COMP_ID': '000001', 'PART_NO': 'P-1', 'REV_NO': 'B', 'QTY': '999'})
        reference = {'source': self.write('WOHEAD.DBF', data), 'physical_record': physical}
        self.item['candidate'] = [reference]
        return reference

    def native_chain(self):
        self.native_specs = {
            'sales_order': ([('QUOTE_NO', 'C', 7), ('COMP_ID', 'C', 6), ('PART_NO', 'C', 16), ('JOBNO', 'C', 12),
                             ('REV_NO', 'C', 8), ('QTY', 'N', 8)],
                            {'QUOTE_NO': '0000001', 'COMP_ID': '000001', 'PART_NO': 'P-1', 'JOBNO': 'SYNTHETIC-J', 'REV_NO': 'B', 'QTY': '999'}),
            'sales_lot': ([('JOBNO', 'C', 12), ('COMP_ID', 'C', 6), ('WO_NO', 'C', 12), ('LOT', 'C', 4)],
                          {'JOBNO': 'SYNTHETIC-J', 'COMP_ID': '000001', 'WO_NO': 'SYNTHETIC-WO', 'LOT': '1'}),
            'work_order': ([('WO_NO', 'C', 12), ('COMP_ID', 'C', 6), ('PART_NO', 'C', 16), ('REV_NO', 'C', 8), ('QTY', 'N', 8)],
                           {'WO_NO': 'SYNTHETIC-WO', 'COMP_ID': '000001', 'PART_NO': 'P-1', 'REV_NO': 'B', 'QTY': '999'}),
            'work_order_job': ([('JOBNO', 'C', 12), ('WO_NO', 'C', 12), ('LOT', 'C', 4)],
                               {'JOBNO': 'SYNTHETIC-J', 'WO_NO': 'SYNTHETIC-WO', 'LOT': '1'})}
        chain = {}
        for key, (fields, values) in self.native_specs.items():
            data, physical = synthetic_dbf(fields, values)
            chain[key] = {'source': self.write(FULL.NATIVE_TABLES[key], data), 'physical_record': physical}
        self.item['native_order_chains'] = [chain]
        return chain

    def change_native(self, key, values):
        fields, original = self.native_specs[key]
        data, physical = synthetic_dbf(fields, {**original, **values})
        self.item['native_order_chains'][0][key] = {'source': self.write(FULL.NATIVE_TABLES[key], data), 'physical_record': physical}

    def primary_chain(self, zero_outside=False):
        assumptions = {'material': 'synthetic steel', 'finish': 'none', 'routing': 'cut and bend', 'tolerances': 'D-1 revision A'}
        specification = self.primary('manufacturing_specification', 'synthetic-specification', '2026-10-01T07:00:00Z', manufacturing=assumptions)
        spec = {'source': self.write('specification.json', specification), 'pointer': ''}
        self.bind('rfq', self.primary('full_rfq_requirements', 'synthetic-rfq', '2026-10-01T08:00:00Z', schema_version=1,
            case_id=self.case_id, quote_date='2026-10-01', customer_id='000001', currency='USD',
            lines=[{'line_id': '1', 'identity': copy.deepcopy(self.identity), 'manufacturing': assumptions, 'manufacturing_evidence': spec}],
            terms={'payment_terms': 'Net 30', 'valid_until': '2026-10-31', 'lead_time_days': 10,
                   'shipping': '0.00', 'tax': '0.00', 'additional_charges': []}))
        self.bind('issuance', self.primary('customer_quote_issuance', 'synthetic-send', '2026-10-01T09:00:00Z',
            event='customer_quote_sent', letter='00000001', document_sha256=self.pdf['sha256'], rfq=self.item['rfq'],
            amount={'unit_price': '2.00000', 'extension': '20.00'}))
        self.bind('acceptance', self.primary('customer_order_acceptance', 'synthetic-acceptance', '2026-10-01T10:00:00Z',
            event='customer_accepted_order', customer_order_no='SYNTHETIC-PO', amount_basis='accepted_order',
            issued_quote=self.item['issuance'], amount={'unit_price': '2.00000', 'extension': '20.00'}))
        self.bind('work_order', self.primary('manufacturing_work_order', 'synthetic-work-order', '2026-10-01T11:00:00Z',
            job_no='SYNTHETIC-JOB', opened_at='2026-10-01T11:00:00Z', customer_order_no='SYNTHETIC-PO',
            acceptance=self.item['acceptance'], manufacturing=assumptions, manufacturing_evidence=spec))
        amounts = {'material': '4.00', 'labor': '5.00', 'outside': '0.00' if zero_outside else '2.00', 'setup': '1.00'}
        postings, ids = [], []
        for component, amount in amounts.items():
            if amount == '0.00':
                continue
            record_id = 'synthetic-posting-' + component
            posting = self.primary('actual_job_cost_posting', record_id, '2026-10-02T10:00:00Z', job_no='SYNTHETIC-JOB',
                                   component=component, amount=amount, basis='job_total', incurred_at='2026-10-02T09:00:00Z')
            postings.append({'source': self.write(component + '-posting.json', posting), 'pointer': ''})
            ids.append(record_id)
        period = {'period_start': '2026-10-01T11:00:00Z', 'period_end': '2026-10-03T12:00:00Z'}
        closure = self.primary('manufacturing_job_closure', 'synthetic-closure', '2026-10-02T12:00:00Z',
            job_no='SYNTHETIC-JOB', closed_at='2026-10-02T12:00:00Z', event='manufacturing_job_closed',
            work_order=self.item['work_order'], posting_record_ids=ids, components=amounts, **period)
        closure_ref = {'source': self.write('closure.json', closure), 'pointer': ''}
        zeros = []
        if zero_outside:
            zero = self.primary('closed_job_zero_cost_component', 'synthetic-zero-outside', '2026-10-02T12:00:00Z',
                job_no='SYNTHETIC-JOB', closure=closure_ref, component='outside', basis='job_total', amount='0.00',
                reason='The complete synthetic closed ledger contains no outside-service charge', **period)
            zeros.append({'component': 'outside', 'evidence': {'source': self.write('zero-outside.json', zero), 'pointer': ''}})
        self.bind('actual_cost', self.primary('actual_job_cost', 'synthetic-actual-cost', '2026-10-03T12:00:00Z',
            job_no='SYNTHETIC-JOB', amount_basis='actual_closed_job', work_order=self.item['work_order'], closure=closure_ref,
            amount={'unit_price': '1.00000' if zero_outside else '1.20000', 'extension': '10.00' if zero_outside else '12.00'},
            components=amounts, postings=postings, zero_components=zeros, **period))

    def build(self, cases=None):
        self.version += 1
        self.full_config['out'] = str(self.root / f'full-data-v{self.version}')
        self.full_config['confirmations'] = self.write('confirmations.json', {'schema_version': 1,
            'kind': 'historical_full_data_confirmations', 'prepared_by': self.preparer, 'cases': cases if cases is not None else [self.item]})
        summary = FULL.build(self.full_config)
        output = Path(self.full_config['out'])
        audit = GROUND.parse_json((output / 'all-case-tags.private.json').read_bytes())
        return summary, audit, output

    def independent_review(self):
        _, audit, _ = self.build()
        findings = [{'condition': name, 'verdict': 'VERIFIED', 'identity': self.identity, 'reason': 'Inspected the supplied synthetic primary bytes and reconciled the condition',
                     'sources': FULL.source_refs(audit['cases'][0]['tags'][name]['provenance'])} for name in FULL.MANDATORY[:-1]]
        review = self.primary('historical_full_data_source_review', 'synthetic-review', '2026-10-03T14:00:00Z',
            case_id=self.case_id, reviewer_id='synthetic-independent-reviewer', executor_id='synthetic-independent-executor',
            started_at='2026-10-03T13:00:00Z', finished_at='2026-10-03T14:00:00Z', findings=findings)
        self.bind('review', review)
        receipt = {'kind': 'historical_full_data_review_execution', 'case_id': self.case_id,
                   'review_source_sha256': self.item['review']['source']['sha256'], 'reviewer_id': review['reviewer_id'],
                   'executor_id': review['executor_id'], 'review_job_id': 'synthetic-review-job',
                   'started_at': review['started_at'], 'finished_at': review['finished_at'],
                   'sources': FULL.source_refs([finding['sources'] for finding in findings])}
        self.bind('review_receipt', receipt)


class FullDataTests(unittest.TestCase):
    def test_native_quote_level_pointer_is_non_gating_deduplicated_and_cached(self):
        fixture = FullFixture(self)
        fixture.candidates()
        chain = fixture.native_chain()
        fixture.item['native_order_chains'].append(chain)
        with mock.patch.object(FULL.h, 'private_bytes', wraps=FULL.h.private_bytes) as reader:
            summary, audit, output = fixture.build()
        tags = audit['cases'][0]['tags']
        self.assertEqual(tags['erp_quote_work_order_pointer_verified']['value'], 1)
        self.assertEqual(tags['erp_quote_work_order_pointer_verified']['state'], 'QUOTE_LEVEL_ERP_POINTER_ONLY')
        self.assertEqual(len(tags['erp_quote_work_order_pointer_verified']['observations']), 1)
        self.assertEqual((summary['native_order_chains_supplied'], summary['unique_verified_native_order_chains']), (2, 1))
        self.assertEqual(tags['work_order_candidate_present']['value'], 1)
        self.assertNotIn('erp_quote_work_order_pointer_verified', FULL.MANDATORY)
        for name in ('work_order_link_confirmed', 'customer_acceptance_confirmed', 'closed_job_actual_cost_complete',
                     'manufacturing_identity_confirmed', 'quantity_currency_uom_confirmed'):
            self.assertEqual(tags[name]['value'], 0)
        self.assertEqual(summary['eligible'], 0)
        for key, reference in chain.items():
            large_reads = [call for call in reader.call_args_list if call.args == (reference['source']['path'], FULL.NATIVE_LIMIT)]
            self.assertEqual(len(large_reads), 2, key)
        manifest = GROUND.parse_json((output / 'manifest.json').read_bytes())
        self.assertEqual(manifest['native_input_pins'], {reference['source']['path']: reference['source']['sha256'] for reference in chain.values()})
        self.assertTrue(set(manifest['native_input_pins']) <= set(manifest['inputs']))
        self.assertEqual(manifest['source_limits']['native_order_chain_bytes'], 128 * 1024 * 1024)
        self.assertEqual(manifest['source_limits']['default_bytes'], 64 * 1024 * 1024)
        conflict = FULL.h.EvidenceIO()
        conflict.inputs[chain['sales_order']['source']['path']] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'NATIVE_INPUT_PIN_CONFLICT'):
            FULL.native_row(chain['sales_order'], 'SOMAST.DBF', conflict, {}, {})
        targets = audit['cases'][0]['evidence_roles']['post_quote_operator_only_target_references']
        self.assertTrue(set(manifest['native_input_pins']) <= {ref['path'] for ref in targets})

    def test_native_pointer_fk_source_and_physical_attacks_remain_rejections(self):
        for attack, key, changed in (
                ('job', 'sales_lot', {'JOBNO': 'WRONG-JOB'}),
                ('job_tail', 'work_order_job', {'JOBNO': 'WRONG-JOB'}),
                ('order_customer', 'sales_order', {'COMP_ID': '000002'}),
                ('lot_customer', 'sales_lot', {'COMP_ID': '000002'}),
                ('work_customer', 'work_order', {'COMP_ID': '000002'}),
                ('part', 'work_order', {'PART_NO': 'P-2'}),
                ('quote', 'sales_order', {'QUOTE_NO': '0000002'}),
                ('lot', 'work_order_job', {'LOT': '2'}),
                ('work_number', 'work_order_job', {'WO_NO': 'WRONG-WO'}),
                ('blank_job', 'sales_order', {'JOBNO': ''}),
                ('blank_work', 'sales_lot', {'WO_NO': ''}),
                ('blank_lot', 'sales_lot', {'LOT': ''}),
                ('source_hash', 'sales_order', None),
                ('physical_hash', 'sales_lot', None),
                ('table', 'sales_order', None),
                ('narrative', 'sales_order', None)):
            with self.subTest(attack=attack):
                fixture = FullFixture(self)
                chain = fixture.native_chain()
                if changed is not None:
                    fixture.change_native(key, changed)
                elif attack == 'source_hash':
                    chain[key]['source']['sha256'] = '0' * 64
                elif attack == 'physical_hash':
                    chain[key]['physical_record']['record_sha256'] = '0' * 64
                elif attack == 'table':
                    chain[key]['source'] = fixture.write('NOT-SOMAST.DBF', Path(chain[key]['source']['path']).read_bytes())
                else:
                    chain[key] = {'source': fixture.write('pointer-assertion.json', {'quote_link_confirmed': True}), 'pointer': ''}
                summary, audit, _ = fixture.build()
                tag = audit['cases'][0]['tags']['erp_quote_work_order_pointer_verified']
                self.assertEqual((tag['value'], summary['erp_quote_work_order_pointer_cases']), (0, 0))
                self.assertEqual(len(tag['rejected_references']), 1)
                self.assertTrue(tag['rejected_references'][0]['reason'])

    def test_one_verified_native_pointer_preserves_rejected_alternatives_and_limit(self):
        fixture = FullFixture(self)
        chain = fixture.native_chain()
        bad = copy.deepcopy(chain)
        bad['sales_order']['source']['sha256'] = '0' * 64
        fixture.item['native_order_chains'].append(bad)
        summary, audit, _ = fixture.build()
        self.assertEqual(summary['erp_quote_work_order_pointer_cases'], 1)
        self.assertEqual(summary['rejected_native_order_chains'], 1)
        self.assertEqual(len(audit['cases'][0]['tags']['erp_quote_work_order_pointer_verified']['observations']), 1)
        self.assertEqual(audit['cases'][0]['tags']['erp_quote_work_order_pointer_verified']['rejected_references'][0]['reason'], 'NATIVE_INPUT_PIN_CONFLICT')
        fixture.item['native_order_chains'] = [chain] * 10001
        with self.assertRaisesRegex(ValueError, 'INVALID_NATIVE_ORDER_CHAINS'):
            fixture.build()

    def test_native_128mib_limit_is_narrow_and_standard_reader_stays_64mib(self):
        fixture = FullFixture(self)
        chain = fixture.native_chain()
        source = chain['sales_order']['source']
        path = Path(source['path'])
        with path.open('r+b') as stream:
            stream.truncate(64 * 1024 * 1024 + 4096)
        source['sha256'] = GROUND.digest(path.read_bytes())
        with self.assertRaisesRegex(ValueError, 'PRIVATE_FILE_REQUIRED'):
            GROUND.private_bytes(str(path))
        summary, _, output = fixture.build()
        self.assertEqual(summary['erp_quote_work_order_pointer_cases'], 1)
        seal = GROUND.parse_json((output / 'seal.json').read_bytes())
        self.assertEqual(seal['native_input_pins'][str(path)], source['sha256'])
        with path.open('r+b') as stream:
            stream.truncate(FULL.NATIVE_LIMIT + 1)
        source['sha256'] = '0' * 64
        summary, audit, _ = fixture.build()
        self.assertEqual(summary['erp_quote_work_order_pointer_cases'], 0)
        self.assertEqual(audit['cases'][0]['tags']['erp_quote_work_order_pointer_verified']['rejected_references'][0]['reason'], 'PRIVATE_FILE_REQUIRED')
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_NATIVE_TABLE'):
            FULL.native_row(chain['sales_order'], 'WOBILL.DBF', FULL.h.EvidenceIO(), {}, {})

    def test_native_inputs_are_rehashed_before_publication(self):
        fixture = FullFixture(self)
        fixture.native_chain()
        original = FULL.native_row
        def changed_after_read(reference, table, evidence, inputs, cache):
            row = original(reference, table, evidence, inputs, cache)
            if table == 'SOMAST.DBF':
                with Path(reference['source']['path']).open('ab') as stream:
                    stream.write(b'changed-synthetic-input')
            return row
        with mock.patch.object(FULL, 'native_row', side_effect=changed_after_read):
            with self.assertRaisesRegex(ValueError, 'NATIVE_INPUT_CHANGED'):
                fixture.build()

    def test_empty_set_retains_all_cases_and_not_established_reasons(self):
        fixture = FullFixture(self)
        summary, audit, output = fixture.build()
        self.assertEqual((summary['cases'], summary['eligible'], summary['excluded']), (1, 0, 1))
        self.assertEqual((output / 'eligible-historical-cases.jsonl').read_bytes(), b'')
        case = audit['cases'][0]
        self.assertEqual(case['tags']['internal_calculation_verified']['value'], 1)
        self.assertEqual(case['tags']['recorded_customer_amount_verified']['value'], 1)
        self.assertEqual(case['tags']['issued_customer_quote_matches_case']['value'], 0)
        self.assertEqual(case['business_outcome'], 'NOT_ESTABLISHED')
        self.assertTrue(case['exclusion_reasons'])
        excluded = json.loads((output / 'excluded-cases.private.jsonl').read_bytes())
        self.assertEqual(excluded['original_case'], fixture.case)
        with (output / 'all-case-tags.private.csv').open(newline='') as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['full_data_eligible'], '0')
        for tag in case['tags'].values():
            self.assertIs(type(tag['value']), int)
            self.assertIn(tag['value'], (0, 1))
            self.assertTrue(tag['state'] and tag['reason'])
            self.assertIsInstance(tag['provenance'], list)

    def test_original_work_order_candidate_does_not_imply_revision_quantity_link_or_acceptance(self):
        fixture = FullFixture(self)
        reference = fixture.candidates()
        fixture.item['candidate'].append(reference)
        summary, audit, _ = fixture.build()
        tags = audit['cases'][0]['tags']
        self.assertEqual(summary['candidate_references_supplied'], 2)
        self.assertEqual(summary['unique_verified_candidate_records'], 1)
        self.assertEqual(tags['work_order_candidate_present']['value'], 1)
        self.assertEqual(len(tags['work_order_candidate_present']['observations']), 1)
        self.assertEqual(tags['work_order_candidate_present']['observations'][0]['fields']['REV_NO'], 'B')
        for name in ('work_order_link_confirmed', 'customer_acceptance_confirmed', 'closed_job_actual_cost_complete'):
            self.assertEqual(tags[name]['value'], 0)
        self.assertEqual(summary['eligible'], 0)

    def test_candidate_hash_physical_customer_part_and_table_attacks_fail_closed(self):
        for attack in ('file_hash', 'record_hash', 'offset', 'customer', 'part', 'table', 'narrative'):
            with self.subTest(attack=attack):
                fixture = FullFixture(self)
                reference = fixture.candidates()
                if attack == 'file_hash':
                    reference['source']['sha256'] = '0' * 64
                elif attack == 'record_hash':
                    reference['physical_record']['record_sha256'] = '0' * 64
                elif attack == 'offset':
                    reference['physical_record']['byte_offset'] += 1
                elif attack in ('customer', 'part'):
                    fields = [('WO_NO', 'C', 12), ('COMP_ID', 'C', 6), ('PART_NO', 'C', 16)]
                    data, physical = synthetic_dbf(fields, {'WO_NO': 'SYNTHETIC-WO', 'COMP_ID': '000002' if attack == 'customer' else '000001',
                                                          'PART_NO': 'P-2' if attack == 'part' else 'P-1'})
                    reference.update(source=fixture.write('WOHEAD.DBF', data), physical_record=physical)
                elif attack == 'table':
                    reference['source'] = fixture.write('QUOTEN-copy.DBF', Path(reference['source']['path']).read_bytes())
                else:
                    fixture.item['candidate'] = [{'source': fixture.write('narrative.json', {'full_data_eligible': True, 'won': True}), 'pointer': ''}]
                summary, audit, _ = fixture.build()
                self.assertEqual(summary['work_order_candidate_cases'], 0)
                self.assertTrue(audit['cases'][0]['tags']['work_order_candidate_present']['rejected_references'])

    def test_all_250_cases_and_102_candidate_cases_are_source_bound_not_assumed(self):
        fixture = FullFixture(self)
        cases = [fixture.case] + [{**fixture.case, 'id': f'0000001|{index}@10'} for index in range(1, 250)]
        fixture.config['evalset'] = fixture.write('evalset.jsonl', b''.join(GROUND.encode(case) for case in cases))
        fixture.config['expected_cases'] = 250
        fixture.full_config['assessment_config'] = fixture.write('assessment-config.private.json', fixture.config)
        fixture.manifest['frozen_evalset'] = {**fixture.config['evalset'], 'bytes': Path(fixture.config['evalset']['path']).stat().st_size}
        fixture.config['source_manifest'] = fixture.write('source-manifest.json', {'inputs': fixture.manifest})
        fixture.full_config['assessment_config'] = fixture.write('assessment-config.private.json', fixture.config)
        data, first = synthetic_dbf([('COMP_ID', 'C', 6), ('PART_NO', 'C', 16)], {'COMP_ID': '000001', 'PART_NO': 'P-1'})
        count, start, length = struct.unpack_from('<IHH', data, 4)
        self.assertEqual(count, 1)
        header = bytearray(data[:start])
        struct.pack_into('<I', header, 4, 853)
        record = data[start:start + length]
        source = fixture.write('WOHEAD.DBF', bytes(header) + record * 853 + b'\x1a')
        physical = [{**first, 'record_index': index, 'record_no': index + 1, 'byte_offset': start + index * length} for index in range(853)]
        declarations, index = [], 0
        for case_index in range(102):
            size = 8 if case_index < 101 else 45
            declarations.append({'case_id': cases[case_index]['id'], 'candidate': [
                {'source': source, 'physical_record': physical[pos]} for pos in range(index, index + size)]})
            index += size
        summary, audit, output = fixture.build(declarations)
        self.assertEqual((summary['cases'], summary['work_order_candidate_cases'], summary['unique_verified_candidate_records']), (250, 102, 853))
        self.assertEqual(summary['eligible'], 0)
        self.assertEqual(len(audit['cases']), 250)
        self.assertEqual(len((output / 'excluded-cases.private.jsonl').read_bytes().splitlines()), 250)
        self.assertTrue(all(case['tags']['customer_acceptance_confirmed']['value'] == 0 for case in audit['cases']))

    def test_positive_historical_chain_uses_fixed_and_and_preserves_original_case_bytes(self):
        fixture = FullFixture(self)
        original = b'{ "synthetic_extra":{"target_basis":"unchanged"}, ' + GROUND.encode(fixture.case)[1:].rstrip(b'\n')
        original = original.replace(b'"actual_unit_price":"2.50000"', b'"actual_unit_price":2.50000')
        fixture.config['evalset'] = fixture.write('evalset.jsonl', original + b'\n')
        fixture.manifest['frozen_evalset'] = {**fixture.config['evalset'], 'bytes': len(original) + 1}
        fixture.config['source_manifest'] = fixture.write('source-manifest.json', {'inputs': fixture.manifest})
        fixture.full_config['assessment_config'] = fixture.write('assessment-config.private.json', fixture.config)
        fixture.primary_chain()
        fixture.independent_review()
        summary, audit, output = fixture.build()
        self.assertEqual(summary['eligible'], 1)
        tags = audit['cases'][0]['tags']
        self.assertTrue(all(tags[name]['value'] == 1 for name in FULL.MANDATORY))
        self.assertEqual(tags['current_quote_support_verified']['value'], 0)
        self.assertEqual(tags['business_optimum_verified']['value'], 0)
        self.assertEqual(tags['work_order_candidate_present']['value'], 0)
        self.assertEqual((output / 'eligible-historical-cases.jsonl').read_bytes(), original + b'\n')
        self.assertEqual((output / 'excluded-cases.private.jsonl').read_bytes(), b'')
        manifest = GROUND.parse_json((output / 'manifest.json').read_bytes())
        self.assertEqual(manifest['mandatory_tags'], list(FULL.MANDATORY))
        self.assertFalse(audit['cases'][0]['evidence_roles']['worker_context_generated'])
        self.assertNotIn(b'SYNTHETIC-PO', (output / 'eligible-historical-cases.jsonl').read_bytes())
        for name in FULL.MANDATORY:
            self.assertIn(name + ' == 1', manifest['eligibility_predicate'])

    def test_explicit_zero_component_requires_independent_closure_disposition(self):
        fixture = FullFixture(self)
        fixture.primary_chain(zero_outside=True)
        fixture.independent_review()
        self.assertEqual(fixture.build()[0]['eligible'], 1)
        cost = copy.deepcopy(fixture.records['actual_cost'])
        cost['zero_components'] = []
        fixture.bind('actual_cost', cost)
        _, audit, _ = fixture.build()
        self.assertEqual(audit['cases'][0]['tags']['closed_job_actual_cost_complete']['value'], 0)
        self.assertIn('ZERO_COMPONENT', audit['cases'][0]['tags']['closed_job_actual_cost_complete']['reason'])

    def test_partial_duplicate_estimated_wrong_job_and_bad_totals_cannot_be_complete_actual_cost(self):
        for attack in ('missing_posting', 'duplicate', 'estimated', 'wrong_job', 'bad_component', 'open_job', 'closure_omits_posting'):
            with self.subTest(attack=attack):
                fixture = FullFixture(self)
                fixture.primary_chain()
                cost = copy.deepcopy(fixture.records['actual_cost'])
                if attack == 'missing_posting':
                    cost['postings'] = cost['postings'][:-1]
                elif attack == 'duplicate':
                    cost['postings'].append(cost['postings'][0])
                elif attack == 'estimated':
                    cost['amount_basis'] = 'estimated_job'
                elif attack == 'wrong_job':
                    cost['job_no'] = 'WRONG-JOB'
                elif attack == 'bad_component':
                    cost['components']['labor'] = '4.00'
                else:
                    closure = GROUND.parse_json(Path(cost['closure']['source']['path']).read_bytes())
                    if attack == 'open_job':
                        closure['event'] = 'manufacturing_job_open'
                    else:
                        closure['posting_record_ids'] = closure['posting_record_ids'][:-1]
                    cost['closure'] = {'source': fixture.write('changed-closure.json', closure), 'pointer': ''}
                fixture.bind('actual_cost', cost)
                summary, audit, _ = fixture.build()
                self.assertEqual(summary['eligible'], 0)
                self.assertEqual(audit['cases'][0]['tags']['closed_job_actual_cost_complete']['value'], 0)

    def test_customer_quote_link_full_rfq_manufacturing_units_and_chronology_are_checked(self):
        for key, field, value, tag in (
                ('issuance', 'document_sha256', '0' * 64, 'issued_customer_quote_matches_case'),
                ('acceptance', 'event', 'won_history', 'customer_acceptance_confirmed'),
                ('work_order', 'customer_order_no', 'UNRELATED-PO', 'work_order_link_confirmed'),
                ('rfq', 'terms', {}, 'full_rfq_verified'),
                ('work_order', 'manufacturing', {'material': 'wrong', 'finish': 'none', 'routing': 'cut and bend', 'tolerances': 'D-1 revision A'}, 'manufacturing_identity_confirmed'),
                ('acceptance', 'identity', {'currency': 'EUR'}, 'quantity_currency_uom_confirmed'),
                ('acceptance', 'identity', {'uom': 'LB'}, 'quantity_currency_uom_confirmed'),
                ('acceptance', 'identity', {'quantity': 11}, 'quantity_currency_uom_confirmed'),
                ('acceptance', 'identity', {'revision': 'B'}, 'quantity_currency_uom_confirmed'),
                ('acceptance', 'identity', {'drawing_no': 'D-2'}, 'quantity_currency_uom_confirmed'),
                ('acceptance', 'recorded_at', '2026-10-05T10:00:00Z', 'customer_acceptance_confirmed'),
                ('acceptance', 'recorded_at', '2026-10-01T08:30:00Z', 'chronology_confirmed')):
            with self.subTest(key=key, field=field):
                fixture = FullFixture(self)
                fixture.primary_chain()
                changed = copy.deepcopy(fixture.records[key])
                changed[field] = {**changed[field], **value} if field == 'identity' else value
                fixture.bind(key, changed)
                if key == 'acceptance':
                    job = copy.deepcopy(fixture.records['work_order'])
                    job['acceptance'] = fixture.item['acceptance']
                    fixture.bind('work_order', job)
                    cost = copy.deepcopy(fixture.records['actual_cost'])
                    cost['work_order'] = fixture.item['work_order']
                    closure = GROUND.parse_json(Path(cost['closure']['source']['path']).read_bytes())
                    closure['work_order'] = fixture.item['work_order']
                    cost['closure'] = {'source': fixture.write('changed-closure.json', closure), 'pointer': ''}
                    fixture.bind('actual_cost', cost)
                _, audit, _ = fixture.build()
                self.assertEqual(audit['cases'][0]['tags'][tag]['value'], 0)

    def test_independent_review_rejects_self_review_boolean_hash_and_receipt_forgery(self):
        for attack in ('self', 'boolean', 'hash', 'negative_finding', 'receipt', 'missing_receipt'):
            with self.subTest(attack=attack):
                fixture = FullFixture(self)
                fixture.primary_chain()
                fixture.independent_review()
                review = copy.deepcopy(fixture.records['review'])
                if attack == 'self':
                    review['reviewer_id'] = fixture.preparer
                elif attack == 'boolean':
                    review['findings'] = [{'condition': name, 'passed': True} for name in FULL.MANDATORY[:-1]]
                elif attack == 'hash':
                    review['findings'][0]['sources'][0]['sha256'] = '0' * 64
                elif attack == 'negative_finding':
                    review['findings'][0]['verdict'] = 'NOT_ESTABLISHED'
                elif attack == 'receipt':
                    receipt = copy.deepcopy(fixture.records['review_receipt'])
                    receipt['sources'] = []
                    fixture.bind('review_receipt', receipt)
                else:
                    del fixture.item['review_receipt']
                if attack in ('self', 'boolean', 'hash', 'negative_finding'):
                    fixture.bind('review', review)
                summary, audit, _ = fixture.build()
                self.assertEqual(summary['eligible'], 0)
                self.assertEqual(audit['cases'][0]['tags']['independent_source_review_confirmed']['value'], 0)

    def test_existing_domain_assertions_and_scores_never_select_membership(self):
        fixture = FullFixture(self)
        fixture.primary_chain()
        fixture.independent_review()
        self.assertEqual(fixture.build()[0]['eligible'], 1)
        candidate = GROUND.parse_json(Path(fixture.candidate['path']).read_bytes())
        candidate['results'][0].update(predicted='999.00000', all_pass=True, ape='998', criteria={'price': {'pass': True}})
        fixture.config['candidate_report'] = fixture.write('candidate.json', candidate)
        fixture.manifest['candidate_report'] = {**fixture.config['candidate_report'], 'bytes': Path(fixture.candidate['path']).stat().st_size}
        fixture.config['source_manifest'] = fixture.write('source-manifest.json', {'inputs': fixture.manifest})
        assertion = fixture.write('assertion.json', {'kind': 'operator_assertion', 'identity': fixture.identity, 'full_data_eligible': True})
        fixture.config['confirmed_evidence'] = [{'case_id': fixture.case_id, 'domain': 'actual_manufacturing_cost',
            'authority': 'operator_assertion', 'evidence': {'source': assertion, 'pointer': ''}}]
        fixture.full_config['assessment_config'] = fixture.write('assessment-config.private.json', fixture.config)
        self.assertEqual(fixture.build()[0]['eligible'], 1)
        fixture.bind('acceptance', {'kind': 'operator_assertion', 'identity': fixture.identity, 'accepted': True})
        self.assertEqual(fixture.build()[0]['eligible'], 0)

    def test_fixed_semantics_population_and_private_artifact_guards(self):
        fixture = FullFixture(self)
        fixture.full_config['required_tags'] = ['internal_calculation_verified']
        with self.assertRaisesRegex(ValueError, 'INVALID_SCHEMA'):
            fixture.build()
        del fixture.full_config['required_tags']
        fixture.item['full_data_eligible'] = True
        with self.assertRaisesRegex(ValueError, 'INVALID_SCHEMA'):
            fixture.build()
        del fixture.item['full_data_eligible']
        with self.assertRaisesRegex(ValueError, 'UNDECLARED'):
            fixture.build([{'case_id': 'not-in-frozen-population'}])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_CONFIRMATION_CASE'):
            fixture.build([fixture.item, fixture.item])
        fixture.build()
        with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS'):
            FULL.build(fixture.full_config)
        reference = fixture.candidates()
        Path(reference['source']['path']).chmod(0o644)
        self.assertEqual(fixture.build()[0]['work_order_candidate_cases'], 0)
        Path(reference['source']['path']).chmod(0o600)
        link = fixture.root / 'candidate-alias.DBF'
        link.symlink_to(reference['source']['path'])
        reference['source']['path'] = str(link)
        self.assertEqual(fixture.build()[0]['work_order_candidate_cases'], 0)

    def test_seals_reproduce_hashes_and_outputs_stay_private_under_umask022(self):
        fixture = FullFixture(self)
        fixture.primary_chain()
        fixture.independent_review()
        prior = os.umask(0o022)
        try:
            _, _, first = fixture.build()
            _, _, second = fixture.build()
        finally:
            os.umask(prior)
        for output in (first, second):
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            seal = GROUND.parse_json((output / 'seal.json').read_bytes())
            for name, digest in seal['files'].items():
                self.assertEqual(GROUND.digest((output / name).read_bytes()), digest)
            for path in output.rglob('*'):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o400)
            self.assertIn('keller-full-data-set.py', seal['implementation_sha256'])
            self.assertIn('keller-ground-truth.py', seal['implementation_sha256'])
        for path in first.iterdir():
            if path.is_file():
                self.assertEqual(path.read_bytes(), (second / path.name).read_bytes())

    def test_cli_stdout_is_counts_only_and_invalid_inputs_fail_without_source_disclosure(self):
        fixture = FullFixture(self)
        fixture.candidates()
        fixture.full_config['confirmations'] = fixture.write('confirmations.json', {'schema_version': 1,
            'kind': 'historical_full_data_confirmations', 'prepared_by': fixture.preparer, 'cases': [fixture.item]})
        config = fixture.write('full-config.json', fixture.full_config)
        result = subprocess.run(['python', '-B', str(REPO / 'scripts/keller-full-data-set.py'), '--config', config['path']], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        def counts_only(value):
            return all(counts_only(item) for item in value.values()) if isinstance(value, dict) else type(value) is int
        self.assertTrue(counts_only(json.loads(result.stdout)))
        for private_value in ('P-1', fixture.case_id, str(fixture.root), '2.50000'):
            self.assertNotIn(private_value, result.stdout)
        invalid = subprocess.run(['python', '-B', str(REPO / 'scripts/keller-full-data-set.py'), '--config', config['path']], capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(invalid.stdout, '')
        self.assertNotIn(str(fixture.root), invalid.stderr)

    def test_candidate_only_supplement_can_omit_preparer_and_bom_case_remains_valid(self):
        fixture = FullFixture(self)
        fixture.candidates()
        fixture.config['evalset'] = fixture.write('evalset.jsonl', b'\xef\xbb\xbf' + GROUND.encode(fixture.case))
        fixture.manifest['frozen_evalset'] = {**fixture.config['evalset'], 'bytes': Path(fixture.config['evalset']['path']).stat().st_size}
        fixture.config['source_manifest'] = fixture.write('source-manifest.json', {'inputs': fixture.manifest})
        fixture.full_config['assessment_config'] = fixture.write('assessment-config.private.json', fixture.config)
        fixture.full_config['confirmations'] = fixture.write('confirmations.json', {'schema_version': 1,
            'kind': 'historical_full_data_confirmations', 'cases': [fixture.item]})
        summary = FULL.build(fixture.full_config)
        self.assertEqual(summary['work_order_candidate_cases'], 1)
        excluded = json.loads((Path(fixture.full_config['out']) / 'excluded-cases.private.jsonl').read_bytes())
        self.assertEqual(excluded['original_case'], fixture.case)


if __name__ == '__main__':
    unittest.main()
