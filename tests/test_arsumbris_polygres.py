"""Synthetic contract checks for the native read-only Polygres tool."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / "arsumbris/polygres/read.py"
spec = importlib.util.spec_from_file_location("keller_polygres_reader", READER)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
CORPUS = "a" * 64


class FakeConnection:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.queries = []

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        self.result = next(self.rows)
        return self

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class NativePolygresTest(unittest.TestCase):
    def test_actions_require_scope_and_bounded_inputs(self):
        self.assertEqual(reader.validate({"action": "corpora"})["action"], "corpora")
        valid = {"action": "search", "corpus": CORPUS, "query": "bracket", "limit": 50}
        self.assertEqual(reader.validate(valid), valid)
        for payload in (
            {"action": "search", "query": "bracket"},
            {"action": "prices", "corpus": CORPUS},
            {"action": "prices", "corpus": CORPUS, "part_no": "P", "limit": 51},
            {"action": "prices", "corpus": CORPUS, "part_no": "P", "sql": "delete from quotes"},
            {"action": "page", "corpus": CORPUS, "source_path": "x", "page_number": 0},
            {"action": "page", "corpus": CORPUS, "source_path": "x", "page_number": 1, "limit": 4001},
            {"action": "corpora", "corpus": CORPUS},
        ):
            with self.subTest(payload=payload), self.assertRaises(reader.InvalidRequest):
                reader.validate(payload)

    def test_search_matches_individual_pages_and_explicit_corpus(self):
        hit = ("OUTPUT/quote.pdf", 2, "b" * 64, "c" * 64, "quote", "bracket")
        conn = FakeConnection([None, (3, {}), [hit, hit]])
        response = reader.read(conn, reader.validate({"action": "search", "corpus": CORPUS, "query": "bracket", "limit": 1}))
        self.assertEqual(response["hits"][0]["page_number"], 2)
        self.assertTrue(response["has_more"])
        sql, params = conn.queries[-1]
        self.assertIn("to_tsvector('english',p.layout_text)", sql)
        self.assertIn("d.corpus_key=%s", sql)
        self.assertNotIn("bracket", sql)
        self.assertEqual(params[0:3], (3, "bracket", "bracket"))
        self.assertTrue(all("insert " not in q.lower() and "update " not in q.lower() for q, _ in conn.queries))
        self.assertEqual(conn.queries[1][0], "select corpus_key,prepared_manifest from document_corpora where corpus_id=%s")
        self.assertEqual(conn.queries[1][1], (CORPUS,))

    def test_corpora_returns_snapshot_timestamp_and_counts(self):
        conn = FakeConnection([None, [('a' * 64, 3, 4, 5, '2026-09-28T00:00:00+00:00')]])
        response = reader.read(conn, reader.validate({'action': 'corpora'}))
        self.assertEqual(response['corpora'], [{'corpus': 'a' * 64, 'documents': 3, 'pages': 4,
                                                'verified_prices': 5, 'ingested_at': '2026-09-28T00:00:00+00:00'}])
        self.assertIn('order by ingested_at desc', conn.queries[1][0])

    def test_price_result_uses_existing_csv_validation(self):
        record = (1, "csv", "Q", "", 2, 1.2345, 2.47, None, None, "P", "C", "PRICE", "OUTPUT/quote.pdf", "b" * 64, "c" * 64)
        fields = {key: "unknown" if key == "status" else "customer_quote_pdf" if key == "price_basis" else "value"
                  for key in reader.PRICE_FIELDS}
        class Evidence:
            PRICE_SELECT = "select verified columns from verified_document_prices v join evidence_documents d on d.corpus_key=v.corpus_key and d.document_id=v.document_id"
            def checked_price(self, result, columns):
                self.calls.append((result, columns))
                return fields
            calls = []

        evidence = Evidence()
        conn = FakeConnection([None, (3, {"csv_columns": ["quote_no"]}), [record]])
        with patch.object(reader, "evidence_module", return_value=evidence):
            response = reader.read(conn, reader.validate({"action": "prices", "corpus": CORPUS, "part_no": "P"}))
        self.assertEqual(evidence.calls, [(record, ["quote_no"])])
        self.assertEqual(response["outcome"], "unknown")
        self.assertEqual(response["prices"][0]["pdf_sha256"], "b" * 64)
        self.assertEqual(conn.queries[-1][1], (3, "P", "P", None, None, 21, 0))

    def test_page_is_bounded_and_keeps_hash_citation(self):
        conn = FakeConnection([None, (3, {}), ("b" * 64, "quote", 4, "c" * 64, "abc", 10)])
        request = reader.validate({"action": "page", "corpus": CORPUS, "source_path": "OUTPUT/quote.pdf",
                                   "page_number": 2, "limit": 3, "offset": 2})
        response = reader.read(conn, request)
        self.assertEqual((response["text"], response["next_offset"], response["page_sha256"]), ("abc", 5, "c" * 64))
        sql, params = conn.queries[-1]
        self.assertIn("d.source_path=%s and p.page_number=%s", sql)
        self.assertEqual(params, (3, 3, 3, "OUTPUT/quote.pdf", 2))

    def test_connection_forces_tls_identity_and_read_only_defaults(self):
        url = "postgresql://user:secret@db.example.org/app_peb68ccd10bc4e4ea3b43852"
        class FakeDatabase:
            def execute(self, *_):
                return self
            def fetchone(self):
                return (reader.EXPECTED_DATABASE,)
        with patch.dict(os.environ, {"POLYGRES_DIRECT_URL": url}, clear=True), patch.object(reader.psycopg, "connect", return_value=FakeDatabase()) as connect:
            reader.connect()
        conninfo = connect.call_args.args[0]
        self.assertNotIn("secret", str(connect.call_args.kwargs))
        self.assertEqual(reader.conninfo_to_dict(conninfo)["sslmode"], "verify-full")
        self.assertEqual(reader.conninfo_to_dict(conninfo)["sslrootcert"], reader.CA_CERT)
        self.assertIn("default_transaction_read_only=on", conninfo)
        self.assertIn("statement_timeout=5000", conninfo)

    def test_native_callable_executes_helper_without_mcp_emulation(self):
        environment = dict(os.environ)
        environment["KELLER_PYTHON"] = sys.executable
        environment["POLYGRES_DIRECT_URL"] = "configured-for-validation-only"
        script = """import { createPlugin } from './arsumbris/polygres/tool.ts';
