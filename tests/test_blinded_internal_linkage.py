"""Synthetic-only checks for the separate, operator-only source-linkage audit."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('linkage', ROOT / 'evals/diagnose-internal-linkage.py')
LINKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINKAGE)


def fixture(table, rows):
    numeric = ('THICKNESS', 'PART_L', 'PART_W', 'STOCK_L', 'STOCK_W', 'WGHT_PIECE') if table == 'QUOTEM' else ('SUTIME', 'RUNTIME') + tuple(f'{p}_V{i}' for p in ('SU', 'RUN') for i in range(1, 11))
    text = ('ID',) if table == 'QUOTEM' else ('OPER_ID', 'SU_FORM_ID', 'RU_FORM_ID')
    fields = [('QUOTE_NO', 'C', 7)] + [(f, 'N', 12) for f in numeric] + [(f, 'C', 5) for f in text]
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(n for _, _, n in fields)
    header = bytearray(header_len)
    header[0] = 3
    header[4:8] = len(rows).to_bytes(4, 'little')
    header[8:10] = header_len.to_bytes(2, 'little')
    header[10:12] = record_len.to_bytes(2, 'little')
    for i, (name, kind, size) in enumerate(fields):
        pos = 32 + 32 * i
        header[pos:pos+len(name)] = name.encode()
        header[pos+11] = ord(kind)
        header[pos+16] = size
    header[-1] = 13
    data = bytes(header)
    for row in rows:
        data += b'*' if row.get('deleted') else b' '
        for name, kind, size in fields:
            value = str(row.get(name, 0 if kind == 'N' else '')).encode()
            assert len(value) <= size
            data += value.ljust(size)
    return data


class InternalLinkageTest(unittest.TestCase):
    def inspect(self, table, data, targets, digest=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / (table + '.DBF')
            path.write_bytes(data)
            with patch.dict(LINKAGE.SOURCE_PINS, {table: digest or hashlib.sha256(data).hexdigest()}):
                return LINKAGE.dbf_links(path, table, targets)

    def test_excluded_quote_fields_are_not_decoded(self):
        data = fixture('QUOTEM', [
            {'QUOTE_NO': 'DEMO001', 'THICKNESS': 2, 'STOCK_L': 10, 'ID': 'MAT01'},
            {'QUOTE_NO': 'DEMO002', 'THICKNESS': 'INVALID'},
        ])
        result = self.inspect('QUOTEM', data, {'DEMO001'})
        self.assertEqual(list(result), ['DEMO001'])
        self.assertEqual(result['DEMO001']['active_rows'], 1)
        self.assertTrue(result['DEMO001']['positive_fields']['THICKNESS'])
        self.assertFalse(result['DEMO001']['positive_fields']['PART_L'])

    def test_deleted_records_are_counted_but_not_used(self):
        data = fixture('QUOTEM', [{'QUOTE_NO': 'DEMO001', 'deleted': True, 'THICKNESS': 'INVALID'}])
        result = self.inspect('QUOTEM', data, {'DEMO001'})['DEMO001']
        self.assertEqual(result, {'active_rows': 0, 'deleted_rows': 1, 'positive_fields': {}, 'nonblank_fields': {}})

    def test_formula_variables_are_not_direct_time_measurements(self):
        data = fixture('QUOTOPER', [{'QUOTE_NO': 'DEMO001', 'SU_V1': 5, 'RUN_V1': '.2', 'SU_FORM_ID': 'F001'}])
        result = self.inspect('QUOTOPER', data, {'DEMO001'})['DEMO001']
        self.assertTrue(result['positive_fields']['SU_V1'])
        self.assertTrue(result['positive_fields']['RUN_V1'])
        self.assertFalse(result['positive_fields']['SUTIME'])
        self.assertFalse(result['positive_fields']['RUNTIME'])

    def test_target_order_is_stable_and_missing_rows_remain_visible(self):
        result = self.inspect('QUOTEM', fixture('QUOTEM', []), {'DEMO003', 'DEMO001'})
        self.assertEqual(list(result), ['DEMO001', 'DEMO003'])
        self.assertEqual(result['DEMO003']['active_rows'], 0)

    def test_changed_source_bytes_are_rejected(self):
        data = fixture('QUOTEM', [])
        with self.assertRaises(AssertionError):
            self.inspect('QUOTEM', data + b'changed', set(), hashlib.sha256(data).hexdigest())

    def test_truncated_source_is_rejected(self):
        data = fixture('QUOTEM', [{'QUOTE_NO': 'DEMO001'}])
        with self.assertRaises(AssertionError):
            self.inspect('QUOTEM', data[:-1], {'DEMO001'})

    def test_all_recorded_dates_must_pass_strict_cutoff(self):
        row = {'quote_date': '2024-02-29', 'date_stamp': '', 'letter_date': ''}
        self.assertTrue(LINKAGE.historical_metadata([row], '2024-03-01'))
        self.assertFalse(LINKAGE.historical_metadata([row], '2024-02-29'))
        self.assertFalse(LINKAGE.historical_metadata([{**row, 'quote_date': '2023-02-29'}], '2024-03-01'))
        self.assertFalse(LINKAGE.historical_metadata([row, {**row, 'date_stamp': '2024-03-02'}], '2024-03-01'))

    def test_public_summary_is_bound_to_operator_script(self):
        report = json.loads((ROOT / 'evals/steve-internal-linkage-diagnostic.public.json').read_bytes())
        self.assertEqual(report['script_sha256'], hashlib.sha256((ROOT / 'evals/diagnose-internal-linkage.py').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
