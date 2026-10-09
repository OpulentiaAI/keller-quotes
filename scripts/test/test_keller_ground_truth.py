import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('keller_ground_truth', REPO / 'scripts/keller-ground-truth.py')
GROUND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GROUND)


def synthetic_dbf(fields, values):
    length = 1 + sum(width for _, _, width in fields)
    start = 32 + len(fields) * 32 + 1
    header = bytearray(32)
    header[0] = 3
    struct.pack_into('<IHH', header, 4, 1, start, length)
    descriptors, record, raw_hex = bytearray(), bytearray(b' '), {}
    for name, kind, width in fields:
        field = bytearray(32)
        field[:len(name)] = name.encode()
        field[11], field[16] = ord(kind), width
        descriptors.extend(field)
        token = values[name].replace('-', '') if kind == 'D' else values[name]
        encoded = token.encode('cp1252').ljust(width, b' ')
        if len(encoded) != width:
            raise ValueError('synthetic fixture field too long')
        record.extend(encoded)
        raw_hex[name] = encoded.hex()
    data = bytes(header + descriptors + b'\r' + record + b'\x1a')
    return data, {'record_index': 0, 'record_no': 1, 'byte_offset': start,
                  'record_sha256': GROUND.digest(record), 'raw_field_hex': raw_hex}


def synthetic_pdf(lines):
    commands = ['BT /F1 10 Tf 40 760 Td']
    for line in lines:
        escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        commands.append(f'({escaped}) Tj 0 -16 Td')
    commands.append('ET')
    stream = '\n'.join(commands).encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>',
               f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream']
    result, offsets = b'%PDF-1.4\n', [0]
    for ordinal, value in enumerate(objects, 1):
        offsets.append(len(result))
        result += f'{ordinal} 0 obj\n'.encode() + value + b'\nendobj\n'
    position = len(result)
    result += f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    result += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return result + f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{position}\n%%EOF\n'.encode()


