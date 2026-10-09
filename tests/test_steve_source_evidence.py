"""Synthetic DBFs only: exact keys, physical evidence and bounded fail-closed reads."""

import base64
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("steve_source_reader", ROOT / "arsumbris/sources/read.py")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def dbf_bytes(fields, rows, *, version=0x30, codepage=3, backlink=False):
    """Rows are (deletion marker, field values); no production files are used."""
    header_length = 32 + 32 * len(fields) + 1 + (263 if backlink else 0)
    record_length = 1 + sum(field[2] for field in fields)
    header = bytearray(32)
    header[0], header[29] = version, codepage
    struct.pack_into("<IHH", header, 4, len(rows), header_length, record_length)
    output = bytearray(header)
    for name, kind, length in fields:
        descriptor = bytearray(32)
        descriptor[:len(name)] = name.encode("ascii")
        descriptor[11], descriptor[16] = ord(kind), length
        output.extend(descriptor)
    output.extend(b"\r" + (b"\x00" * 263 if backlink else b""))
    for marker, values in rows:
        output.extend(marker)
        for (_, kind, length), value in zip(fields, values):
            raw = value if isinstance(value, bytes) else value.encode("cp1252")
            assert len(raw) <= length
            output.extend(raw.rjust(length, b" ") if kind in "NF" else raw.ljust(length, b" "))
    output.extend(b"\x1a")
    return bytes(output)


class SteveSourceEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bindings = {"fabritrak": str(self.root)}

    def put(self, name, fields, rows, **options):
        data = dbf_bytes(fields, rows, **options)
        (self.root / name).write_bytes(data)
        return data

    def call(self, name, action="dbf_rows", **fields):
        request = reader.validate({"action": action, "source_set": "fabritrak", "path": name, **fields})
        return reader.read(self.bindings, request)

    def test_stdlib_schema_and_hash_proof_without_dbfread(self):
        fields = [("QUOTE_NO", "C", 7), ("PRICE", "N", 12), ("COMMENT", "M", 4)]
        data = self.put("QUOTEN.DBF", fields, [(b" ", ["Q1", "12.5000", b"\x01\x00\x00\x00"])], backlink=True)
        original_import = builtins.__import__

        def without_dbfread(name, *args, **kwargs):
            if name == "dbfread":
                raise ImportError("deliberately unavailable")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_dbfread):
            schema = self.call("QUOTEN.DBF", "dbf_schema")
            result = self.call("QUOTEN.DBF", quote_no="Q1")
        self.assertEqual(schema["fields"][1]["record_byte_offset"], 8)
        self.assertEqual(schema["exact_filters"], [{"quote_no": "QUOTE_NO"}])
        self.assertEqual(schema["citation"]["dbf_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(schema["citation"], result["citation"])
        row = result["rows"][0]
        offset, length = row["record_byte_offset"], row["record_bytes"]
        self.assertEqual(offset, schema["header_bytes"])
        self.assertEqual(length, schema["record_bytes"])
        self.assertEqual(row["record_sha256"], hashlib.sha256(data[offset:offset + length]).hexdigest())
        self.assertEqual(row["values"]["PRICE"], "12.5000")
        self.assertEqual(result["record_index_base"], 0)
        self.assertIn("not authenticated", schema["citation"]["verification"])

    def test_memo_deferred_is_not_empty_or_binary_pointer_text(self):
        self.put("QUOTEN.DBF", [("QUOTE_NO", "C", 7), ("COMMENT", "M", 4)],
                 [(b" ", ["Q1", b"ABCD"])])
        result = self.call("QUOTEN.DBF", quote_no="Q1")
        row = result["rows"][0]
        self.assertIsNone(row["values"]["COMMENT"])
        self.assertEqual(row["memo_fields"], ["COMMENT"])
        pointer = row["binary_fields"]["COMMENT"]
        self.assertEqual(pointer["status"], "memo_decode_deferred")
        self.assertEqual(base64.b64decode(pointer["raw_bytes"]), b"ABCD")
        self.assertNotIn("ABCD", json.dumps(result))
        # Even a present/symlinked sibling must not be opened by the deferred reader.
        (self.root / "QUOTEN.FPT").symlink_to(self.root / "does-not-exist")
        self.assertEqual(self.call("QUOTEN.DBF", quote_no="Q1"), result)

    def test_letter_item_filters_are_exact_table_specific_and_keep_duplicates(self):
        fields = [("QUOTLETTER", "C", 8), ("ITEM", "C", 3), ("QUOTE_NO", "C", 7)]
        rows = [(b" ", ["L1", "001", "Q1"]), (b" ", ["L1", "002", "Q1"]),
                (b" ", ["L2", "001", "Q1"]), (b" ", ["L1", "001", "Q2"])]
        for name in ("QUOTLINE.DBF", "QUOTLEIT.DBF"):
            self.put(name, fields, rows)
            result = self.call(name, quotletter="L1", item="001")
            self.assertEqual([row["record_index"] for row in result["rows"]], [0, 3])
            self.assertEqual(result["filter_fields"], {"quotletter": "QUOTLETTER", "item": "ITEM"})
            self.assertEqual(self.call(name, quotletter="L1", item="1")["rows"], [])
            with self.assertRaises(reader.InvalidRequest):
                self.call(name, quotletter="L1")
        self.put("OTHER.DBF", fields, rows)
        with self.assertRaises(reader.InvalidRequest):
            self.call("OTHER.DBF", quotletter="L1", item="001")
        self.put("QUOTLETT.DBF", [("QUOTLETTER", "C", 8)], [(b" ", ["L1"])])
        self.assertEqual(len(self.call("QUOTLETT.DBF", quotletter="L1")["rows"]), 1)

    def test_work_order_job_and_operation_composite_keys(self):
        fields = [("WO_NO", "C", 8), ("PAGE_NO", "N", 3), ("SEQ", "C", 3)]
        rows = [(b" ", ["W1", "1", "001"]), (b" ", ["W1", "2", "001"]),
                (b" ", ["W1", "1", "002"]), (b" ", ["W2", "1", "001"])]
        for name in ("WOSEQ.DBF", "wocoll.dbf"):
            self.put(name, fields, rows)
            result = self.call(name, wo_no="W1", page_no="1", seq="001")
            self.assertEqual([row["record_index"] for row in result["rows"]], [0])
            self.assertEqual(len(self.call(name, wo_no="W1")["rows"]), 3)
            self.assertEqual(self.call(name, wo_no="W1", page_no="01", seq="001")["rows"], [])
        for name in ("WOJOBS.DBF", "SOLOTS.DBF", "WOBOM.DBF"):
            self.put(name, [("WO_NO", "C", 8), ("JOBNO", "C", 8)], [(b" ", ["W1", "J1"])])
            self.assertEqual(len(self.call(name, wo_no="W1")["rows"]), 1)
            self.assertEqual(len(self.call(name, jobno="J1")["rows"]), 1)
        for name in ("WOHEAD.DBF", "WOBILL.DBF", "WOSHIP.DBF"):
            self.put(name, [("WO_NO", "C", 8)], [(b" ", ["W1"])])
            self.assertEqual(len(self.call(name, wo_no="W1")["rows"]), 1)
        self.put("SOMAST.DBF", [("JOBNO", "C", 8), ("QUOTE_NO", "C", 7)], [(b" ", ["J1", "Q1"])])
        self.assertEqual(len(self.call("SOMAST.DBF", jobno="J1")["rows"]), 1)
        self.assertEqual(len(self.call("SOMAST.DBF", quote_no="Q1")["rows"]), 1)

    def test_physical_paging_deleted_rows_and_bounded_miss(self):
        self.put("QUOTEN.DBF", [("QUOTE_NO", "C", 7)],
                 [(b"*", ["Q1"]), (b" ", ["Q2"]), (b" ", ["Q1"]), (b" ", ["Q1"])])
        with patch.object(reader, "MAX_SCAN_RECORDS", 2):
            first = self.call("QUOTEN.DBF", quote_no="Q1")
        self.assertEqual(first["rows"], [])
        self.assertEqual((first["scanned_records"], first["deleted_records_skipped"], first["next_offset"]), (2, 1, 2))
        self.assertTrue(first["has_more"])
        self.assertIn("not corpus-wide absence", first["lookup_scope_note"])
        second = self.call("QUOTEN.DBF", quote_no="Q1", offset=first["next_offset"], limit=1,
                           expected_dbf_sha256=first["citation"]["dbf_sha256"])
        self.assertEqual(second["rows"][0]["record_index"], 2)
        self.assertEqual(second["next_offset"], 3)
        last = self.call("QUOTEN.DBF", quote_no="Q1", offset=3)
        self.assertEqual(last["rows"][0]["record_index"], 3)
        self.assertFalse(last["has_more"])
        self.assertEqual(self.call("QUOTEN.DBF", quote_no="Q1", offset=4)["rows"], [])
        with self.assertRaises(reader.InvalidRequest):
            self.call("QUOTEN.DBF", quote_no="Q1", offset=5)
        with patch.object(reader, "MAX_SCAN_BYTES", 16):
            self.assertEqual(self.call("QUOTEN.DBF", quote_no="Q1")["next_offset"], 2)

    def test_file_hash_pin_and_midread_mutation_fail_closed(self):
        data = self.put("QUOTEN.DBF", [("QUOTE_NO", "C", 7)], [(b" ", ["Q1"])])
        with self.assertRaisesRegex(reader.InvalidRequest, "hash mismatch"):
            self.call("QUOTEN.DBF", quote_no="Q1", expected_dbf_sha256="0" * 64)
        original_values = reader.record_values

        def change_during_read(table, record):
            (self.root / "QUOTEN.DBF").write_bytes(data + b"extra")
            return original_values(table, record)

        with patch.object(reader, "record_values", side_effect=change_during_read):
            with self.assertRaisesRegex(reader.InvalidRequest, "changed during read"):
                self.call("QUOTEN.DBF", quote_no="Q1")

    def test_malformed_headers_and_records_fail_closed_not_partial(self):
        good = dbf_bytes([("QUOTE_NO", "C", 7)], [(b" ", ["Q1"])])
        variants = [good[:-3], good + b"junk", good[:64] + b"x" + good[65:]]
        for position, value in ((0, 0), (8, 0), (10, 0), (14, 1), (15, 1), (29, 0xFF), (50, 2)):
            changed = bytearray(good)
            changed[position] = value
            variants.append(bytes(changed))
        variants += [dbf_bytes([("QUOTE_NO", "C", 7), ("quote_no", "C", 7)], [(b" ", ["Q1", "Q1"])]),
                     dbf_bytes([("QUOTE_NO", "C", 7)], [(b"!", ["Q1"])]),
                     dbf_bytes([("QUOTE_NO", "C", 7)], [(b" ", ["Q1"]), (b"!", ["Q2"])]),
                     dbf_bytes([("QUOTE_NO", "C", 7), ("PRICE", "N", 8)], [(b" ", ["Q1", "NaN"])]),
                     dbf_bytes([("QUOTE_NO", "C", 7), ("DATE", "D", 8)], [(b" ", ["Q1", "20260231"])]),
                     dbf_bytes([("QUOTE_NO", "C", 7), ("FLAG", "L", 1)], [(b" ", ["Q1", "X"])])]
        for index, data in enumerate(variants):
            with self.subTest(index=index):
                (self.root / "QUOTEN.DBF").write_bytes(data)
                with self.assertRaises(reader.InvalidRequest):
                    self.call("QUOTEN.DBF", quote_no="Q1")
        (self.root / "QUOTEN.DBF").write_bytes(good)
        with patch.object(reader, "MAX_DBF_BYTES", len(good) - 1):
            with self.assertRaises(reader.InvalidRequest):
                self.call("QUOTEN.DBF", "dbf_schema")

    def test_oversized_projection_fails_instead_of_nonadvancing_pagination(self):
        fields = [("QUOTE_NO", "C", 7)] + [(f"F{i}", "C", 255) for i in range(255)]
        self.put("QUOTEN.DBF", fields, [(b" ", ["Q1"] + ["x" * 255] * 255)])
        with self.assertRaisesRegex(reader.InvalidRequest, "projection exceeds response limit"):
            self.call("QUOTEN.DBF", quote_no="Q1")
        fields.append(("EXTRA", "C", 1))
        self.put("QUOTEN.DBF", fields, [(b" ", ["Q1"] + ["x" * 255] * 255 + ["x"])])
        with self.assertRaises(reader.InvalidRequest):
            self.call("QUOTEN.DBF", "dbf_schema")

    def test_undecodable_text_is_not_replacement_evidence(self):
        self.put("QUOTEN.DBF", [("QUOTE_NO", "C", 7), ("NOTE", "C", 4)], [(b" ", ["Q1", b"\x81"])])
        with self.assertRaises(reader.InvalidRequest):
            self.call("QUOTEN.DBF", quote_no="Q1")

    def test_arbitrary_filters_partial_keys_and_ambiguous_identifiers_rejected(self):
        for fields in ({"wo_no": "W1", "page_no": "1"}, {"wo_no": "W1", "seq": "001"},
                       {"wo_no": "W1", "jobno": "J1"}, {"item": "001"}, {"quote_no": "Q1", "column": "ID"},
                       {"quote_no": "Q1", "sql": "select *"}, {"quote_no": " Q1"}, {"quote_no": "Q1\x7f"},
                       {"quote_no": "Q1", "limit": True}, {"wo_no": "W1", "page_no": 1, "seq": "001"},
                       {"quote_no": "Q1", "expected_dbf_sha256": "abc"}):
            with self.subTest(fields=fields), self.assertRaises(reader.InvalidRequest):
                self.call("QUOTEN.DBF", **fields)
        self.put("FORMULA.DBF", [("ID", "C", 7), ("FORM_ID", "C", 7)], [(b" ", ["A", "A"])])
        with self.assertRaises(reader.InvalidRequest):
            self.call("FORMULA.DBF", record_id="A")
        self.put("WOSEQ.DBF", [("WO_NO", "C", 8), ("PAGE_NO", "C", 3), ("SEQ", "C", 3)],
                 [(b" ", ["W1", "1", "001"])])
        with self.assertRaises(reader.InvalidRequest):
            self.call("WOSEQ.DBF", wo_no="W1", page_no="1", seq="001")

    def test_dbf_confinement_blocks_symlink_file_directory_and_path_escape(self):
        self.put("QUOTEN.DBF", [("QUOTE_NO", "C", 7)], [(b" ", ["Q1"])])
        (self.root / "LINK.DBF").symlink_to(self.root / "QUOTEN.DBF")
        (self.root / "alias").symlink_to(self.root, target_is_directory=True)
        for path in ("LINK.DBF", "alias/QUOTEN.DBF", "../QUOTEN.DBF", str(self.root / "QUOTEN.DBF")):
            with self.subTest(path=path), self.assertRaises((reader.InvalidRequest, OSError)):
                self.call(path, quote_no="Q1")
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.root / "PIPE.DBF")
            with self.assertRaises(reader.InvalidRequest):
                self.call("PIPE.DBF", quote_no="Q1")


if __name__ == "__main__":
    unittest.main()
