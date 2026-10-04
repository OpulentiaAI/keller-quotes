#!/usr/bin/env python3
"""Build a private, source-selected historical case set without changing targets."""
import argparse
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys


SPEC = importlib.util.spec_from_file_location('keller_full_data_helpers', Path(__file__).with_name('keller-ground-truth.py'))
h = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(h)
MANDATORY = ('internal_calculation_verified', 'issued_customer_quote_matches_case', 'full_rfq_verified',
             'work_order_link_confirmed', 'customer_acceptance_confirmed', 'closed_job_actual_cost_complete',
             'manufacturing_identity_confirmed', 'quantity_currency_uom_confirmed', 'chronology_confirmed',
             'independent_source_review_confirmed')
OPTIONAL = ('recorded_customer_amount_verified', 'work_order_candidate_present',
            'current_quote_support_verified', 'business_optimum_verified', 'erp_quote_work_order_pointer_verified')
FIELDS = ('rfq', 'issuance', 'acceptance', 'work_order', 'actual_cost', 'current_quote', 'review', 'review_receipt')
COMPONENTS = ('material', 'labor', 'outside', 'setup')
NATIVE_TABLES = {'sales_order': 'SOMAST.DBF', 'sales_lot': 'SOLOTS.DBF',
                 'work_order': 'WOHEAD.DBF', 'work_order_job': 'WOJOBS.DBF'}
NATIVE_LIMIT = 128 * 1024 * 1024
LIMITATIONS = ('Binary zero means not established, not a verified negative or lost order. '
               'Source kinds, named reviewers and receipts are supplied provenance, not cryptographic issuer or human authentication; '
               'external primary-source authenticity and reviewer independence approval remain necessary. '
               'Completeness is relative to the independently supplied primary RFQ, closure and ledger enumeration. '
               'Native ERP pointers establish quote-level stored foreign-key equality only, not acceptance, quote-item, revision, quantity, drawing or complete cost. '
               'No model-performance selection, target substitution, current-vendor-freshness requirement, optimum certification, '
               'business outcome, blinded confirmation or customer release is established.')


def source_refs(value):
    found = {}
    def visit(item):
        if isinstance(item, dict):
            if set(item) == {'path', 'sha256'}:
                found[item['path']] = item['sha256']
            else:
                for child in item.values():
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    return [{'path': path, 'sha256': sha} for path, sha in sorted(found.items())]


def primary(record, kind, identity, as_of, preparer):
    h.require(record.get('kind') == kind, 'PRIMARY_RECORD_KIND_REQUIRED')
    h.text(record.get('record_id'))
    h.require(h.text(record.get('issuer')).casefold() not in ('agent', 'operator', (preparer or 'NOT_SUPPLIED').casefold()), 'OPERATOR_ASSERTION_NOT_PRIMARY')
    h.require(h.timestamp(record.get('recorded_at')).date().isoformat() <= as_of, 'LATER_EVIDENCE')
    h.verify_identity(record.get('identity'), identity, full=True)
    return record


def manufacturing(value):
    h.shape(value, ('material', 'finish', 'routing', 'tolerances'))
    for item in value.values():
        h.text(item)
    return value


def native_row(reference, table, evidence, native_inputs, cache):
    h.require(table in NATIVE_TABLES.values(), 'UNSUPPORTED_NATIVE_TABLE')
    h.shape(reference, ('source', 'physical_record'))
    source = h.shape(reference['source'], ('path', 'sha256'))
    h.require(isinstance(source['sha256'], str) and h.re.fullmatch(r'[a-f0-9]{64}', source['sha256']), 'INVALID_HASH')
    h.require(Path(source['path']).name.upper() == table, 'NATIVE_TABLE_SOURCE_MISMATCH')
    physical = h.shape(reference['physical_record'], ('record_index', 'record_no', 'byte_offset', 'record_sha256', 'raw_field_hex'),
                       ('record_index', 'record_no', 'byte_offset', 'record_sha256'))
    path, expected = source['path'], source['sha256']
    h.require(path not in evidence.inputs or evidence.inputs[path] == expected, 'NATIVE_INPUT_PIN_CONFLICT')
    if path not in cache:
        data = h.private_bytes(path, NATIVE_LIMIT)
        h.require(h.digest(data) == expected, 'DIGEST_MISMATCH')
        cache[path] = (expected, data)
    h.require(cache[path][0] == expected, 'NATIVE_INPUT_PIN_CONFLICT')
    native_inputs[path] = expected
    return h.dbf_record(cache[path][1], physical)


