"""Synthetic physical routing/formula selection through native reviewed pricing."""
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
OPS = [("QUOTE_NO", "C", 7), ("SEQ", "C", 3), ("OPER_ID", "C", 4),
       ("SU_FORM_ID", "C", 4), ("RU_FORM_ID", "C", 4), ("SU_V1", "N", 20),
       ("RUN_V1", "N", 20), ("SUTIME", "N", 10), ("RUNTIME", "N", 10), ("RUN_RATE", "N", 10)]
FORMS = [("FORM_ID", "C", 4), ("FORMULA", "C", 80), ("FORM_VARS", "N", 2), ("V1_DESC", "C", 40)]


class RoutingTimeBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-routing-time-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bindings = {"fabritrak": str(self.root)}
        self.review = {"input_unit": "pieces_per_hour", "operation_source_date": "2020-01-01",
                       "formula_source_date": "2021-01-01", "reviewer": "Synthetic estimator", "date": "2024-05-31",
                       "reason": "Synthetic selected historical timing estimate, not actual/current time", "applicability": "assumed"}
        self.ops = [(b" ", ["Q1", "001", "OP1", "S", "R", "99", "999", "0", "0", "9000"]),
                    (b"*", ["Q1", "001", "OP1", "S", "R", "99", "999", "0", "0", "9000"]),
                    (b" ", ["Q1", "001", "OP1", "S", "R", "30.0000", "3.0000", "", "0", "9000"])]
        self.forms = [(b" ", ["S", "SU_V1", "1", "SU Time (MINUTES)"]),
                      (b" ", ["R", "60/RUN_V1", "1", "Parts Per Hour"]),
                      (b" ", ["R", "TABLE('SAW',RUN_V1)", "1", "Parts Per Hour"])]
        self.write_tables()

    def write_tables(self, ops_fields=OPS, form_fields=FORMS):
        for name, fields, rows in [("QUOTOPER.DBF", ops_fields, self.ops), ("FORMULA.DBF", form_fields, self.forms)]:
            (self.root / name).write_bytes(dbf_bytes(fields, rows))

    def request(self, phase="run", index=2, formula_index=None):
        formula_index = (0 if phase == "setup" else 1) if formula_index is None else formula_index
        payload = {"action": "dbf_routing_time", "source_set": "fabritrak", "path": "QUOTOPER.DBF",
                   "quote_no": "Q1", "phase": phase, "record_index": index,
                   "formula_path": "FORMULA.DBF", "formula_record_index": formula_index,
                   "time_review": json.dumps({**self.review, "input_unit": "minutes" if phase == "setup" else self.review['input_unit']})}
        for name, selected, prefix in [("QUOTOPER.DBF", index, ""), ("FORMULA.DBF", formula_index, "formula_")]:
            data = (self.root / name).read_bytes()
            start, length = int.from_bytes(data[8:10], 'little'), int.from_bytes(data[10:12], 'little')
            raw = data[start + selected * length:start + (selected + 1) * length]
            payload[f"expected_{prefix}dbf_sha256"] = hashlib.sha256(data).hexdigest()
            payload[f"expected_{prefix}record_sha256"] = hashlib.sha256(raw).hexdigest()
        return payload

    def call(self, request=None):
        return reader.read(self.bindings, reader.validate(request or self.request()))

    def native_source(self, request):
        config = self.root / 'sources.json'; config.write_text(json.dumps(self.bindings)); config.chmod(0o600)
        script = """import {createPlugin} from './arsumbris/sources/tool.ts';
console.log(JSON.stringify(await createPlugin({workspace: process.cwd()}).invoke(JSON.parse(process.argv[1]))));"""
        result = subprocess.run(['node', '--input-type=module', '-e', script, json.dumps(request)], cwd=ROOT,
            env={**os.environ, 'KELLER_SOURCE_CONFIG': str(config), 'KELLER_PYTHON': sys.executable},
            capture_output=True, text=True, check=True, timeout=20)
        return json.loads(result.stdout)

    def test_preserves_selected_duplicate_original_units_and_both_sources(self):
        request = self.request(); result = self.call(request)
        self.assertEqual(result['timing_input']['run_time'], {'unit': 'pieces_per_hour', 'values': {'low': 3, 'base': 3, 'high': 3}})
        self.assertEqual(result['evidence']['operation']['original_variable_text'], '3.0000')
        self.assertEqual(result['evidence']['operation']['record_index'], 2)
        self.assertEqual(result['evidence']['formula']['record_index'], 1)
        self.assertEqual(result['evidence']['formula']['expression'], '60/RUN_V1')
        for source, prefix in zip(result['sources'], ['', 'formula_']):
            self.assertEqual(source['sha256'], request[f'expected_{prefix}dbf_sha256'])
            self.assertIn(request[f'expected_{prefix}record_sha256'], source['locator'])
            self.assertEqual(source['status'], 'approved_estimate')
            self.assertEqual(source['approval']['reviewer'], self.review['reviewer'])
        self.assertNotIn('9000', json.dumps(result))
        self.assertEqual(self.call(self.request(index=0))['timing_input']['run_time']['values']['base'], 999)

    def test_pins_all_records_identities_and_required_fields(self):
        request = self.request()
        for key in request:
            if key == 'action':
                continue
            invalid = dict(request); invalid.pop(key)
            with self.subTest(missing=key), self.assertRaises(reader.InvalidRequest):
                self.call(invalid)
        for key, value in [('quote_no', 'Q2'), ('record_index', 0), ('record_index', 99), ('record_index', True),
                           ('record_index', -1), ('formula_record_index', 0), ('formula_record_index', None),
                           ('formula_record_index', 99), ('formula_record_index', 0.5), ('phase', 'other'), ('offset', 0)]:
            with self.subTest(key=key, value=value), self.assertRaises(reader.InvalidRequest):
                self.call({**request, key: value})
        for key in [key for key in request if key.startswith('expected_')]:
            with self.subTest(key=key), self.assertRaises(reader.InvalidRequest):
                self.call({**request, key: '0' * 64})
        with self.assertRaisesRegex(reader.InvalidRequest, 'deleted'):
            self.call(self.request(index=1))
        self.forms[1] = (b'*', self.forms[1][1]); self.write_tables()
        with self.assertRaisesRegex(reader.InvalidRequest, 'deleted'):
            self.call()

    def test_blank_zero_negative_and_precision_never_fall_back_to_stored_time_or_rates(self):
        for value in ['', '0', '-1', '1000000001', '1.0000001']:
            self.ops[2][1][6] = value; self.write_tables()
            with self.subTest(value=value), self.assertRaises(reader.InvalidRequest):
                self.call()
        self.ops[2][1][6] = '1.234567'; self.write_tables()
        self.assertEqual(self.call()['timing_input']['run_time']['values']['base'], 1.234567)
        self.forms[1][1][1:] = ['RUN_V1', '1', 'Minutes Per Part']
        self.review['input_unit'] = 'minutes_per_piece'
        self.ops[2][1][6] = '0'; self.write_tables()
        with self.assertRaisesRegex(reader.InvalidRequest, 'zero_reason'):
            self.call()
        self.review['zero_reason'] = 'Explicit synthetic no-run estimate; not an omitted process'
        result = self.call()
        self.assertEqual(result['timing_input']['run_time']['values']['base'], 0)
        self.assertEqual(result['zero_reason'], self.review['zero_reason'])
        self.forms[1][1][1:] = ['60/RUN_V1', '1', 'Parts Per Hour']; self.write_tables()
        self.review['input_unit'] = 'pieces_per_hour'
        with self.assertRaisesRegex(reader.InvalidRequest, 'must be positive'):
            self.call()

    def test_only_explicit_formula_shapes_and_units_are_supported(self):
        for expression, count, label in [("RUN_V1*RUN_V2", '2', 'Parts Per Hour'), ('60/RUN_V1', '2', 'Parts Per Hour'),
                                         ('60/RUN_V1', '1', 'Minutes Per Part'), ('__import__("os")', '1', 'Parts Per Hour')]:
            self.forms[1][1][1:] = [expression, count, label]; self.write_tables()
            with self.subTest(expression=expression, count=count, label=label), self.assertRaises(reader.InvalidRequest):
                self.call()
        with self.assertRaisesRegex(reader.InvalidRequest, 'unsupported'):
            self.call(self.request(formula_index=2))
        self.forms[0][1][1:] = ['SU_V1*60', '1', 'SU Time (Hours)']; self.ops[2][1][5] = '0.5'; self.write_tables()
        req = self.request(phase='setup')
        with self.assertRaisesRegex(reader.InvalidRequest, 'input_unit'):
            self.call(req)
        req['time_review'] = json.dumps({**self.review, 'input_unit': 'hours'})
        self.assertEqual(self.call(req)['timing_input']['setup_time'], {'unit': 'hours', 'values': {'low': 0.5, 'base': 0.5, 'high': 0.5}})

    def test_review_is_explicit_bounded_and_chronologically_consistent(self):
        for key in self.review:
            review = dict(self.review); review.pop(key)
            with self.subTest(missing=key), self.assertRaises(reader.InvalidRequest):
                self.call({**self.request(), 'time_review': json.dumps(review)})
        for key, value in [('input_unit', 'minutes_per_piece'), ('applicability', 'unknown'), ('applicability', 'conflict'),
                           ('reason', ''), ('reviewer', '\x85'), ('date', '2024-02-30'), ('date', '2019-01-01'),
                           ('operation_source_date', '2025-01-01'), ('formula_source_date', '2025-01-01'), ('current', True)]:
            with self.subTest(key=key), self.assertRaises(reader.InvalidRequest):
                self.call({**self.request(), 'time_review': json.dumps({**self.review, key: value})})
        duplicate = json.dumps(self.review)[:-1] + ', "input_unit": "pieces_per_hour"}'
        for value in [None, self.review, '{}', '[]', '{', 'x' * 2401, duplicate]:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(reader.InvalidRequest):
                self.call({**self.request(), 'time_review': value})

    def test_paths_and_field_schemas_stay_confined(self):
        for key, paths in [('path', ['OPERATIO.DBF', '../QUOTOPER.DBF', '/QUOTOPER.DBF']),
                           ('formula_path', ['QUOTOPER.DBF', '../FORMULA.DBF', '/FORMULA.DBF'])]:
            for path in paths:
                with self.subTest(key=key, path=path), self.assertRaises(reader.InvalidRequest):
                    self.call({**self.request(), key: path})
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((reader.InvalidRequest, OSError)):
            self.call({**self.request(), 'formula_path': 'alias/FORMULA.DBF'})
        self.write_tables(ops_fields=[(name, 'C' if name == 'RUN_V1' else kind, width) for name, kind, width in OPS])
        with self.assertRaisesRegex(reader.InvalidRequest, 'schema'):
            self.call()
        self.write_tables(form_fields=[(name, 'C' if name == 'FORM_VARS' else kind, width) for name, kind, width in FORMS])
        with self.assertRaisesRegex(reader.InvalidRequest, 'schema'):
            self.call()

    def test_native_source_to_retained_quote_preserves_time_sources_and_margin(self):
        bridges = []
        for phase in ['setup', 'run']:
            result = self.native_source(self.request(phase))
            self.assertFalse(result.get('isError'), result)
            bridges.append(result['content'])
        self.assertTrue(self.native_source({**self.request(), 'expected_formula_dbf_sha256': '0' * 64}).get('isError'))
        quote = quote_tests.NativeQuoteTest(); quote.setUp(); self.addCleanup(quote.doCleanups)
        request = json.loads((ROOT / 'estimator/examples/should-cost-intake.json').read_text())
        part = request['parts'][0]; route = part['pricing']['cost_basis']['routing'][0]
        for bridge in bridges:
            route.update(bridge['timing_input']); route['sources'].extend(bridge['sources'])
            for index, source in enumerate(bridge['sources']):
                identity = f"{bridge['phase']}-time-{index}"
                part['source_evidence'].append({'id': identity, 'sha256': source['sha256'], 'locator': source['locator']})
                part['geometry'].append({'id': identity, 'field': f"{bridge['phase']}_time_support",
                    'value': bridge['evidence']['operation']['original_variable_text'] if index == 0 else bridge['evidence']['formula']['expression'],
                    'original_unit': bridge['time_review']['input_unit'], 'source_ids': [identity], 'applicability': 'assumed',
                    'review': {key: self.review[key] for key in ['reviewer', 'reason']}})
                route['engineering_fact_ids'].append(identity)
        original = quote.home / 'request.json'; original.write_text(json.dumps(request))
        uploads = []
        for name in ['drawing', 'worksheet']:
            path = quote.home / f'{name}.txt'; path.write_text(f'SYNTHETIC {name}, not customer evidence')
            uploads.append({'id': name, 'path': str(path), 'media_type': 'text/plain'})
        manifest = quote.home / 'uploads.json'; manifest.write_text(json.dumps(uploads))
        captured = subprocess.run(['node', str(ROOT / 'estimator/node_modules/tsx/dist/cli.mjs'),
            str(ROOT / 'estimator/src/intake-cli.ts'), str(original), '--attachments', str(manifest), '--operator', 'Synthetic operator'],
            env={**os.environ, 'HOME': str(quote.home)}, capture_output=True, text=True, check=True, timeout=20)
        retained_path = Path(json.loads(captured.stdout)['request_path']); self.addCleanup(lambda: retained_path.parent.chmod(0o700))
        retained = json.loads(retained_path.read_text()); result = quote.invoke(retained, corpus=None, no_database=True)
        self.assertFalse(result.get('isError'), result)
        content = result['content']; breakdown = content['order']['lines'][0]['cost_breakdown']
        self.assertEqual(content['total'], 120)
        self.assertEqual(breakdown['estimated_line_cost']['base'], 90)
        self.assertEqual(breakdown['estimated_line_margin_pct']['base'], 25)
        self.assertEqual(breakdown['routing'][0]['run_minutes_per_piece']['base'], 20)
        self.assertEqual(breakdown['supplied_basis']['routing'][0]['sources'][-4:], [s for b in bridges for s in b['sources']])
        self.assertEqual(content['order']['request'], retained)
        self.assertFalse(content['review']['customer_release_authorized'])
        self.assertTrue(content['review']['requires_human_review'])
