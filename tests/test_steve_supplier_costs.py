"""Synthetic selected supplier evidence -> reviewed worksheet inputs, never live prices."""

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
FIELDS = [("VEND_QUOT", "C", 8), ("QUOTE_NO", "C", 7), ("VENDOR_ID", "C", 5), ("ID", "C", 5),
          ("QTY1", "N", 20), ("PRICE1", "N", 20), ("QTY2", "N", 20), ("PRICE2", "N", 20),
          ("QTY8", "N", 20), ("PRICE8", "N", 20), ("MINIMUM", "N", 20), ("SU_CHARGE", "N", 20),
          ("DATE_STAMP", "D", 8), ("GOOD_UNTIL", "D", 8), ("VOIDED", "L", 1), ("COMMENT", "M", 4)]


class SupplierCostBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-supplier-costs-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bindings = {"fabritrak": str(self.root)}
        self.review = {"currency": "USD", "price_basis": "cost_per_original_unit", "original_unit": "kg",
                       "quantity_basis": "Synthetic selected 10 kg break applies to this one-line purchase, not finished pieces",
                       "minimum_scope": "excluding_setup", "setup_occurrences": 1,
                       "source_date": "2020-01-01", "reviewer": "Synthetic estimator", "date": "2024-05-31",
                       "reason": "Synthetic expired offer reviewed as estimate, not current procurement cost",
                       "applicability": "assumed", "charge_inclusion": "Synthetic material and supplier setup; no freight/tax"}
        self.write_table()

    def write_table(self, changes=None, marker=b" ", fields=FIELDS):
        values = ["00000072", "Q1", "00008", "00007", "1", "9.99999", "10", "4.12345", "1000", "2.00001",
                  "80.0000", "15.0000", "20200101", "20200201", "F", b'\x00\x00\x00\x00']
        for name, value in (changes or {}).items():
            values[next(i for i, f in enumerate(FIELDS) if f[0] == name)] = value
        first = list(values); first[7] = "8.76543"
        data = bytearray(dbf_bytes(fields, [(b" ", first), (b"*", values), (marker, values)]))
        for i, (name, kind, _) in enumerate(fields):
            if kind == 'N':
                data[32 + i * 32 + 17] = 5 if name.upper().startswith('PRICE') else 4 if name.upper() in ('MINIMUM', 'SU_CHARGE') else 0
        (self.root / 'VENDQUOT.DBF').write_bytes(data)

    def request(self, index=2, tier=2):
        data = (self.root / 'VENDQUOT.DBF').read_bytes()
        header, length = int.from_bytes(data[8:10], 'little'), int.from_bytes(data[10:12], 'little')
        offset = header + index * length
        return {"action": "dbf_supplier_costs", "source_set": "fabritrak", "path": "VENDQUOT.DBF",
                "vendor_quote": "00000072", "record_index": index, "price_break": tier,
                "expected_dbf_sha256": hashlib.sha256(data).hexdigest(),
                "expected_record_sha256": hashlib.sha256(data[offset:offset + length]).hexdigest(),
                "supplier_review": json.dumps(self.review)}

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

    def test_explicit_duplicate_and_break_preserve_original_values_and_hashes(self):
        result = self.call()
        inputs = result['worksheet_inputs']; primary = inputs['component']
        self.assertEqual(primary['unit_cost'], dict.fromkeys(('low', 'base', 'high'), 4.12345))
        self.assertEqual(primary['minimum_charge']['base'], 80)
        self.assertEqual(primary['original_unit'], 'kg')
        self.assertNotIn('minimum_quantity', primary)
        self.assertEqual(inputs['setup_component']['unit_cost']['base'], 15)
        self.assertEqual(inputs['setup_component']['quantity'], 1)
        self.assertEqual(result['selection']['record_index'], 2)
        rows = reader.read(self.bindings, reader.validate({'action': 'dbf_rows', 'source_set': 'fabritrak',
                           'path': 'VENDQUOT.DBF', 'quote_no': 'Q1'}))
        self.assertEqual(result['selection']['record_sha256'], rows['rows'][1]['record_sha256'])
        self.assertEqual(result['citation'], rows['citation'])
        self.assertEqual(result['record_values']['GOOD_UNTIL'], '20200201')
        self.assertIsNone(result['record_values']['COMMENT'])
        self.assertIn('not empty', result['memo_note'])
        self.assertEqual(result['field_evidence']['PRICE2']['original_value'], '4.12345')
        self.assertEqual(result['field_evidence']['PRICE2']['decimal_count'], 5)
        for field, evidence in result['field_evidence'].items():
            offset = result['selection']['record_byte_offset'] + evidence['record_byte_offset']
            raw = (self.root / 'VENDQUOT.DBF').read_bytes()[offset:offset + evidence['field_bytes']]
            self.assertEqual(raw.decode().strip(), evidence['original_value'])
        for source in primary['sources']:
            self.assertEqual(source['sha256'], self.request()['expected_dbf_sha256'])
            self.assertIn(self.request()['expected_record_sha256'], source['locator'])
            self.assertEqual(source['status'], 'approved_estimate')
            self.assertEqual(source['expires_date'], '2020-02-01')
            self.assertEqual(source['approval']['reviewer'], self.review['reviewer'])
        self.assertEqual(self.call(self.request(index=0))['worksheet_inputs']['component']['unit_cost']['base'], 8.76543)
        for tier, quantity, price in [(1, 1, 9.99999), (8, 1000, 2.00001)]:
            request = self.request(tier=tier)
            request['supplier_review'] = json.dumps({**self.review,
                'quantity_basis': f'Synthetic {quantity} kg purchase at explicitly selected break {tier}'})
            self.assertEqual(self.call(request)['worksheet_inputs']['component']['unit_cost']['base'], price)

    def test_explicit_minimum_scope_counts_setup_once_and_preserves_raw_charge(self):
        for occurrences, expected in [(1, 65), (2, 50), (6, 0)]:
            self.review.update(minimum_scope='including_setup', setup_occurrences=occurrences)
            result = self.call()
            self.assertEqual(result['worksheet_inputs']['component']['minimum_charge']['base'], expected)
            self.assertEqual(result['worksheet_inputs']['setup_component']['quantity'], occurrences)
            self.assertEqual(result['field_evidence']['MINIMUM']['original_value'], '80.0000')
        self.write_table({'MINIMUM': '0', 'SU_CHARGE': '0'})
        self.assertIsNone(self.call()['worksheet_inputs']['setup_component'])
        self.assertEqual(self.call()['worksheet_inputs']['component']['minimum_charge']['base'], 0)

    def test_selection_never_falls_back_or_loses_hash_pinning(self):
        request = self.request()
        for key, value in [('vendor_quote', '72'), ('record_index', 0), ('record_index', 1), ('record_index', 3),
                           ('record_index', None), ('record_index', True), ('record_index', -1),
                           ('price_break', 0), ('price_break', 9), ('price_break', None), ('price_break', True),
                           ('price_break', 1.5), ('expected_dbf_sha256', '0' * 64), ('expected_record_sha256', '0' * 64),
                           ('quote_no', 'Q1'), ('offset', 0), ('limit', 1), ('path', '../VENDQUOT.DBF'),
                           ('path', 'MATERIAL.DBF'), ('source_set', 'pdfs')]:
            with self.subTest(key=key, value=value), self.assertRaises(reader.InvalidRequest):
                self.call({**request, key: value})
        for key in request:
            broken = dict(request); broken.pop(key)
            with self.subTest(missing=key), self.assertRaises(reader.InvalidRequest):
                self.call(broken)
        self.write_table({'PRICE2': '5'})
        with self.assertRaisesRegex(reader.InvalidRequest, 'hash mismatch'):
            self.call(request)

    def test_deleted_voided_unknown_and_malformed_records_cannot_supply_costs(self):
        for marker in [b'*', b'?']:
            self.write_table(marker=marker)
            with self.assertRaisesRegex(reader.InvalidRequest, 'deleted or malformed'):
                self.call()
        for changes in [{'VOIDED': v} for v in ['T', 'Y', '?', '']] + [{'ID': ''}, {'VENDOR_ID': ''},
                        {'DATE_STAMP': '20200230'}, {'GOOD_UNTIL': '20201301'}]:
            self.write_table(changes)
            with self.subTest(changes=changes), self.assertRaises(reader.InvalidRequest):
                self.call()

    def test_unknown_amounts_are_not_zero_and_precision_is_not_silently_lost(self):
        for field in ['PRICE2', 'QTY2', 'MINIMUM', 'SU_CHARGE']:
            for value in ['', '-1', '1000000001', '1.1234567', 'oops']:
                self.write_table({field: value})
                with self.subTest(field=field, value=value), self.assertRaises(reader.InvalidRequest):
                    self.call()
        for field in ['PRICE2', 'QTY2']:
            self.write_table({field: '0'})
            with self.assertRaises(reader.InvalidRequest):
                self.call()
        self.write_table({'PRICE2': '0'})
        self.review['zero_reason'] = 'Synthetic setup-only charge; unit cost intentionally zero, not missing'
        result = self.call()['worksheet_inputs']['component']
        self.assertEqual(result['unit_cost']['base'], 0)
        self.assertEqual(result['zero_reason'], self.review['zero_reason'])

    def test_review_is_explicit_well_formed_and_never_current_cost_authority(self):
        for key in self.review:
            review = dict(self.review); review.pop(key)
            with self.subTest(missing=key), self.assertRaises(reader.InvalidRequest):
                self.call({**self.request(), 'supplier_review': json.dumps(review)})
        for key, value in [('currency', 'EUR'), ('price_basis', 'sell'), ('minimum_scope', 'unknown'),
                           ('setup_occurrences', 0), ('setup_occurrences', None), ('setup_occurrences', True),
                           ('setup_occurrences', '1'), ('setup_occurrences', 1000001), ('applicability', 'conflict'),
                           ('date', '2024-02-30'), ('source_date', '2025-01-01'), ('reason', ''),
                           ('reason', '\x85'), ('original_unit', ' kg'), ('reviewer', None), ('status', 'current')]:
            with self.subTest(key=key, value=value), self.assertRaises(reader.InvalidRequest):
                self.call({**self.request(), 'supplier_review': json.dumps({**self.review, key: value})})
        duplicate = json.dumps(self.review)[:-1] + ', "currency": "USD"}'
        for value in [None, self.review, '[]', '{', 'a' * 2801, duplicate]:
            with self.assertRaises(reader.InvalidRequest):
                self.call({**self.request(), 'supplier_review': value})
        fields = [(name, 'C' if name == 'PRICE2' else kind, length) for name, kind, length in FIELDS]
        self.write_table(fields=fields)
        with self.assertRaisesRegex(reader.InvalidRequest, 'VENDQUOT requires'):
            self.call()
        self.write_table(fields=[(name.lower(), kind, length) for name, kind, length in FIELDS])
        self.assertEqual(self.call()['field_evidence']['PRICE2']['field'], 'price2')
        self.assertEqual(self.call()['field_evidence']['GOOD_UNTIL']['field'], 'good_until')

    def test_expiry_survives_primary_and_setup_without_becoming_current_authority(self):
        for raw, normalized, timing in [('20200201', '2020-02-01', 'before'),
                                        ('20240229', '2024-02-29', 'before'),
                                        ('20240531', '2024-05-31', 'not before'),
                                        ('20281201', '2028-12-01', 'not before')]:
            with self.subTest(expiry=raw):
                self.write_table({'GOOD_UNTIL': raw})
                result = self.call()
                evidence = result['field_evidence']['GOOD_UNTIL']
                self.assertEqual(evidence['original_value'], raw)
                self.assertEqual(evidence['normalized_date'], normalized)
                self.assertEqual(evidence['field_bytes'], 8)
                for component in result['worksheet_inputs'].values():
                    self.assertIn(f'Supplier GOOD_UNTIL {normalized}; {timing} review date 2024-05-31; '
                                  'reviewed estimate only, not current-price authority', component['assumptions'])
                    for source in component['sources']:
                        self.assertEqual(source['expires_date'], normalized)
                        self.assertEqual(source['source_date'], self.review['source_date'])
                        self.assertNotIn('effective_date', source)
                        self.assertEqual(source['status'], 'approved_estimate')
                        self.assertEqual(source['approval']['date'], self.review['date'])
                        self.assertIn(f"GOOD_UNTIL original '{raw}', field offset {evidence['record_byte_offset']}, width 8", source['basis'])
                self.assertEqual(result['worksheet_inputs']['component']['unit_cost']['base'], 4.12345)
                self.assertEqual(result['worksheet_inputs']['component']['minimum_charge']['base'], 80)
                self.assertEqual(result['worksheet_inputs']['setup_component']['unit_cost']['base'], 15)

    def test_unknown_expiry_is_not_unlimited_or_an_invented_date(self):
        for raw in ['', '00000000']:
            with self.subTest(raw=raw):
                self.write_table({'GOOD_UNTIL': raw})
                result = self.call()
                self.assertEqual(result['field_evidence']['GOOD_UNTIL']['original_value'], raw)
                self.assertIsNone(result['field_evidence']['GOOD_UNTIL']['normalized_date'])
                for component in result['worksheet_inputs'].values():
                    self.assertIn('Supplier GOOD_UNTIL is unknown; blank/zero date is not unlimited validity; '
                                  'reviewed estimate only, not current-price authority', component['assumptions'])
                    for source in component['sources']:
                        self.assertNotIn('expires_date', source)
                        self.assertEqual(source['status'], 'approved_estimate')
                        self.assertIn(f'GOOD_UNTIL original {raw!r}', source['basis'])

    def test_native_supplier_costs_reach_retained_margin_quote_with_setup_and_minimum(self):
        for scope, expected_cost, expected_total in [('excluding_setup', 145, 193.33), ('including_setup', 130, 173.33)]:
            with self.subTest(scope=scope):
                self.review['minimum_scope'] = scope
                source_request = self.request()
                source = self.native_source(source_request)
                self.assertFalse(source.get('isError'), source)
                self.assertTrue(self.native_source({**source_request, 'expected_record_sha256': '0' * 64}).get('isError'))
                inputs = source['content']['worksheet_inputs']
                quote = quote_tests.NativeQuoteTest(); quote.setUp(); self.addCleanup(quote.doCleanups)
                request = json.loads((ROOT / 'estimator/examples/should-cost-intake.json').read_text())
                part = request['parts'][0]; basis = part['pricing']['cost_basis']
                material = basis['components'][0]
                material.update(inputs['component'], quantity=10, quantity_unit='kg', minimum_quantity=0)
                basis['components'].append({'id': 'supplier-setup', **inputs['setup_component']})
                basis['not_applicable'] = [item for item in basis['not_applicable'] if item['category'] != 'other']
                material['sources'].append({'source_class': 'operator_estimate', 'locator': 'upload:worksheet',
                    'source_date': self.review['source_date'], 'status': 'approved_estimate', 'applicability': 'assumed',
                    'basis': self.review['quantity_basis'], 'approval': {key: self.review[key] for key in ('reviewer', 'date', 'reason')}})
                next(f for f in part['geometry'] if f['id'] == 'material')['value'] = self.review['quantity_basis']
                original = quote.home / 'request.json'; original.write_text(json.dumps(request))
                uploads = []
                for name in ['drawing', 'worksheet']:
                    path = quote.home / f'{name}.txt'; path.write_text('SYNTHETIC ' + name + '; ten kg for one piece')
                    uploads.append({'id': name, 'path': str(path), 'media_type': 'text/plain'})
                manifest = quote.home / 'uploads.json'; manifest.write_text(json.dumps(uploads))
                captured = subprocess.run(['node', str(ROOT / 'estimator/node_modules/tsx/dist/cli.mjs'),
                    str(ROOT / 'estimator/src/intake-cli.ts'), str(original), '--attachments', str(manifest),
                    '--operator', 'Synthetic operator'], env={**os.environ, 'HOME': str(quote.home)},
                    capture_output=True, text=True, check=True, timeout=20)
                retained_path = Path(json.loads(captured.stdout)['request_path'])
                self.addCleanup(lambda p=retained_path.parent: p.chmod(0o700))
                retained = json.loads(retained_path.read_text())
                result = quote.invoke(retained, corpus=None, no_database=True)
                self.assertFalse(result.get('isError'), result)
                content = result['content']; line = content['order']['lines'][0]
                self.assertEqual(content['total'], expected_total)
                self.assertEqual(line['cost_breakdown']['estimated_line_cost']['base'], expected_cost)
                self.assertEqual(line['cost_breakdown']['estimated_line_margin_pct']['base'], 25)
                self.assertEqual(line['cost_breakdown']['components'][0]['priced_quantity'], 10)
                validity_warnings = [w for w in line['warnings'] if w.startswith('Source validity:')]
                self.assertTrue(validity_warnings)
                for warning in validity_warnings:
                    self.assertIn('expired on 2020-02-01', warning)
                    self.assertIn('retained as approved_estimate, not current-cost authority', warning)
                self.assertIn(r'expired on 2020\-02\-01', content['markdown'])
                self.assertEqual(line['cost_breakdown']['supplied_basis']['components'][1]['sources'], inputs['setup_component']['sources'])
                for component in line['cost_breakdown']['supplied_basis']['components'][:2]:
                    for item in component['sources']:
                        if item['source_class'] == 'supplier_quote':
                            self.assertEqual(item['expires_date'], '2020-02-01')
                            self.assertEqual(item['status'], 'approved_estimate')
                    self.assertIn('before review date', ' '.join(component['assumptions']))
                self.assertIn(r'GOOD\_UNTIL', content['markdown'])
                self.assertIn(r'2020\-02\-01', content['markdown'])
                self.assertEqual(content['order']['request'], retained)
                self.assertEqual(content['review']['request_sha256'], content['order']['provenance']['request_sha256'])
                self.assertFalse(content['review']['customer_release_authorized'])
                self.assertTrue(content['review']['requires_human_review'])
                self.assertIsNone(content['order']['provenance']['register_sha256'])
