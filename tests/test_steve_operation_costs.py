"""Selected synthetic operation -> reviewed rate inputs -> native quote. No private prices."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_arsumbris_quote as quote_tests
from test_steve_source_evidence import dbf_bytes, reader

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [("OPER_ID", "C", 4), ("NAME", "C", 30), ("SU_COST", "N", 20),
          ("RUN_COST", "N", 20), ("SU_RATE", "N", 20), ("RUN_RATE", "N", 20)]


class OperationCostBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-operation-costs-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bindings = {"fabritrak": str(self.root)}
        self.review = {"rate_unit": "USD/hour", "source_date": "2020-01-01",
                       "reviewer": "Synthetic estimator", "date": "2024-05-31",
                       "reason": "Synthetic reviewed historical COST estimate, not a current rate",
                       "applicability": "assumed", "charge_inclusion": "Synthetic loaded labor/machine COST; no freight/tax"}
        self.write_table()

    def write_table(self, fields=FIELDS, rows=None, path="OPERATIO.DBF"):
        if rows is None:
            rows = [(b" ", ["0002", "SYNTHETIC alternate", "40.1250", "50.2500", "9000", "9000"]),
                    (b"*", ["0002", "SYNTHETIC deleted", "0", "0", "9000", "9000"]),
                    (b" ", ["0002", "SYNTHETIC selected", "60.0000", "60.0000", "9000", "9000"])]
        (self.root / path).write_bytes(dbf_bytes(fields, rows))

    def request(self, index=2, path="OPERATIO.DBF"):
        rows = reader.read(self.bindings, reader.validate({"action": "dbf_rows", "source_set": "fabritrak",
                            "path": path, "record_id": "0002"}))
        selected = next(row for row in rows['rows'] if row['record_index'] == index)
        return {"action": "dbf_operation_costs", "source_set": "fabritrak", "path": path,
                "record_id": "0002", "record_index": index,
                "expected_dbf_sha256": rows['citation']['dbf_sha256'],
                "expected_record_sha256": selected['record_sha256'], "rate_review": json.dumps(self.review)}

    def call(self, request=None):
        return reader.read(self.bindings, reader.validate(request or self.request()))

    def native_source(self, request):
        config = self.root / 'sources.json'
        config.write_text(json.dumps(self.bindings))
        config.chmod(0o600)
        script = """import {createPlugin} from './arsumbris/sources/tool.ts';
