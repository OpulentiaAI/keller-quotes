"""Synthetic association, privacy, pinning and filesystem tests for the offline index."""

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/index-keller-documents.py"
SPEC = importlib.util.spec_from_file_location("keller_document_index", SCRIPT)
indexer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(indexer)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def frontmatter(path):
    lines = path.read_text().splitlines()
    return {key: json.loads(value) for key, value in (line.split(":", 1) for line in lines[1:-1])}


class DocumentIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keller-document-index-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.restored = self.root / "restored"
        self.restored.mkdir(mode=0o700)
        self.catalog = self.root / "catalog.private.json"
        self.out = self.root / "out"
        self.files = []
        self.serial = 0

    def add_file(self, alias, data):
        path = self.restored / alias
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entry = {"path": alias, "original_path": "/original/private/" + alias,
                 "sha256": sha256(data).hexdigest(), "bytes": len(data)}
        self.files.append(entry)
        return entry

    def document(self, source="private-customer/Invoice0001.pdf", pdf=b"%PDF synthetic private evidence",
                 status="success", transcript=b"private customer Part-P42 $999.12\n", label="Invoice",
                 basis="filename-only", with_record=True):
        self.serial += 1
        pdf_entry = self.add_file(indexer.PDF_PREFIX + source, pdf)
        if not with_record:
            return pdf_entry, None, None
        transcript_path = f"transcripts/unrelated-markdown-id-{self.serial}.md"
        record = {
            "relative_source_path": source, "source_sha256": pdf_entry["sha256"],
            "source_bytes": len(pdf), "filename_classification": label,
            "classification_basis": basis, "status": status, "transcript_path": transcript_path,
            "tool": "firecrawl-anydoc", "tool_version": "0.2.4", "pages": 1,
            "covered_pages": [1], "page_methods": ["anydoc"],
        }
        transcript_entry = None
        if transcript is not None:
            transcript_entry = self.add_file(indexer.TRANSCRIPTION_PREFIX + transcript_path, transcript)
            record.update(transcript_sha256=transcript_entry["sha256"], transcript_bytes=len(transcript))
        record_entry = self.add_file(indexer.RECORD_PREFIX + f"not-a-pdf-hash-{self.serial}.json", encode(record))
        return pdf_entry, record_entry, transcript_entry

    def update_record(self, entry, updates=None, remove=()):
        path = self.restored / entry["path"]
        record = json.loads(path.read_bytes())
        record.update(updates or {})
        for key in remove:
            record.pop(key, None)
        self.replace_entry(entry, encode(record))

    def replace_entry(self, entry, data):
        (self.restored / entry["path"]).write_bytes(data)
        entry.update(sha256=sha256(data).hexdigest(), bytes=len(data))

    def write_catalog(self):
        data = {"schema_version": 1, "scope": "OPERATOR_ONLY", "kind": "KELLER_OPERATOR_EVIDENCE_ARCHIVE",
                "files": self.files}
        self.catalog.write_bytes(encode(data))
        return digest(self.catalog)

    def cli(self, args, success=True):
        proc = subprocess.run([sys.executable, "-B", str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True, check=False)
        if success:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            return json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "document index operation failed\n")
        return proc

    def build(self, success=True, out=None, catalog=None, pin=None, restored=None):
        pin = self.write_catalog() if pin is None else pin
        return self.cli(["build", "--catalog", catalog or self.catalog, "--catalog-sha256", pin,
                         "--restored-root", restored or self.restored, "--out", out or self.out], success)

    def rows(self):
        return [json.loads(line) for line in (self.out / "document-index.private.jsonl").read_bytes().splitlines()]

    def native(self):
        return list((self.out / "native-documents").glob("*.md"))

    def rejected_build(self):
        self.build(success=False)
        self.assertFalse(self.out.exists())

    def lookup(self, receipt, document_id, success=True, index=None, pin=None):
        return self.cli(["lookup", "--index", index or self.out / "document-index.private.jsonl",
                         "--index-sha256", pin or receipt["index_sha256"], "--document-id", document_id], success)

    def test_exact_alias_identity_duplicate_bytes_native_privacy_and_modes(self):
        first = self.document(source="Private One/Invoice Same.PDF")
        second = self.document(source="Private Two/Invoice Same.PDF")
        third = self.document(source="Unicode café/Invoice Same.pdf")
        receipt = self.build()
        rows = self.rows()
        expected_ids = sorted(sha256(entry[0]["path"].encode()).hexdigest() for entry in (first, second, third))
        self.assertEqual([row["document_id"] for row in rows], expected_ids)
        self.assertEqual(len({row["pdf"]["sha256"] for row in rows}), 1)
        self.assertNotIn(first[0]["sha256"], expected_ids)
        self.assertEqual(receipt["documents"], 3)
        self.assertEqual(receipt["index_sha256"], digest(self.out / "document-index.private.jsonl"))
        self.assertEqual(receipt["manifest_sha256"], digest(self.out / "manifest.json"))
        h = sha256()
        for native in sorted(self.native()):
            fields = frontmatter(native)
            h.update(f"{native.name}\t{digest(native)}\n".encode())
            self.assertEqual(fields["type"], "keller.document")
            self.assertEqual(fields["archive"], indexer.ARCHIVE)
            self.assertEqual(fields["classification_hint"], "Invoice")
            self.assertEqual(fields["classification_basis"], "filename-only")
            self.assertEqual(fields["extraction_status"], "success")
            self.assertEqual(set(fields), {"type", "tldr", "document_id", "pdf_sha256", "record_sha256",
                                           "transcript_sha256", "classification_hint", "classification_basis",
                                           "extraction_status", "archive"})
            self.assertIn("Retained Keller document metadata", fields["tldr"])
            self.assertIn("do not establish business outcomes", fields["tldr"])
            for private in ("Private One", "Private Two", "Unicode", "Part-P42", "$999.12", "/original/", ".PDF"):
                self.assertNotIn(private, native.read_text())
        manifest = json.loads((self.out / "manifest.json").read_bytes())
        self.assertEqual(manifest["inputs"], {"catalog_sha256": digest(self.catalog), "builder_sha256": digest(SCRIPT)})
        self.assertEqual(manifest["outputs"]["native_documents"]["sha256"], h.hexdigest())
        self.assertEqual(manifest["counts"]["unique_pdf_hashes"], 1)
        self.assertEqual(manifest["counts"]["pdf_documents"], 3)
        for path in (self.out, *self.out.rglob("*")):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o400)

    def test_lookup_returns_exact_private_recovery_aliases_and_original_names(self):
        pdf, record, transcript = self.document()
        receipt = self.build()
        row = self.lookup(receipt, indexer.alias_id(pdf["path"]))
        self.assertEqual(row, self.rows()[0])
        self.assertEqual(row["relative_source_path"], "private-customer/Invoice0001.pdf")
        for name, entry in (("pdf", pdf), ("record", record), ("transcript", transcript)):
            self.assertEqual(row[name], indexer.descriptor(entry))
        self.assertEqual(row["declared_transcript_alias"], transcript["path"])
        self.assertNotEqual(Path(record["path"]).stem, pdf["sha256"])
        self.assertNotIn("private customer Part-P42", json.dumps(row))

    def test_outputs_are_deterministic_and_identity_is_independent_of_restoration_root(self):
        self.document()
        receipt = self.build()
        restored_second = self.root / "restored-second"
        self.restored.rename(restored_second)
        out_second = self.root / "out-second"
        second = self.build(out=out_second, restored=restored_second)
        self.assertEqual(receipt, second)
        for path in self.out.rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (out_second / path.relative_to(self.out)).read_bytes())

    def test_case_distinct_source_aliases_are_distinct_physical_documents(self):
        first, _, _ = self.document(source="case/Document.pdf")
        second, _, _ = self.document(source="case/document.pdf")
        self.build()
        self.assertEqual(len(self.rows()), 2)
        self.assertNotEqual(indexer.alias_id(first["path"]), indexer.alias_id(second["path"]))

    def test_lookup_checks_whole_file_pin_before_printing_a_matching_row(self):
        self.document()
        self.document(source="different/PO.pdf", label="PO")
        receipt = self.build()
        document_id = self.rows()[0]["document_id"]
        self.lookup(receipt, document_id, success=False, pin="0" * 64)
        self.lookup(receipt, "0" * 64, success=False)
        path = self.out / "document-index.private.jsonl"
        path.chmod(0o600)
        with path.open("ab") as stream:
            stream.write(b"\n")
        self.lookup(receipt, document_id, success=False)

    def test_lookup_requires_explicit_pin_and_document_id_and_sanitizes_errors(self):
        self.document()
        self.build()
        base = ["lookup", "--index", self.out / "document-index.private.jsonl"]
        self.cli(base, success=False)
        self.cli(base + ["--index-sha256", "1" * 64], success=False)
        self.cli(base + ["--index-sha256", "untrusted-credential-error", "--document-id", "x"], success=False)
        self.cli(["untrusted-credential-error"], success=False)

    def test_failed_and_zero_byte_pdf_and_blank_transcripts_are_retained(self):
        self.document(source="zero.pdf", pdf=b"", status="failed", transcript=None)
        self.document(source="failed.pdf", status="failed", transcript=None)
        self.document(source="blank.pdf", status="blank", transcript=b"")
        self.document(source="empty-success.pdf", status="success", transcript=b"")
        receipt = self.build()
        rows = {row["relative_source_path"]: row for row in self.rows()}
        fields = {frontmatter(path)["document_id"]: frontmatter(path) for path in self.native()}
        self.assertEqual(receipt["documents"], 4)
        for source, status in (("zero.pdf", "failed:zero-byte-pdf"), ("failed.pdf", "failed"),
                               ("blank.pdf", "blank:empty-transcript"), ("empty-success.pdf", "success:empty-transcript")):
            self.assertEqual(fields[rows[source]["document_id"]]["extraction_status"], status)
        for source in ("zero.pdf", "failed.pdf"):
            self.assertIsNone(rows[source]["transcript"])
            self.assertIsNotNone(rows[source]["declared_transcript_alias"])
            self.assertNotIn("transcript_sha256", fields[rows[source]["document_id"]])
        manifest = json.loads((self.out / "manifest.json").read_bytes())
        self.assertEqual(manifest["counts"]["zero_byte_pdfs"], 1)
        self.assertEqual(manifest["counts"]["associated_records"], 4)
        self.assertEqual(manifest["counts"]["associated_transcripts"], 2)

    def test_pdf_without_record_is_indexed_as_missing_not_reclassified_by_name(self):
        self.document(source="Invoice123.pdf", with_record=False)
        self.build()
        row = self.rows()[0]
        fields = frontmatter(self.native()[0])
        self.assertIsNone(row["record"])
        self.assertIsNone(row["transcript"])
        self.assertEqual(fields["extraction_status"], "missing-record")
        self.assertEqual(fields["classification_hint"], "unavailable")
        self.assertEqual(fields["classification_basis"], "no-record")
        self.assertNotIn("record_sha256", fields)

    def test_orphan_and_auxiliary_metadata_dispositions_do_not_inflate_pdf_counts(self):
        orphan, record, transcript = self.document(source="orphan-private.pdf")
        self.files.remove(orphan)
        (self.restored / orphan["path"]).unlink()
        auxiliary = self.add_file(indexer.TRANSCRIPTION_PREFIX + "summary.json", encode({"private-name": "Part-P42"}))
        stray = self.add_file(indexer.TRANSCRIPT_PREFIX + "stray-private.md", b"Private orphan text")
        self.document(source="present.pdf")
        self.build()
        manifest = json.loads((self.out / "manifest.json").read_bytes())
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(manifest["counts"]["pdf_documents"], 1)
        self.assertEqual(manifest["counts"]["transcription_json_files"], 3)
        self.assertEqual(manifest["counts"]["dispositions"], {"auxiliary-metadata": 1, "orphan-record": 1, "orphan-transcript": 2})
        dispositions = {item["alias_id"]: item for item in manifest["dispositions"]}
        for entry, kind in ((record, "orphan-record"), (transcript, "orphan-transcript"),
                             (auxiliary, "auxiliary-metadata"), (stray, "orphan-transcript")):
            self.assertEqual(dispositions[indexer.alias_id(entry["path"])],
                             {"alias_id": indexer.alias_id(entry["path"]), "sha256": entry["sha256"], "disposition": kind})
        for private in ("orphan-private", "stray-private", "Part-P42", "/original/", "private-name"):
            self.assertNotIn(private, (self.out / "manifest.json").read_text())

    def test_associations_are_exact_not_fuzzy_or_based_on_pdf_content_hash(self):
        _, record, _ = self.document(source="Original.pdf")
        self.update_record(record, {"relative_source_path": "original.pdf"})
        self.build()
        row = self.rows()[0]
        self.assertIsNone(row["record"])
        manifest = json.loads((self.out / "manifest.json").read_bytes())
        self.assertEqual(manifest["counts"]["missing_records"], 1)
        self.assertEqual(manifest["counts"]["dispositions"]["orphan-record"], 1)

    def test_unknown_annotations_and_statuses_remain_private_source_annotations(self):
        self.document(label="PrivateCustomer123", basis="issuer says accepted and paid",
                      status="paid", transcript=None)
        receipt = self.build()
        row = self.rows()[0]
        self.assertEqual(row["filename_classification"], "PrivateCustomer123")
        self.assertEqual(row["classification_basis"], "issuer says accepted and paid")
        self.assertEqual(row["record_status"], "paid")
        self.assertEqual(self.lookup(receipt, row["document_id"]), row)
        fields = frontmatter(self.native()[0])
        for key in ("classification_hint", "classification_basis", "extraction_status"):
            self.assertEqual(fields[key], "private-source-annotation")
        self.assertNotIn("PrivateCustomer123", self.native()[0].read_text())
        self.assertNotIn("issuer says", (self.out / "manifest.json").read_text())

    def test_native_fields_do_not_allow_untrusted_annotation_injection(self):
        self.document(label="---\ncustomer: private-price-$123\n---", basis="/private/customer")
        self.build()
        text = self.native()[0].read_text()
        self.assertEqual(text.count("---"), 2)
        self.assertNotIn("private-price", text)
        self.assertNotIn("/private/customer", text)

    def test_original_source_hash_and_size_must_match_catalog(self):
        _, record, _ = self.document()
        for update in ({"source_sha256": "0" * 64}, {"source_bytes": 1}, {"source_bytes": True}):
            with self.subTest(update=update):
                old = (self.restored / record["path"]).read_bytes()
                self.update_record(record, update)
                self.rejected_build()
                self.replace_entry(record, old)

    def test_restored_pdf_record_and_transcript_whole_bytes_are_hash_pinned(self):
        entries = self.document()
        for entry in entries:
            with self.subTest(role=entry["path"].split("/")[-2]):
                path = self.restored / entry["path"]
                old = path.read_bytes()
                path.write_bytes(old + b" ")
                self.rejected_build()
                path.write_bytes(old)

    def test_record_transcript_hash_and_size_must_match_catalog(self):
        _, record, _ = self.document()
        old = (self.restored / record["path"]).read_bytes()
        for update in ({"transcript_sha256": "0" * 64}, {"transcript_bytes": 0}, {"transcript_bytes": False}):
            with self.subTest(update=update):
                self.update_record(record, update)
                self.rejected_build()
                self.replace_entry(record, old)

    def test_partial_or_missing_success_transcript_metadata_is_rejected(self):
        _, record, _ = self.document()
        old = (self.restored / record["path"]).read_bytes()
        for keys in (("transcript_sha256",), ("transcript_bytes",),
                     ("transcript_bytes", "transcript_sha256"), ("transcript_path",)):
            with self.subTest(keys=keys):
                self.update_record(record, remove=keys)
                self.rejected_build()
                self.replace_entry(record, old)

    def test_catalog_missing_success_transcript_is_rejected(self):
        _, _, transcript = self.document()
        self.files.remove(transcript)
        self.rejected_build()

    def test_unpinned_transcript_on_a_failed_record_is_rejected(self):
        _, record, _ = self.document(status="failed")
        self.update_record(record, remove=("transcript_sha256", "transcript_bytes"))
        self.rejected_build()

    def test_failed_record_with_valid_transcript_does_not_become_success(self):
        self.document(status="failed")
        self.build()
        self.assertEqual(frontmatter(self.native()[0])["extraction_status"], "failed")
        self.assertIsNotNone(self.rows()[0]["transcript"])

    def test_missing_record_association_keys_and_non_pdf_associations_are_rejected(self):
        _, record, _ = self.document()
        old = (self.restored / record["path"]).read_bytes()
        for key in ("relative_source_path", "source_sha256", "source_bytes", "status",
                    "filename_classification", "classification_basis"):
            with self.subTest(key=key):
                self.update_record(record, remove=(key,))
                self.rejected_build()
                self.replace_entry(record, old)
        self.update_record(record, {"relative_source_path": "source.txt"})
        self.rejected_build()

    def test_duplicate_or_conflicting_records_for_one_source_are_rejected(self):
        _, record, _ = self.document()
        raw = (self.restored / record["path"]).read_bytes()
        duplicate = self.add_file(indexer.RECORD_PREFIX + "duplicate.json", raw)
        self.rejected_build()
        self.update_record(duplicate, {"status": "failed"})
        self.rejected_build()

    def test_two_sources_cannot_claim_one_transcript_alias(self):
        _, _, transcript = self.document(source="first.pdf")
        _, second_record, _ = self.document(source="second.pdf")
        self.update_record(second_record, {"transcript_path": transcript["path"][len(indexer.TRANSCRIPTION_PREFIX):]})
        self.rejected_build()

    def test_orphan_record_pins_are_validated_instead_of_silently_dropped(self):
        pdf, record, _ = self.document()
        self.files.remove(pdf)
        self.update_record(record, {"transcript_sha256": "0" * 64})
        self.rejected_build()

    def test_duplicate_catalog_aliases_and_file_directory_collisions_are_rejected(self):
        pdf, _, _ = self.document()
        self.files.append(dict(pdf))
        self.rejected_build()
        self.files.pop()
        self.files.append(dict(pdf, path=pdf["path"].rsplit("/", 1)[0]))
        self.rejected_build()

    def test_same_catalog_hash_cannot_have_two_sizes(self):
        pdf, _, _ = self.document()
        self.files.append(dict(pdf, path="other-family/alias.pdf", bytes=pdf["bytes"] + 1))
        self.rejected_build()

    def test_catalog_pin_and_schema_validation_are_fail_closed(self):
        self.document()
        pin = self.write_catalog()
        self.build(success=False, pin="0" * 64)
        data = json.loads(self.catalog.read_bytes())
        for update in ({"schema_version": True}, {"scope": "PUBLIC"}, {"files": {}}, {"kind": "other"}):
            with self.subTest(update=update):
                self.catalog.write_bytes(encode(dict(data, **update)))
                self.build(success=False, pin=digest(self.catalog))
        self.assertFalse(self.out.exists())
        self.assertNotEqual(pin, "0" * 64)

    def test_duplicate_json_keys_in_catalog_record_and_auxiliary_metadata_are_rejected(self):
        _, record, _ = self.document()
        self.write_catalog()
        raw = self.catalog.read_bytes().replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        self.catalog.write_bytes(raw)
        self.build(success=False, pin=digest(self.catalog))
        record_raw = (self.restored / record["path"]).read_bytes()
        self.replace_entry(record, record_raw.rstrip()[:-1] + b',"nested":{"x":1,"x":1}}\n')
        self.rejected_build()
        self.replace_entry(record, record_raw)
        self.add_file(indexer.TRANSCRIPTION_PREFIX + "summary.json", b'{"x":1,"x":1}\n')
        self.rejected_build()

    def test_unsafe_catalog_source_and_transcript_paths_are_rejected(self):
        pdf, record, _ = self.document()
        old_alias = pdf["path"]
        old_record = (self.restored / record["path"]).read_bytes()
        bad_paths = ("../escape.pdf", "/absolute.pdf", "folder/../escape.pdf", "folder//a.pdf",
                     "folder/./a.pdf", "C:/absolute.pdf", "folder\\a.pdf", "folder/a.pdf/", "bad\x00.pdf", "bad\n.pdf")
        for bad in bad_paths:
            with self.subTest(field="catalog", bad=bad):
                pdf["path"] = bad
                self.rejected_build()
                pdf["path"] = old_alias
            with self.subTest(field="source", bad=bad):
                self.update_record(record, {"relative_source_path": bad})
                self.rejected_build()
                self.replace_entry(record, old_record)
            with self.subTest(field="transcript", bad=bad):
                self.update_record(record, {"transcript_path": bad})
                self.rejected_build()
                self.replace_entry(record, old_record)

    def test_existing_outputs_are_never_overwritten_or_cleaned(self):
        self.document()
        self.out.write_text("keep original output file")
        self.build(success=False)
        self.assertEqual(self.out.read_text(), "keep original output file")
        self.out.unlink()
        self.out.mkdir()
        keep = self.out / "keep.txt"
        keep.write_text("keep original output directory")
        self.build(success=False)
        self.assertEqual(keep.read_text(), "keep original output directory")

    def test_output_parent_must_be_owner_controlled_and_outside_git(self):
        self.document()
        parent = self.root / "unsafe-parent"
        parent.mkdir(mode=0o700)
        for mode in (0o722, 0o770, 0o777):
            with self.subTest(mode=mode):
                parent.chmod(mode)
                self.build(success=False, out=parent / "out")
                self.assertFalse((parent / "out").exists())
        parent.chmod(0o700)
        (parent / ".git").mkdir()
        self.build(success=False, out=parent / "out")
        pin = self.write_catalog()
        with patch.object(indexer.os, "geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(indexer.IndexError):
                indexer.build(self.catalog, pin, self.restored, self.out)
        self.assertFalse(self.out.exists())

    def test_relative_traversing_missing_parent_and_source_nested_outputs_are_rejected(self):
        self.document()
        for out in ("relative-out", str(self.root) + "/../escape-out", self.root / "missing" / "out",
                    self.restored / "nested-out"):
            with self.subTest(out=out):
                self.build(success=False, out=out)
        self.assertFalse((self.restored / "nested-out").exists())

    def test_symlink_catalog_root_output_and_output_parent_are_rejected(self):
        self.document()
        pin = self.write_catalog()
        catalog_link = self.root / "catalog-link"
        catalog_link.symlink_to(self.catalog)
        self.build(success=False, catalog=catalog_link, pin=pin)
        root_link = self.root / "root-link"
        root_link.symlink_to(self.restored, target_is_directory=True)
        self.build(success=False, restored=root_link)
        parent_link = self.root / "parent-link"
        parent_link.symlink_to(self.root, target_is_directory=True)
        self.build(success=False, out=parent_link / "out")
        self.out.symlink_to(self.restored, target_is_directory=True)
        self.build(success=False)
        self.assertTrue(self.out.is_symlink())

    def test_symlink_pdf_record_transcript_and_input_directory_are_rejected(self):
        entries = self.document()
        for entry in entries:
            with self.subTest(alias=entry["path"]):
                path = self.restored / entry["path"]
                saved = self.root / "saved-file"
                path.rename(saved)
                path.symlink_to(saved)
                self.rejected_build()
                path.unlink()
                saved.rename(path)
        source_dir = self.restored / indexer.PDF_PREFIX.rstrip("/")
        saved_dir = self.root / "saved-directory"
        source_dir.rename(saved_dir)
        source_dir.symlink_to(saved_dir, target_is_directory=True)
        self.rejected_build()

    def test_nonregular_input_is_rejected_without_blocking(self):
        pdf, _, _ = self.document()
        path = self.restored / pdf["path"]
        path.unlink()
        os.mkfifo(path)
        self.rejected_build()

    def test_partial_failure_cleans_only_exclusively_created_outputs(self):
        self.document()
        pin = self.write_catalog()
        keep = self.root / "keep.txt"
        keep.write_text("keep sibling")
        original = indexer.write_private
        calls = 0

        def failing_write(path, chunks, created):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("untrusted private failure")
            return original(path, chunks, created)

        with patch.object(indexer, "write_private", side_effect=failing_write):
            with self.assertRaises(OSError):
                indexer.build(self.catalog, pin, self.restored, self.out)
        self.assertFalse(self.out.exists())
        self.assertEqual(keep.read_text(), "keep sibling")

    def test_cleanup_leaves_an_uncreated_file_inside_the_output_alone(self):
        self.document()
        pin = self.write_catalog()
        uncreated = self.out / "operator-file.txt"

        def failure(path, chunks, created):
            uncreated.write_text("not created by indexer")
            raise OSError

        with patch.object(indexer, "write_private", side_effect=failure):
            with self.assertRaises(OSError):
                indexer.build(self.catalog, pin, self.restored, self.out)
        self.assertEqual(uncreated.read_text(), "not created by indexer")
        self.assertEqual(list(self.out.iterdir()), [uncreated])

    def test_competing_output_created_after_validation_is_not_cleaned(self):
        self.document()
        pin = self.write_catalog()
        collect = indexer.collect_documents

        def compete(entries, root):
            result = collect(entries, root)
            self.out.mkdir()
            (self.out / "keep").write_text("other creator")
            return result

        with patch.object(indexer, "collect_documents", side_effect=compete):
            with self.assertRaises(FileExistsError):
                indexer.build(self.catalog, pin, self.restored, self.out)
        self.assertEqual((self.out / "keep").read_text(), "other creator")

    def test_cleanup_does_not_follow_replaced_output_root(self):
        self.document()
        pin = self.write_catalog()
        moved = self.root / "moved-created-output"
        original = indexer.write_private
        calls = 0

        def replace_root(path, chunks, created):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.out.rename(moved)
                self.out.symlink_to(moved, target_is_directory=True)
                raise OSError
            return original(path, chunks, created)

        with patch.object(indexer, "write_private", side_effect=replace_root):
            with self.assertRaises(OSError):
                indexer.build(self.catalog, pin, self.restored, self.out)
        self.assertTrue(self.out.is_symlink())
        self.assertTrue((moved / "document-index.private.jsonl").is_file())

    def test_lookup_rejects_unsafe_permissions_symlinks_duplicate_and_out_of_order_rows(self):
        self.document()
        self.document(source="second.pdf")
        receipt = self.build()
        rows = self.rows()
        path = self.out / "document-index.private.jsonl"
        path.chmod(0o644)
        self.lookup(receipt, rows[0]["document_id"], success=False)
        path.chmod(0o400)
        link = self.root / "index-link"
        link.symlink_to(path)
        self.lookup(receipt, rows[0]["document_id"], success=False, index=link)
        path.chmod(0o600)
        for data in (b"".join(encode(row) for row in reversed(rows)), encode(rows[0]) * 2,
                     encode(rows[0]).replace(b'"record_status":"success"', b'"record_status":"success","record_status":"success"'),
                     encode(dict(rows[0], document_id="0" * 64)), encode(dict(rows[0], extra="private error"))):
            with self.subTest(data=data[:40]):
                path.write_bytes(data)
                self.lookup(receipt, rows[0]["document_id"], success=False, pin=digest(path))

    def test_type_extends_native_source_and_only_adds_requested_metadata_fields(self):
        lines = (ROOT / "type/keller.document.type.yaml").read_text().splitlines()
        self.assertEqual(lines[:2], ["extends: source::au-base-types", "fields:"])
        self.assertEqual(lines[2:], ["  document_id: String", "  pdf_sha256: String", "  record_sha256?: String",
                                     "  transcript_sha256?: String", "  classification_hint: String",
                                     "  classification_basis: String", "  extraction_status: String",
                                     "  archive: source::au-base-types*"])


if __name__ == "__main__":
    unittest.main()
