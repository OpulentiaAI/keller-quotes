"""Synthetic exact supplier-offer evidence; no customer prices or private corpus."""

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
VENDOR_FIELDS = [("VEND_QUOT", "C", 8), ("QUOTE_NUM", "C", 20), ("QUOTE_NO", "C", 7),
                 ("ID", "C", 5), ("VENDOR_ID", "C", 5), ("TYPE", "C", 1),
                 ("PRICE1", "N", 13), ("QTY1", "N", 10), ("MINIMUM", "N", 12),
                 ("SU_CHARGE", "N", 12), ("DATE_STAMP", "D", 8), ("GOOD_UNTIL", "D", 8),
                 ("VOIDED", "L", 1)]


def vendor_row(identity="00000001", vendor="V0001", material="00001", quote="Q000001", price="2.00000", voided="F"):
    return [identity, "SYNTHETIC-PRINTED", quote, material, vendor, "M", price, "10", "100.0000",
            "0", "20240501", "20240630", voided]


class VendorEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-vendor-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bindings = {"fabritrak": str(self.root)}
        self.put("VENDQUOT.DBF", VENDOR_FIELDS, [
            (b" ", vendor_row()), (b" ", vendor_row(identity="00000002", vendor="V0002", price="9000")),
            (b" ", vendor_row(identity="00000003", material="00002", price="8000")),
            (b" ", vendor_row(identity="00000004", quote="Q000002", price="7000")),
            (b"*", vendor_row()), (b" ", vendor_row(price="2.50000", voided="T"))])

    def put(self, path, fields, rows):
        (self.root / path).write_bytes(dbf_bytes(fields, rows))

    def call(self, path="VENDQUOT.DBF", action="dbf_rows", **keys):
        request = {"action": action, "source_set": "fabritrak", "path": path, **keys}
        return reader.read(self.bindings, reader.validate(request))

    def native(self, request):
        config = self.root / "sources.json"
        config.write_text(json.dumps(self.bindings)); config.chmod(0o600)
        script = """import {createPlugin} from './arsumbris/sources/tool.ts';
console.log(JSON.stringify(await createPlugin({workspace: process.cwd()}).invoke(JSON.parse(process.argv[1]))));"""
        result = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(request)], cwd=ROOT,
                                env={**os.environ, "KELLER_SOURCE_CONFIG": str(config), "KELLER_PYTHON": sys.executable},
                                capture_output=True, text=True, check=True, timeout=20)
        return json.loads(result.stdout)

    def test_exact_vendor_reference_is_distinct_from_printed_quote_and_preserves_duplicates(self):
        schema = self.call(action="dbf_schema")
        self.assertIn({"vendor_quote": "VEND_QUOT"}, schema["exact_filters"])
        result = self.call(vendor_quote="00000001")
        self.assertEqual(result["filter_fields"], {"vendor_quote": "VEND_QUOT"})
        self.assertEqual([row["record_index"] for row in result["rows"]], [0, 5])
        self.assertEqual(result["deleted_records_skipped"], 1)
        self.assertEqual([row["values"]["PRICE1"] for row in result["rows"]], ["2.00000", "2.50000"])
        self.assertEqual([row["values"]["VOIDED"] for row in result["rows"]], ["F", "T"])
        for key in ["1", "SYNTHETIC-PRINTED", "00000001' OR 1=1"]:
            self.assertEqual(self.call(vendor_quote=key)["rows"], [])
        for row in result["rows"]:
            content = (self.root / "VENDQUOT.DBF").read_bytes()
            raw = content[row["record_byte_offset"]:row["record_byte_offset"] + row["record_bytes"]]
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["record_sha256"])

    def test_composite_supplier_scope_excludes_other_vendor_material_and_quote(self):
        result = self.call(quote_no="Q000001", material_id="00001", vendor_id="V0001")
        self.assertEqual(result["filter_fields"], {"quote_no": "QUOTE_NO", "material_id": "ID", "vendor_id": "VENDOR_ID"})
        self.assertEqual([row["record_index"] for row in result["rows"]], [0, 5])
        self.assertNotIn("9000", json.dumps(result["rows"]))
        self.assertNotIn("8000", json.dumps(result["rows"]))
        self.assertNotIn("7000", json.dumps(result["rows"]))
        self.assertIn("not a current-cost authority", result["warning"])
        for key, value in [("quote_no", "q000001"), ("material_id", "1"), ("vendor_id", "v0001")]:
            args = {"quote_no": "Q000001", "material_id": "00001", "vendor_id": "V0001", key: value}
            self.assertEqual(self.call(**args)["rows"], [])

    def test_quote_material_and_outside_sequence_are_literal_and_schema_gated(self):
        fields = [("QUOTE_NO", "C", 7), ("SEQ", "C", 3), ("ID", "C", 5), ("VEND_UNIT", "N", 15)]
        rows = [(b" ", ["Q000001", "001", "00001", "0.0625000"]),
                (b" ", ["Q000001", "002", "00001", "0.1250000"]),
                (b" ", ["Q000002", "001", "00001", "0.2500000"])]
        for path in ["QUOTEM.DBF", "QUOTEO.DBF", "quotem.dbf"]:
            self.put(path, fields, rows)
            result = self.call(path, quote_no="Q000001", seq="001")
            self.assertEqual(result["filter_fields"], {"quote_no": "QUOTE_NO", "seq": "SEQ"})
            self.assertEqual([row["record_index"] for row in result["rows"]], [0])
            self.assertEqual(result["rows"][0]["values"]["VEND_UNIT"], "0.0625000")
            self.assertEqual(self.call(path, quote_no="Q000001", seq="1")["rows"], [])
        self.put("QUOTEM.DBF", [("QUOTE_NO", "C", 7), ("SEQ", "N", 3)], [(b" ", ["Q000001", "1"])])
        with self.assertRaises(reader.InvalidRequest):
            self.call("QUOTEM.DBF", quote_no="Q000001", seq="1")

    def test_rejects_partial_mixed_unknown_or_wrong_table_key_forms(self):
        invalid = [{"material_id": "00001"}, {"vendor_id": "V0001"},
                   {"quote_no": "Q000001", "material_id": "00001"},
                   {"quote_no": "Q000001", "vendor_id": "V0001"},
                   {"vendor_quote": "00000001", "quote_no": "Q000001"},
                   {"vendor_quote": "00000001", "record_id": "00001"},
                   {"quote_no": "Q000001", "material_id": "00001", "vendor_id": "V0001", "record_id": "00001"},
                   {"vendor_quote": " 00000001"}, {"vendor_quote": "00000001\n"}, {"vendor_quote": True},
                   {"vendor_quote": "00000001", "column": "VEND_QUOT"}]
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(reader.InvalidRequest):
                self.call(**args)
        for table in ["MATERIAL.DBF", "OPERATIO.DBF", "HISTORY.DBF"]:
            self.put(table, VENDOR_FIELDS, [(b" ", vendor_row())])
            for args in [{"vendor_quote": "00000001"}, {"quote_no": "Q000001", "material_id": "00001", "vendor_id": "V0001"}]:
                with self.subTest(table=table, args=args), self.assertRaises(reader.InvalidRequest):
                    self.call(table, **args)
        with self.assertRaises(reader.InvalidRequest):
            self.call("VENDQUOT.DBF", quote_no="Q000001", seq="001")

    def test_vendor_schema_types_paging_hashes_and_raw_validity_are_preserved(self):
        first = self.call(vendor_quote="00000001", limit=1)
        second = self.call(vendor_quote="00000001", offset=first["next_offset"], expected_dbf_sha256=first["citation"]["dbf_sha256"])
        self.assertEqual([row["record_index"] for row in second["rows"]], [5])
        self.assertEqual(second["rows"][0]["values"]["GOOD_UNTIL"], "20240630")
        with self.assertRaisesRegex(reader.InvalidRequest, "hash mismatch"):
            self.call(vendor_quote="00000001", expected_dbf_sha256="0" * 64)
        for column in [0, 2, 3, 4]:
            fields = list(VENDOR_FIELDS); name, _, length = fields[column]
            fields[column] = (name, "N", length)
            values = vendor_row(); values[column] = "1"
            self.put("VENDQUOT.DBF", fields, [(b" ", values)])
            if column == 0:
                args = {"vendor_quote": "1"}
            else:
                args = {"quote_no": "Q000001", "material_id": "00001", "vendor_id": "V0001"}
            with self.subTest(column=column), self.assertRaises(reader.InvalidRequest):
                self.call(**args)
        self.put("VENDQUOT.DBF", VENDOR_FIELDS, [(b" ", [*vendor_row()[:10], "00000000", "", "?"])])
        row = self.call(vendor_quote="00000001")["rows"][0]
        self.assertEqual({key: row["values"][key] for key in ["DATE_STAMP", "GOOD_UNTIL", "VOIDED"]},
                         {"DATE_STAMP": "00000000", "GOOD_UNTIL": "", "VOIDED": "?"})

    def test_native_supplier_evidence_supports_reviewed_line_minimum_and_margin_without_release(self):
        payload = {"action": "dbf_rows", "source_set": "fabritrak", "path": "VENDQUOT.DBF",
                   "vendor_quote": "00000001", "limit": 1}
        result = self.native(payload)
        self.assertFalse(result.get("isError"), result)
        offer = result["content"]; row = offer["rows"][0]; fields = row["values"]
        self.assertTrue(self.native({**payload, "expected_dbf_sha256": "0" * 64}).get("isError"))
        self.assertEqual(fields["VOIDED"], "F")
        self.assertEqual(fields["TYPE"], "M")  # Synthetic fixture code only; no installed TYPE semantics inferred.
        quote = quote_tests.NativeQuoteTest(); quote.setUp(); self.addCleanup(quote.doCleanups)
        request = json.loads((ROOT / "estimator/examples/should-cost-intake.json").read_text())
        part = request["parts"][0]; part["quantity"] = 10; part["uom"]["original_quantity"] = 10
        component = part["pricing"]["cost_basis"]["components"][0]
        component.update(original_unit="kg", quantity_unit="kg", quantity=10,
                         unit_cost={key: float(fields["PRICE1"]) for key in ["low", "base", "high"]},
                         minimum_charge={key: float(fields["MINIMUM"]) for key in ["low", "base", "high"]})
        component["assumptions"] = ["Synthetic explicit review: ten kg across ten requested pieces, USD/kg tier 1 applies",
                                     "USD100 supplier minimum once for the line; zero supplier setup; freight/tax excluded"]
        locator = f"fabritrak:VENDQUOT.DBF#record_index=0&record_sha256={row['record_sha256']}&field=PRICE1,MINIMUM"
        iso_date = lambda value: f"{value[:4]}-{value[4:6]}-{value[6:]}"
        source = {"source_class": "supplier_quote", "sha256": offer["citation"]["dbf_sha256"], "locator": locator,
                  "source_date": iso_date(fields["DATE_STAMP"]), "effective_date": iso_date(fields["DATE_STAMP"]),
                  "expires_date": iso_date(fields["GOOD_UNTIL"]), "status": "current", "applicability": "assumed",
                  "basis": "Synthetic supplied review confirms grade, dimensions, ten-kg tier, USD/kg COST and one USD100 minimum; not authenticated"}
        component["sources"].append(source)
        part["source_evidence"].append({"id": "supplier", "sha256": source["sha256"], "locator": locator,
                                        "record_index": 0, "field": "PRICE1,MINIMUM"})
        fact = next(f for f in part["geometry"] if f["id"] == "material")
        fact.update(value="Ten kg for ten pieces; USD/kg COST, USD100 line minimum", original_unit="kg",
                    source_ids=["worksheet", "supplier"])
        route = part["pricing"]["cost_basis"]["routing"][0]; route["process_quantity"] = 10
        original = quote.home / "request.json"; original.write_text(json.dumps(request))
        uploads = []
        for name in ["drawing", "worksheet"]:
            path = quote.home / f"{name}.txt"; path.write_text(f"SYNTHETIC {name}, ten-piece costing assumption only")
            uploads.append({"id": name, "path": str(path), "media_type": "text/plain"})
        manifest = quote.home / "uploads.json"; manifest.write_text(json.dumps(uploads))
        capture = subprocess.run(["node", str(ROOT / "estimator/node_modules/tsx/dist/cli.mjs"),
                                  str(ROOT / "estimator/src/intake-cli.ts"), str(original), "--attachments", str(manifest),
                                  "--operator", "Synthetic operator"], env={**os.environ, "HOME": str(quote.home)},
                                 capture_output=True, text=True, check=True, timeout=20)
        retained_path = Path(json.loads(capture.stdout)["request_path"])
        self.addCleanup(lambda: retained_path.parent.chmod(0o700))
        retained = json.loads(retained_path.read_text())
        priced = quote.invoke(retained, corpus=None, no_database=True)
        self.assertFalse(priced.get("isError"), priced)
        content = priced["content"]; cost = content["order"]["lines"][0]["cost_breakdown"]
        self.assertEqual(cost["components"][0]["total_cost"]["base"], 100)
        self.assertEqual(cost["reconciled_flat"]["material_per_unit"], 10)
        self.assertEqual(cost["estimated_line_cost"]["base"], 330)
        self.assertEqual(cost["estimated_line_margin_pct"]["base"], 25)
        self.assertEqual(content["total"], 440)
        self.assertEqual(cost["supplied_basis"]["components"][0]["sources"][-1], source)
        self.assertEqual(content["review"]["request_sha256"], content["order"]["provenance"]["request_sha256"])
        self.assertFalse(content["review"]["customer_release_authorized"])
        self.assertTrue(content["review"]["requires_human_review"])
        invalid = json.loads(json.dumps(retained))
        invalid["parts"][0]["pricing"]["cost_basis"]["components"][0]["sources"][-1]["expires_date"] = "2024-05-31"
        check = """import assert from 'node:assert/strict';
import {deriveCostBasis} from './estimator/src/costing.ts';
assert.throws(() => deriveCostBasis(JSON.parse(process.argv[1]), 10, '2024-06-01'), /expired/);"""
        subprocess.run(["node", "--input-type=module", "-e", check, json.dumps(invalid["parts"][0]["pricing"]["cost_basis"])],
                       cwd=ROOT, capture_output=True, text=True, check=True, timeout=20)
        receipts = set(quote.home.rglob("review.json"))
        held = quote.invoke(invalid, corpus=None, no_database=True)
        self.assertTrue(held.get("isError"), held)
        self.assertEqual(set(quote.home.rglob("review.json")), receipts)
