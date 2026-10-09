"""Synthetic native quote-tool integration; no real database or customer data."""
import hashlib
import csv
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CORPUS = "a" * 64
CSV = b"quote_no,item_no,quote_date,part_no,description,customer,quantity,unit_price,status\nQ-OLD,,2024-01-01,AXLE-101,Axle,Sample Shop,10,12.5,won\nQ-FUTURE,,2025-02-01,AXLE-101,Axle,Sample Shop,10,99,won\n"


class NativeQuoteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-quote-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.python = self.home / "fixture-export"
        self.python.write_text("""#!/usr/bin/env python3
import hashlib, json, os, pathlib, sys
assert len(sys.argv) == 4 and sys.argv[1].endswith('/arsumbris/quote/export.py')
assert sys.argv[2] == '""" + CORPUS + """'
assert 'AI_GATEWAY_API_KEY' not in os.environ
assert 'TEAMVIEWER_PASSWORD' not in os.environ
assert 'TAILSCALE_AUTH_KEY' not in os.environ
assert 'POLYGRES_DIRECT_URL' in os.environ
data = """ + repr(CSV) + """
pathlib.Path(sys.argv[3]).write_bytes(data)
pathlib.Path(sys.argv[3]).chmod(0o600)
print(json.dumps({'sha256': hashlib.sha256(data).hexdigest(), 'rows': 2}))
""")
        self.python.chmod(0o700)

    def request(self, parts, charges=None):
        return {"order_id": "SYNTHETIC-1", "quote_date": "2024-06-01", "customer": "Sample Shop",
                "parts": parts, **({"charges": charges} if charges is not None else {})}

    def invoke(self, request, corpus=CORPUS, reviewer="Synthetic Reviewer", internal=None):
        env = {**os.environ, "HOME": str(self.home), "KELLER_PYTHON": str(self.python),
               "POLYGRES_DIRECT_URL": "secret-never-exposed", "AI_GATEWAY_API_KEY": "sentinel-key",
               "TEAMVIEWER_PASSWORD": "sentinel-remote", "TAILSCALE_AUTH_KEY": "sentinel-tailnet"}
        script = """import {createPlugin} from './arsumbris/quote/tool.ts';
const result = await createPlugin({workspace: process.cwd()}).invoke(JSON.parse(process.argv[1]));
console.log(JSON.stringify(result));"""
        payload = {"corpus": corpus, "request": json.dumps(request) if not isinstance(request, str) else request,
                   "reviewer": reviewer, **(internal or {})}
        completed = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(payload)], cwd=ROOT,
                                   env=env, capture_output=True, text=True, timeout=45, check=True)
        self.assertNotIn("secret-never-exposed", completed.stdout + completed.stderr)
        self.assertNotIn("sentinel-key", completed.stdout + completed.stderr)
        self.assertNotIn("sentinel-remote", completed.stdout + completed.stderr)
        self.assertNotIn("sentinel-tailnet", completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def artifacts(self, result):
        content = result["content"]
        directory = self.home / ".local/share/keller-quotes/drafts" / content["draft_id"]
        self.assertEqual(content["artifacts"]["order_json"], f'quote-draft:{content["draft_id"]}/order.json')
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        files = [directory / name for name in ("request.json", "corpus.csv", "output/order.json", "output/order.md", "output/review.json")]
        for file in files:
            self.assertTrue(file.is_file())
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(hashlib.sha256(files[1].read_bytes()).hexdigest(), content["corpus_sha256"])
        review = json.loads(files[4].read_text())
        self.assertEqual(review["reviewer"], "Synthetic Reviewer")
        self.assertFalse(review["customer_release_authorized"])
        self.assertEqual(content["artifacts"]["review_json"], f'quote-draft:{content["draft_id"]}/review.json')
        order, markdown = json.loads(files[2].read_text()), files[3].read_text()
        self.assertEqual(content["order"], order)
        self.assertEqual(content["markdown"], markdown)
        self.assertEqual(content["review"], review)
        return order, markdown

    def test_explicit_operator_amount_and_costs_stay_internal(self):
        parts = [{"line_id": "explicit", "part_no": "SYNTHETIC", "quantity": 3,
                  "pricing": {"method": "unit_price", "unit_price": 0.3333, "reason": "operator proposal"}},
                 {"line_id": "cost", "part_no": "SYNTHETIC-2", "quantity": 3,
                  "pricing": {"method": "cost_plus", "material_per_unit": 1, "labor_per_unit": .1,
                              "outside_per_unit": 0, "setup_total": 1, "margin_pct": 20, "reason": "synthetic cost sheet"}}]
        result = self.invoke(self.request(parts, {"shipping": 0, "tax": 0}))
        self.assertFalse(result.get("isError"))
        content = result["content"]
        self.assertEqual(content["state"], "PRICED_REQUIRES_REVIEW")
        self.assertEqual(content["review_status"], "PENDING_NAMED_HUMAN_REVIEW")
        self.assertEqual(content["reviewer"], "Synthetic Reviewer")
        self.assertTrue(content["requires_human_review"])
        self.assertEqual(set(content["price_bases"]), {"explicit_unit_price", "cost_build_up"})
        self.assertIn("not current", content["warning"])
        order, markdown = self.artifacts(result)
        self.assertEqual(order["total"], content["total"])
        self.assertIn("human review required", markdown)
        self.assertNotIn(str(self.home), json.dumps(content))

    def test_unmatched_and_missing_charges_stay_blocked_without_total(self):
        result = self.invoke(self.request([{"line_id": "unknown", "part_no": "UNMATCHED", "quantity": 2}]))
        self.assertEqual(result["content"]["state"], "BLOCKED")
        self.assertIsNone(result["content"]["total"])
        order, markdown = self.artifacts(result)
        self.assertIsNone(order["subtotal"])
        self.assertIsNone(order["total"])
        self.assertIn("line unknown is unpriced", result["content"]["blockers"])
        self.assertIn("Total: —", markdown)

    def test_historical_draft_uses_cutoff_and_warns_of_unknown_outcome(self):
        result = self.invoke(self.request([{"line_id": "history", "part_no": "AXLE-101", "quantity": 10}],
                                                  {"shipping": 0, "tax": 0}))
        self.assertEqual(result["content"]["state"], "PRICED_REQUIRES_REVIEW")
        self.assertIn("historical_analog", result["content"]["price_bases"])
        self.assertIn("unknown outcome", result["content"]["warning"])
        order, _ = self.artifacts(result)
        self.assertEqual([item["quote_no"] for item in order["lines"][0]["analogs"]], ["Q-OLD"])

    def test_scoped_register_filters_before_pricing_and_reconciles_verified_breaks(self):
        fields = ["quote_no", "item_no", "quantity", "unit_price", "extended_price", "quote_date",
                  "letter_date", "date_stamp", "part_no", "customer_id", "source_document",
                  "source_document_sha256", "source_transcript_sha256", "source_price_field",
                  "price_basis", "status", "quote_letter", "description", "customer"]
        allowed = {"quote_no": "ALLOWED", "item_no": "", "quantity": "3.000", "unit_price": "1.23456",
                   "extended_price": "3.70", "quote_date": "2023-01-01", "letter_date": "2023-01-01",
                   "date_stamp": "", "part_no": "SYNTHETIC-P", "customer_id": "C",
                   "source_document": "synthetic/allowed.pdf", "source_document_sha256": "b" * 64,
                   "source_transcript_sha256": "c" * 64, "source_price_field": "PRICE",
                   "price_basis": "customer_quote_pdf", "status": "unknown", "quote_letter": "L-A",
                   "description": "Synthetic Part", "customer": "Synthetic Customer"}
        forbidden = {**allowed, "quote_no": "EXCLUDED", "item_no": "2", "unit_price": "9.99999",
                     "extended_price": "30.00", "quote_date": "2024-01-01", "letter_date": "2024-01-01",
                     "source_document": "synthetic/excluded.pdf", "source_document_sha256": "d" * 64,
                     "source_transcript_sha256": "e" * 64, "quote_letter": "L-E"}
        second_break = {**allowed, "quantity": "5.00", "unit_price": "1.11111", "extended_price": "5.56"}
        request = self.request([{"line_id": "line", "part_no": "SYNTHETIC-P", "quantity": 3}],
                               {"shipping": 0, "tax": 0})
        request["customer_id"] = "C"
        scope = {"schema_version": 1, "case_id": "synthetic", "corpus": CORPUS,
                 "quote_date": request["quote_date"], "excluded_quote_nos": ["EXCLUDED"],
                 "request": {**request, "reviewer": "Synthetic Reviewer"},
                 "eligible_prices": [], "allowed_files": []}
        def eligible(row):
            return {key: row[source] for key, source in {
                "source_path": "source_document", "pdf_sha256": "source_document_sha256",
                "transcript_sha256": "source_transcript_sha256"}.items()} | {
                    key: row[key] for key in ("quote_no", "item_no", "quantity", "unit_price", "extended_price",
                                         "quote_date", "letter_date", "date_stamp", "part_no", "customer_id",
                                         "source_price_field", "price_basis", "status")}
        scope["eligible_prices"] = [eligible(allowed), eligible(second_break)]
        private = self.home / "scope"
        private.mkdir(mode=0o700)
        scope_path = private / "scope.json"
        def write_scope():
            scope_path.write_text(json.dumps(scope))
            scope_path.chmod(0o600)
            return {"evaluation_scope_path": str(scope_path),
                    "evaluation_scope_sha256": hashlib.sha256(scope_path.read_bytes()).hexdigest()}
        def export(rows):
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fields)
            writer.writeheader()
            writer.writerows(rows)
            data = output.getvalue().encode()
            self.python.write_text("""#!/usr/bin/env python3
import hashlib, json, pathlib, sys
data = """ + repr(data) + """
pathlib.Path(sys.argv[3]).write_bytes(data)
pathlib.Path(sys.argv[3]).chmod(0o600)
print(json.dumps({'sha256': hashlib.sha256(data).hexdigest(), 'rows': """ + str(len(rows)) + """}))
""")
        export([forbidden, allowed, second_break])
        binding = write_scope()
        full = self.invoke(request)["content"]
        self.assertEqual(full["order"]["lines"][0]["analogs"][0]["quote_no"], "EXCLUDED")
        first = self.invoke(request, internal=binding)
        self.assertFalse(first.get("isError"), first)
        content = first["content"]
        self.assertEqual(content["state"], "PRICED_REQUIRES_REVIEW")
        self.assertEqual(content["source_rows"], 2)
        self.assertEqual(content["evaluation_scope_sha256"], binding["evaluation_scope_sha256"])
        self.assertEqual([a["quote_no"] for a in content["order"]["lines"][0]["analogs"]], ["ALLOWED"])
        folder = self.home / ".local/share/keller-quotes/drafts" / content["draft_id"]
        original = folder / "corpus.csv"
        filtered = folder / "scoped-corpus.csv"
        self.assertEqual(original.stat().st_mode & 0o777, 0o600)
        self.assertEqual(filtered.stat().st_mode & 0o777, 0o600)
        self.assertIn(b"EXCLUDED", original.read_bytes())
        self.assertNotIn(b"EXCLUDED", filtered.read_bytes())
        self.assertIn(b"1.23456", filtered.read_bytes())
        self.assertIn(b"1.11111", filtered.read_bytes())
        self.assertNotIn(b"description", filtered.read_bytes())
        self.assertNotIn(b"L-A", filtered.read_bytes())
        self.assertNotIn("evidence", content["order"]["lines"][0]["analogs"][0])
        self.assertIn("evidence", full["order"]["lines"][0]["analogs"][0])
        self.assertEqual(content["corpus_sha256"], hashlib.sha256(filtered.read_bytes()).hexdigest())
        self.assertEqual(content["order"]["provenance"]["register_sha256"], content["corpus_sha256"])
        self.assertEqual(json.loads((folder / "output/review.json").read_text())["source_rows"], 2)

        export([{**forbidden, "unit_price": "2.22222", "extended_price": "6.67"}, allowed, second_break])
        second = self.invoke(request, internal=binding)["content"]
        self.assertEqual(second["corpus_sha256"], content["corpus_sha256"])
        self.assertEqual(second["order"]["lines"][0]["unit_price"], content["order"]["lines"][0]["unit_price"])
        self.assertEqual(second["order"]["lines"][0]["analogs"], content["order"]["lines"][0]["analogs"])

        export([forbidden, {**allowed, "description": "unfrozen engineering", "customer": "unfrozen name", "quote_letter": "unfrozen letter"}, second_break])
        isolated = self.invoke(request, internal=binding)["content"]
        self.assertEqual(isolated["corpus_sha256"], content["corpus_sha256"])
        self.assertEqual(isolated["order"]["lines"], content["order"]["lines"])

        scope["eligible_prices"] = []
        empty = self.invoke(request, internal=write_scope())["content"]
        self.assertEqual(empty["state"], "BLOCKED")
        self.assertIsNone(empty["order"]["lines"][0]["unit_price"])
        self.assertEqual(empty["source_rows"], 0)
        scope["eligible_prices"] = [eligible(allowed), eligible(second_break)]
        binding = write_scope()
        for change in [{"evaluation_scope_sha256": "0" * 64},
                       {"evaluation_scope_path": str(scope_path), "evaluation_scope_sha256": "bad"}]:
            self.assertTrue(self.invoke(request, internal={**binding, **change})["isError"])
        scope["eligible_prices"][0]["unit_price"] = "7.77777"
        self.assertTrue(self.invoke(request, internal=write_scope())["isError"])
        scope["eligible_prices"] = [eligible(allowed), eligible(second_break),
                                    {**eligible(allowed), "quote_no": "MISSING"}]
        self.assertTrue(self.invoke(request, internal=write_scope())["isError"])
        scope["eligible_prices"] = [eligible(allowed), eligible(second_break)]
        self.assertTrue(self.invoke(request, reviewer="Wrong Reviewer", internal=write_scope())["isError"])

    def test_invalid_inputs_fail_without_export_or_artifacts(self):
        for request, corpus, reviewer in [
            ("{", CORPUS, "Person"),
            (self.request([{"line_id": "x", "part_no": "P", "quantity": 1,
                            "pricing": {"method": "unit_price", "unit_price": 1}}]), CORPUS, "Person"),
            (self.request([{"line_id": "x", "part_no": "P", "quantity": 1}]), "bad", "Person"),
            (self.request([{"line_id": "x", "part_no": "P", "quantity": 1}]), CORPUS, " "),
        ]:
            with self.subTest(corpus=corpus, reviewer=reviewer):
                result = self.invoke(request, corpus, reviewer)
                self.assertTrue(result["isError"])
                self.assertNotIn("artifacts", result["content"])
        storage = self.home / ".local/share/keller-quotes/drafts"
        self.assertEqual(list(storage.iterdir()) if storage.exists() else [], [])

    def test_incomplete_scope_binding_fails_before_export(self):
        marker = self.home / "export-was-called"
        self.python.write_text("#!/usr/bin/env python3\nfrom pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n")
        scope_path = self.home / "not-a-scope.json"
        request = self.request([{"line_id": "line", "part_no": "SYNTHETIC", "quantity": 3}],
                               {"shipping": 0, "tax": 0})
        for internal in [
            {"evaluation_scope_path": ""},
            {"evaluation_scope_sha256": "a" * 64},
            {"evaluation_scope_path": "", "evaluation_scope_sha256": "a" * 64},
            {"evaluation_scope_path": str(scope_path)},
            {"evaluation_scope_path": str(scope_path), "evaluation_scope_sha256": ""},
            {"evaluation_scope_path": str(scope_path), "evaluation_scope_sha256": "bad"},
            {"evaluation_scope_path": str(scope_path), "evaluation_scope_sha256": "a" * 64},
        ]:
            with self.subTest(internal=internal):
                self.assertTrue(self.invoke(request, internal=internal)["isError"])
                self.assertFalse(marker.exists())
        storage = self.home / ".local/share/keller-quotes/drafts"
        self.assertEqual(list(storage.iterdir()) if storage.exists() else [], [])

    def test_private_storage_rejects_insecure_existing_directory(self):
        storage = self.home / ".local/share/keller-quotes/drafts"
        storage.mkdir(parents=True, mode=0o700)
        storage.chmod(0o755)
        result = self.invoke(self.request([{"line_id": "x", "part_no": "P", "quantity": 1}]))
        self.assertTrue(result["isError"])
        self.assertEqual(list(storage.iterdir()), [])

    def test_node_children_receive_no_credentials(self):
        probe = self.home / 'probe.cjs'
        observed = self.home / 'child-environments.jsonl'
        probe.write_text("""const child = require('node:child_process');
const fs = require('node:fs');
const util = require('node:util');
const original = child.execFile;
function inspect(binary, args, options) {
  if (binary === process.execPath) {
    const env = options.env;
    fs.appendFileSync('""" + str(observed) + """', JSON.stringify({
      args: args.slice(0, 2), names: Object.keys(env)
    }) + '\\n');
    for (const key of ['POLYGRES_DIRECT_URL', 'AI_GATEWAY_API_KEY',
      'TEAMVIEWER_PASSWORD', 'TAILSCALE_AUTH_KEY', 'NODE_OPTIONS']) {
      if (key in env) throw new Error('child credential leaked');
    }
  }
}
child.execFile = function(binary, args, options, callback) {
  inspect(binary, args, options);
  return original.call(this, binary, args, options, callback);
};
child.execFile[util.promisify.custom] = function(binary, args, options) {
  inspect(binary, args, options);
  return original[util.promisify.custom](binary, args, options);
};
""")
        with patch.dict(os.environ, {'NODE_OPTIONS': f'--require={probe}'}):
            result = self.invoke(self.request([{"line_id": "x", "part_no": "P", "quantity": 1,
                                                "pricing": {"method": "unit_price", "unit_price": 1,
                                                            "reason": "fixture"}}], {"shipping": 0, "tax": 0}))
        self.assertFalse(result.get('isError'), (result, observed.read_text() if observed.exists() else 'probe did not run'))
        children = [json.loads(line) for line in observed.read_text().splitlines()]
        self.assertEqual(len(children), 2)
        self.assertTrue(all('POLYGRES_DIRECT_URL' not in child['names'] for child in children))

    def test_unknown_export_failure_is_redacted(self):
        self.python.write_text('#!/usr/bin/env python3\nimport sys\nprint("secret-never-exposed", file=sys.stderr)\nsys.exit(1)\n')
        result = self.invoke(self.request([{"line_id": "x", "part_no": "P", "quantity": 1}]))
        self.assertTrue(result['isError'])
        self.assertEqual(result['content'], {'error': 'Invalid request or verified offline draft unavailable; no quote was released'})
        self.assertEqual(list((self.home / '.local/share/keller-quotes/drafts').iterdir()), [])

    @unittest.skipUnless(importlib.util.find_spec('psycopg'), 'requires configured psycopg interpreter')
    def test_guarded_export_uses_existing_readonly_cli_and_redacts_credentials(self):
        spec = importlib.util.spec_from_file_location("quote_export", ROOT / "arsumbris/quote/export.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        url = "postgresql://user:secret@db.example.org/" + module.EXPECTED_DATABASE
        run = subprocess.CompletedProcess([], 0, '{"rows":2,"sha256":"digest"}\n', "")
        with patch.dict(os.environ, {"POLYGRES_DIRECT_URL": url, "AI_GATEWAY_API_KEY": "secret-gateway"}, clear=True), \
             patch.object(module.subprocess, "run", return_value=run) as invoke:
            self.assertEqual(module.export(CORPUS, "/private/output.csv"), run.stdout)
        args, kwargs = invoke.call_args
        self.assertEqual(args[0][2:7], ["export", "--expected-database", module.EXPECTED_DATABASE,
                                         "--corpus", CORPUS])
        self.assertEqual(args[0][-2:], ["--out", "/private/output.csv"])
        config = module.conninfo_to_dict(kwargs["env"]["POLYGRES_DIRECT_URL"])
        self.assertEqual(config["sslmode"], "verify-full")
        self.assertEqual(config["sslrootcert"], module.CA_CERT)
        self.assertIn("default_transaction_read_only=on", config["options"])
        self.assertNotIn("PGSERVICE", kwargs["env"])
        with patch.dict(os.environ, {"POLYGRES_DIRECT_URL": "postgresql://user:secret@db.example.org/wrong"}, clear=True), \
             self.assertRaises(ValueError):
            module.export(CORPUS, "/private/output.csv")


if __name__ == "__main__":
    unittest.main()
