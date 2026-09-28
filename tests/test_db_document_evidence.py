"""Disposable PostgreSQL document-evidence tests, with no production endpoint."""
import csv
from decimal import Decimal
from hashlib import sha256
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/document-evidence-db.py"
H = lambda b: sha256(b).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


class EvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ.get("KELLER_TEST_DATABASE_URL")
        if not url:
            raise unittest.SkipTest("set KELLER_TEST_DATABASE_URL to a disposable local PostgreSQL URL")
        params = conninfo_to_dict(url)
        loopback = ("localhost", "127.0.0.1", "::1")
        if (params.get("service") or params.get("host") not in loopback
                or params.get("hostaddr", params.get("host")) not in loopback):
            raise ValueError("tests require a loopback PostgreSQL host")
        cls.admin_url = url

    def setUp(self):
        self.dbname = "keller_evidence_test_" + uuid.uuid4().hex
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("create database {}").format(sql.Identifier(self.dbname)))
        self.url = make_conninfo(self.admin_url, dbname=self.dbname)
        with psycopg.connect(self.url) as conn:
            conn.execute("create table quotes (quote_no text primary key, status text)")
            conn.execute("create table quote_qty_breaks (break_id bigint primary key)")
            conn.execute("create table estimates (estimate_id bigint primary key)")
            conn.execute("insert into quotes values ('Q1','open')")
            conn.execute("insert into quote_qty_breaks values (10)")
            conn.execute("insert into estimates values (20)")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(self.dbname)))

    def db(self, query, params=()):
        with psycopg.connect(self.url) as conn:
            return conn.execute(query, params).fetchall()

    def cli(self, *args, success=True, url=None):
        process = subprocess.run([os.sys.executable, str(SCRIPT), *map(str, args)],
                                 env={"PATH": os.environ["PATH"], "POLYGRES_DIRECT_URL": url or self.url},
                                 capture_output=True, text=True)
        if success:
            self.assertEqual(process.returncode, 0, process.stderr)
        else:
            self.assertNotEqual(process.returncode, 0, process.stdout)
        return process

    def make_bundle(self, quote="Q1", price="1.2345", status="unknown", comment="first line\nsecond line", failed_empty=False):
        path = self.root / uuid.uuid4().hex
        path.mkdir()
        pdf = H(b"pdf")
        transcript = H(b"markdown")
        document = dict(source_path="OUTPUT/InvoiceQuote.pdf", pdf_sha256=pdf, pdf_bytes=3,
                        modified_utc="2024-01-01T00:00:00Z", page_count=2, filename_hint="Invoice",
                        content_kind="quote", extraction_status="text", anydoc_status="success",
                        anydoc_record_sha256=H(b"record"), anydoc_transcript_sha256=transcript,
                        metadata={"extraction_engine": "pdftotext-layout"})
        failed = dict(document, source_path="OUTPUT/blank.pdf", page_count=1, filename_hint="other",
                      content_kind="unknown", extraction_status="blank", anydoc_status="failed",
                      anydoc_transcript_sha256=None)
        if failed_empty:
            failed["page_count"] = 0
            failed["extraction_status"] = "failed"
        pages = [dict(source_path=document["source_path"], page_number=i,
                      layout_text=text, text_sha256=H(text.encode()))
                 for i, text in enumerate(("QUOTATION widget assembly\n", "Page two plated\n"), 1)]
        if not failed_empty:
            pages.append(dict(source_path=failed["source_path"], page_number=1, layout_text="", text_sha256=H(b"")))
        row = dict(quote_no=quote, item_no="", quantity="2", unit_price=price, extended_price="2.47",
                   quote_date="2024-01-01", letter_date="2024-01-02", part_no="P-1", customer_id="C-1",
                   source_document=document["source_path"], source_document_sha256=pdf,
                   source_transcript_sha256=transcript, source_price_field="PRICE", price_basis="customer_quote_pdf",
                   status=status, won_date="", comment=comment)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(row), lineterminator="\r\n")
        writer.writeheader()
        header = stream.getvalue()
        writer.writerow(row)
        raw = stream.getvalue()[len(header):]
        payload = {"documents.jsonl": [document, failed], "pages.jsonl": pages,
                   "prices.jsonl": [dict(csv_row_number=1, row=row, raw_csv=raw)]}
        hashes = {}
        for name, items in payload.items():
            content = b"".join(canonical(item) + b"\n" for item in items)
            (path / name).write_bytes(content)
            hashes[name] = H(content)
        manifest = {"schema_version": 1, "inputs": {"price_csv": H(stream.getvalue().encode())},
                    "payload_sha256": hashes, "counts": {"documents": 2, "pages": len(pages), "prices": 1,
                    "blank": 0 if failed_empty else 1, "extraction_failed": 1 if failed_empty else 0}, "csv_header": header,
                    "csv_columns": list(row), "tool_versions": {"pdftotext": "synthetic"},
                    "test_tag": path.name}
        manifest["corpus_id"] = H(canonical(manifest))
        (path / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        return path, manifest["corpus_id"], stream.getvalue().encode()

    def apply(self, path, success=True, growth="1", budget="500"):
        return self.cli("load", path, "--expected-database", self.dbname,
                        "--expected-growth-mib", growth, "--storage-budget-mib", budget,
                        "--apply", success=success)

    def rewrite_bundle(self, path, name, mutate):
        payload = path / name
        rows = [json.loads(line) for line in payload.read_text().splitlines()]
        mutate(rows)
        content = b"".join(canonical(row) + b"\n" for row in rows)
        payload.write_bytes(content)
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["payload_sha256"][name] = H(content)
        manifest.pop("corpus_id")
        manifest["corpus_id"] = H(canonical(manifest))
        manifest_path.write_bytes(canonical(manifest) + b"\n")

    def test_import_query_export_and_idempotence_preserve_core(self):
        path, corpus, original = self.make_bundle()
        dry = self.cli("load", path, "--expected-database", self.dbname)
        self.assertTrue(json.loads(dry.stdout)["dry_run"])
        self.assertEqual(self.db("select count(*) from pg_tables where tablename='document_corpora'"), [(0,)])
        self.apply(path)
        before = self.db("select ingested_at from document_corpora")
        view_oid = self.db("select to_regclass('evidence_pages')::oid")[0][0]
        helper_oid = self.db("select to_regprocedure('evidence_pages_valid(jsonb)')::oid")[0][0]
        self.apply(path)
        replay = self.cli("load", path, "--expected-database", self.dbname, "--apply")
        self.assertTrue(json.loads(replay.stdout)["skipped"])
        self.assertEqual(self.db("select to_regclass('evidence_pages')::oid"), [(view_oid,)])
        self.assertEqual(self.db("select to_regprocedure('evidence_pages_valid(jsonb)')::oid"), [(helper_oid,)])
        self.assertEqual(before, self.db("select ingested_at from document_corpora"))
        self.assertEqual(self.db("select quantity, unit_price, extended_price from verified_document_prices"),
                         [(Decimal("2"), Decimal("1.2345"), Decimal("2.47"))])
        self.assertEqual(self.db("select quote_no,status from quotes"), [("Q1", "open")])
        self.assertEqual(self.db("select break_id from quote_qty_breaks"), [(10,)])
        self.assertEqual(self.db("select estimate_id from estimates"), [(20,)])
        result = self.cli("search", "plated", "--expected-database", self.dbname, "--corpus", corpus,
                          "--kind", "quote", "--quote", "Q1")
        hit = json.loads(result.stdout)
        self.assertEqual((hit["path"], hit["page"], hit["kind"]), ("OUTPUT/InvoiceQuote.pdf", 2, "quote"))
        self.assertEqual(hit["page_sha256"], H(b"Page two plated\n"))
        split = self.cli("search", "widget plated", "--expected-database", self.dbname, "--corpus", corpus)
        self.assertEqual(split.stdout, "")
        prices = self.cli("prices", "--part", "P-1", "--expected-database", self.dbname, "--corpus", corpus)
        self.assertEqual(json.loads(prices.stdout)["row"]["unit_price"], "1.2345")
        output = self.root / "export.csv"
        self.cli("export", "--out", output, "--expected-database", self.dbname, "--corpus", corpus)
        self.assertEqual(output.read_bytes(), original)
        self.cli("export", "--out", output, "--expected-database", self.dbname, "--corpus", corpus, success=False)

    def test_missing_quote_rolls_back_migration_and_rows(self):
        path, _, _ = self.make_bundle(quote="ABSENT")
        result = self.apply(path, success=False)
        self.assertIn("absent", result.stderr)
        self.assertEqual(self.db("select count(*) from pg_tables where tablename='document_corpora'"), [(0,)])
        self.assertEqual(self.db("select count(*) from estimates"), [(1,)])

    def test_document_sql_check_failure_rolls_back_after_corpus_insert(self):
        path, _, _ = self.make_bundle()
        self.rewrite_bundle(path, "documents.jsonl", lambda rows: rows[0].update(content_kind="not_a_kind"))
        result = self.apply(path, success=False)
        self.assertIn("database operation failed", result.stderr)
        self.assertEqual(self.db("select count(*) from pg_tables where tablename in ('document_corpora','evidence_documents','evidence_page_sets','verified_document_prices')"), [(0,)])
        self.assertEqual(self.db("select to_regclass('evidence_pages'),to_regprocedure('evidence_pages_valid(jsonb)')"), [(None, None)])
        self.assertEqual(self.db("select quote_no,status from quotes"), [("Q1", "open")])
        self.assertEqual(self.db("select break_id from quote_qty_breaks"), [(10,)])
        self.assertEqual(self.db("select estimate_id from estimates"), [(20,)])

    def test_late_budget_failure_rolls_back_all_imported_relations(self):
        path, _, _ = self.make_bundle()
        alphabet = b"!?%&*+,-./:;<=>@[]^_{|}~"
        table = bytes(alphabet[byte % len(alphabet)] for byte in range(256))
        text = os.urandom(4_000_000).translate(table).decode("ascii")
        def expand(rows):
            rows[0]["layout_text"] = text
            rows[0]["text_sha256"] = H(text.encode())
        self.rewrite_bundle(path, "pages.jsonl", expand)
        before = self.db("select pg_database_size(current_database())")[0][0]
        budget = str((before + 1048576) / 1048576)
        result = self.apply(path, success=False, growth="0.001", budget=budget)
        self.assertIn("storage budget exceeded during import", result.stderr)
        self.assertEqual(self.db("select count(*) from pg_tables where tablename in ('document_corpora','evidence_documents','evidence_page_sets','verified_document_prices')"), [(0,)])
        self.assertEqual(self.db("select to_regclass('evidence_pages'),to_regprocedure('evidence_pages_valid(jsonb)')"), [(None, None)])
        self.assertEqual(self.db("select quote_no,status from quotes"), [("Q1", "open")])
        self.assertEqual(self.db("select break_id from quote_qty_breaks"), [(10,)])
        self.assertEqual(self.db("select estimate_id from estimates"), [(20,)])

    def test_proof_price_wrong_database_and_budget_guards(self):
        path, _, _ = self.make_bundle()
        self.cli("load", path, "--expected-database", "postgres", "--apply", success=False)
        masked_remote = self.url + " hostaddr=203.0.113.10"
        result = self.cli("load", path, "--expected-database", self.dbname, url=masked_remote, success=False)
        self.assertIn("verify-full", result.stderr)
        self.assertNotIn("203.0.113.10", result.stderr)
        result = self.cli("load", path, "--expected-database", self.dbname, url=self.url + " service=remote", success=False)
        self.assertIn("service aliases", result.stderr)
        self.cli("load", path, "--expected-database", self.dbname, "--apply", success=False)
        self.apply(path, success=False, budget="0.01")
        self.assertEqual(self.db("select count(*) from pg_tables where tablename='document_corpora'"), [(0,)])
        bad, _, _ = self.make_bundle(status="won")
        self.apply(bad, success=False)
        bad, _, _ = self.make_bundle(price="NaN")
        self.apply(bad, success=False)
        bad, _, _ = self.make_bundle()
        with (bad / "pages.jsonl").open("ab") as stream:
            stream.write(b"corruption")
        self.apply(bad, success=False)
        self.assertEqual(self.db("select count(*) from estimates"), [(1,)])

    def test_existing_corpus_corruption_rejects_replay(self):
        path, corpus, _ = self.make_bundle()
        self.apply(path)
        with psycopg.connect(self.url) as conn:
            conn.execute("update evidence_page_sets set pages=pages-1 where document_id=(select document_id from evidence_documents where source_path='OUTPUT/InvoiceQuote.pdf')")
        self.apply(path, success=False)
        self.assertEqual(self.db("select count(*) from document_corpora where corpus_id=%s", (corpus,)), [(1,)])

    def test_same_count_corruption_and_path_guards(self):
        path, _, _ = self.make_bundle()
        self.apply(path)
        with psycopg.connect(self.url) as conn:
            conn.execute("update evidence_page_sets set pages=jsonb_set(jsonb_set(pages,'{1,text}',to_jsonb('tampered'::text)),'{1,sha256}',to_jsonb(%s::text)) where document_id=(select document_id from evidence_documents where source_path='OUTPUT/InvoiceQuote.pdf')", (H(b"tampered"),))
        result = self.apply(path, success=False)
        self.assertIn("page proof mismatch", result.stderr)
        source = self.root / "source"
        source.mkdir()
        input_file = self.root / "manifest.json"
        input_file.write_text("{}")
        base = ("prepare", "--source-dir", source, "--source-manifest", input_file,
                "--transcripts", source, "--price-bundle", source)
        self.cli(*base, "--out", source, success=False)
        self.cli(*base, "--out", ROOT / "not-allowed-private-output", success=False)
        linked = self.root / "linked"
        linked.symlink_to(source, target_is_directory=True)
        self.cli("prepare", "--source-dir", linked, "--source-manifest", input_file,
                 "--transcripts", source, "--price-bundle", source,
                 "--out", self.root / "new-output", success=False)

    def test_search_bounds_and_exact_filters(self):
        path, corpus, _ = self.make_bundle()
        self.apply(path)
        args = ("--expected-database", self.dbname, "--corpus", corpus)
        self.cli("search", "widget", *args, "--limit", "101", success=False)
        result = self.cli("search", "plated", *args, "--kind", "invoice")
        self.assertEqual(result.stdout, "")
        result = self.cli("prices", *args, "--quote", "wrong")
        self.assertEqual(result.stdout, "")

    def test_sql_price_constraints_reject_nan_and_provenance_edits(self):
        path, _, _ = self.make_bundle()
        self.apply(path)
        for statement in ("update verified_document_prices set unit_price='NaN'",
                          "update verified_document_prices set unit_price='Infinity'",
                          "update verified_document_prices set quantity=-1",
                          "update verified_document_prices set quantity=2.5",
                          "update verified_document_prices set unit_price=1.234567",
                          "update verified_document_prices set extended_price=2.471",
                          "update verified_document_prices set extended_price=2.48",
                          "update evidence_page_sets set pages=jsonb_set(pages,'{1,text}',to_jsonb('changed'::text)) where document_id=(select document_id from evidence_documents where source_path='OUTPUT/InvoiceQuote.pdf')",
                          "update verified_document_prices set quote_date=null",
                          "update verified_document_prices set letter_date=null",
                          "update verified_document_prices set source_price_field='INTERNAL'"):
            with self.assertRaises(psycopg.Error), psycopg.connect(self.url) as conn:
                conn.execute(statement)
        self.assertEqual(self.db("select unit_price from verified_document_prices"), [(Decimal("1.2345"),)])

    def test_utf8_multiline_csv_record_exact_bytes(self):
        spec = importlib.util.spec_from_file_location("evidence_cli", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        file = self.root / "unicode.csv"
        with file.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\r\n")
            writer.writerow(["quote_no", *[f for f in module.FIELDS if f != "quote_no"], "comment"])
            writer.writerow(["Q1", *["A" for _ in module.FIELDS if _ != "quote_no"], "café\r\nline 2"])
            writer.writerow(["Q2", *["B" for _ in module.FIELDS if _ != "quote_no"], "Piñata"])
        header = file.read_bytes().split(b"\r\n", 1)[0] + b"\r\n"
        parsed = list(module.price_rows(file, header.decode()))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(header + b"".join(record.encode() for _, _, record in parsed), file.read_bytes())
        self.assertEqual(parsed[0][1]["comment"], "café\r\nline 2")
        path, corpus, original = self.make_bundle(comment="café\r\nsecond line")
        self.apply(path)
        output = self.root / "unicode-export.csv"
        self.cli("export", "--expected-database", self.dbname, "--corpus", corpus, "--out", output)
        self.assertEqual(output.read_bytes(), original)

    def test_content_header_classification_is_not_keyword_search(self):
        spec = importlib.util.spec_from_file_location("evidence_cli", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.kind("       QUOTE      Delivery : 4 weeks\nTo: Example"), "quote")
        self.assertEqual(module.kind("Quote # : 0000123\nTerms"), "quote")
        self.assertEqual(module.kind("PACKING SLIP\nInvoice Ref: 123"), "packing_slip")
        self.assertEqual(module.kind("INVOICE\nPurchase order reference: 44"), "invoice")
        self.assertEqual(module.kind("PURCHASE ORDER\nInvoice terms apply"), "supplier_po")
        self.assertEqual(module.kind("Customer letter\nPrior quote and invoice terms"), "unknown")
        self.assertEqual(module.kind("No : 00107209\nInvoice Date : 07/31/13\n\" Shipped Date : 08/01/13\nTo: Customer"), "invoice")
        self.assertEqual(module.kind("C. Keller Mfg Inc       INVOICE\nNo: 12345"), "invoice")
        self.assertEqual(module.kind("PACKING SLIP\nNo : 00107209\nInvoice Date : 07/31/13\nShipped Date : 08/01/13"), "packing_slip")
        self.assertEqual(module.kind("No : 00107209\nInvoice Date : 07/31/13\nUnlabeled date"), "unknown")

    def test_compact_provenance_proofs_and_cross_corpus_foreign_key(self):
        first, corpus_a, _ = self.make_bundle()
        second, corpus_b, _ = self.make_bundle()
        self.apply(first)
        self.apply(second)
        self.assertNotEqual(corpus_a, corpus_b)
        self.assertEqual(self.db("select relkind from pg_class where oid=to_regclass('evidence_pages')"), [("v",)])
        self.assertEqual(self.db("select count(*) from information_schema.columns where table_name='evidence_page_sets' and column_name='fts'"), [(0,)])
        self.assertEqual(self.db("select count(*) from information_schema.columns where table_name='verified_document_prices' and column_name='original_row'"), [(0,)])
        self.assertEqual(self.db("select count(*) from pg_indexes where indexname='evidence_page_sets_fts' and indexdef like '%%to_tsvector%%'"), [(1,)])
        self.assertEqual(self.db("select count(*) from evidence_page_sets"), [(4,)])
        first_doc = self.db("select document_id from evidence_documents d join document_corpora c using(corpus_key) where c.corpus_id=%s and d.source_path='OUTPUT/InvoiceQuote.pdf'", (corpus_a,))[0][0]
        with self.assertRaises(psycopg.Error), psycopg.connect(self.url) as conn:
            conn.execute("update verified_document_prices set document_id=%s where corpus_key=(select corpus_key from document_corpora where corpus_id=%s)", (first_doc, corpus_b))
        with psycopg.connect(self.url) as conn:
            conn.execute("update verified_document_prices set part_no='TAMPERED' where corpus_key=(select corpus_key from document_corpora where corpus_id=%s)", (corpus_b,))
        self.apply(second, success=False)
        self.cli("prices", "--expected-database", self.dbname, "--corpus", corpus_b, "--quote", "Q1", success=False)
        output = self.root / "corrupt-export.csv"
        self.cli("export", "--expected-database", self.dbname, "--corpus", corpus_b, "--out", output, success=False)
        self.assertFalse(output.exists())
        with psycopg.connect(self.url) as conn:
            conn.execute("update verified_document_prices set part_no='P-1', raw_csv=replace(raw_csv,'1.2345','1.2346') where corpus_key=(select corpus_key from document_corpora where corpus_id=%s)", (corpus_b,))
        self.assertIn("price proof mismatch", self.apply(second, success=False).stderr)
        self.cli("prices", "--expected-database", self.dbname, "--corpus", corpus_b, "--quote", "Q1", success=False)
        self.cli("export", "--expected-database", self.dbname, "--corpus", corpus_b, "--out", output, success=False)
        self.assertFalse(output.exists())
        self.assertEqual(self.db("select count(*) from verified_document_prices"), [(2,)])

    def test_same_corpus_document_link_corruption_is_detected(self):
        path, corpus, _ = self.make_bundle()
        self.apply(path)
        failed_id = self.db("select document_id from evidence_documents where source_path='OUTPUT/blank.pdf'")[0][0]
        with psycopg.connect(self.url) as conn:
            conn.execute("update verified_document_prices set document_id=%s", (failed_id,))
        self.assertIn("provenance mismatch", self.apply(path, success=False).stderr)
        self.cli("prices", "--expected-database", self.dbname, "--corpus", corpus, "--quote", "Q1", success=False)
        output = self.root / "wrong-document.csv"
        self.cli("export", "--expected-database", self.dbname, "--corpus", corpus, "--out", output, success=False)
        self.assertFalse(output.exists())

    def test_empty_page_set_is_required_and_page_json_integrity_is_sql_enforced(self):
        path, _, _ = self.make_bundle(failed_empty=True)
        self.apply(path)
        self.assertEqual(self.db("select count(*) from evidence_page_sets"), [(2,)])
        self.assertEqual(self.db("select count(*) from evidence_pages"), [(2,)])
        for statement in ("update evidence_page_sets set pages='{}'::jsonb",
                          "update evidence_page_sets set pages='[{}]'::jsonb",
                          "update evidence_page_sets set pages='[{\"text\":null,\"sha256\":null}]'::jsonb",
                          "update evidence_page_sets set pages='[{\"text\":\"wrong\",\"sha256\":\"bad\"}]'::jsonb"):
            with self.assertRaises(psycopg.Error), psycopg.connect(self.url) as conn:
                conn.execute(statement)
        with psycopg.connect(self.url) as conn:
            conn.execute("delete from evidence_page_sets where document_id=(select document_id from evidence_documents where source_path='OUTPUT/blank.pdf')")
        result = self.apply(path, success=False)
        self.assertIn("count mismatch", result.stderr)

    def test_partial_schema_fails_closed_without_mutating_it(self):
        path, _, _ = self.make_bundle()
        with psycopg.connect(self.url) as conn:
            conn.execute("create table evidence_documents (placeholder text)")
        result = self.apply(path, success=False)
        self.assertIn("partial or incompatible", result.stderr)
        self.assertEqual(self.db("select count(*) from information_schema.columns where table_name='evidence_documents' and column_name='placeholder'"), [(1,)])
        self.assertEqual(self.db("select count(*) from pg_tables where tablename='document_corpora'"), [(0,)])


if __name__ == "__main__":
    unittest.main()
