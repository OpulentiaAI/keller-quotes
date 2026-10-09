"""Synthetic security and paging checks for the native Keller source reader."""

import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / "arsumbris/sources/read.py"
spec = importlib.util.spec_from_file_location("keller_source_reader", READER)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def synthetic_dbf(path, identifier="QUOTE_NO"):
    fields = [(identifier, "C", 7), ("PRICE1", "N", 12), ("COMMENT", "M", 4)]
    records = [("Q100", "12.50", "0"), ("Q200", "5", "0"), ("Q100", "17.25", "0")]
    header_length = 32 + 32 * len(fields) + 1
    record_length = 1 + sum(field[2] for field in fields)
    header = bytearray(32)
    header[0] = 0x03
    header[1:4] = bytes((126, 9, 28))
    struct.pack_into("<IHH", header, 4, len(records), header_length, record_length)
    with path.open("wb") as file:
        file.write(header)
        for name, kind, length in fields:
            field = bytearray(32)
            field[:len(name)] = name.encode()
            field[11] = ord(kind)
            field[16] = length
            file.write(field)
        file.write(b"\r")
        for quote, price, memo in records:
            file.write(b" " + quote.encode().ljust(7) + price.encode().rjust(12) + memo.encode().ljust(4))
        file.write(b"\x1a")


class SourceToolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.sources = self.base / "sources"
        self.sources.mkdir()
        (self.sources / "nested").mkdir()
        (self.sources / "nested/text.txt").write_bytes("é abc\n".encode())
        (self.sources / "credentials.txt").write_text("synthetic-secret")
        (self.sources / "ignore.conf").write_text("synthetic-secret")
        (self.sources / ".hidden.json").write_text("synthetic-secret")
        (self.base / "outside.txt").write_text("synthetic-secret")
        (self.sources / "escape.txt").symlink_to(self.base / "outside.txt")
        (self.sources / "alias").symlink_to(self.base)
        synthetic_dbf(self.sources / "QUOTE.DBF")
        synthetic_dbf(self.sources / "MATERIAL.DBF", "ID")
        synthetic_dbf(self.sources / "FORMULA.DBF", "FORM_ID")
        synthetic_dbf(self.sources / "OPERATIO.DBF", "OPER_ID")
        synthetic_dbf(self.sources / "UNKEYED.DBF", "PART_NO")
        self.config = self.base / "sources.json"
        self.config.write_text(json.dumps({name: str(self.sources) for name in reader.SETS}))
        self.env = patch.dict(os.environ, {"KELLER_SOURCE_CONFIG": str(self.config)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def call(self, action, **fields):
        request = reader.validate({"action": action, **fields})
        return reader.read(reader.configuration(), request)

    def test_owner_configuration_and_closed_inventory(self):
        self.assertEqual(len(self.call("sets")["source_sets"]), 4)
        listing = self.call("list", source_set="transcripts")
        self.assertEqual([entry["name"] for entry in listing["entries"]], ["nested"])
        self.assertNotIn("synthetic-secret", json.dumps(listing))
        with self.assertRaises(reader.InvalidRequest):
            self.call("list", source_set="undefined")
        with self.assertRaises((reader.InvalidRequest, OSError)):
            self.call("list", source_set="transcripts", path="alias")
        self.config.write_text(json.dumps({"fabritrak": str(self.base / "no-such-path")}))
        with self.assertRaises(reader.InvalidRequest):
            reader.configuration()

    def test_traversal_symlink_and_credential_filename_rejected(self):
        for path in ("../outside.txt", "/etc/passwd", "nested/../../outside.txt", "nested//text.txt",
                     "alias/outside.txt", "escape.txt", "credentials.txt", ".hidden.json", "ignore.conf"):
            with self.subTest(path=path), self.assertRaises((reader.InvalidRequest, OSError)):
                self.call("read", source_set="transcripts", path=path)

    def test_bounded_byte_reads_and_explicit_encoding(self):
        for payload in ({"limit": 4097}, {"offset": -1}, {"limit": True}, {"encoding": "utf-16"}):
            with self.subTest(payload=payload), self.assertRaises(reader.InvalidRequest):
                reader.validate({"action": "read", "source_set": "transcripts", "path": "nested/text.txt", **payload})
        with self.assertRaises(reader.InvalidRequest):
            self.call("read", source_set="transcripts", path="nested/text.txt", limit=1)
        result = self.call("read", source_set="transcripts", path="nested/text.txt", limit=2)
        self.assertEqual((result["content"], result["next_offset"], result["size_bytes"]), ("é", 2, 7))
        next_result = self.call("read", source_set="transcripts", path="nested/text.txt", offset=2, limit=2)
        self.assertEqual(next_result["content"], " a")
        raw = self.call("read", source_set="transcripts", path="nested/text.txt", limit=1, encoding="base64")
        self.assertEqual(raw["content"], "ww==")
        self.assertEqual(raw["next_offset"], 1)

    def test_directory_pagination_and_only_allowed_types(self):
        (self.sources / "nested/a.txt").write_text("a")
        (self.sources / "nested/b.json").write_text("b")
        first = self.call("list", source_set="transcripts", path="nested", limit=1)
        self.assertEqual(first["entries"][0]["name"], "a.txt")
        self.assertTrue(first["has_more"])
        second = self.call("list", source_set="transcripts", path="nested", offset=first["next_offset"], limit=1)
        self.assertEqual(second["entries"][0]["name"], "b.json")
        with self.assertRaises(reader.InvalidRequest):
            self.call("list", source_set="transcripts", limit=51)

    def test_dbf_schema_and_exact_quote_paging(self):
        schema = self.call("dbf_schema", source_set="fabritrak", path="QUOTE.DBF")
        self.assertEqual([f["name"] for f in schema["fields"]], ["QUOTE_NO", "PRICE1", "COMMENT"])
        page = self.call("dbf_rows", source_set="fabritrak", path="QUOTE.DBF", quote_no="Q100", limit=1)
        self.assertEqual(page["rows"][0]["values"]["PRICE1"], "12.50")
        self.assertEqual(page["rows"][0]["record_index"], 0)
        self.assertTrue(page["has_more"])
        second = self.call("dbf_rows", source_set="fabritrak", path="QUOTE.DBF", quote_no="Q100",
                           offset=page["next_offset"])
        self.assertEqual([row["record_index"] for row in second["rows"]], [2])
        self.assertFalse(second["has_more"])
        for fields in ({"quote_no": ""}, {"quote_no": "Q100", "limit": 6}, {"quote_no": "Q100", "offset": -1}):
            with self.assertRaises(reader.InvalidRequest):
                self.call("dbf_rows", source_set="fabritrak", path="QUOTE.DBF", **fields)

    def test_catalog_exact_id_and_filter_exclusivity(self):
        for name, field in (("MATERIAL.DBF", "ID"), ("FORMULA.DBF", "FORM_ID"), ("OPERATIO.DBF", "OPER_ID")):
            with self.subTest(name=name):
                first = self.call("dbf_rows", source_set="fabritrak", path=name, record_id="Q100", limit=1)
                self.assertEqual(first["filter_field"], field)
                self.assertEqual(first["record_id"], "Q100")
                self.assertEqual(first["rows"][0]["record_index"], 0)
                last = self.call("dbf_rows", source_set="fabritrak", path=name, record_id="Q100",
                                 offset=first["next_offset"])
                self.assertEqual([row["record_index"] for row in last["rows"]], [2])
                self.assertEqual(self.call("dbf_rows", source_set="fabritrak", path=name, record_id="q100")["rows"], [])
        for payload in ({}, {"quote_no": "Q100", "record_id": "Q100"}, {"record_id": ""}, {"record_id": "Q100", "column": "PART_NO"}):
            with self.subTest(payload=payload), self.assertRaises(reader.InvalidRequest):
                self.call("dbf_rows", source_set="fabritrak", path="MATERIAL.DBF", **payload)
        with self.assertRaises(reader.InvalidRequest):
            self.call("dbf_rows", source_set="fabritrak", path="UNKEYED.DBF", record_id="Q100")
        with self.assertRaises(reader.InvalidRequest):
            self.call("dbf_rows", source_set="fabritrak", path="MATERIAL.DBF", quote_no="Q100")

    def test_native_child_environment_redacts_credentials(self):
        worker = self.base / "worker"
        worker.write_text("#!/usr/bin/env python3\nimport json, os\n"
                          "print(json.dumps({'config':bool(os.getenv('KELLER_SOURCE_CONFIG')),'leaked':"
                          "any(os.getenv(k) for k in ('POLYGRES_DIRECT_URL','POLYGRES_DB_PASSWORD',"
                          "'TEAMVIEWER_PASSWORD','AI_GATEWAY_API_KEY','PGPASSWORD'))}))\n")
        worker.chmod(0o700)
        script = """import {createPlugin} from './arsumbris/sources/tool.ts';
console.log(JSON.stringify(await createPlugin({workspace:process.cwd()}).invoke({action:'sets'})));"""
        env = dict(os.environ, KELLER_PYTHON=str(worker), POLYGRES_DIRECT_URL="synthetic-db-secret",
                   TEAMVIEWER_PASSWORD="synthetic-device-secret", PGPASSWORD="synthetic-pg-secret")
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=env,
                                capture_output=True, text=True, check=True, timeout=10)
        content = json.loads(result.stdout)["content"]
        self.assertEqual(content, {"config": True, "leaked": False})
        worker.write_text("#!/usr/bin/env python3\nimport sys\nsys.stderr.write('synthetic-db-secret')\nsys.exit(1)\n")
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=env,
                                capture_output=True, text=True, check=True, timeout=10)
        self.assertTrue(json.loads(result.stdout)["isError"])
        self.assertNotIn("synthetic-db-secret", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