def build(config):
    h.shape(config, ('schema_version', 'as_of', 'assessment_config', 'confirmations', 'out'))
    h.require(type(config['schema_version']) is int and config['schema_version'] == 1, 'INVALID_FULL_DATA_CONFIG')
    as_of = h.iso_date(config['as_of'])
    evidence = h.EvidenceIO()
    assessment_config = evidence.json(config['assessment_config'])
    h.require(assessment_config['as_of'] == as_of, 'ASSESSMENT_AS_OF_MISMATCH')
    supplement = evidence.json(config['confirmations'])
    h.shape(supplement, ('schema_version', 'kind', 'prepared_by', 'cases'), ('schema_version', 'kind', 'cases'))
    h.require(type(supplement['schema_version']) is int and supplement['schema_version'] == 1 and
              supplement['kind'] == 'historical_full_data_confirmations' and isinstance(supplement['cases'], list) and
              len(supplement['cases']) <= 10000, 'INVALID_CONFIRMATIONS')
    preparer = h.text(supplement['prepared_by']) if 'prepared_by' in supplement else None
    declared = {}
    for item in supplement['cases']:
        h.shape(item, ('case_id', 'candidate', 'native_order_chains', *FIELDS), ('case_id',))
        case_id = h.text(item['case_id'])
        h.require(case_id not in declared, 'DUPLICATE_CONFIRMATION_CASE')
        declared[case_id] = item
    destination = h.private_path(config['out'], directory=True, absent=True)
    raw_lines = [line for line in evidence.read(assessment_config['evalset']).splitlines() if line.strip()]
    originals = [h.parse_json(line) for line in raw_lines]
    original_ids = [h.text(case['id']) for case in originals]
    h.require(len(set(original_ids)) == len(original_ids) and set(declared) <= set(original_ids), 'UNDECLARED_OR_DUPLICATE_CASE')
    h.require(all(destination != Path(p) and destination not in Path(p).parents and Path(p) not in destination.parents
                  for p in evidence.inputs), 'OUTPUT_INPUT_ALIAS')
    destination.mkdir(mode=0o700)
    reopened_config = {**assessment_config, 'confirmed_evidence': [], 'out': str(destination / 'reopened-assessment')}
    h.assess(reopened_config)
    reopened_bytes = h.private_bytes(str(destination / 'reopened-assessment/assessment.private.json'))
    reopened = h.parse_json(reopened_bytes)
    reopened_files = {'reopened-assessment/' + name: h.digest(h.private_bytes(str(destination / 'reopened-assessment' / name)))
                      for name in ('assessment.private.json', 'aggregate.json', 'seal.json')}
    for path, sha in reopened['inputs'].items():
        evidence.read({'path': path, 'sha256': sha})
    h.require([case['id'] for case in reopened['cases']] == original_ids, 'REOPENED_POPULATION_MISMATCH')
    results, eligible, excluded = [], [], []
    candidate_physical = set()
    candidate_references = 0
    native_inputs, native_cache, native_chains = {}, {}, set()
    native_references = 0
    for assessed, raw_line in zip(reopened['cases'], raw_lines):
        case_id, identity = assessed['id'], assessed['identity']
        item = declared.get(case_id, {'case_id': case_id})
        records, errors = {}, {}
        tags = {name: {'value': 0, 'state': 'NOT_ESTABLISHED', 'reason': 'NO_INDEPENDENT_PRIMARY_RECORD', 'provenance': []}
                for name in (*MANDATORY, *OPTIONAL)}
        def check(name, fn, provenance):
            tags[name]['provenance'] = provenance
            try:
                observations = fn()
                tags[name].update(value=1, state='VERIFIED_SUPPLIED_SOURCE_EVIDENCE',
                                  reason='SOURCE_BYTES_AND_CONDITION_RECONCILED', observations=observations)
            except (ValueError, OSError, KeyError, TypeError, ArithmeticError, IndexError, AttributeError, subprocess.SubprocessError) as error:
                tags[name]['reason'] = str(error) if isinstance(error, ValueError) else 'MALFORMED_OR_UNAVAILABLE_PRIMARY_EVIDENCE'
        def record(key):
            h.require(key in item, 'PRIMARY_RECORD_NOT_SUPPLIED:' + key)
            h.require(key not in errors, errors.get(key, 'PRIMARY_RECORD_UNAVAILABLE'))
            return records[key]
        def dependent(*names):
            h.require(all(tags[name]['value'] == 1 for name in names), 'REQUIRED_EVIDENCE_NOT_ESTABLISHED:' + ','.join(names))
        for key in FIELDS:
            if key in item:
                try:
                    records[key] = h.bound_record(item[key], evidence)
                except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
                    errors[key] = str(error) if isinstance(error, ValueError) else 'PRIMARY_RECORD_UNAVAILABLE'
        calculation = assessed['domains']['internal_calculation']
        document = assessed['domains']['recorded_customer_quote']
        document_source_refs = [
            {'path': assessment_config['source_paths'][name], 'sha256': reopened['inputs'][assessment_config['source_paths'][name]]}
            for name in ('QUOTLETT.DBF', 'QUOTLINE.DBF', 'QUOTLEIT.DBF')
            if name in assessment_config['source_paths'] and assessment_config['source_paths'][name] in reopened['inputs']]
        def calculation_verified():
            h.require(calculation['state'] == 'VERIFIED_SOURCE_BYTES', calculation.get('reason', 'CALCULATION_BYTES_UNVERIFIED'))
            return {key: calculation[key] for key in ('source_field', 'unit_price', 'extension', 'currency', 'uom')}
        check('internal_calculation_verified', calculation_verified, calculation.get('evidence', calculation.get('expected_evidence', [])))
        def recorded_verified():
            h.require(document['state'] == 'VERIFIED_RECORDED_AMOUNT', document.get('reason', 'RECORDED_DOCUMENT_UNVERIFIED'))
            return {key: document[key] for key in ('unit_price', 'extension', 'letter', 'target_comparable', 'original_availability')}
        check('recorded_customer_amount_verified', recorded_verified, document.get('evidence', [document.get('expected_evidence', {})]))
        candidate_refs = item.get('candidate', [])
        h.require(isinstance(candidate_refs, list) and len(candidate_refs) <= 10000, 'INVALID_CANDIDATE_REFERENCES')
        candidate_references += len(candidate_refs)
        h.require(candidate_references <= 10000, 'TOO_MANY_CANDIDATE_REFERENCES')
        observations, rejected, seen = [], [], set()
        for reference in candidate_refs:
            try:
                h.shape(reference, ('source', 'physical_record'))
                physical = h.shape(reference['physical_record'], ('record_index', 'record_no', 'byte_offset', 'record_sha256', 'raw_field_hex'),
                                   ('record_index', 'record_no', 'byte_offset', 'record_sha256'))
                h.require(Path(reference['source']['path']).name.upper() == 'WOHEAD.DBF', 'WOHEAD_SOURCE_REQUIRED')
                fields = h.dbf_record(evidence.read(reference['source']), physical)
                h.require(fields.get('COMP_ID') == identity['customer_id'] and fields.get('PART_NO') == identity['part_no'], 'CANDIDATE_CUSTOMER_PART_MISMATCH')
                physical_id = (reference['source']['sha256'], physical['record_index'])
                candidate_physical.add(physical_id)
                if physical_id not in seen:
                    seen.add(physical_id)
                    observations.append({'reference': reference, 'fields': fields, 'acceptance_linkage_cost': 'NOT_ESTABLISHED'})
            except (ValueError, OSError, KeyError, TypeError) as error:
                rejected.append({'reference': reference, 'reason': str(error) if isinstance(error, ValueError) else 'CANDIDATE_SOURCE_UNAVAILABLE'})
        tags['work_order_candidate_present'] = {'value': int(bool(observations)),
            'state': 'VERIFIED_SOURCE_CANDIDATE' if observations else 'NOT_ESTABLISHED',
            'reason': 'ORIGINAL_CUSTOMER_PART_CANDIDATE_EXISTS_ONLY' if observations else 'NO_VERIFIED_ORIGINAL_WORK_ORDER_CANDIDATE',
            'provenance': candidate_refs, 'observations': observations, 'rejected_references': rejected}
        chain_refs = item.get('native_order_chains', [])
        h.require(isinstance(chain_refs, list) and len(chain_refs) <= 10000, 'INVALID_NATIVE_ORDER_CHAINS')
        native_references += len(chain_refs)
        h.require(native_references <= 10000, 'TOO_MANY_NATIVE_ORDER_CHAINS')
        chain_observations, chain_rejections, seen_chains = [], [], set()
        for chain in chain_refs:
            rows = {}
            try:
                h.shape(chain, NATIVE_TABLES)
                rows = {key: native_row(chain[key], table, evidence, native_inputs, native_cache) for key, table in NATIVE_TABLES.items()}
                order, lot, work, job = [rows[key] for key in NATIVE_TABLES]
                job_no = h.text(order.get('JOBNO'))
                work_no, lot_no = h.text(lot.get('WO_NO')), h.text(lot.get('LOT'))
                mismatches = [reason for condition, reason in (
                    (order.get('QUOTE_NO') == identity['quote_no'] and order.get('COMP_ID') == identity['customer_id'] and
                     order.get('PART_NO') == identity['part_no'], 'NATIVE_ORDER_QUOTE_CUSTOMER_PART_MISMATCH'),
                    (job_no == h.text(lot.get('JOBNO')) == h.text(job.get('JOBNO')), 'NATIVE_JOBNO_MISMATCH'),
                    (lot.get('COMP_ID') == identity['customer_id'] and work.get('COMP_ID') == identity['customer_id'] and
                     work.get('PART_NO') == identity['part_no'], 'NATIVE_LOT_WORK_CUSTOMER_PART_MISMATCH'),
                    (work_no == h.text(work.get('WO_NO')) == h.text(job.get('WO_NO')), 'NATIVE_WO_NO_MISMATCH'),
                    (lot_no == h.text(job.get('LOT')), 'NATIVE_LOT_MISMATCH')) if not condition]
                h.require(not mismatches, ';'.join(mismatches))
                chain_id = tuple((chain[key]['source']['sha256'], chain[key]['physical_record']['record_index']) for key in NATIVE_TABLES)
                native_chains.add(chain_id)
                if chain_id not in seen_chains:
                    seen_chains.add(chain_id)
                    chain_observations.append({'references': chain, 'fields': rows, 'job_no': job_no, 'work_order_no': work_no, 'lot': lot_no,
                                               'acceptance_item_revision_quantity_drawing_complete_cost': 'NOT_ESTABLISHED'})
            except (ValueError, OSError, KeyError, TypeError) as error:
                chain_rejections.append({'references': chain, 'fields': rows,
                                         'reason': str(error) if isinstance(error, ValueError) else 'NATIVE_CHAIN_SOURCE_UNAVAILABLE'})
        tags['erp_quote_work_order_pointer_verified'] = {'value': int(bool(chain_observations)),
            'state': 'QUOTE_LEVEL_ERP_POINTER_ONLY' if chain_observations else 'NOT_ESTABLISHED',
            'reason': 'ORIGINAL_QUOTE_LEVEL_FOREIGN_KEYS_EQUAL_ONLY' if chain_observations else 'NO_VERIFIED_ORIGINAL_QUOTE_LEVEL_ERP_POINTER',
            'provenance': chain_refs, 'observations': chain_observations, 'rejected_references': chain_rejections}
        rfq_line, specifications, ledger_records = {}, [], []
        def rfq_verified():
            rfq = primary(record('rfq'), 'full_rfq_requirements', identity, as_of, preparer)
            h.require(rfq.get('schema_version') == 1 and rfq.get('case_id') == case_id and
                      h.iso_date(rfq.get('quote_date')) == assessed['quote_date'] and
                      rfq.get('customer_id') == identity['customer_id'] and rfq.get('currency') == rfq['identity']['currency'], 'RFQ_CASE_IDENTITY_MISMATCH')
            lines = rfq.get('lines')
            h.require(isinstance(lines, list) and lines and len(lines) <= 1000 and
                      len({line['line_id'] for line in lines}) == len(lines), 'FULL_RFQ_LINES_REQUIRED')
            selected = []
            for line in lines:
                h.shape(line, ('line_id', 'identity', 'manufacturing', 'manufacturing_evidence', 'drawing_asset'),
                        ('line_id', 'identity', 'manufacturing', 'manufacturing_evidence'))
                h.text(line['line_id'])
                h.verify_identity(line['identity'], line['identity'], full=True)
                h.require(line['identity']['customer_id'] == identity['customer_id'] and line['identity']['currency'] == rfq['currency'], 'RFQ_LINE_CUSTOMER_CURRENCY_MISMATCH')
                specification = primary(h.bound_record(line['manufacturing_evidence'], evidence), 'manufacturing_specification', line['identity'], as_of, preparer)
                h.require(manufacturing(line['manufacturing']) == manufacturing(specification.get('manufacturing')), 'RFQ_MANUFACTURING_MISMATCH')
                h.require(h.timestamp(specification['recorded_at']) <= h.timestamp(rfq['recorded_at']), 'LATER_RFQ_SPECIFICATION')
                if 'drawing_asset' in line:
                    asset = h.shape(line['drawing_asset'], ('request_ref', 'source', 'drawing_no', 'revision'))
                    h.require(asset == specification.get('drawing_asset') and asset['drawing_no'] == line['identity']['drawing_no'] and
                              asset['revision'] == line['identity']['revision'] and evidence.read(asset['source']), 'DRAWING_ASSET_MISMATCH')
                    h.text(asset['request_ref'])
                specifications.append(specification)
                if all(line['identity'][key] == rfq['identity'][key] for key in h.IDENTITY_KEYS if key != 'quantity') and h.number(
                        line['identity']['quantity'], True, 0) == h.number(rfq['identity']['quantity'], True, 0):
                    selected.append(line)
            h.require(len(selected) == 1, 'RFQ_TARGET_LINE_MISSING_OR_AMBIGUOUS')
            terms = h.shape(rfq.get('terms'), ('payment_terms', 'valid_until', 'lead_time_days', 'shipping', 'tax', 'additional_charges'))
            h.text(terms['payment_terms'])
            h.require(h.iso_date(terms['valid_until']) >= rfq['quote_date'] and h.number(terms['lead_time_days'], True, 0) > 0, 'RFQ_TERMS_INVALID')
            for key in ('shipping', 'tax'):
                h.number(terms[key], places=2)
            h.require(isinstance(terms['additional_charges'], list), 'RFQ_CHARGES_REQUIRED')
            for charge in terms['additional_charges']:
                h.shape(charge, ('description', 'amount'))
                h.text(charge['description'])
                h.number(charge['amount'], places=2)
            rfq_line.update(selected[0])
            return rfq
        check('full_rfq_verified', rfq_verified, [item.get('rfq', {}), records.get('rfq', {})])
        def issuance_verified():
            dependent('internal_calculation_verified', 'recorded_customer_amount_verified')
            issued = primary(record('issuance'), 'customer_quote_issuance', identity, as_of, preparer)
            h.require(document['target_comparable'] and issued.get('event') == 'customer_quote_sent' and
                      issued.get('letter') == document['letter'] and issued.get('document_sha256') == document['evidence'][0]['sha256'] and
                      issued.get('rfq') == item.get('rfq') and 'rfq' in item, 'ISSUED_QUOTE_CASE_OR_SOURCE_MISMATCH')
            amount = h.shape(issued.get('amount'), ('unit_price', 'extension'))
            h.require(h.number(amount['unit_price'], True) == h.number(document['unit_price'], True) and
                      h.number(amount['extension'], True, 2) == h.number(document['extension'], True, 2), 'ISSUED_QUOTE_AMOUNT_MISMATCH')
            return issued
        check('issued_customer_quote_matches_case', issuance_verified, [item.get('issuance', {}), *document.get('evidence', []), *document_source_refs])
        def acceptance_verified():
            dependent('issued_customer_quote_matches_case')
            accepted = primary(record('acceptance'), 'customer_order_acceptance', identity, as_of, preparer)
            h.verify_financial_record(accepted, 'independently_confirmed_acceptance', record('issuance')['identity'], as_of, evidence)
            h.require(accepted.get('issued_quote') == item['issuance'], 'ACCEPTED_QUOTE_PRIMARY_LINK_REQUIRED')
            return accepted
        check('customer_acceptance_confirmed', acceptance_verified, [item.get('acceptance', {}), item.get('issuance', {})])
        def work_order_verified():
            dependent('customer_acceptance_confirmed')
            job = primary(record('work_order'), 'manufacturing_work_order', record('acceptance')['identity'], as_of, preparer)
            h.text(job.get('job_no'))
            h.require(job.get('acceptance') == item['acceptance'] and job.get('customer_order_no') == record('acceptance')['customer_order_no'], 'DIRECT_ACCEPTANCE_JOB_LINK_REQUIRED')
            h.timestamp(job.get('opened_at'))
            return job
        check('work_order_link_confirmed', work_order_verified, [item.get('work_order', {}), item.get('acceptance', {})])
        def actual_cost_verified():
            dependent('work_order_link_confirmed')
            job = record('work_order')
            cost = primary(record('actual_cost'), 'actual_job_cost', job['identity'], as_of, preparer)
            h.verify_financial_record(cost, 'actual_manufacturing_cost', job['identity'], as_of, evidence)
            h.require(cost.get('work_order') == item['work_order'] and cost['job_no'] == job['job_no'], 'DIRECT_COST_JOB_LINK_REQUIRED')
            closure = primary(h.bound_record(cost.get('closure'), evidence), 'manufacturing_job_closure', job['identity'], as_of, preparer)
            start, end = h.timestamp(cost.get('period_start')), h.timestamp(cost.get('period_end'))
            closed = h.timestamp(closure.get('closed_at'))
            h.require(closure.get('event') == 'manufacturing_job_closed' and closure.get('work_order') == item['work_order'] and
                      closure.get('job_no') == job['job_no'] and closure.get('period_start') == cost['period_start'] and
                      closure.get('period_end') == cost['period_end'] and start <= h.timestamp(job['opened_at']) <= closed <= end <=
                      h.timestamp(cost['recorded_at']) and closed <= h.timestamp(closure['recorded_at']) <= h.timestamp(cost['recorded_at']), 'CLOSED_JOB_PERIOD_OR_LINK_MISMATCH')
            postings = cost.get('postings')
            h.require(isinstance(postings, list) and len(postings) <= 10000, 'ACTUAL_LEDGER_POSTINGS_REQUIRED')
            totals = {component: h.number('0') for component in COMPONENTS}
            ids, posting_refs = [], set()
            for ref in postings:
                posting = primary(h.bound_record(ref, evidence), 'actual_job_cost_posting', job['identity'], as_of, preparer)
                h.require(posting.get('job_no') == job['job_no'] and posting.get('component') in COMPONENTS and
                          posting.get('basis') == 'job_total', 'ACTUAL_LEDGER_COMPONENT_OR_JOB_MISMATCH')
                incurred = h.timestamp(posting.get('incurred_at'))
                h.require(start <= h.timestamp(job['opened_at']) <= incurred <= closed <= end and
                          incurred <= h.timestamp(posting['recorded_at']) <= h.timestamp(cost['recorded_at']), 'LEDGER_POSTING_OUTSIDE_CLOSED_JOB')
                ref_id = (ref['source']['sha256'], ref['pointer'])
                h.require(posting['record_id'] not in ids and ref_id not in posting_refs, 'DUPLICATE_LEDGER_POSTING')
                ids.append(posting['record_id'])
                posting_refs.add(ref_id)
                totals[posting['component']] += h.number(posting.get('amount'), True, 2)
                ledger_records.append(posting)
            h.require(isinstance(closure.get('posting_record_ids'), list) and sorted(closure['posting_record_ids']) == sorted(ids), 'CLOSURE_LEDGER_ENUMERATION_MISMATCH')
            h.shape(closure.get('components'), COMPONENTS)
            h.require(all(totals[key] == h.number(cost['components'][key], places=2) == h.number(closure['components'][key], places=2)
                          for key in COMPONENTS), 'ACTUAL_LEDGER_COMPONENT_TOTAL_MISMATCH')
            zeros = cost.get('zero_components')
            h.require(isinstance(zeros, list), 'ZERO_COMPONENT_DISPOSITION_REQUIRED')
            zero_names = []
            for entry in zeros:
                h.shape(entry, ('component', 'evidence'))
                zero = primary(h.bound_record(entry['evidence'], evidence), 'closed_job_zero_cost_component', job['identity'], as_of, preparer)
                h.require(entry['component'] in COMPONENTS and zero.get('component') == entry['component'] and zero.get('job_no') == job['job_no'] and
                          zero.get('closure') == cost['closure'] and zero.get('period_start') == cost['period_start'] and
                          zero.get('period_end') == cost['period_end'] and zero.get('basis') == 'job_total' and
                          h.number(zero.get('amount'), places=2) == 0, 'ZERO_COMPONENT_PRIMARY_DISPOSITION_MISMATCH')
                h.text(zero.get('reason'))
                h.require(closed <= h.timestamp(zero['recorded_at']) <= h.timestamp(cost['recorded_at']), 'ZERO_COMPONENT_TIME_MISMATCH')
                zero_names.append(entry['component'])
                ledger_records.append(zero)
            h.require(sorted(zero_names) == sorted(key for key in COMPONENTS if totals[key] == 0), 'MISSING_OR_DUPLICATE_ZERO_COMPONENT_DISPOSITION')
            ledger_records.append(closure)
            return {'record': cost, 'closure': closure, 'postings_and_zero_dispositions': ledger_records}
        check('closed_job_actual_cost_complete', actual_cost_verified, [item.get('actual_cost', {}), records.get('actual_cost', {})])
        def manufacturing_verified():
            dependent('full_rfq_verified', 'work_order_link_confirmed')
            job = record('work_order')
            specification = primary(h.bound_record(job.get('manufacturing_evidence'), evidence), 'manufacturing_specification', job['identity'], as_of, preparer)
            h.require(manufacturing(job.get('manufacturing')) == rfq_line['manufacturing'] == manufacturing(specification.get('manufacturing')) and
                      job.get('manufacturing_evidence') == rfq_line['manufacturing_evidence'], 'MANUFACTURING_SPECIFICATION_OR_REVISION_MISMATCH')
            return {'manufacturing': job['manufacturing'], 'specification': specification}
        check('manufacturing_identity_confirmed', manufacturing_verified, [item.get('rfq', {}), item.get('work_order', {}), records.get('work_order', {})])
        def units_verified():
            expected = record('rfq')['identity']
            h.verify_identity(expected, identity, full=True)
            for key in ('issuance', 'acceptance', 'work_order', 'actual_cost'):
                h.verify_identity(record(key)['identity'], expected, full=True)
            return {key: expected[key] for key in ('quantity', 'currency', 'uom')}
        check('quantity_currency_uom_confirmed', units_verified, [item.get(key, {}) for key in ('rfq', 'issuance', 'acceptance', 'work_order', 'actual_cost')])
        def chronology_verified():
            dependent('full_rfq_verified', 'issued_customer_quote_matches_case', 'customer_acceptance_confirmed',
                      'work_order_link_confirmed', 'closed_job_actual_cost_complete')
            rfq, issued, accepted, job, cost = [record(key) for key in ('rfq', 'issuance', 'acceptance', 'work_order', 'actual_cost')]
            h.require(h.timestamp(rfq['recorded_at']).date().isoformat() <= assessed['quote_date'] <=
                      h.timestamp(issued['recorded_at']).date().isoformat() and document['chronology'] == 'CONSISTENT' and
                      document['known_latest_date'] <= h.timestamp(issued['recorded_at']).date().isoformat(), 'ORIGINAL_QUOTE_DOCUMENT_CHRONOLOGY_UNRESOLVED')
            times = [rfq['recorded_at'], issued['recorded_at'], accepted['recorded_at'], job['opened_at'],
                     ledger_records[-1]['closed_at'], cost['recorded_at']]
            h.require(all(h.timestamp(first) <= h.timestamp(second) for first, second in zip(times, times[1:])) and
                      h.timestamp(job['opened_at']) <= h.timestamp(job['recorded_at']) <= h.timestamp(cost['recorded_at']), 'HISTORICAL_CHAIN_CHRONOLOGY_MISMATCH')
            return {'ordered_times': times, 'as_of': as_of, 'post_quote_evidence_role': 'OPERATOR_ONLY_TARGET_NOT_WORKER_INPUT'}
        check('chronology_confirmed', chronology_verified, [item.get(key, {}) for key in ('rfq', 'issuance', 'acceptance', 'work_order', 'actual_cost')])
        def review_verified():
            dependent(*MANDATORY[:-1])
            h.require(preparer is not None, 'PREPARER_ID_REQUIRED_FOR_INDEPENDENT_REVIEW')
            review = primary(record('review'), 'historical_full_data_source_review', record('rfq')['identity'], as_of, preparer)
            h.require(review.get('case_id') == case_id and h.text(review.get('reviewer_id')).casefold() != preparer.casefold() and
                      h.text(review.get('executor_id')).casefold() != preparer.casefold(), 'SELF_OR_UNBOUND_SOURCE_REVIEW')
            started, finished = h.timestamp(review.get('started_at')), h.timestamp(review.get('finished_at'))
            latest = max(h.timestamp(value['recorded_at']) for value in [*(records[key] for key in ('rfq', 'issuance', 'acceptance', 'work_order', 'actual_cost')),
                                                                          *specifications, *ledger_records])
            h.require(latest <= started <= finished <= h.timestamp(review['recorded_at']), 'SOURCE_REVIEW_CHRONOLOGY_MISMATCH')
            findings = review.get('findings')
            h.require(isinstance(findings, list) and len(findings) == len(MANDATORY) - 1 and
                      {finding['condition'] for finding in findings} == set(MANDATORY[:-1]), 'REQUIRED_SOURCE_REVIEW_FINDINGS_MISSING')
            reviewed = []
            for finding in findings:
                h.shape(finding, ('condition', 'verdict', 'reason', 'identity', 'sources'))
                h.require(finding['verdict'] == 'VERIFIED', 'SOURCE_REVIEW_DID_NOT_CONFIRM_CONDITION')
                h.text(finding['reason'])
                h.verify_identity(finding['identity'], record('rfq')['identity'], full=True)
                refs = source_refs(tags[finding['condition']]['provenance'])
                h.require(finding['sources'] == refs and refs, 'SOURCE_REVIEW_FINDING_HASH_MISMATCH')
                for ref in refs:
                    evidence.read(ref)
                reviewed.extend(refs)
            receipt = record('review_receipt')
            h.require(receipt.get('kind') == 'historical_full_data_review_execution' and receipt.get('case_id') == case_id and
                      receipt.get('review_source_sha256') == item['review']['source']['sha256'] and receipt.get('reviewer_id') == review['reviewer_id'] and
                      receipt.get('executor_id') == review['executor_id'] and receipt.get('started_at') == review['started_at'] and
                      receipt.get('finished_at') == review['finished_at'] and receipt.get('sources') == source_refs(reviewed), 'SOURCE_REVIEW_EXECUTION_RECEIPT_MISMATCH')
            h.text(receipt.get('review_job_id'))
            return {'review': review, 'receipt': receipt, 'authentication': 'SUPPLIED_PROVENANCE_REQUIRES_EXTERNAL_APPROVAL'}
        check('independent_source_review_confirmed', review_verified, [item.get('review', {}), item.get('review_receipt', {})])
        def current_verified():
            current = primary(record('current_quote'), 'supported_current_quote', identity, as_of, preparer)
            h.verify_financial_record(current, 'supported_current_quote', identity, as_of, evidence)
            return current
        check('current_quote_support_verified', current_verified, [item.get('current_quote', {}), records.get('current_quote', {})])
        tags['business_optimum_verified']['reason'] = 'NO_INDEPENDENT_PAIRED_COST_PROFIT_OUTCOME_STUDY_SUPPORTED_IN_V1'
        reasons = [{'tag': name, 'state': tags[name]['state'], 'reason': tags[name]['reason']} for name in MANDATORY if tags[name]['value'] != 1]
        is_eligible = int(not reasons)
        result = {'id': case_id, 'identity': identity, 'original_case_sha256': h.digest(raw_line),
                  'original_target': {key: assessed['frozen_case'][key] for key in ('actual_quantity', 'actual_unit_price')},
                  'tags': tags, 'full_data_eligible': is_eligible, 'exclusion_reasons': reasons,
                  'evidence_roles': {'quote_time_input_references': source_refs([item.get('rfq', {}), records.get('rfq', {})]),
                                     'post_quote_operator_only_target_references': source_refs(
                                         [item.get(key, {}) for key in FIELDS if key != 'rfq'] + [candidate_refs, chain_refs]),
                                     'worker_context_generated': False}, 'business_outcome': 'NOT_ESTABLISHED'}
        results.append(result)
        if is_eligible:
            eligible.append(raw_line + b'\n')
        else:
            metadata = h.encode({'id': case_id, 'exclusion_reasons': reasons, 'business_outcome': 'NOT_ESTABLISHED'}).rstrip(b'\n')
            excluded.append(metadata[:-1] + b',"original_case":' + raw_line.removeprefix(b'\xef\xbb\xbf') + b'}\n')
    summary = {'cases': len(results), 'eligible': len(eligible), 'excluded': len(excluded),
               'work_order_candidate_cases': sum(result['tags']['work_order_candidate_present']['value'] for result in results),
               'candidate_references_supplied': candidate_references, 'unique_verified_candidate_records': len(candidate_physical),
               'rejected_candidate_references': sum(len(result['tags']['work_order_candidate_present']['rejected_references']) for result in results),
               'erp_quote_work_order_pointer_cases': sum(result['tags']['erp_quote_work_order_pointer_verified']['value'] for result in results),
               'native_order_chains_supplied': native_references, 'unique_verified_native_order_chains': len(native_chains),
               'rejected_native_order_chains': sum(len(result['tags']['erp_quote_work_order_pointer_verified']['rejected_references']) for result in results),
               'verified_tags': {name: sum(result['tags'][name]['value'] for result in results) for name in (*MANDATORY, *OPTIONAL)}}
    audit = {'schema_version': 1, 'kind': 'historical_full_data_tag_audit', 'as_of': as_of, 'summary': summary, 'cases': results}
    table = io.StringIO(newline='')
    columns = ['id', 'full_data_eligible', *[column for name in (*MANDATORY, *OPTIONAL) for column in (name, name + '_state', name + '_reason', name + '_provenance')]]
    writer = csv.DictWriter(table, fieldnames=columns)
    writer.writeheader()
    for result in results:
        row = {'id': result['id'], 'full_data_eligible': result['full_data_eligible']}
        for name, tag in result['tags'].items():
            row.update({name: tag['value'], name + '_state': tag['state'], name + '_reason': tag['reason'],
                        name + '_provenance': h.encode(tag['provenance']).decode().strip()})
        writer.writerow(row)
    implementation = {path.name: h.digest(path.read_bytes()) for path in (Path(__file__), Path(h.__file__))}
    all_inputs = dict(evidence.inputs)
    for path, expected in native_inputs.items():
        h.require(path not in all_inputs or all_inputs[path] == expected, 'NATIVE_INPUT_PIN_CONFLICT')
        all_inputs[path] = expected
    manifest = {'schema_version': 1, 'kind': 'historical_full_data_case_set', 'as_of': as_of, 'summary': summary,
                'mandatory_tags': list(MANDATORY), 'optional_non_gating_tags': list(OPTIONAL),
                'eligibility_predicate': ' AND '.join(name + ' == 1' for name in MANDATORY),
                'binary_semantics': {'1': 'verified supplied evidence condition', '0': 'not established; not a verified negative'},
                'selection': 'Source availability and confirmation only; scores, predictions and post-run successes are never consulted',
                'original_case_ids_sha256': h.digest(h.encode(original_ids)), 'original_evalset': assessment_config['evalset'],
                'inputs': all_inputs, 'native_input_pins': native_inputs, 'implementation_sha256': implementation,
                'source_limits': {'default_bytes': 64 * 1024 * 1024, 'native_order_chain_bytes': NATIVE_LIMIT,
                                  'native_order_chain_tables': list(NATIVE_TABLES.values())},
                'reopened_assessment_sha256': h.digest(reopened_bytes), 'reopened_assessment_files': reopened_files,
                'roles': {'bundle': 'OPERATOR_ONLY', 'eligible_jsonl': 'UNCHANGED_ORIGINAL_CASES_WITH_ORIGINAL_TARGETS',
                          'future_acceptance_job_cost_records': 'TARGET_EVIDENCE_NEVER_WORKER_CONTEXT', 'worker_context_generated': False},
                'limitations': LIMITATIONS}
    files = {'all-case-tags.private.json': h.encode(audit), 'all-case-tags.private.csv': table.getvalue().encode(),
             'eligible-historical-cases.jsonl': b''.join(eligible), 'excluded-cases.private.jsonl': b''.join(excluded),
             'manifest.json': h.encode(manifest)}
    h.require(all(destination != Path(path) and destination not in Path(path).parents and Path(path) not in destination.parents
                  for path in all_inputs), 'OUTPUT_INPUT_ALIAS')
    evidence.recheck()
    for path, expected in native_inputs.items():
        h.require(h.digest(h.private_bytes(path, NATIVE_LIMIT)) == expected, 'NATIVE_INPUT_CHANGED')
    directory = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        hashes = {**reopened_files, **{name: h.digest(data) for name, data in files.items()}}
        files['seal.json'] = h.encode({'schema_version': 1, 'kind': manifest['kind'], 'files': hashes,
                                       'inputs': all_inputs, 'native_input_pins': native_inputs, 'implementation_sha256': implementation})
        for name, data in files.items():
            h.require(not h.SECRET.search(data.decode('utf-8-sig')), 'CREDENTIAL_BEARING_OUTPUT')
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=directory)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        os.fsync(directory)
        current, opened = h.private_path(config['out'], directory=True).lstat(), os.fstat(directory)
        h.require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino), 'OUTPUT_DIRECTORY_CHANGED')
    finally:
        os.close(directory)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    data = h.private_bytes(args.config)
    h.require(not h.SECRET.search(data.decode('utf-8-sig')), 'CREDENTIAL_BEARING_CONFIG')
    print(json.dumps(build(h.parse_json(data)), sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, ArithmeticError, IndexError, AttributeError, subprocess.SubprocessError):
        print('KELLER_FULL_DATA_VALIDATION_FAILED; inspect private inputs and use a new output version', file=sys.stderr)
        sys.exit(2)