class Fixture:
    def __init__(self, owner, letter_revision='A', footer='10/01/26', document_quantity=10,
                 part_no='P-1', printed_part_no=None, printed_revision=None):
        scratch = Path.home() / '.capy/work'
        scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='keller-ground-truth-synthetic-', dir=scratch))
        owner.addCleanup(shutil.rmtree, self.root)
        self.case_id = '0000001|@10'
        self.identity = {'quote_no': '0000001', 'item_no': '', 'customer_id': '000001', 'part_no': part_no,
                         'revision': 'A', 'drawing_no': 'D-1', 'quantity': 10, 'currency': 'USD', 'uom': 'EA'}
        case = {'id': self.case_id, 'source_quote_no': '0000001', 'quote_date': '2026-10-01',
                'input': {'part_no': part_no, 'description': 'SYNTHETIC PART', 'customer_id': '000001', 'quantity': 10},
                'actual_quantity': 10, 'actual_unit_price': '2.50000'}
        self.case = case
        candidate = {'schema_version': 2, 'results': [{'id': self.case_id, 'source_quote_no': '0000001',
            'quote_date': '2026-10-01', 'quantity': 10, 'actual': '2.50000', 'predicted': '2.00000',
            'status': 'priced', 'all_pass': False, 'ape': '0.2', 'criteria': {'price': {'pass': False}}}]}
        self.evalset = self.write('evalset.jsonl', GROUND.encode(case))
        self.candidate = self.write('candidate.json', candidate)
        table_specs = {
            'QUOTEN': ([('QUOTE_NO', 'C', 7), ('ITEM_NO', 'C', 10), ('COMP_ID', 'C', 6), ('PART_NO', 'C', 16),
                        ('REV_NO', 'C', 8), ('DRAWING_NO', 'C', 16), ('DESCR', 'C', 32), ('ORG_DATE', 'D', 8)],
                       {'QUOTE_NO': '0000001', 'ITEM_NO': '', 'COMP_ID': '000001', 'PART_NO': part_no,
                        'REV_NO': 'A', 'DRAWING_NO': 'D-1', 'DESCR': 'SYNTHETIC PART', 'ORG_DATE': '2026-10-01'}),
            'QUOTQTYS': ([('QUOTE_NO', 'C', 7), ('QTY', 'N', 8), ('UNIT_SELL', 'N', 12), ('UNIT_COST', 'N', 12), ('DEL', 'N', 3)],
                         {'QUOTE_NO': '0000001', 'QTY': '10', 'UNIT_SELL': '2.50000', 'UNIT_COST': '1.20000', 'DEL': '1'}),
            'QUOTLETT': ([('QUOTLETTER', 'C', 8), ('COMP_ID', 'C', 6), ('CNAME', 'C', 32), ('DATE_STAMP', 'D', 8), ('REVISION_D', 'D', 8)],
                         {'QUOTLETTER': '00000001', 'COMP_ID': '000001', 'CNAME': 'SYNTHETIC CUSTOMER', 'DATE_STAMP': '2026-10-01', 'REVISION_D': ''}),
            'QUOTLINE': ([('QUOTLETTER', 'C', 8), ('QUOTE_NO', 'C', 7), ('PART_NO', 'C', 16), ('ITEM', 'N', 3), ('REV_NO', 'C', 8), ('DRAWING_NO', 'C', 16)],
                         {'QUOTLETTER': '00000001', 'QUOTE_NO': '0000001', 'PART_NO': part_no, 'ITEM': '1', 'REV_NO': letter_revision, 'DRAWING_NO': 'D-1'}),
            'QUOTLEIT': ([('QUOTLETTER', 'C', 8), ('ITEM', 'N', 3), ('QTY', 'N', 8), ('PRICE', 'N', 12), ('QUOTEPRICE', 'N', 12)],
                         {'QUOTLETTER': '00000001', 'ITEM': '1', 'QTY': str(document_quantity), 'PRICE': '2.00000', 'QUOTEPRICE': '2.00000'})}
        self.manifest, self.source_paths, records = {}, {}, {}
        for table, (fields, values) in table_specs.items():
            data, reference = synthetic_dbf(fields, values)
            source = self.write(table + '.DBF', data)
            self.source_paths[table + '.DBF'] = source['path']
            self.manifest[table + '.DBF'] = {**source, 'bytes': len(data)}
            records[table] = [reference]
        pdf = synthetic_pdf(['QUOTE', 'Letter: 00000001', 'Item #: 1       Quote #: 0000001',
            f'P/N: {printed_part_no if printed_part_no is not None else part_no}            Rev: {printed_revision if printed_revision is not None else letter_revision}', 'Inquiry Date: 10/01/26',
            'To: SYNTHETIC CUSTOMER      Buyer: SYNTHETIC', 'Description     Quantity     Price Each     Extended Price',
            f'SYNTHETIC PART       {document_quantity}          $2.00          ${document_quantity * 2:.2f}', f'By: SYNTHETIC           {footer}'])
        self.pdf = self.write('letter.pdf', pdf)
        layout = subprocess.run(['pdftotext', '-layout', self.pdf['path'], '-'], capture_output=True, check=True).stdout
        self.transcript = self.write('transcript.txt', layout)
        for key, ref in [('original_pdf', self.pdf), ('original_transcript', self.transcript)]:
            self.source_paths[key] = ref['path']
            self.manifest[key] = {**ref, 'bytes': len(Path(ref['path']).read_bytes())}
        for key, ref in [('frozen_evalset', self.evalset), ('candidate_report', self.candidate)]:
            self.manifest[key] = {**ref, 'bytes': len(Path(ref['path']).read_bytes())}
        self.documents = {'documents': {'synthetic': {'document': 'OUTPUT/QuoteLetter00000001.pdf',
            'letter': '00000001', 'source_pdf_sha256': self.pdf['sha256'], 'source_transcript_sha256': self.transcript['sha256'],
            'layout_text_sha256': GROUND.digest(layout), 'source_header_refs': records['QUOTLETT'], 'source_line_refs': records['QUOTLINE'],
            'verified_curve': [{'quantity': str(document_quantity), 'unit_price': '2.00000', 'source_price_field': 'PRICE',
                'printed_extension': f'{document_quantity * 2:.2f}', 'source_quantity_ref': records['QUOTLEIT'][0]}]}}}
        self.binding = {'id': self.case_id, 'quote_no': '0000001', 'item_no': '', 'part_no': part_no, 'customer_id': '000001',
            'revision': 'A', 'drawing_no': 'D-1', 'quantity': '10', 'target_UNIT_SELL': '2.50000', 'delivery_count_DEL': '1',
            'raw_QUOTEN_record_index': '0', 'raw_QUOTQTYS_record_index': '0', 'csv_quantity_only_match_count': '1',
            'document_path': 'OUTPUT/QuoteLetter00000001.pdf', 'quote_letter': '00000001',
            'document_sha256': self.pdf['sha256'], 'transcript_sha256': self.transcript['sha256'], 'fresh_layout_sha256': GROUND.digest(layout)}
        self.config = {'schema_version': 1, 'as_of': '2026-10-04', 'expected_cases': 1, 'evalset': self.evalset,
            'candidate_report': self.candidate, 'bindings': self.write_bindings([self.binding]),
            'raw_bindings': self.write('raw.json', {'records': records}), 'documents': self.write('documents.json', self.documents),
            'source_manifest': self.write('source-manifest.json', {'inputs': self.manifest}),
            'source_paths': self.source_paths, 'out': str(self.root / 'assessment-v1')}

    def write(self, name, value):
        data = value if isinstance(value, bytes) else GROUND.encode(value)
        path = self.root / name
        path.write_bytes(data)
        path.chmod(0o600)
        return {'path': str(path), 'sha256': GROUND.digest(data)}

    def write_bindings(self, rows):
        output = io.StringIO(newline='')
        fields = list(rows[0]) if rows else list(self.binding)
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return self.write('bindings.csv', output.getvalue().encode())

    def assess(self):
        GROUND.assess(self.config)
        return GROUND.parse_json((Path(self.config['out']) / 'assessment.private.json').read_bytes())

    def current_quote(self):
        manufacturing = {'material': 'synthetic steel', 'finish': 'none', 'routing': 'cut and bend', 'tolerances': 'D-1 revision A'}
        costs = []
        for component, amount in [('material', '0.70000'), ('labor', '0.50000'), ('outside', '0.30000'), ('setup', '0.00')]:
            source = self.write(component + '-cost.json', {'kind': 'current_cost_observation', 'identity': self.identity,
                'component': component, 'amount': amount, 'basis': 'job_total' if component == 'setup' else 'per_unit',
                'extension': str(GROUND.number(amount) if component == 'setup' else GROUND.extension(amount, 10)),
                'record_id': 'synthetic-' + component, 'issuer': 'synthetic independently supplied cost source',
                'recorded_at': '2026-10-01T08:00:00Z', 'valid_from': '2026-10-01', 'valid_until': '2026-10-31'})
            costs.append({'component': component, 'amount': amount, 'evidence': {'source': source, 'pointer': ''}})
        record = {'kind': 'supported_current_quote', 'record_id': 'synthetic-current-1', 'issuer': 'synthetic client source',
            'identity': self.identity, 'amount': {'unit_price': '2.00000', 'extension': '20.00'},
            'amount_basis': 'current_supported_quote', 'recorded_at': '2026-10-01T08:00:00Z',
            'valid_from': '2026-10-01', 'valid_until': '2026-10-31', 'manufacturing': manufacturing, 'costs': costs, 'margin_pct': '25'}
        source = self.write('current-quote.json', record)
        bound = {'source': source, 'pointer': ''}
        self.config['confirmed_evidence'] = [{'case_id': self.case_id, 'domain': 'supported_current_quote', 'authority': 'source_record', 'evidence': bound}]
        return record, bound