console.log(JSON.stringify(await createPlugin({workspace: process.cwd()}).invoke(JSON.parse(process.argv[1]))));"""
        result = subprocess.run(['node', '--input-type=module', '-e', script, json.dumps(request)],
                                cwd=ROOT, env={**os.environ, 'KELLER_SOURCE_CONFIG': str(config), 'KELLER_PYTHON': sys.executable},
                                capture_output=True, text=True, check=True, timeout=20)
        return json.loads(result.stdout)

    def test_selected_duplicate_keeps_original_cost_fields_and_physical_provenance(self):
        request = self.request()
        result = self.call(request)
        self.assertEqual(result['selection']['record_index'], 2)
        self.assertEqual(result['selection']['record_sha256'], request['expected_record_sha256'])
        inputs = result['worksheet_inputs']
        for role, field in [('setup_rate', 'SU_COST'), ('run_rate', 'RUN_COST')]:
            self.assertEqual(inputs[role], {'rate_kind': 'cost', 'unit': 'USD/hour',
                                           'values': {'low': 60.0, 'base': 60.0, 'high': 60.0}})
            evidence = result['field_evidence'][role]
            self.assertEqual(evidence['field'], field)
            self.assertEqual(evidence['original_value'], '60.0000')
            offset = result['selection']['record_byte_offset'] + evidence['record_byte_offset']
            raw = (self.root / 'OPERATIO.DBF').read_bytes()[offset:offset + evidence['field_bytes']]
            self.assertEqual(raw.strip().decode(), evidence['original_value'])
        for source in inputs['sources']:
            self.assertEqual(source['sha256'], request['expected_dbf_sha256'])
            self.assertIn('record_index=2', source['locator'])
            self.assertIn(request['expected_record_sha256'], source['locator'])
            self.assertIn('0002 (SYNTHETIC selected)', source['basis'])
            self.assertEqual(source['status'], 'approved_estimate')
            self.assertEqual(source['approval']['reviewer'], self.review['reviewer'])
        self.assertNotIn('9000', json.dumps(inputs))
        first = self.call(self.request(index=0))
        self.assertEqual(first['worksheet_inputs']['setup_rate']['values']['base'], 40.125)
        self.assertIn('Partial routing', result['selection_note'])

    def test_pins_identity_index_and_hashes_without_first_match_fallback(self):
        request = self.request()
        mutations = [('record_id', '2'), ('record_index', 0), ('record_index', 1), ('record_index', 3),
                     ('record_index', -1), ('record_index', None), ('record_index', True), ('record_index', 0.5),
                     ('expected_record_sha256', '0' * 64), ('expected_dbf_sha256', '0' * 64),
                     ('quote_no', 'Q1'), ('limit', 5), ('offset', 0)]
        for key, value in mutations:
            with self.subTest(key=key, value=value), self.assertRaises(reader.InvalidRequest):
                self.call({**request, key: value})
        for key in ['record_id', 'record_index', 'expected_record_sha256', 'expected_dbf_sha256', 'rate_review']:
            invalid = dict(request); invalid.pop(key)
            with self.subTest(missing=key), self.assertRaises(reader.InvalidRequest):
                self.call(invalid)
        self.write_table(rows=[(b' ', ['0002', 'CHANGED', '60', '60', '9000', '9000'])])
        with self.assertRaisesRegex(reader.InvalidRequest, 'hash mismatch'):
            self.call(request)

    def test_deleted_and_malformed_physical_records_are_not_selected(self):
        request = self.request()
        data = bytearray((self.root / 'OPERATIO.DBF').read_bytes())
        result = self.call(request)
        offset, length = result['selection']['record_byte_offset'], result['selection']['record_bytes']
        for marker in (b'*', b'?'):
            data[offset] = marker[0]
            (self.root / 'OPERATIO.DBF').write_bytes(data)
            request.update(expected_dbf_sha256=hashlib.sha256(data).hexdigest(),
                           expected_record_sha256=hashlib.sha256(data[offset:offset + length]).hexdigest())
            with self.assertRaisesRegex(reader.InvalidRequest, 'deleted or malformed'):
                self.call(request)

    def test_no_sell_fallback_or_silent_zero_or_rounding(self):
        for value in ['', '-1', '1000000001', '1.0000001', '0']:
            with self.subTest(value=value):
                self.write_table(rows=[(b' ', ['0002', 'SYNTHETIC', value, '60', '9000', '9000'])])
                with self.assertRaises(reader.InvalidRequest):
                    self.call(self.request(index=0))
        self.review['zero_reason'] = 'Synthetic no-charge setup explicitly reviewed; no hidden missing rate'
        result = self.call(self.request(index=0))
        self.assertEqual(result['worksheet_inputs']['setup_rate']['values']['base'], 0)
        self.assertEqual(result['worksheet_inputs']['zero_reason'], self.review['zero_reason'])
        self.write_table(rows=[(b' ', ['0002', 'SYNTHETIC', '1.234567', '60', '9000', '9000'])])
        self.assertEqual(self.call(self.request(index=0))['worksheet_inputs']['setup_rate']['values']['base'], 1.234567)

    def test_requires_explicit_well_formed_rate_review(self):
        request = self.request()
        for key in self.review:
            review = dict(self.review); review.pop(key)
            with self.subTest(missing=key), self.assertRaises(reader.InvalidRequest):
                self.call({**request, 'rate_review': json.dumps(review)})
        for key, value in [('rate_unit', 'USD/minute'), ('rate_unit', 'USD/hour SELL'), ('applicability', 'conflict'),
                           ('applicability', 'unknown'), ('reason', ''), ('reason', '\x85'), ('reviewer', None),
                           ('date', '2024-02-30'), ('source_date', '2025-01-01'), ('current', True)]:
            with self.subTest(key=key, value=value), self.assertRaises(reader.InvalidRequest):
                self.call({**request, 'rate_review': json.dumps({**self.review, key: value})})
        duplicate = json.dumps(self.review)[:-1] + ', "rate_unit": "USD/hour"}'
        for value in [None, self.review, '[]', '{', 'a' * 2401, duplicate]:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(reader.InvalidRequest):
                self.call({**request, 'rate_review': value})

    def test_schema_and_path_confinement_remain_closed(self):
        request = self.request()
        for path in ['QUOTOPER.DBF', 'MATERIAL.DBF', 'FORMULA.DBF', '../OPERATIO.DBF', '/OPERATIO.DBF']:
            with self.subTest(path=path), self.assertRaises(reader.InvalidRequest):
                self.call({**request, 'path': path})
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((reader.InvalidRequest, OSError)):
            self.call({**request, 'path': 'alias/OPERATIO.DBF'})
        for extra in [('QUOTE_NO', 'C', 4), ('ID', 'C', 4), ('FORM_ID', 'C', 4)]:
            self.write_table(fields=[*FIELDS, extra], rows=[(b' ', ['0002', 'SYNTHETIC', '60', '60', '9000', '9000', 'Q1'])])
            with self.subTest(extra=extra), self.assertRaises(reader.InvalidRequest):
                self.call(request)
        for column, kind in [(0, 'N'), (1, 'M'), (2, 'C'), (3, 'F')]:
            fields = list(FIELDS); name, _, length = fields[column]
            fields[column] = (name, kind, 4 if kind == 'M' else length)
            self.write_table(fields=fields, rows=[(b' ', ['0002', '0', '60', '60', '9000', '9000'])])
            with self.subTest(column=column, kind=kind), self.assertRaises(reader.InvalidRequest):
                self.call(request)
        self.write_table(fields=[(name.lower(), kind, length) for name, kind, length in FIELDS])
        lower = self.call(self.request())
        self.assertEqual(lower['field_evidence']['setup_rate']['field'], 'su_cost')

    def test_native_source_to_retained_request_and_review_preserves_rates_and_margin(self):
        source_request = self.request()
        source = self.native_source(source_request)
        self.assertFalse(source.get('isError'), source)
        self.assertTrue(self.native_source({**source_request, 'expected_record_sha256': '0' * 64}).get('isError'))
        bridge = source['content']
        quote = quote_tests.NativeQuoteTest()
        quote.setUp()
        self.addCleanup(quote.doCleanups)
        request = json.loads((ROOT / 'estimator/examples/should-cost-intake.json').read_text())
        part = request['parts'][0]
        route = part['pricing']['cost_basis']['routing'][0]
        inputs = bridge['worksheet_inputs']
        for key in ['setup_rate', 'run_rate', 'charge_inclusion']:
            route[key] = inputs[key]
        route['sources'].extend(inputs['sources'])
        for role, cost_source in zip(['setup_rate', 'run_rate'], inputs['sources']):
            part['source_evidence'].append({'id': role, 'sha256': cost_source['sha256'], 'locator': cost_source['locator'],
                                            'field': bridge['field_evidence'][role]['field'], 'record_index': 2})
            part['geometry'].append({'id': role, 'field': role, 'value': bridge['field_evidence'][role]['original_value'],
                                     'original_unit': 'USD/hour', 'source_ids': [role], 'applicability': 'assumed',
                                     'review': {key: self.review[key] for key in ['reviewer', 'reason']}})
            route['engineering_fact_ids'].append(role)
        original = quote.home / 'request.json'; original.write_text(json.dumps(request))
        uploads = []
        for name in ['drawing', 'worksheet']:
            path = quote.home / f'{name}.txt'; path.write_text(f'SYNTHETIC {name}, not customer evidence')
            uploads.append({'id': name, 'path': str(path), 'media_type': 'text/plain'})
        manifest = quote.home / 'uploads.json'; manifest.write_text(json.dumps(uploads))
        captured = subprocess.run(['node', str(ROOT / 'estimator/node_modules/tsx/dist/cli.mjs'),
                                  str(ROOT / 'estimator/src/intake-cli.ts'), str(original), '--attachments', str(manifest),
                                  '--operator', 'Synthetic operator'], env={**os.environ, 'HOME': str(quote.home)},
                                 capture_output=True, text=True, check=True, timeout=20)
        retained_path = Path(json.loads(captured.stdout)['request_path'])
        self.addCleanup(lambda: retained_path.parent.chmod(0o700))
        retained = json.loads(retained_path.read_text())
        result = quote.invoke(retained, corpus=None, no_database=True)
        self.assertFalse(result.get('isError'), result)
        content = result['content']; line = content['order']['lines'][0]
        self.assertEqual(content['total'], 120)
        self.assertEqual(line['cost_breakdown']['estimated_line_cost']['base'], 90)
        self.assertEqual(line['cost_breakdown']['estimated_line_margin_pct']['base'], 25)
        self.assertEqual(line['cost_breakdown']['supplied_basis']['routing'][0]['sources'][-2:], inputs['sources'])
        self.assertEqual(content['order']['request'], retained)
        self.assertEqual(content['review']['request_sha256'], content['order']['provenance']['request_sha256'])
        self.assertIsNone(content['order']['provenance']['register_sha256'])
        self.assertFalse(content['review']['customer_release_authorized'])
        self.assertTrue(content['review']['requires_human_review'])
