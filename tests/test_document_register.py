"""Synthetic evidence and fail-closed tests for the separate document register."""

import csv
from datetime import date
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build-document-register.py"
SPEC = importlib.util.spec_from_file_location("document_register", SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)

NAME = "QuoteLetter00000123.pdf"
QUOTE = "0004567"
PART = "SYN-001"
COLUMNS = ("quote_no,item_no,assembly_no,quote_date,date_stamp,customer_id,customer,part_no,"
           "description,rev,drawing_no,rfq_no,buyer_name,salesperson,quote_letter,letter_date,"
           "quantity,unit_price,unit_cost,extended_price,markup,del_seq,material,status,won_date,"
           "to_quote,user_quote,newsellpri,comment").split(",")


def document(prices="10 $39.07 $390.75 250 $17.53 $4,383.18", quote=QUOTE,
             part=PART, letter="00000123", day="07/06/26"):
    return (f"Inquiry Date : {day} Letter : {letter}\n# QUOTE\n"
            f"Item # : Quote # : {quote} RFQ # : 1 Rev : A P/N : {part} Comment :\n"
            "Description Quantity Price Each Extended Price\n"
            f"SYNTHETIC PART {prices}\nBy: Page 1\n")


def fixtures():
    original = dict.fromkeys(COLUMNS, "")
    original.update(quote_no=QUOTE, item_no="", part_no=PART, customer_id="000014",
                    date_stamp="2026-07-06", quote_date="2026-07-01", unit_price="2.0",
                    quantity="10", status="open")
    originals = [original]
    tables = {
        "QUOTLINE": [dict(QUOTLETTER="00000123", QUOTE_NO=QUOTE, ITEM="  1",
                          PART_NO=PART, DESCR="SYNTHETIC PART", REV_NO="A")],
        "QUOTLEIT": [dict(QUOTLETTER="00000123", ITEM="  1", QTY=qty,
                          PRICE=price, QUOTEPRICE=price)
                     for qty, price in ((10, "39.0751"), (250, "17.5327"))],
        "QUOTLETT": [dict(QUOTLETTER="00000123", DATE_STAMP=date(2026, 7, 6),
                          REVISION_D=None, COMP_ID="000014", CNAME="SYNTHETIC")],
    }
    return originals, tables


class DocumentEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.originals, self.tables = fixtures()

    def verify(self, content=None):
        return builder.verify_document(content or document(), "00000123",
                                       list(self.originals[0]),
                                       builder.index_sources(self.tables, self.originals))

    def held(self, reason, content=None):
        with self.assertRaisesRegex(builder.Hold, reason):
            self.verify(content)

    def test_full_precision_and_customer_quote_metadata(self):
        _, _, rows, field, counts, legacy = self.verify()
        self.assertEqual(field, "PRICE")
        self.assertEqual([row["unit_price"] for row in rows], ["39.0751", "17.5327"])
        self.assertEqual([row["extended_price"] for row in rows], ["390.75", "4383.18"])
        self.assertEqual(rows[0]["quote_date"], "2026-07-06")
        self.assertEqual(rows[0]["status"], "unknown")
        self.assertEqual((rows[0]["unit_cost"], rows[0]["markup"], rows[0]["newsellpri"]),
                         ("", "", ""))
        self.assertEqual((counts["fields_agree"], legacy), (2, 2))

    def test_price_field_is_evidence_selected_not_internal_fallback(self):
        self.tables["QUOTLEIT"][0]["PRICE"] = "39.0100"
        self.tables["QUOTLEIT"][1]["PRICE"] = "17.0100"
        _, _, rows, field, counts, _ = self.verify()
        self.assertEqual((field, rows[0]["unit_price"], counts["QUOTEPRICE_only"]),
                         ("QUOTEPRICE", "39.0751", 2))
        self.tables["QUOTLEIT"][1]["QUOTEPRICE"] = "17.0300"
        self.held("printed_price_mismatch")

    def test_unusable_secondary_field_and_legacy_prices_do_not_veto_evidence(self):
        self.tables["QUOTLEIT"][0]["QUOTEPRICE"] = 0
        self.tables["QUOTLEIT"][1]["QUOTEPRICE"] = ""
        self.originals[0]["unit_price"] = ""
        _, _, rows, field, counts, mismatch = self.verify()
        self.assertEqual((field, len(rows), counts["PRICE_only"], mismatch), ("PRICE", 2, 2, 2))
        self.originals[0]["unit_price"] = "0"
        self.assertEqual(self.verify()[-1], 2)
        self.tables["QUOTLEIT"][0]["PRICE"] = -1
        self.held("printed_price_mismatch")

    def test_indistinguishable_or_mixed_price_fields_hold(self):
        self.tables["QUOTLEIT"][0]["PRICE"] = "39.0752"
        self.held("indistinguishable_price_fields")
        self.tables["QUOTLEIT"][0]["PRICE"] = "39.0100"
        self.tables["QUOTLEIT"][1]["QUOTEPRICE"] = "17.0100"
        self.held("inconsistent_price_field")

    def test_agreeing_rows_do_not_override_a_decisive_price_field(self):
        self.tables["QUOTLEIT"][1]["PRICE"] = "17.0100"
        _, _, rows, field, counts, _ = self.verify()
        self.assertEqual((field, len(rows), counts["fields_agree"]), ("QUOTEPRICE", 2, 1))

    def test_rounded_display_is_not_accepted_as_source_precision(self):
        self.tables["QUOTLEIT"][0]["PRICE"] = "39.0751"
        self.tables["QUOTLEIT"][0]["QUOTEPRICE"] = "39.0751"
        self.held("printed_price_mismatch",
                  document(prices="10 $39.08 $390.75 250 $17.53 $4,383.18"))

    def test_adjacent_rows_and_markdown_separators(self):
        content = document(prices="10|$39.07|$390.75\n250 $17.53 $4,383.18")
        self.assertEqual(len(self.verify(content)[2]), 2)

    def test_signed_quantities_and_malformed_grouping_cannot_be_stripped(self):
        for quantity in ("-10", "−10", "- 10", "-\n10", "0"):
            with self.subTest(quantity=quantity), self.assertRaises(builder.Hold):
                self.verify(document(prices=f"{quantity} $39.07 $390.75 250 $17.53 $4,383.18"))
        for prices in ("10 $3,9.07 $390.75 250 $17.53 $4,383.18",
                       "10 $39.07 $390.75 250 $17.53 $4,38,3.18",
                       "10 $39.07 $390.75 250 $17.53 $4,383.18 extra $-9.99"):
            with self.subTest(prices=prices), self.assertRaises(builder.Hold):
                self.verify(document(prices=prices))

    def test_layout_rows_verify_but_separated_markdown_columns_do_not(self):
        layout = ("Inquiry Date : 07/06/26\nLetter : 00000123\n"
                  "QUOTE                            Delivery :\n"
                  "Item # : Quote # : 0004567\nP/N : SYN-001         Rev : A\n"
                  "Description      Quantity      Price Each      Extended Price\n"
                  "SYNTHETIC PART     10           $39.07          $390.75\n"
                  "                  250           $17.53         $4,383.18\nBy: 07/06/26\n")
        self.assertEqual(len(self.verify(layout)[2]), 2)
        separated = document(prices="|$39.07|$390.75|\n|$17.53|$4,383.18|\n"
                             "10 250")
        self.held("unparsed_or_extra_price_row", separated)

    def test_all_breaks_required_without_duplicate_or_extra_money(self):
        self.held("source_break_count_mismatch", document(prices="10 $39.07 $390.75"))
        self.held("duplicate_printed_quantity",
                  document(prices="10 $39.07 $390.75 10 $39.07 $390.75"))
        self.held("unparsed_or_extra_price_row",
                  document(prices="10 $39.07 $390.75 $9.99 250 $17.53 $4,383.18"))
        self.tables["QUOTLEIT"].append(dict(QUOTLETTER="00000123", ITEM="  1", QTY=-10,
                                             PRICE="1.00", QUOTEPRICE="1.00"))
        self.held("source_break_count_mismatch")
        self.tables["QUOTLEIT"].pop()
        self.tables["QUOTLEIT"][0]["QTY"] = 0
        self.held("nonpositive_or_nonfinite_value")

    def test_content_identity_and_document_type_are_verified(self):
        self.held("letter_identity_mismatch", document(letter="00000124"))
        self.held("ambiguous_or_missing_letter_line", document(quote="0004568"))
        self.held("part_identity_mismatch", document(part="OTHER-PART"))
        self.held("non_quotation_content", document().replace("# QUOTE", "# INVOICE"))
        self.held("ambiguous_quote_or_part_identity", document() + "Quote # : 0004999\n")
        self.originals[0]["customer_id"] = "DIFFERENT"
        self.held("original_identity_mismatch")

    def test_letter_and_revision_dates_gate_historical_metadata(self):
        self.held("document_date_mismatch", document(day="07/07/26"))
        self.tables["QUOTLETT"][0]["REVISION_D"] = date(2026, 7, 5)
        self.held("document_date_mismatch")
        self.tables["QUOTLETT"][0]["REVISION_D"] = date(2026, 7, 6)
        self.originals[0]["date_stamp"] = "2026-07-09"
        self.assertEqual(self.verify()[2][0]["date_stamp"], "2026-07-09")
        self.tables["QUOTLETT"][0]["DATE_STAMP"] = date(2069, 7, 6)
        self.tables["QUOTLETT"][0]["REVISION_D"] = date(2069, 7, 6)
        self.assertEqual(self.verify(document(day="07/06/69"))[2][0]["quote_date"], "2069-07-06")

    def test_multiquote_multiitem_and_duplicate_dbf_lines_hold(self):
        self.tables["QUOTLINE"].append(dict(self.tables["QUOTLINE"][0]))
        self.held("ambiguous_or_missing_letter_line")
        self.tables["QUOTLINE"].pop()
        self.originals.append(dict(self.originals[0], item_no="2"))
        self.held("ambiguous_or_missing_original_quote")

    def test_latest_verified_document_is_selected_without_blending(self):
        with tempfile.TemporaryDirectory() as temp:
            register = Path(temp) / "register.csv"
            with register.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=list(self.originals[0]))
                writer.writeheader()
                writer.writerows(self.originals)
            records = [(NAME, {"source_sha256": "a" * 64,
                               "transcript_sha256": "b" * 64, "pages": 1},
                        document(), Path(temp) / NAME)]
            with patch.object(builder, "layout_text", return_value=document()):
                data, manifest, audit = builder.render(register, self.tables, records, {})
            rows = list(csv.DictReader(io.StringIO(data)))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["source_price_field"], "PRICE")
            self.assertEqual(rows[0]["source_document"], NAME)
            self.assertEqual(manifest["counts"]["legacy_price_mismatched_rows"], 2)
            self.assertEqual(audit[0]["verification_engine"], "pdftotext-layout")
            self.assertEqual(audit[0]["verification_text_sha256"], sha256(document().encode()).hexdigest())
            other = ("QuoteLetter00000124.pdf", records[0][1], document(letter="00000124"),
                     Path(temp) / "QuoteLetter00000124.pdf")
            self.tables["QUOTLINE"].append(dict(self.tables["QUOTLINE"][0], QUOTLETTER="00000124"))
            self.tables["QUOTLEIT"] += [dict(row, QUOTLETTER="00000124") for row in self.tables["QUOTLEIT"]]
            self.tables["QUOTLETT"].append(dict(self.tables["QUOTLETT"][0], QUOTLETTER="00000124"))
            with patch.object(builder, "layout_text", side_effect=[document(), other[2]]):
                data, manifest, _ = builder.render(register, self.tables, records + [other], {})
            self.assertEqual(len(list(csv.DictReader(io.StringIO(data)))), 0)
            self.assertEqual(manifest["counts"]["ambiguous_latest_groups"], 1)

    def test_source_and_transcript_digests_are_rechecked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "pdf"
            source.mkdir()
            pdf = source / NAME
            pdf.write_bytes(b"synthetic pdf bytes")
            transcripts = root / "transcripts"
            (transcripts / "records").mkdir(parents=True)
            (transcripts / "transcripts").mkdir()
            markdown = transcripts / "transcripts" / "sample.md"
            markdown.write_text(document())
            source_hash = builder.digest(pdf)
            transcript_hash = builder.digest(markdown)
            inventory = root / "source-manifest.json"
            inventory.write_text(json.dumps({"file_count": 1, "files": [{"path": NAME,
                                   "sha256": source_hash, "bytes": pdf.stat().st_size}]}))
            record = {"relative_source_path": NAME, "source_sha256": source_hash,
                      "source_bytes": pdf.stat().st_size, "status": "success",
                      "transcript_path": "transcripts/sample.md", "transcript_sha256": transcript_hash,
                      "transcript_bytes": markdown.stat().st_size, "pages": 1,
                      "covered_pages": [1], "ocr_pages": [], "tool": "firecrawl-anydoc",
                      "tool_version": "0.2.4", "page_methods": ["anydoc"],
                      "local_ocr": False}
            key = sha256(NAME.encode()).hexdigest()
            record["transcript_path"] = f"transcripts/{key}.md"
            markdown.rename(transcripts / record["transcript_path"])
            markdown = transcripts / record["transcript_path"]
            toolchain = {"script_sha256": builder.digest(SCRIPT.with_name("transcribe-pdfs.py"))}
            fingerprint = sha256(json.dumps(toolchain, sort_keys=True).encode()).hexdigest()
            record["toolchain_sha256"] = fingerprint
            (transcripts / "records" / (key + ".json")).write_text(json.dumps(record))
            (transcripts / "summary.json").write_text(json.dumps({"schema_version": 1,
                         "source_manifest_sha256": builder.digest(inventory), "tool_version": "0.2.4",
                         "toolchain": toolchain, "toolchain_sha256": fingerprint,
                         "local_ocr": False, "document_count": 1,
                         "records": {NAME: f"records/{key}.json"}}))
            self.assertEqual(len(builder.load_records(transcripts, source, inventory)[0]), 1)
            record["toolchain_sha256"] = "0" * 64
            (transcripts / "records" / (key + ".json")).write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "provenance mismatch"):
                builder.load_records(transcripts, source, inventory)
            record["toolchain_sha256"] = fingerprint
            record["page_methods"] = ["uncovered"]
            (transcripts / "records" / (key + ".json")).write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "transcript provenance"):
                builder.load_records(transcripts, source, inventory)
            record["page_methods"] = ["anydoc"]
            (transcripts / "records" / (key + ".json")).write_text(json.dumps(record))
            linked = transcripts / "transcripts" / "linked.md"
            linked.symlink_to(markdown)
            record["transcript_path"] = "transcripts/linked.md"
            (transcripts / "records" / (key + ".json")).write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "transcript path mismatch"):
                builder.load_records(transcripts, source, inventory)
            linked.unlink()
            record["transcript_path"] = f"transcripts/{key}.md"
            (transcripts / "records" / (key + ".json")).write_text(json.dumps(record))
            markdown.rename(linked)
            markdown.symlink_to(linked)
            with self.assertRaisesRegex(ValueError, "symlinked input component"):
                builder.load_records(transcripts, source, inventory)
            markdown.unlink()
            linked.rename(markdown)
            markdown.write_text("tampered")
            with self.assertRaisesRegex(ValueError, "transcript provenance"):
                builder.load_records(transcripts, source, inventory)
            markdown.write_text(document())
            pdf.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "PDF source provenance"):
                builder.load_records(transcripts, source, inventory)

    def test_local_ocr_requires_every_page_and_is_labelled(self):
        with tempfile.TemporaryDirectory() as temp:
            register = Path(temp) / "register.csv"
            with register.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(self.originals)
            record = {"source_sha256": "a" * 64, "transcript_sha256": "b" * 64,
                      "local_ocr": True, "ocr_pages": [1], "pages": 1,
                      "page_methods": ["local-ocr"]}
            records = [(NAME, record, document(), Path(temp) / NAME)]
            with patch.object(builder, "layout_text", return_value=""):
                data, manifest, audit = builder.render(register, self.tables, records, {})
            self.assertEqual(len(list(csv.DictReader(io.StringIO(data)))), 2)
            self.assertEqual(audit[0]["verification_engine"], "local-ocr")
            self.assertEqual(manifest["verification_engines"]["local-ocr"], 1)
            record["ocr_pages"] = []
            with patch.object(builder, "layout_text", return_value=""):
                data, _, audit = builder.render(register, self.tables, records, {})
            self.assertEqual(len(list(csv.DictReader(io.StringIO(data)))), 0)
            self.assertEqual(audit[0]["reason"], "no_independent_text_or_complete_local_ocr")

    def test_render_is_deterministic_for_identical_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            register = Path(temp) / "register.csv"
            with register.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(self.originals)
            records = [(NAME, {"source_sha256": "a" * 64,
                               "transcript_sha256": "b" * 64, "pages": 1},
                        document(), Path(temp) / NAME)]
            with patch.object(builder, "layout_text", return_value=document()):
                before = builder.render(register, self.tables, records, {})
                after = builder.render(register, self.tables, records, {})
            self.assertEqual(before, after)

    def test_cli_publishes_complete_bundle_once_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            register = root / "register.csv"
            register.write_text("quote_no\n")
            manifest_file = root / "pdf-manifest.json"
            manifest_file.write_text("{}")
            transcripts = root / "transcripts"
            transcripts.mkdir()
            (transcripts / "summary.json").write_text("{}")
            dbf = root / "dbf"
            dbf.mkdir()
            pdf = root / "pdf"
            pdf.mkdir()
            out = root / "output"
            args = ["--register", str(register), "--dbf-dir", str(dbf),
                    "--transcripts", str(transcripts), "--source-dir", str(pdf),
                    "--source-manifest", str(manifest_file), "--out", str(out)]
            hashes = {"pdf_source_manifest": builder.digest(manifest_file),
                      "transcription_summary": builder.digest(transcripts / "summary.json"),
                      "transcription_records": {}, "transcripts": {},
                      "transcription_tool_version": "0.2.4"}
            with (patch.object(builder, "load_tables", return_value=({}, {})),
                  patch.object(builder, "load_records", return_value=([], hashes)),
                  patch.object(builder, "render", return_value=("quote_no\n", {"counts": {}}, [])),
                  redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO())):
                self.assertEqual(builder.main(args), 0)
                self.assertEqual((out / "document-quotes.csv").read_text(), "quote_no\n")
                self.assertTrue((out / "evidence-manifest.json").exists())
                self.assertTrue((out / "private-document-audit.json").exists())
                self.assertEqual(builder.main(args), 2)
                self.assertEqual((out / "document-quotes.csv").read_text(), "quote_no\n")
                out.rename(root / "former-output")
                def change_input(*_):
                    register.write_text("mutated\n")
                    return "quote_no\n", {"counts": {}}, []
                with patch.object(builder, "render", side_effect=change_input):
                    self.assertEqual(builder.main(args), 2)
                self.assertFalse(out.exists())
                self.assertEqual(list(root.glob(".document-register-*")), [])


if __name__ == "__main__":
    unittest.main()