class GroundTruthTests(unittest.TestCase):
    def test_original_bytes_distinguish_calculation_customer_price_and_outcomes(self):
        fixture = Fixture(self)
        report = fixture.assess()
        case = report['cases'][0]
        self.assertEqual(case['domains']['internal_calculation']['state'], 'VERIFIED_SOURCE_BYTES')
        document = case['domains']['recorded_customer_quote']
        self.assertEqual(document['state'], 'VERIFIED_RECORDED_AMOUNT')
        self.assertTrue(document['target_comparable'])
        self.assertFalse(document['numeric_agreement_with_calculation'])
        self.assertFalse(document['as_of_eligible'])
        for domain in ('independently_confirmed_acceptance', 'actual_manufacturing_cost', 'supported_current_quote', 'optimum_business_outcome'):
            self.assertEqual(case['domains'][domain]['state'], 'UNSUPPORTED')
        self.assertEqual(case['legacy_diagnostic']['signed_unit_error'], '-0.50000')
        self.assertEqual(case['legacy_diagnostic']['result']['all_pass'], False)
        self.assertLessEqual(len(report['remediation_queue']), 10)
        for path in Path(fixture.config['out']).iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)

    def test_mismatched_revision_and_later_footer_never_prove_quote_time_fitness(self):
        fixture = Fixture(self, letter_revision='B', footer='10/02/26')
        case = fixture.assess()['cases'][0]
        doc = case['domains']['recorded_customer_quote']
        self.assertEqual(doc['state'], 'VERIFIED_RECORDED_AMOUNT')
        self.assertFalse(doc['target_comparable'])
        self.assertFalse(doc['as_of_eligible'])
        self.assertEqual(doc['chronology'], 'INQUIRY_FOOTER_CONFLICT')
        self.assertIn('DOCUMENT_LATER_THAN_CALCULATION', case['remediation_reasons'])

    def test_layout_whitespace_and_absent_revision_presentation_do_not_invent_identity(self):
        for printed_revision in ('', '-'):
            with self.subTest(printed_revision=printed_revision):
                fixture = Fixture(self, part_no='P-1  X', printed_part_no='P-1   X', letter_revision='', printed_revision=printed_revision)
                doc = fixture.assess()['cases'][0]['domains']['recorded_customer_quote']
                self.assertEqual(doc['state'], 'VERIFIED_RECORDED_AMOUNT')
                self.assertEqual(doc['identity']['part_no'], 'P-1  X')
                self.assertEqual(doc['identity']['revision'], '')
                self.assertEqual(doc['revision_identity'], 'ABSENT_IN_SOURCE')
                self.assertFalse(doc['revision_and_drawing_match'])
        for printed_part, printed_rev in [('P1 X', 'A'), ('P-1  X', 'B')]:
            with self.subTest(printed_part=printed_part, printed_rev=printed_rev):
                fixture = Fixture(self, part_no='P-1  X', printed_part_no=printed_part, printed_revision=printed_rev)
                doc = fixture.assess()['cases'][0]['domains']['recorded_customer_quote']
                self.assertEqual(doc['state'], 'UNVERIFIED')
                self.assertEqual(doc['reason'], 'PRINTED_IDENTITY_MISMATCH')

    def test_identity_tampering_and_quantity_mismatch_fail_closed(self):
        fixture = Fixture(self, document_quantity=12)
        fixture.binding['customer_id'] = '000002'
        fixture.config['bindings'] = fixture.write_bindings([fixture.binding])
        case = fixture.assess()['cases'][0]
        self.assertEqual(case['domains']['internal_calculation']['state'], 'UNVERIFIED')
        self.assertEqual(case['domains']['recorded_customer_quote']['state'], 'UNVERIFIED')

    def test_missing_bindings_and_missing_candidate_retain_every_frozen_case(self):
        fixture = Fixture(self)
        fixture.config['bindings'] = fixture.write_bindings([])
        fixture.config['candidate_report']['path'] = str(fixture.root / 'missing-candidate.json')
        report = fixture.assess()
        self.assertEqual(report['summary']['cases'], 1)
        self.assertEqual(report['cases'][0]['legacy_diagnostic']['state'], 'MISSING_OR_DUPLICATE_ATTEMPT')
        self.assertEqual(report['cases'][0]['domains']['internal_calculation']['state'], 'UNVERIFIED')

    def test_hidden_case_changes_and_tampered_sources_cannot_pass(self):
        fixture = Fixture(self)
        fixture.config['expected_cases'] = 2
        with self.assertRaisesRegex(ValueError, 'FROZEN_CASES'):
            fixture.assess()
        fixture.config['expected_cases'] = 1
        Path(fixture.source_paths['QUOTQTYS.DBF']).write_bytes(b'tampered')
        report = fixture.assess()
        self.assertEqual(report['cases'][0]['domains']['internal_calculation']['state'], 'UNVERIFIED')
        self.assertEqual(report['summary']['source_errors'], {'DIGEST_MISMATCH': 1})

    def test_won_history_internal_cost_and_operator_assertion_never_promote_truth(self):
        fixture = Fixture(self)
        history = fixture.write('history.json', {'kind': 'posted_quote_history', 'identity': fixture.identity, 'status': 'won'})
        assertion = fixture.write('assertion.json', {'kind': 'operator_assertion', 'identity': fixture.identity, 'statement': 'An operator says costs were confirmed'})
        fixture.config['confirmed_evidence'] = [
            {'case_id': fixture.case_id, 'domain': 'independently_confirmed_acceptance', 'authority': 'source_record', 'evidence': {'source': history, 'pointer': ''}},
            {'case_id': fixture.case_id, 'domain': 'actual_manufacturing_cost', 'authority': 'operator_assertion', 'evidence': {'source': assertion, 'pointer': ''}}]
        case = fixture.assess()['cases'][0]
        self.assertEqual(case['domains']['independently_confirmed_acceptance']['state'], 'UNVERIFIED')
        self.assertEqual(case['domains']['actual_manufacturing_cost']['state'], 'OPERATOR_ASSERTION_NOT_INDEPENDENT_TRUTH')

    def test_source_bound_acceptance_requires_identity_unit_time_and_full_arithmetic(self):
        fixture = Fixture(self)
        record = {'kind': 'customer_order_acceptance', 'record_id': 'synthetic-acceptance', 'issuer': 'synthetic customer',
            'recorded_at': '2026-10-02T10:00:00Z', 'identity': fixture.identity, 'amount': {'unit_price': '2.00000', 'extension': '20.00'},
            'event': 'customer_accepted_order', 'customer_order_no': 'SYNTHETIC-PO', 'amount_basis': 'accepted_order'}
        source = fixture.write('accepted.json', record)
        fixture.config['confirmed_evidence'] = [{'case_id': fixture.case_id, 'domain': 'independently_confirmed_acceptance',
            'authority': 'source_record', 'evidence': {'source': source, 'pointer': ''}}]
        case = fixture.assess()['cases'][0]
        self.assertEqual(case['domains']['independently_confirmed_acceptance']['state'], 'SOURCE_BOUND_INDEPENDENTLY_INSPECTABLE_RECORD')
        record['amount']['extension'] = '21.00'
        fixture.config['confirmed_evidence'][0]['evidence']['source'] = fixture.write('bad-accepted.json', record)
        fixture.config['out'] = str(fixture.root / 'assessment-v2')
        self.assertEqual(fixture.assess()['cases'][0]['domains']['independently_confirmed_acceptance']['state'], 'UNVERIFIED')

    def test_current_quote_requires_fresh_independent_cost_components_and_reconciled_margin(self):
        fixture = Fixture(self)
        record, bound = fixture.current_quote()
        self.assertEqual(fixture.assess()['cases'][0]['domains']['supported_current_quote']['state'], 'SOURCE_BOUND_INDEPENDENTLY_INSPECTABLE_RECORD')
        record['costs'][0]['amount'] = '0.80000'
        bound['source'] = fixture.write('bad-current.json', record)
        fixture.config['out'] = str(fixture.root / 'assessment-v2')
        self.assertEqual(fixture.assess()['cases'][0]['domains']['supported_current_quote']['state'], 'UNVERIFIED')

    def test_financial_sources_require_explicit_units_revision_time_and_actual_cost_totals(self):
        fixture = Fixture(self)
        actual = {'kind': 'actual_job_cost', 'record_id': 'synthetic-job-ledger', 'issuer': 'synthetic independent ledger',
            'recorded_at': '2026-10-03T10:00:00Z', 'identity': fixture.identity, 'job_no': 'SYNTHETIC-JOB',
            'amount_basis': 'actual_closed_job', 'amount': {'unit_price': '1.20000', 'extension': '12.00'},
            'components': {'material': '4.00', 'labor': '5.00', 'outside': '2.00', 'setup': '1.00'}}
        GROUND.verify_financial_record(actual, 'actual_manufacturing_cost', fixture.identity, '2026-10-04', GROUND.EvidenceIO())
        for key, value in [('currency', 'EUR'), ('uom', ''), ('revision', '-')]:
            changed = {**actual, 'identity': {**fixture.identity, key: value}}
            with self.subTest(key=key), self.assertRaises(ValueError):
                GROUND.verify_financial_record(changed, 'actual_manufacturing_cost', fixture.identity, '2026-10-04', GROUND.EvidenceIO())
        changed = {**actual, 'recorded_at': '2026-10-05T10:00:00Z'}
        with self.assertRaisesRegex(ValueError, 'LATER_EVIDENCE'):
            GROUND.verify_financial_record(changed, 'actual_manufacturing_cost', fixture.identity, '2026-10-04', GROUND.EvidenceIO())
        changed = {**actual, 'components': {**actual['components'], 'labor': '4.00'}}
        with self.assertRaisesRegex(ValueError, 'COST_SUM_MISMATCH'):
            GROUND.verify_financial_record(changed, 'actual_manufacturing_cost', fixture.identity, '2026-10-04', GROUND.EvidenceIO())

    def test_private_paths_modes_aliases_and_duplicate_json_are_denied(self):
        fixture = Fixture(self)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_JSON_KEY'):
            GROUND.parse_json(b'{"a":1,"a":2}')
        alias = fixture.root / 'alias'
        alias.symlink_to(fixture.pdf['path'])
        with self.assertRaises(ValueError):
            GROUND.private_bytes(str(alias))
        hardlink = fixture.root / 'hardlink'
        os.link(fixture.pdf['path'], hardlink)
        with self.assertRaises(ValueError):
            GROUND.private_bytes(fixture.pdf['path'])
        hardlink.unlink()
        Path(fixture.pdf['path']).chmod(0o644)
        with self.assertRaises(ValueError):
            GROUND.private_bytes(fixture.pdf['path'])
        Path(fixture.pdf['path']).chmod(0o600)
        fixture.assess()
        with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS'):
            fixture.assess()
        fixture.config['out'] = str(REPO / 'private-invalid')
        with self.assertRaises(ValueError):
            fixture.assess()

    def test_cli_returns_only_aggregate_not_client_prices(self):
        fixture = Fixture(self)
        config = fixture.write('config.json', fixture.config)
        result = subprocess.run(['python', str(REPO / 'scripts/keller-ground-truth.py'), 'assess', '--config', config['path']], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('P-1', result.stdout)
        self.assertNotIn('2.50000', result.stdout)
        self.assertNotIn(fixture.case_id, result.stdout)
        self.assertEqual(json.loads(result.stdout)['cases'], 1)


if __name__ == '__main__':
    unittest.main()