const tool = createPlugin({workspace: process.cwd()});
const result = await tool.invoke({action:'search',query:'synthetic'});
console.log(JSON.stringify(result));"""
        output = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=environment,
                                capture_output=True, text=True, check=True, timeout=10)
        response = json.loads(output.stdout)
        self.assertTrue(response["isError"])
        self.assertIn("explicit public corpus ID", response["content"]["error"])
        self.assertNotIn("configured-for-validation-only", output.stdout)

    def test_native_subprocess_environment_and_errors_do_not_leak_credentials(self):
        script = """import {createPlugin} from './arsumbris/polygres/tool.ts';
const result = await createPlugin({workspace:process.cwd()}).invoke({action:'corpora'});
console.log(JSON.stringify(result));"""
        with tempfile.TemporaryDirectory() as temp:
            worker = Path(temp) / "worker"
            environment = dict(os.environ)
            environment.update({"KELLER_PYTHON": str(worker), "POLYGRES_DIRECT_URL": "synthetic-db-url",
                                "AI_GATEWAY_API_KEY": "synthetic-gateway-secret", "TEAMVIEWER_PASSWORD": "synthetic-device-secret",
                                "POLYGRES_DB_PASSWORD": "synthetic-db-secret", "PGPASSWORD": "synthetic-libpq-secret"})
            worker.write_text("#!/usr/bin/env python3\nimport json, os\n"
                              "print(json.dumps({'db_present': bool(os.getenv('POLYGRES_DIRECT_URL')), "
                              "'other_credentials_present': any(os.getenv(key) for key in "
                              "('AI_GATEWAY_API_KEY','TEAMVIEWER_PASSWORD','POLYGRES_DB_PASSWORD','PGPASSWORD'))}))\n")
            worker.chmod(0o700)
            output = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=environment,
                                    capture_output=True, text=True, check=True, timeout=10)
            response = json.loads(output.stdout)
            self.assertFalse(response.get("isError"))
            self.assertEqual(response["content"], {"db_present": True, "other_credentials_present": False})

            worker.write_text("#!/usr/bin/env python3\nimport sys\n"
                              "sys.stderr.write('synthetic-gateway-secret synthetic-db-url')\n"
                              "sys.stdout.write('synthetic-device-secret')\n"
                              "sys.exit(1)\n")
            output = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=environment,
                                    capture_output=True, text=True, check=True, timeout=10)
            response = json.loads(output.stdout)
            self.assertTrue(response["isError"])
            self.assertIn("Polygres read unavailable", response["content"]["error"])
            self.assertNotIn("synthetic-", output.stdout + output.stderr)


if __name__ == "__main__":
    unittest.main()
